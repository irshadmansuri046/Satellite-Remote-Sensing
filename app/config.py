import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "FarmRemoteSensingPlatform"
    DEBUG: bool = False
    API_V1_STR: str = "/api/v1"

    # Database (PostgreSQL + PostGIS)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/farm_db"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/farm_db"

    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"

    # Cloudflare R2 / S3 compatible storage
    R2_ENDPOINT_URL: Optional[str] = None
    R2_ACCESS_KEY_ID: Optional[str] = None
    R2_SECRET_ACCESS_KEY: Optional[str] = None
    R2_BUCKET_NAME: str = "farm-rasters"
    R2_PUBLIC_URL_PREFIX: Optional[str] = None  # Custom domain or public endpoint if applicable

    # STAC API for Sentinel-2
    STAC_API_URL: str = "https://earth-search.aws.element84.com/v1"

    # Storage Temp Dir
    TEMP_DIR: str = "/tmp/farm_sensing"

    # Environment variables loading
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Ensure local directories exist
os.makedirs(settings.TEMP_DIR, exist_ok=True)
os.makedirs(os.path.join(settings.TEMP_DIR, "raw"), exist_ok=True)
os.makedirs(os.path.join(settings.TEMP_DIR, "processed"), exist_ok=True)
