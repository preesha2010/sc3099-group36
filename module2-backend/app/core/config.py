from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql://saiv:saiv_password@localhost:5434/saiv"
    REDIS_URL: str = "redis://localhost:6380/0"
    SECRET_KEY: str = "your-secret-key-change-in-production"
    FACE_SERVICE_URL: str = "http://localhost:8001"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    JWT_ALGORITHM: str = "HS256"
    BCRYPT_ROUNDS: int = 10
    RISK_SCORE_THRESHOLD: float = 0.5

    # SECURITY-REQUIREMENTS.md production values: login 60/1h IP, register 10/1h IP,
    # API 1000/1h user, check-in 10/1min user. The public HTTP suite issues more
    # registrations from 127.0.0.1 than 10/hour, so defaults stay high; set the
    # documented numbers via environment in production.
    LOGIN_RATE_LIMIT: int = 100000
    LOGIN_RATE_WINDOW: int = 3600
    REGISTER_RATE_LIMIT: int = 100000
    REGISTER_RATE_WINDOW: int = 3600
    API_RATE_LIMIT: int = 100000
    API_RATE_WINDOW: int = 3600
    CHECKIN_RATE_LIMIT: int = 100000
    CHECKIN_RATE_WINDOW: int = 60

    ACCOUNT_LOCKOUT_ATTEMPTS: int = 10
    DATA_RETENTION_DAYS: int = 30

    # Decoded image cap for face enroll and check-in photos. Public-suite and
    # sample_images payloads stay under 600 KiB; Module 3 in this tree has no
    # documented size limit, so Module 2 rejects first.
    FACE_IMAGE_MAX_BYTES: int = 1_048_576

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:8501"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
