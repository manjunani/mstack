import os

from config import DATABASE_URL


def queue_name():
    return os.environ.get("QUEUE_NAME", "bookings")


def batch_size():
    return int(os.environ["WORKER_BATCH_SIZE"])


def connect():
    return DATABASE_URL
