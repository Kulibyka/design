"""Модели запросов и ответов API (DTO)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, StringConstraints, field_validator


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserCreate(RequestModel):
    login: NonEmptyText
    first_name: NonEmptyText
    last_name: NonEmptyText
    password: str

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "login": "ivan",
        "first_name": "Ivan",
        "last_name": "Petrov",
        "password": "example-password",
    }]})

    @field_validator("password")
    @classmethod
    def password_is_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Пароль не должен быть пустым")
        return value


class UserResponse(BaseModel):
    id: UUID
    login: str
    first_name: str
    last_name: str
    created_at: datetime

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id": "11111111-1111-4111-8111-111111111111",
        "login": "ivan", "first_name": "Ivan", "last_name": "Petrov",
        "created_at": "2026-10-12T12:00:00Z",
    }]})


class LoginRequest(RequestModel):
    login: NonEmptyText
    password: str

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "login": "ivan", "password": "example-password",
    }]})


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "access_token": "example-session-token", "token_type": "bearer", "expires_in": 3600,
    }]})


class FolderCreate(RequestModel):
    name: NonEmptyText

    model_config = ConfigDict(json_schema_extra={"examples": [{"name": "Study"}]})


class FolderResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "id": "22222222-2222-4222-8222-222222222222",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "name": "Study", "created_at": "2026-10-12T12:00:00Z",
    }]})


class MessageCreate(RequestModel):
    subject: NonEmptyText
    body: NonEmptyText
    recipient_address: EmailStr

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "subject": "Homework",
        "body": "Project description.",
        "recipient_address": "teacher@example.com",
    }]})


class MessageResponse(BaseModel):
    code: UUID
    folder_id: UUID
    subject: str
    body: str
    recipient_address: EmailStr
    created_at: datetime

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "code": "33333333-3333-4333-8333-333333333333",
        "folder_id": "22222222-2222-4222-8222-222222222222",
        "subject": "Homework", "body": "Project description.",
        "recipient_address": "teacher@example.com", "created_at": "2026-10-12T12:00:00Z",
    }]})


class ErrorResponse(BaseModel):
    detail: str

    model_config = ConfigDict(json_schema_extra={"examples": [{"detail": "Папка не найдена"}]})
