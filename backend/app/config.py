from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+asyncpg://autotest:autotest@localhost:5432/autotestvision"
    adb_path: str = "adb"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    agent_llm_api_key: str = ""
    agent_llm_base_url: str = ""
    agent_llm_model: str = "gpt-4o-mini"
    agent_verify_model: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
