import os


DATABASE_URL = os.getenv("DATABASE_URL")
CACHE_DIR = r"C:\Users\developer\AppData\Local\sample-cache"


def configured_database() -> str | None:
    return DATABASE_URL
