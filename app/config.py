"""Runtime configuration loaded from environment variables."""

import logging
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

PLACEHOLDER_API_KEY = "replace-with-a-long-random-string"
MINIMUM_API_KEY_LENGTH = 16


def configure_logging() -> None:
    """Attach a standard log handler once, without printing secrets."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    api_key: SecretStr
    database_url: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    ollama_timeout_seconds: float = 90
    ollama_connect_timeout_seconds: float = 5

    @field_validator("app_port")
    @classmethod
    def port_must_be_valid(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("APP_PORT must be between 1 and 65535")
        return value

    @field_validator("api_key")
    @classmethod
    def api_key_must_be_replaced(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if (
            secret == PLACEHOLDER_API_KEY
            or len(secret) < MINIMUM_API_KEY_LENGTH
            or secret != secret.strip()
        ):
            raise ValueError(
                "API_KEY must be a non-placeholder value of at least "
                f"{MINIMUM_API_KEY_LENGTH} characters"
            )
        return value

    @field_validator("ollama_base_url")
    @classmethod
    def ollama_url_must_be_absolute(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("OLLAMA_BASE_URL must be an absolute http(s) URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("OLLAMA_BASE_URL must not include credentials")
        return normalized.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def database_url_must_use_mysql(cls, value: str) -> str:
        if value == "":
            return value
        parsed = urlparse(value)
        database_name = parsed.path.lstrip("/")
        if (
            parsed.scheme != "mysql+pymysql"
            or parsed.hostname is None
            or not database_name
        ):
            raise ValueError(
                "DATABASE_URL must be a mysql+pymysql URL with a host and database name"
            )
        return value

    @field_validator("ollama_model")
    @classmethod
    def model_name_must_be_present(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("OLLAMA_MODEL must not be empty")
        return normalized

    @field_validator("ollama_timeout_seconds")
    @classmethod
    def response_timeout_must_be_reasonable(cls, value: float) -> float:
        if not 1 <= value <= 300:
            raise ValueError("OLLAMA_TIMEOUT_SECONDS must be between 1 and 300")
        return value

    @field_validator("ollama_connect_timeout_seconds")
    @classmethod
    def connect_timeout_must_be_reasonable(cls, value: float) -> float:
        if not 1 <= value <= 30:
            raise ValueError("OLLAMA_CONNECT_TIMEOUT_SECONDS must be between 1 and 30")
        return value


@lru_cache
def get_settings() -> Settings:
    """Load settings. Fail closed without echoing secret values."""
    configure_logging()
    try:
        return Settings()
    except ValidationError as exc:
        field_names = ", ".join(
            str(error["loc"][0]) for error in exc.errors() if error.get("loc")
        )
        logger.error("Invalid configuration. Check: %s", field_names or "environment")
        raise RuntimeError("Invalid configuration") from None
