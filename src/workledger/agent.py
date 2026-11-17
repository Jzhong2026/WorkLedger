"""Optional built-in agent configuration and CodeBuddy CLI adapter."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .config import settings


@dataclass
class AgentStatus:
    enabled: bool
    model: str
    cli_available: bool
    key_configured: bool
    connection_ok: bool | None
    error: str | None


def get_agent_status() -> AgentStatus:
    key_configured = bool(settings.codebuddy_api_key)
    cli_available = _check_cli()
    return AgentStatus(
        enabled=settings.agent_enabled,
        model=settings.agent_model,
        cli_available=cli_available,
        key_configured=key_configured,
        connection_ok=None,
        error=None,
    )


def _check_cli() -> bool:
    try:
        result = subprocess.run(
            ["codebuddy", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def test_connection(model: str | None = None) -> dict:
    if not settings.codebuddy_api_key:
        return {"ok": False, "error": "No API key configured. Set CODEBUDDY_API_KEY in .env or via settings."}
    if not _check_cli():
        return {"ok": False, "error": "CodeBuddy CLI not found. Install it and ensure it is on PATH."}

    chosen_model = model or settings.agent_model
    model_id = MODELS.get(chosen_model, {}).get("verified_id") or chosen_model
    try:
        result = subprocess.run(
            ["codebuddy", "-p", "--model", model_id, "--output-format", "text",
             "Reply with exactly: WORKLEDGER_OK"],
            capture_output=True, text=True, timeout=60,
            env=_cli_env(),
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"CLI exited {result.returncode}: {result.stderr[:500]}", "model": model_id}
        output = result.stdout.strip()
        return {
            "ok": "WORKLEDGER_OK" in output,
            "model": model_id,
            "response_preview": output[:200],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "CLI timed out (60s). Check network or model availability.", "model": model_id}
    except Exception as e:
        return {"ok": False, "error": str(e), "model": model_id}


def _cli_env() -> dict:
    import os
    env = os.environ.copy()
    env["CODEBUDDY_API_KEY"] = settings.codebuddy_api_key
    return env


MODELS = {
    "deepseek-flash": {"display": "DeepSeek Flash", "verified_id": "deepseek-v4.1-flash"},
    "hy4-flash": {"display": "HY4 Flash", "verified_id": "hy4-preview"},
}