"""Публикация события после сохранения сущности в MongoDB."""

from datetime import datetime, timezone
import json
from uuid import uuid4

import pika

from events.broker import connect, ROUTING_KEYS, setup_queue
from events.schema import Event


def publish_event(event_type: str, payload: dict) -> dict:
    event = Event(
        event_id=uuid4(), event_type=event_type, version=1,
        occurred_at=datetime.now(timezone.utc), payload=payload,
    ).model_dump(mode="json")
    with connect() as connection:
        channel = connection.channel()
        exchange, _ = setup_queue(channel)
        channel.confirm_delivery()
        channel.basic_publish(
            exchange=exchange, routing_key=ROUTING_KEYS[event_type],
            body=json.dumps(event, ensure_ascii=True).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json", content_encoding="utf-8",
                delivery_mode=2, message_id=event["event_id"], type=event_type,
            ),
            mandatory=True,
        )
    return event
