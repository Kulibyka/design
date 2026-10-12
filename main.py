"""Учебный REST API: пользователи, почтовые папки и письма."""

from datetime import datetime, timedelta, timezone
import re
import secrets
from urllib.parse import urlencode
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from pymongo.errors import DuplicateKeyError

from database import get_database

from models import (
    ErrorResponse, FolderCreate, FolderResponse, LoginRequest, MessageCreate,
    MessageResponse, TokenResponse, UserCreate, UserResponse,
)


app = FastAPI(
    title="Электронная почта — вариант 9",
    description="Домашнее задание 04. Пользователи, папки и письма хранятся в MongoDB.",
    version="1.0.0",
)

# Сессии остались в памяти: после перезапуска API нужно войти заново.
sessions: dict[str, dict] = {}

password_hasher = PasswordHasher()
SESSION_SECONDS = 3600

INVALID_DATA = {400: {"model": ErrorResponse, "description": "Некорректные данные"}}
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Ресурс не найден или недоступен"}}
CONFLICT = {409: {"model": ErrorResponse, "description": "Ресурс уже существует"}}
UNAUTHORIZED = {401: {"model": ErrorResponse, "description": "Требуется вход в систему"}}


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    ]
    return JSONResponse(status_code=400, content={"detail": "; ".join(errors)})


@app.middleware("http")
async def authentication(request: Request, call_next):
    path = request.url.path.rstrip("/")
    public_request = request.method == "POST" and path in {
        "/api/v1/users", "/api/v1/auth/login",
    }
    if (path == "/api/v1" or path.startswith("/api/v1/")) and not public_request:
        authorization = request.headers.get("Authorization", "")
        parts = authorization.split()
        session = None
        if len(parts) == 2 and parts[0].lower() == "bearer":
            session = sessions.get(parts[1])
            if session and session["expires_at"] <= datetime.now(timezone.utc):
                sessions.pop(parts[1], None)
                session = None
        if not session:
            return JSONResponse(
                status_code=401,
                content={"detail": "Отсутствует или недействителен токен"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.user_id = session["user_id"]
    return await call_next(request)


def public_user(user: dict) -> UserResponse:
    # Пароль и его хеш никогда не попадают в ответ.
    return UserResponse(id=user["_id"], **{
        field: user[field] for field in UserResponse.model_fields if field != "id"
    })


def folder_response(folder: dict) -> FolderResponse:
    return FolderResponse(id=folder["_id"], **folder)


def message_response(message: dict) -> MessageResponse:
    return MessageResponse(
        code=message["_id"], folder_id=message["folder_id"],
        subject=message["content"]["subject"], body=message["content"]["body"],
        recipient_address=message["recipients"][0], created_at=message["created_at"],
    )


def mongo_now() -> datetime:
    # BSON Date хранит миллисекунды: округляем до сохранения и ответа API.
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def find_user(login: str) -> dict | None:
    return get_database().users.find_one({"login": login.strip().lower()})


def mask_to_regex(mask: str) -> str:
    # Только * и ? имеют специальное значение; остальной текст экранируется.
    return "^" + re.escape(mask).replace(r"\*", ".*").replace(r"\?", ".") + "$"


def get_owned_folder(database, folder_id: UUID, user_id: str) -> dict:
    folder = database.folders.find_one({"_id": str(folder_id), "user_id": user_id})
    if folder is None:
        raise HTTPException(status_code=404, detail="Папка не найдена")
    return folder


@app.post(
    "/api/v1/users", response_model=UserResponse, status_code=201,
    tags=["Пользователи"], summary="Создать пользователя (регистрация)",
    responses={**INVALID_DATA, **CONFLICT},
)
def create_user(data: UserCreate, response: Response):
    user = {
        "_id": str(uuid4()), "login": data.login.lower(),
        "first_name": data.first_name, "last_name": data.last_name,
        "password_hash": password_hasher.hash(data.password), "created_at": mongo_now(),
    }
    try:
        get_database().users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Логин уже занят")
    response.headers["Location"] = "/api/v1/users/by-login?" + urlencode({"login": user["login"]})
    return public_user(user)


@app.post(
    "/api/v1/auth/login", response_model=TokenResponse,
    tags=["Аутентификация"], summary="Войти и получить сессионный токен",
    responses={**INVALID_DATA, **UNAUTHORIZED},
)
def login(data: LoginRequest):
    user = find_user(data.login)
    valid_password = False
    if user:
        try:
            valid_password = password_hasher.verify(user["password_hash"], data.password)
        except VerifyMismatchError:
            pass
    if not valid_password:
        raise HTTPException(
            status_code=401, detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = secrets.token_urlsafe(32)
    sessions[token] = {
        "user_id": user["_id"],
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=SESSION_SECONDS),
    }
    return TokenResponse(access_token=token, expires_in=SESSION_SECONDS)


# HTTPBearer добавляет кнопку Authorize и описание токена в Swagger.
# Саму проверку токена выполняет middleware выше.
api = APIRouter(
    prefix="/api/v1", dependencies=[Depends(HTTPBearer(auto_error=False))],
    responses=UNAUTHORIZED,
)


@api.get(
    "/users/by-login", response_model=UserResponse,
    tags=["Пользователи"], summary="Найти пользователя по логину",
    responses={**INVALID_DATA, **NOT_FOUND},
)
def get_user_by_login(login: str = Query(min_length=1, description="Логин без учёта регистра")):
    user = find_user(login)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return public_user(user)


@api.get(
    "/users", response_model=list[UserResponse],
    tags=["Пользователи"], summary="Найти пользователей по маске имени и фамилии",
    responses=INVALID_DATA,
)
def search_users(
    first_name_mask: str | None = Query(default=None, min_length=1, description="Маска имени: * — любое число символов, ? — один"),
    last_name_mask: str | None = Query(default=None, min_length=1, description="Маска фамилии: * — любое число символов, ? — один"),
):
    if first_name_mask is None and last_name_mask is None:
        raise HTTPException(status_code=400, detail="Укажите маску имени или фамилии")
    if any(mask is not None and not mask.strip() for mask in (first_name_mask, last_name_mask)):
        raise HTTPException(status_code=400, detail="Маска не должна быть пустой")
    query = {}
    if first_name_mask is not None:
        query["first_name"] = {"$regex": mask_to_regex(first_name_mask), "$options": "is"}
    if last_name_mask is not None:
        query["last_name"] = {"$regex": mask_to_regex(last_name_mask), "$options": "is"}
    found = get_database().users.find(query, {"password_hash": 0}).sort("login", 1)
    return [public_user(user) for user in found]


@api.post(
    "/folders", response_model=FolderResponse, status_code=201,
    tags=["Папки"], summary="Создать почтовую папку",
    responses={**INVALID_DATA, **CONFLICT},
)
def create_folder(data: FolderCreate, request: Request):
    database = get_database()
    user_id = request.state.user_id
    if database.users.find_one({"_id": user_id}, {"_id": 1}) is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден", headers={"WWW-Authenticate": "Bearer"})
    folder = {"_id": str(uuid4()), "user_id": user_id, "name": data.name, "created_at": mongo_now()}
    try:
        database.folders.insert_one(folder)
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Папка с таким именем уже существует")
    return folder_response(folder)


@api.get(
    "/folders", response_model=list[FolderResponse],
    tags=["Папки"], summary="Получить все папки текущего пользователя",
)
def get_folders(request: Request):
    found = get_database().folders.find({"user_id": request.state.user_id}).sort([("name", 1), ("_id", 1)])
    return [folder_response(folder) for folder in found]


@api.post(
    "/folders/{folder_id}/messages", response_model=MessageResponse, status_code=201,
    tags=["Письма"], summary="Создать письмо в папке",
    responses={**INVALID_DATA, **NOT_FOUND},
)
def create_message(folder_id: UUID, data: MessageCreate, request: Request, response: Response):
    database = get_database()
    get_owned_folder(database, folder_id, request.state.user_id)
    message = {
        "_id": str(uuid4()), "folder_id": str(folder_id),
        "content": {"subject": data.subject, "body": data.body},
        "recipients": [str(data.recipient_address)],
        "size_bytes": len(data.body.encode("utf-8")), "created_at": mongo_now(),
    }
    database.messages.insert_one(message)
    response.headers["Location"] = f"/api/v1/messages/{message['_id']}"
    return message_response(message)


@api.get(
    "/folders/{folder_id}/messages", response_model=list[MessageResponse],
    tags=["Письма"], summary="Получить все письма в папке",
    responses={**INVALID_DATA, **NOT_FOUND},
)
def get_messages(folder_id: UUID, request: Request):
    database = get_database()
    get_owned_folder(database, folder_id, request.state.user_id)
    found = database.messages.find({"folder_id": str(folder_id)}).sort([("created_at", 1), ("_id", 1)])
    return [message_response(message) for message in found]


@api.get(
    "/messages/{code}", response_model=MessageResponse,
    tags=["Письма"], summary="Получить письмо по коду",
    responses={**INVALID_DATA, **NOT_FOUND},
)
def get_message(code: UUID, request: Request):
    database = get_database()
    message = database.messages.find_one({"_id": str(code)})
    if message is None:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    if database.folders.find_one({"_id": message["folder_id"], "user_id": request.state.user_id}) is None:
        raise HTTPException(status_code=404, detail="Письмо не найдено")
    return message_response(message)


app.include_router(api)


def custom_openapi():
    if app.openapi_schema is None:
        schema = get_openapi(
            title=app.title, version=app.version, description=app.description,
            routes=app.routes,
        )
        # Обработчик validation_error возвращает 400 вместо стандартного 422.
        for path in schema["paths"].values():
            for operation in path.values():
                operation["responses"].pop("422", None)
        schemas = schema["components"]["schemas"]
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi
