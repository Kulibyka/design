from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from pymongo.errors import DuplicateKeyError, WriteError
from pika.exceptions import AMQPConnectionError
import yaml

from database import get_database, mongo_client
from main import app, find_user, password_hasher, sessions
from performance import folder_cache, login_limiter, message_cache
from events.consumer import apply_event
import performance


@pytest.fixture(scope="session")
def test_database_name():
    name = os.environ.get("TEST_MONGO_DB", "maildb_test")
    assert name.endswith("_test"), "Нужна отдельная БД с суффиксом _test"
    database = mongo_client[name]
    for collection in ("users", "folders", "messages"):
        assert "$jsonSchema" in database[collection].options().get("validator", {}), \
            "Перед тестами выполните validation.js в тестовой базе, как указано в README"
    return name


@pytest.fixture
def client(monkeypatch, test_database_name):
    monkeypatch.setenv("MONGO_DB", test_database_name)
    monkeypatch.setattr("main.publish_event", lambda event_type, payload: None)
    for collection in ("mail_read_model", "messages", "folders", "users"):
        get_database()[collection].delete_many({})
    sessions.clear()
    folder_cache.clear()
    message_cache.clear()
    login_limiter.clear()
    with TestClient(app) as test_client:
        yield test_client
    for collection in ("mail_read_model", "messages", "folders", "users"):
        get_database()[collection].delete_many({})
    sessions.clear()
    folder_cache.clear()
    message_cache.clear()
    login_limiter.clear()


def count_records(table):
    assert table in {"users", "folders", "messages"}
    return get_database()[table].count_documents({})


def register(client, login="ivan", first_name="Иван", last_name="Петров"):
    return client.post("/api/v1/users", json={
        "login": login, "first_name": first_name, "last_name": last_name,
        "password": "example-password",
    })


def authorization(client, login="ivan"):
    result = client.post("/api/v1/auth/login", json={
        "login": login, "password": "example-password",
    })
    assert result.status_code == 200
    assert result.json()["token_type"] == "bearer"
    assert result.json()["expires_in"] == 3600
    return {"Authorization": "Bearer " + result.json()["access_token"]}


def create_folder(client, headers, name="Учёба"):
    result = client.post("/api/v1/folders", json={"name": name}, headers=headers)
    assert result.status_code == 201
    return result.json()


def create_message(client, headers, folder_id):
    result = client.post(f"/api/v1/folders/{folder_id}/messages", headers=headers, json={
        "subject": "Домашнее задание", "body": "Описание проекта",
        "recipient_address": "teacher@example.com",
    })
    assert result.status_code == 201
    assert result.headers["location"] == "/api/v1/messages/" + result.json()["code"]
    return result.json()


def test_registration_login_and_search_by_login(client):
    result = register(client, login="IVAN")
    assert result.status_code == 201
    user = result.json()
    assert user["login"] == "ivan"
    assert "password" not in user
    assert "password_hash" not in user
    assert password_hasher.verify(find_user("ivan")["password_hash"], "example-password")
    headers = authorization(client, "IvAn")
    found = client.get(result.headers["location"], headers=headers)
    assert found.status_code == 200
    assert found.json() == user


def test_login_is_unique_without_case(client):
    assert register(client).status_code == 201
    assert register(client, " IVAN ").status_code == 409
    assert count_records("users") == 1


def test_search_by_both_masks(client):
    assert register(client).status_code == 201
    assert register(client, "anna", "Анна", "Петрова").status_code == 201
    headers = authorization(client)
    result = client.get("/api/v1/users", headers=headers, params={
        "first_name_mask": "ив?н", "last_name_mask": "пет*",
    })
    assert result.status_code == 200
    assert [user["login"] for user in result.json()] == ["ivan"]
    surname_only = client.get("/api/v1/users", headers=headers, params={"last_name_mask": "ПЕТ*"})
    assert [user["login"] for user in surname_only.json()] == ["anna", "ivan"]
    no_match = client.get("/api/v1/users", headers=headers, params={"first_name_mask": "Нет*"})
    assert no_match.status_code == 200
    assert no_match.json() == []


@pytest.mark.parametrize("params", [{}, {"first_name_mask": ""}, {"last_name_mask": "   "}])
def test_search_requires_nonempty_mask(client, params):
    register(client)
    assert client.get("/api/v1/users", params=params, headers=authorization(client)).status_code == 400


def test_mask_treats_other_symbols_literally(client):
    register(client, first_name="И[в]ан", last_name="Пет%_ров")
    headers = authorization(client)
    result = client.get("/api/v1/users", headers=headers, params={
        "first_name_mask": "И[в]*", "last_name_mask": "Пет%_*",
    })
    assert result.status_code == 200
    assert len(result.json()) == 1


def test_folders_and_message_workflow(client):
    register(client)
    headers = authorization(client)
    assert client.get("/api/v1/folders", headers=headers).json() == []
    folder = create_folder(client, headers)
    path = f"/api/v1/folders/{folder['id']}/messages"
    assert client.get(path, headers=headers).json() == []
    letter = create_message(client, headers, folder["id"])
    listed = client.get("/api/v1/folders", headers=headers)
    assert listed.status_code == 200
    assert listed.json() == [folder]
    listed_messages = client.get(path, headers=headers)
    assert listed_messages.status_code == 200
    assert listed_messages.json() == [letter]
    by_code = client.get(f"/api/v1/messages/{letter['code']}", headers=headers)
    assert by_code.status_code == 200
    assert by_code.json() == letter


def test_duplicate_folder_name_for_same_user(client):
    register(client)
    headers = authorization(client)
    create_folder(client, headers)
    result = client.post("/api/v1/folders", headers=headers, json={"name": " Учёба "})
    assert result.status_code == 409
    assert count_records("folders") == 1


def test_other_users_cannot_access_folders_or_messages(client):
    register(client)
    first_headers = authorization(client)
    folder = create_folder(client, first_headers)
    letter = create_message(client, first_headers, folder["id"])
    register(client, "anna", "Анна", "Петрова")
    second_headers = authorization(client, "anna")
    assert client.get("/api/v1/folders", headers=second_headers).json() == []
    path = f"/api/v1/folders/{folder['id']}/messages"
    assert client.get(path, headers=second_headers).status_code == 404
    result = client.post(path, headers=second_headers, json={
        "subject": "Тема", "body": "Текст", "recipient_address": "teacher@example.com",
    })
    assert result.status_code == 404
    foreign_letter = client.get(f"/api/v1/messages/{letter['code']}", headers=second_headers)
    absent_letter = client.get(f"/api/v1/messages/{uuid4()}", headers=second_headers)
    assert foreign_letter.status_code == absent_letter.status_code == 404
    assert foreign_letter.json() == absent_letter.json()
    own_folder = create_folder(client, second_headers)
    assert own_folder["user_id"] != folder["user_id"]
    assert count_records("messages") == 1


def test_missing_resources(client):
    register(client)
    headers = authorization(client)
    folder_id = str(uuid4())
    assert client.get("/api/v1/users/by-login?login=missing", headers=headers).status_code == 404
    assert client.get(f"/api/v1/folders/{folder_id}/messages", headers=headers).status_code == 404
    assert client.get(f"/api/v1/messages/{uuid4()}", headers=headers).status_code == 404
    result = client.post(f"/api/v1/folders/{folder_id}/messages", headers=headers, json={
        "subject": "Тема", "body": "Текст", "recipient_address": "teacher@example.com",
    })
    assert result.status_code == 404
    assert count_records("messages") == 0


@pytest.mark.parametrize("data", [
    {"login": "", "first_name": "Иван", "last_name": "Петров", "password": "password"},
    {"login": "ivan", "first_name": " ", "last_name": "Петров", "password": "password"},
    {"login": "ivan", "first_name": "Иван", "last_name": "Петров", "password": " "},
    {"login": "ivan", "first_name": "Иван", "last_name": "Петров"},
])
def test_invalid_registration(client, data):
    result = client.post("/api/v1/users", json=data)
    assert result.status_code == 400
    assert isinstance(result.json()["detail"], str)
    assert count_records("users") == 0


def test_invalid_folder_message_and_identifiers(client):
    register(client)
    headers = authorization(client)
    assert client.post("/api/v1/folders", headers=headers, json={"name": " "}).status_code == 400
    assert client.post("/api/v1/folders", headers=headers, json={"name": "A", "user_id": str(uuid4())}).status_code == 400
    folder = create_folder(client, headers)
    path = f"/api/v1/folders/{folder['id']}/messages"
    invalid_letters = [
        {"subject": "Тема", "body": "Текст", "recipient_address": "wrong-address"},
        {"subject": " ", "body": "Текст", "recipient_address": "teacher@example.com"},
        {"subject": "Тема", "body": " ", "recipient_address": "teacher@example.com"},
    ]
    for letter in invalid_letters:
        assert client.post(path, headers=headers, json=letter).status_code == 400
    assert client.get("/api/v1/folders/not-a-uuid/messages", headers=headers).status_code == 400
    assert client.get("/api/v1/messages/not-a-uuid", headers=headers).status_code == 400
    assert count_records("messages") == 0


def test_incorrect_login_and_password(client):
    register(client)
    for data in [
        {"login": "ivan", "password": "wrong"},
        {"login": "missing", "password": "example-password"},
    ]:
        result = client.post("/api/v1/auth/login", json=data)
        assert result.status_code == 401
        assert result.headers["www-authenticate"] == "Bearer"
    assert sessions == {}


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/users/by-login?login=ivan"),
    ("GET", "/api/v1/users?first_name_mask=*"),
    ("POST", "/api/v1/folders"),
    ("GET", "/api/v1/folders"),
    ("POST", f"/api/v1/folders/{uuid4()}/messages"),
    ("GET", f"/api/v1/folders/{uuid4()}/messages"),
    ("GET", f"/api/v1/messages/{uuid4()}"),
])
def test_all_private_endpoints_require_authentication(client, method, path):
    result = client.request(method, path)
    assert result.status_code == 401
    assert result.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("authorization_value", ["Bearer invalid", "Basic invalid", "Bearer", "Bearer a b"])
def test_invalid_token(client, authorization_value):
    assert client.get("/api/v1/folders", headers={"Authorization": authorization_value}).status_code == 401


def test_expired_session(client):
    register(client)
    headers = authorization(client)
    token = headers["Authorization"].split()[1]
    sessions[token]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert client.get("/api/v1/folders", headers=headers).status_code == 401
    assert token not in sessions


def test_openapi_and_swagger(client):
    assert client.get("/docs").status_code == 200
    live = client.get("/openapi.json")
    assert live.status_code == 200
    saved = yaml.safe_load(Path(__file__).parents[1].joinpath("openapi.yaml").read_text(encoding="utf-8"))
    assert live.json() == saved
    operations = [operation for path in saved["paths"].values() for operation in path.values()]
    assert len(operations) == 9
    assert sum(bool(operation.get("security")) for operation in operations) == 7
    assert all("422" not in operation["responses"] for operation in operations)


def test_data_remains_after_session_is_lost(client):
    register(client)
    headers = authorization(client)
    folder = create_folder(client, headers)
    letter = create_message(client, headers, folder["id"])
    sessions.clear()
    assert client.get("/api/v1/folders", headers=headers).status_code == 401
    new_headers = authorization(client)
    result = client.get(f"/api/v1/messages/{letter['code']}", headers=new_headers)
    assert result.status_code == 200
    assert result.json() == letter


def test_mongo_schema_validation(client):
    user = register(client).json()
    folder = create_folder(client, authorization(client))
    database = get_database()
    template = {
        "folder_id": folder["id"], "content": {"subject": "Test", "body": "Body"},
        "recipients": ["teacher@example.com"], "size_bytes": 4,
        "created_at": datetime.now(timezone.utc),
    }
    invalid_messages = [
        {**template, "content": {"subject": "Test"}},
        {**template, "content": {"subject": " ", "body": "Body"}},
        {**template, "recipients": ["invalid-address"]},
        {**template, "size_bytes": 0},
        {**template, "created_at": "2026-10-12"},
    ]
    for document in invalid_messages:
        document["_id"] = str(uuid4())
        with pytest.raises(WriteError) as error:
            database.messages.insert_one(document)
        assert error.value.code == 121  # Document failed validation
    with pytest.raises(WriteError) as error:
        database.users.insert_one({"_id": str(uuid4()), "login": "incomplete-user"})
    assert error.value.code == 121
    with pytest.raises(WriteError) as error:
        database.folders.insert_one({
            "_id": str(uuid4()), "user_id": user["id"], "name": " ", "created_at": datetime.now(timezone.utc),
        })
    assert error.value.code == 121
    with pytest.raises(DuplicateKeyError):
        database.folders.insert_one({
            "_id": str(uuid4()), "user_id": user["id"], "name": folder["name"],
            "created_at": datetime.now(timezone.utc),
        })
    assert count_records("folders") == 1
    assert count_records("messages") == 0


def test_folder_cache_hits_expiry_and_invalidation(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(performance, "monotonic", lambda: now[0])
    register(client)
    headers = authorization(client)
    queries = []
    collection_type = type(get_database().folders)
    original_find = collection_type.find

    def counted_find(collection, *args, **kwargs):
        if collection.name == "folders":
            queries.append(collection.name)
        return original_find(collection, *args, **kwargs)

    monkeypatch.setattr(collection_type, "find", counted_find)
    first = client.get("/api/v1/folders", headers=headers)
    second = client.get("/api/v1/folders", headers=headers)
    assert first.json() == second.json() == []
    assert first.headers["x-cache"] == "MISS"
    assert second.headers["x-cache"] == "HIT"
    assert len(queries) == 1

    folder = create_folder(client, headers)
    refreshed = client.get("/api/v1/folders", headers=headers)
    assert refreshed.headers["x-cache"] == "MISS"
    assert refreshed.json() == [folder]
    assert len(queries) == 2
    assert client.get("/api/v1/folders", headers=headers).headers["x-cache"] == "HIT"
    now[0] += folder_cache.ttl_seconds
    expired = client.get("/api/v1/folders", headers=headers)
    assert expired.headers["x-cache"] == "MISS"
    assert expired.json() == [folder]
    assert len(queries) == 3


def test_message_cache_hits_expiry_and_invalidation(client, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(performance, "monotonic", lambda: now[0])
    register(client)
    headers = authorization(client)
    folder = create_folder(client, headers)
    path = f"/api/v1/folders/{folder['id']}/messages"
    queries = []
    collection_type = type(get_database().messages)
    original_find = collection_type.find

    def counted_find(collection, *args, **kwargs):
        if collection.name == "messages":
            queries.append(collection.name)
        return original_find(collection, *args, **kwargs)

    monkeypatch.setattr(collection_type, "find", counted_find)
    first = client.get(path, headers=headers)
    second = client.get(path, headers=headers)
    assert first.json() == second.json() == []
    assert first.headers["x-cache"] == "MISS"
    assert second.headers["x-cache"] == "HIT"
    assert len(queries) == 1

    letter = create_message(client, headers, folder["id"])
    refreshed = client.get(path, headers=headers)
    assert refreshed.headers["x-cache"] == "MISS"
    assert refreshed.json() == [letter]
    assert len(queries) == 2
    assert client.get(path, headers=headers).headers["x-cache"] == "HIT"
    now[0] += message_cache.ttl_seconds
    expired = client.get(path, headers=headers)
    assert expired.headers["x-cache"] == "MISS"
    assert expired.json() == [letter]
    assert len(queries) == 3


def test_cached_data_still_requires_authentication_and_ownership(client):
    register(client)
    first_headers = authorization(client)
    folder = create_folder(client, first_headers)
    letter = create_message(client, first_headers, folder["id"])
    path = f"/api/v1/folders/{folder['id']}/messages"
    client.get("/api/v1/folders", headers=first_headers)
    client.get(path, headers=first_headers)
    assert client.get(path, headers=first_headers).headers["x-cache"] == "HIT"
    assert client.get(path).status_code == 401
    assert client.get("/api/v1/folders").status_code == 401

    second_user = register(client, "anna", "Anna", "Petrova").json()
    second_headers = authorization(client, "anna")
    assert client.get("/api/v1/folders", headers=second_headers).json() == []
    assert client.get(path, headers=second_headers).status_code == 404
    get_database().folders.update_one({"_id": folder["id"]}, {"$set": {"user_id": second_user["id"]}})
    assert client.get(path, headers=first_headers).status_code == 404
    second_result = client.get(path, headers=second_headers)
    assert second_result.headers["x-cache"] == "MISS"
    assert second_result.json() == [letter]


def test_login_rate_limit_headers_blocking_and_reset(client, monkeypatch):
    now = [1800000000.0]
    monkeypatch.setattr(performance, "time", lambda: now[0])
    register(client)
    valid = {"login": "ivan", "password": "example-password"}
    first = client.post("/api/v1/auth/login", json=valid)
    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "10"
    assert first.headers["x-ratelimit-remaining"] == "9"
    assert first.headers["x-ratelimit-reset"] == "1800000060"
    malformed = client.post("/api/v1/auth/login", content="{", headers={"Content-Type": "application/json"})
    assert malformed.status_code == 400
    assert malformed.headers["x-ratelimit-remaining"] == "8"
    for remaining in range(7, -1, -1):
        result = client.post("/api/v1/auth/login", json={"login": "missing", "password": "wrong"})
        assert result.status_code == 401
        assert result.headers["x-ratelimit-remaining"] == str(remaining)

    with monkeypatch.context() as limited:
        def forbidden_lookup(login):
            pytest.fail("Blocked login must not access MongoDB or verify passwords")
        limited.setattr("main.find_user", forbidden_lookup)
        blocked = client.post("/api/v1/auth/login", json=valid)
        assert blocked.status_code == 429
        assert blocked.json() == {"detail": "Too many login attempts"}
        assert blocked.headers["x-ratelimit-limit"] == "10"
        assert blocked.headers["x-ratelimit-remaining"] == "0"
        assert blocked.headers["x-ratelimit-reset"] == "1800000060"
    with TestClient(app, client=("203.0.113.2", 50000)) as second_client:
        independent = second_client.post("/api/v1/auth/login", json=valid)
        assert independent.status_code == 200
        assert independent.headers["x-ratelimit-remaining"] == "9"
    now[0] += 60
    reset = client.post("/api/v1/auth/login", json=valid)
    assert reset.status_code == 200
    assert reset.headers["x-ratelimit-remaining"] == "9"
    assert reset.headers["x-ratelimit-reset"] == "1800000120"


def test_rate_limit_does_not_exceed_limit_with_parallel_requests(monkeypatch):
    monkeypatch.setattr(performance, "time", lambda: 1800000000.0)
    limiter = performance.FixedWindowLimiter(limit=10, window_seconds=60)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: limiter.check("203.0.113.1"), range(40)))
    assert sum(allowed for allowed, _ in results) == 10
    assert all(headers["X-RateLimit-Remaining"] == "0" for allowed, headers in results if not allowed)


def test_creation_publishes_events_without_secrets(client, monkeypatch):
    published = []
    monkeypatch.setattr("main.publish_event", lambda name, payload: published.append((name, payload)))
    user = register(client).json()
    headers = authorization(client)
    folder = create_folder(client, headers)
    letter = create_message(client, headers, folder["id"])
    assert published == [("UserCreated", user), ("FolderCreated", folder), ("MessageCreated", letter)]
    assert all("password" not in payload and "password_hash" not in payload for _, payload in published)
    assert register(client).status_code == 409
    assert client.post("/api/v1/folders", headers=headers, json={"name": folder["name"]}).status_code == 409
    assert len(published) == 3


def test_publication_failure_reports_saved_data_and_invalidates_cache(client, monkeypatch):
    def unavailable(event_type, payload):
        raise AMQPConnectionError()

    monkeypatch.setattr("main.publish_event", unavailable)
    result = register(client)
    assert result.status_code == 503
    assert count_records("users") == 1
    headers = authorization(client)
    assert client.get("/api/v1/folders", headers=headers).json() == []
    result = client.post("/api/v1/folders", headers=headers, json={"name": "Study"})
    assert result.status_code == 503
    folders = client.get("/api/v1/folders", headers=headers)
    assert folders.headers["x-cache"] == "MISS"
    assert len(folders.json()) == 1
    folder = folders.json()[0]
    path = f"/api/v1/folders/{folder['id']}/messages"
    assert client.get(path, headers=headers).json() == []
    result = client.post(path, headers=headers, json={
        "subject": "Homework", "body": "Project description.", "recipient_address": "teacher@example.com",
    })
    assert result.status_code == 503
    letters = client.get(path, headers=headers)
    assert letters.headers["x-cache"] == "MISS"
    assert len(letters.json()) == 1


def test_message_query_uses_read_model_and_keeps_ownership_check(client, monkeypatch):
    register(client)
    headers = authorization(client)
    folder = create_folder(client, headers)
    letter = create_message(client, headers, folder["id"])
    event = {"event_id": str(uuid4()), "event_type": "MessageCreated", "version": 1,
             "occurred_at": datetime.now(timezone.utc).isoformat(), "payload": letter}
    assert apply_event(event, get_database())
    assert not apply_event(event, get_database())
    assert get_database().mail_read_model.count_documents({}) == 1
    collection_type = type(get_database().messages)
    original_find = collection_type.find

    def projection_only(collection, *args, **kwargs):
        assert collection.name != "messages", "Projected message should not query the write collection"
        return original_find(collection, *args, **kwargs)

    monkeypatch.setattr(collection_type, "find", projection_only)
    result = client.get(f"/api/v1/messages/{letter['code']}", headers=headers)
    assert result.status_code == 200
    assert result.json() == letter
    register(client, "anna", "Anna", "Petrova")
    foreign = client.get(f"/api/v1/messages/{letter['code']}", headers=authorization(client, "anna"))
    assert foreign.status_code == 404
