"""Общий конверт события версии 1."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["UserCreated", "FolderCreated", "MessageCreated"]
    version: Literal[1]
    occurred_at: datetime
    payload: dict
