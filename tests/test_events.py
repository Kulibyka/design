from datetime import datetime, timezone
import json
import os
from uuid import uuid4

from pymongo.errors import AutoReconnect
import pytest

from database import mongo_client
from events.broker import connect, setup_queue, ROUTING_KEYS
from events.consumer import apply_event, handle_message
from events.producer import publish_event


@pytest.fixture
def event_database(monkeypatch):
    name = os.environ.get("TEST_EVENT_DB", "mail_events_test")
    assert name.endswith("_test")
    database = mongo_client[name]
    database.mail_read_model.delete_many({})
    monkeypatch.setattr("events.consumer.get_database", lambda: database)
    yield database
    database.mail_read_model.delete_many({})


@pytest.fixture
def broker(monkeypatch):
    suffix = uuid4().hex + "_test"
    monkeypatch.setenv("EVENT_EXCHANGE", "mail.events." + suffix)
    monkeypatch.setenv("EVENT_QUEUE", "mail.read_model." + suffix)
    with connect() as connection:
        channel = connection.channel()
        exchange, queue = setup_queue(channel)
        try:
            yield channel, exchange, queue
        finally:
            channel.queue_delete(queue=queue)
            channel.exchange_delete(exchange=exchange)


def sample_payload(event_type):
    created_at = "2026-10-12T12:00:00Z"
    if event_type == "UserCreated":
        return {"id": str(uuid4()), "login": "ivan", "first_name": "Ivan",
                "last_name": "Petrov", "created_at": created_at}
    if event_type == "FolderCreated":
        return {"id": str(uuid4()), "user_id": str(uuid4()), "name": "Study", "created_at": created_at}
    return {"code": str(uuid4()), "folder_id": str(uuid4()), "subject": "Homework",
            "body": "Project description.", "recipient_address": "teacher@example.com",
            "created_at": created_at}


@pytest.mark.parametrize("event_type,entity_type", [
    ("UserCreated", "user"), ("FolderCreated", "folder"), ("MessageCreated", "message"),
])
def test_producer_routing_and_consumer_projection(broker, event_database, event_type, entity_type):
    channel, _, queue = broker
    payload = sample_payload(event_type)
    event = publish_event(event_type, payload)
    method, properties, body = channel.basic_get(queue=queue, auto_ack=False)
    assert method is not None
    assert method.routing_key == ROUTING_KEYS[event_type]
    assert properties.delivery_mode == 2
    assert properties.content_type == "application/json"
    assert properties.content_encoding == "utf-8"
    assert properties.message_id == event["event_id"]
    assert json.loads(body) == event
    assert event["version"] == 1
    assert datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00")).tzinfo == timezone.utc
    handle_message(channel, method, properties, body)
    projection = event_database.mail_read_model.find_one({})
    assert projection["entity_type"] == entity_type
    assert projection["data"] == payload
    assert projection["event_id"] == event["event_id"]
    assert channel.queue_declare(queue=queue, passive=True).method.message_count == 0


def test_redelivery_after_write_before_ack_is_idempotent(broker, event_database):
    channel, _, queue = broker
    publish_event("MessageCreated", sample_payload("MessageCreated"))
    method, properties, body = channel.basic_get(queue=queue, auto_ack=False)
    assert apply_event(json.loads(body), event_database)
    original = event_database.mail_read_model.find_one({})
    channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
    redelivered, properties, body = channel.basic_get(queue=queue, auto_ack=False)
    assert redelivered.redelivered
    handle_message(channel, redelivered, properties, body)
    assert event_database.mail_read_model.count_documents({}) == 1
    assert event_database.mail_read_model.find_one({}) == original


@pytest.mark.parametrize("body", [b"{", b'{"event_type":"UnknownEvent"}'])
def test_invalid_event_is_rejected_without_projection(broker, event_database, body):
    channel, exchange, queue = broker
    channel.basic_publish(exchange=exchange, routing_key="message.created", body=body)
    method, properties, received = channel.basic_get(queue=queue, auto_ack=False)
    handle_message(channel, method, properties, received)
    assert event_database.mail_read_model.count_documents({}) == 0
    assert channel.queue_declare(queue=queue, passive=True).method.message_count == 0


def test_database_failure_requeues_message(broker, event_database, monkeypatch):
    channel, _, queue = broker
    publish_event("MessageCreated", sample_payload("MessageCreated"))
    method, properties, body = channel.basic_get(queue=queue, auto_ack=False)
    collection_type = type(event_database.mail_read_model)

    def unavailable(*args, **kwargs):
        raise AutoReconnect("Simulated MongoDB failure")

    with monkeypatch.context() as failed:
        failed.setattr(collection_type, "update_one", unavailable)
        with pytest.raises(AutoReconnect):
            handle_message(channel, method, properties, body)
    redelivered, properties, body = channel.basic_get(queue=queue, auto_ack=False)
    assert redelivered.redelivered
    handle_message(channel, redelivered, properties, body)
    assert event_database.mail_read_model.count_documents({}) == 1
