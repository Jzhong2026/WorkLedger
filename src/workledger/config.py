from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    workledger_data_dir: str = "./data"
    workledger_host: str = "127.0.0.1"
    workledger_port: int = 8600

    codebuddy_api_key: str = ""
    agent_enabled: bool = False
    agent_model: str = "deepseek-flash"

    @property
    def data_path(self) -> Path:
        p = Path(self.workledger_data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_path / "workledger.db"


settings = Settings()