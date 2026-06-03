from __future__ import annotations

import os


class Settings:
    DEV_MODE: bool = os.getenv("DEV_MODE", "false").lower() == "true"
    ERP_BASE_URL: str = os.getenv("ERP_BASE_URL", "http://localhost:8000/api/v1")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "http://localhost:3000")


settings = Settings()
