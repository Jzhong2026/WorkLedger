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

    atlassian_user_email: str = ""
    atlassian_api_token: str = ""
    twg_cli_path: str = "twg"
    sync_interval_minutes: int = 15
    sync_jira_site: str = "transfinder"
    sync_jira_projects: str = "RW,AIP"
    sync_jira_exclude: str = "AIP-96"
    sync_jira_window_days: int = 30
    sync_bitbucket_workspace: str = "transfinderorg"
    sync_bitbucket_repos: str = "core,routefinderapi,routefinder-web"
    sync_bitbucket_project: str = "RW"
    sync_bitbucket_window_days: int = 30
    sync_record_merge_accomplishments: bool = True

    @property
    def data_path(self) -> Path:
        p = Path(self.workledger_data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_path / "workledger.db"


settings = Settings()