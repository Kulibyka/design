from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
import psycopg
from psycopg.conninfo import conninfo_to_dict
import yaml

from database import get_connection
from main import app, find_user, password_hasher, sessions


@pytest.fixture(scope="session")
def test_database_url():
    url = os.environ.get(
        "TEST_DATABASE_URL", "postgresql://mail:mail_password@localhost:5432/maildb_test",
    )
    # Тесты очищают таблицы, поэтому рабочую БД использовать нельзя.
    assert conninfo_to_dict(url)["dbname"].endswith("_test"), "Нужна отдельная БД с суффиксом _test"
    with psycopg.connect(url) as connection:
        connection.execute(Path(__file__).parents[1].joinpath("schema.sql").read_text(encoding="utf-8"))
    return url


@pytest.fixture
def client(monkeypatch, test_database_url):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    with get_connection() as connection:
        connection.execute("TRUNCATE messages, folders, users")
    sessions.clear()
    with TestClient(app) as test_client:
        yield test_client
    with get_connection() as connection:
        connection.execute("TRUNCATE messages, folders, users")
    sessions.clear()


def count_records(table):
    assert table in {"users", "folders", "messages"}
    with get_connection() as connection:
        return connection.execute(f"SELECT count(*) AS count FROM {table}").fetchone()["count"]


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


def test_database_constraints(client):
    user = register(client).json()
    folder = create_folder(client, authorization(client))
    cases = [
        ("INSERT INTO folders (user_id, name) VALUES (%s, %s)",
         (uuid4(), "Несуществующий владелец"), psycopg.errors.ForeignKeyViolation),
        ("INSERT INTO folders (user_id, name) VALUES (%s, %s)",
         (user["id"], folder["name"]), psycopg.errors.UniqueViolation),
        ("INSERT INTO messages (folder_id, subject, body, recipient_address) VALUES (%s, %s, %s, %s)",
         (folder["id"], None, "Текст", "teacher@example.com"), psycopg.errors.NotNullViolation),
        ("INSERT INTO messages (folder_id, subject, body, recipient_address) VALUES (%s, %s, %s, %s)",
         (folder["id"], " ", "Текст", "teacher@example.com"), psycopg.errors.CheckViolation),
    ]
    for query, parameters, error in cases:
        with pytest.raises(error):
            with get_connection() as connection:
                connection.execute(query, parameters)
    assert count_records("folders") == 1
    assert count_records("messages") == 0
