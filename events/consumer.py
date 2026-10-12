"""Consumer: идемпотентная проекция событий в модель для чтения."""

from datetime import datetime, timezone
import json
import logging

from pymongo.errors import PyMongoError

from database import get_database
from events.broker import connect, setup_queue
from events.schema import Event
from models import FolderResponse, MessageResponse, UserResponse


logger = logging.getLogger(__name__)
READ_MODELS = {
    "UserCreated": ("user", UserResponse, "id"),
    "FolderCreated": ("folder", FolderResponse, "id"),
    "MessageCreated": ("message", MessageResponse, "code"),
}


def apply_event(body: dict, database) -> bool:
    event = Event.model_validate(body)
    entity_type, response_model, id_field = READ_MODELS[event.event_type]
    data = response_model.model_validate(event.payload).model_dump(mode="json")
    result = database.mail_read_model.update_one(
        {"_id": f"{entity_type}:{data[id_field]}"},
        {"$setOnInsert": {
            "entity_type": entity_type, "data": data,
            "event_id": str(event.event_id), "occurred_at": event.occurred_at,
            "applied_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )
    return result.upserted_id is not None


def handle_message(channel, method, properties, body):
    try:
        event = json.loads(body)
        inserted = apply_event(event, get_database())
    except (ValueError, TypeError, KeyError):
        logger.warning("Invalid event discarded")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return
    except PyMongoError:
        logger.exception("Read model write failed; event returned to queue")
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
        raise
    channel.basic_ack(delivery_tag=method.delivery_tag)
    logger.info("Processed %s event_id=%s result=%s", event["event_type"], event["event_id"],
                "created" if inserted else "already applied")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("pika").setLevel(logging.WARNING)
    with connect() as connection:
        channel = connection.channel()
        _, queue = setup_queue(channel)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=queue, on_message_callback=handle_message, auto_ack=False)
        logger.info("Consumer waiting for events in %s", queue)
        channel.start_consuming()


if __name__ == "__main__":
    main()
