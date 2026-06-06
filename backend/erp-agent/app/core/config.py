from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 配置 pydantic-settings 的行为
    model_config = SettingsConfigDict(
        env_file="../../.env",           # 指定 .env 文件路径（默认在项目根目录）
        env_file_encoding="utf-8", # 指定文件编码
        extra="ignore",            # 忽略 .env 中定义了但类中没有的多余变量，防止报错
        case_sensitive=False,      # 环境变量名不区分大小写（可选）
    )

    # 直接定义字段、类型和默认值即可
    DEV_MODE: bool = False
    ERP_BASE_URL: str = "http://localhost:8000/api/v1"
    DATABASE_URL: str = ""
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_BASE_URL: str = "http://localhost:3000"

    # LLM (OpenAI-compatible, 默认 DeepSeek)
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.deepseek.com/v1"
    OPENAI_MODEL: str = "deepseek-v4-pro"

    # 飞书开放平台
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_OPEN_ID: str = ""


# 实例化时，pydantic 会自动去系统环境变量和 .env 文件中查找并赋值
settings = Settings()
