from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://autotest:autotest@localhost:5432/autotestvision"
    adb_path: str = "adb"
    cors_origins: str = "http://localhost:5179,http://127.0.0.1:5179"

    agent_llm_api_key: str = ""
    agent_llm_base_url: str = ""
    agent_llm_model: str = "gpt-4o-mini"
    agent_verify_model: str = ""

    # 本地 Ollama（OpenAI 兼容端点）。默认指向宿主机 Ollama，可被 env 覆盖。
    agent_local_base_url: str = "http://host.docker.internal:11434/v1"
    agent_local_model: str = "gemma4:12b"
    agent_local_api_key: str = "ollama"

    # 未在请求中指定 llm_provider 时的兜底：online | local | ""(=启发式)
    agent_default_provider: str = "local"

    # 执行操作后、截取「执行后」图前的等待时间（毫秒）
    agent_after_capture_delay_ms: int = 2000

    # 数据飞轮产物目录（导出 JSONL、RAG、训练 artifact）
    flywheel_artifact_dir: str = "data/flywheel"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def cors_origin_regex(self) -> str:
        """开发环境：允许通过局域网 IP 访问前端时的跨域来源。"""
        return (
            r"https?://("
            r"localhost|127\.0\.0\.1"
            r"|192\.168\.\d{1,3}\.\d{1,3}"
            r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
            r")(:\d+)?"
        )


settings = Settings()
