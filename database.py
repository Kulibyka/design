"""Простое подключение к MongoDB через PyMongo."""

import os

from pymongo import MongoClient


mongo_client = MongoClient(
    os.environ.get("MONGO_URI", "mongodb://localhost:27017"),
    tz_aware=True,
    serverSelectionTimeoutMS=5000,
)


def get_database():
    return mongo_client[os.environ.get("MONGO_DB", "maildb")]
