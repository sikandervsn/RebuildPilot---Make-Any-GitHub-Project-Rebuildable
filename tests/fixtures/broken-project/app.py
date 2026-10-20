import os

CONFIG = os.environ["BROKEN_API_URL"]
PROJECT_CACHE = r"C:\Users\someone\broken-project-cache"


def run() -> str:
    return CONFIG
