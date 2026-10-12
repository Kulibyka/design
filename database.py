"""Подключение к PostgreSQL. Запросы выполняются через обычный psycopg."""

import os

import psycopg
from psycopg.rows import dict_row


def get_connection():
    url = os.environ.get(
        "DATABASE_URL", "postgresql://mail:mail_password@localhost:5432/maildb",
    )
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=5)
