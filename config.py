"""统一配置加载器 — 从 config/*.yaml 和 .env 读取配置"""
import os
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).parent
CONFIG_DIR = BASE_DIR / "config"


def _load_dotenv():
    """手动加载 .env 文件到 os.environ"""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


# 启动时加载 .env
_load_dotenv()


def _load_yaml(name: str) -> dict:
    path = CONFIG_DIR / name
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


class Settings:
    """统一配置入口
    优先级：.env 环境变量 > YAML 配置文件 > 代码默认值
    """

    def __init__(self):
        paths = _load_yaml("paths.yaml")
        llm = _load_yaml("llm.yaml")
        wechat = _load_yaml("wechat.yaml")
        sync = _load_yaml("sync.yaml")
        agent = _load_yaml("agent.yaml")

        # ── 路径 ──
        self.DATA_DIR = paths.get("data_dir", "data")
        self.PROMPTS_FILE = paths.get("prompts_file", "prompts.yaml")

        # ── LLM（.env 优先） ──
        self.LLM_API_KEY = _env("LLM_API_KEY", llm.get("api_key") or "")
        self.LLM_BASE_URL = _env(
            "LLM_BASE_URL",
            llm.get("base_url") or "https://open.bigmodel.cn/api/paas/v4",
        )
        self.LLM_MODEL = _env("LLM_MODEL", llm.get("model") or "glm-5")
        self.LLM_TEMPERATURE = float(llm.get("temperature", 0))
        self.LLM_MAX_TOKENS = int(llm.get("max_tokens", 4096))

        # ── 微信 ──
        self.WECHAT_DATA_DIR = _env(
            "WECHAT_DATA_DIR", wechat.get("data_dir") or ""
        )
        self.WECHAT_VERSION = _env(
            "WECHAT_VERSION", wechat.get("version") or "auto"
        )
        if not self.WECHAT_DATA_DIR:
            try:
                from services.sync.wechat_path import detect_wechat_data_dir, persist_data_dir
                detected = detect_wechat_data_dir(self.WECHAT_VERSION)
                if detected:
                    self.WECHAT_DATA_DIR = detected
                    persist_data_dir(detected)
            except Exception:
                pass

        # ── 同步 ──
        default_lark = os.path.join(
            os.environ.get("APPDATA", ""), "npm", "lark-cli.cmd"
        )
        default_dws = os.path.join(
            os.environ.get("APPDATA", ""), "npm", "dws.cmd"
        )
        self.LARK_CLI_PATH = sync.get("lark_cli_path") or default_lark
        self.DWS_CLI_PATH = sync.get("dws_cli_path") or default_dws
        self.CLI_TIMEOUT = int(sync.get("cli_timeout", 30))

        self.FEISHU_BASE_TOKEN = _env(
            "FEISHU_BASE_TOKEN", sync.get("feishu_base_token") or ""
        )
        self.FEISHU_TABLE_ID = _env(
            "FEISHU_TABLE_ID", sync.get("feishu_table_id") or ""
        )
        self.DINGTALK_BASE_ID = _env(
            "DINGTALK_BASE_ID", sync.get("dingtalk_base_id") or ""
        )
        self.DINGTALK_TABLE_ID = _env(
            "DINGTALK_TABLE_ID", sync.get("dingtalk_table_id") or ""
        )

        # ── Agent ──
        self.DM_MSG_LIMIT = int(agent.get("dm_msg_limit", 200))
        self.LIST_CONTACTS_LIMIT = int(agent.get("list_contacts_limit", 50))

        # ── Bot ──
        bot = _load_yaml("bot.yaml")
        self.BOT_ENABLED = bot.get("enabled", False)
        self.BOT_POLL_INTERVAL = int(bot.get("poll_interval", 5))
        self.BOT_CONTEXT_MESSAGES = int(bot.get("context_messages", 10))
        self.BOT_DEFAULT_MODE = bot.get("default_mode", "semi_auto")


settings = Settings()
