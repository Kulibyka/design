"""Подключение и общая настройка exchange/queue RabbitMQ."""

import os

import pika


ROUTING_KEYS = {
    "UserCreated": "user.created",
    "FolderCreated": "folder.created",
    "MessageCreated": "message.created",
}


def connect():
    parameters = pika.URLParameters(os.environ.get(
        "AMQP_URL", "amqp://mail:mail_password@localhost:5672/%2F",
    ))
    parameters.socket_timeout = 5
    parameters.blocked_connection_timeout = 5
    return pika.BlockingConnection(parameters)


def setup_queue(channel):
    exchange = os.environ.get("EVENT_EXCHANGE", "mail.events")
    queue = os.environ.get("EVENT_QUEUE", "mail.read_model")
    channel.exchange_declare(exchange=exchange, exchange_type="topic", durable=True)
    channel.queue_declare(queue=queue, durable=True)
    channel.queue_bind(queue=queue, exchange=exchange, routing_key="*.created")
    return exchange, queue
