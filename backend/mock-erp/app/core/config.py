# app/core/config.py
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 项目名称
    PROJECT_NAME: str = "Mock ERP API"
    # 数据库 URL，默认使用本地 SQLite 文件
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./mock_erp.db")

    class Config:
        env_file = ".env"
        case_sensitive = True

# 实例化全局配置对象
settings = Settings()
