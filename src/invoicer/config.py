import os
from pathlib import Path

from dotenv import load_dotenv

REQUIRED_ENV = [
    "CLOCKIFY_API_KEY",
    "CLOCKIFY_WORKSPACE_ID",
    "QONTO_LOGIN",
    "QONTO_SECRET_KEY",
]


def load_env() -> None:
    root = Path(__file__).resolve().parents[2]
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Missing env vars: {missing}. Copy .env.example to .env and fill in."
        )
