import ast
import json
import subprocess
from typing import Dict


REDIS0 = {
    "host": "mp-data-prod-jp.rqo9pb.ng.0001.apne1.cache.amazonaws.com",
    "port": 6379,
    "db": 0,
}


def _normalize_payload(payload: str) -> Dict[str, str]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        data = ast.literal_eval(payload)
    if not isinstance(data, dict):
        raise ValueError("Redis account payload is not a dict.")
    return {str(key): str(value) for key, value in data.items()}


def _load_via_redis_py(redis_key: str) -> str:
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise RuntimeError("redis-py is not installed") from exc

    client = redis.StrictRedis(**REDIS0, decode_responses=True)
    payload = client.hget("account", redis_key)
    if not payload:
        raise KeyError(f"Redis key account/{redis_key} not found.")
    return payload


def _load_via_redis_cli(redis_key: str) -> str:
    command = [
        "redis-cli",
        "-h",
        REDIS0["host"],
        "-p",
        str(REDIS0["port"]),
        "-n",
        str(REDIS0["db"]),
        "--raw",
        "HGET",
        "account",
        redis_key,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=8,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"redis-cli failed with code {completed.returncode}: {completed.stderr.strip()}"
        )
    payload = completed.stdout.strip()
    if not payload:
        raise KeyError(f"Redis key account/{redis_key} not found.")
    return payload


def load_account_credentials(exchange: str, account: str) -> Dict[str, str]:
    redis_key = f"{exchange}_{account}"
    try:
        payload = _load_via_redis_py(redis_key)
    except Exception:
        payload = _load_via_redis_cli(redis_key)
    return _normalize_payload(payload)


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def mask_credentials(credentials: Dict[str, str]) -> Dict[str, str]:
    return {key: mask_secret(value) for key, value in credentials.items()}
