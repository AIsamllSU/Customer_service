from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # LLM 配置
    llm_model: str = "qwen-plus"
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_api_key: str
    llm_temperature: float = 0.0
    # LLM 调用失败时的最大尝试次数（含首次）
    llm_max_attempts: int = 2

    # 电商API配置
    commerce_api_base_url: str = "http://127.0.0.1:18081"

    # 数据库配置
    database_url: str
    # 生产默认关闭 SQL 回显；本地排查时把 DATABASE_ECHO 设为 true
    database_echo: bool = False

    # 应用配置
    app_host: str = "127.0.0.1"
    app_port: int = 18082
    app_log_level: str = "INFO"
    # 允许跨域来源；生产环境务必收窄为真实域名
    cors_allow_origins: list[str] = Field(default_factory=lambda: ["*"])

    # extra="ignore" 忽略 .env 文件中有、这里没有的配置项，不会报错
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore", env_file_encoding="utf-8")


settings = Settings()

if __name__ == "__main__":
    print(settings.database_url)
