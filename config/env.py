# config/env.py
import os


def get_env(key, default=None, required=False):
    value = os.environ.get(key, default)
    if required and value is None:
        raise RuntimeError(f"Missing required env var: {key}")
    return value
