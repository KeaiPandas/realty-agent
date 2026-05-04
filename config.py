import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    # LLM配置（智谱GLM，OpenAI兼容接口）
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", os.getenv("ZHIPU_API_KEY", ""))
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "glm-5")

    # 微信
    WECHAT_DATA_DIR: str = os.getenv("WECHAT_DATA_DIR", "")

    # 钉钉
    DINGTALK_BASE_ID: str = os.getenv("DINGTALK_BASE_ID", "")
    DINGTALK_TABLE_ID: str = os.getenv("DINGTALK_TABLE_ID", "")

    model_config = {"env_file": str(BASE_DIR / ".env"), "extra": "ignore"}


settings = Settings()
