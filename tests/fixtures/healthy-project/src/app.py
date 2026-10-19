import os


def application_mode() -> str:
    return os.getenv("APP_MODE", "development")
