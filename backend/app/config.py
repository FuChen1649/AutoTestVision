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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
