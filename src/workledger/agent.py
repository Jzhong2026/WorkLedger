"""Optional built-in agent configuration and CodeBuddy CLI adapter."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import settings


def _cli_base() -> list[str] | None:
    path = shutil.which("codebuddy")
    if not path:
        return None
    if path.lower().endswith((".cmd", ".bat")):
        # Invoke node directly on the JS entry to avoid cmd.exe mangling multi-line prompts.
        base_dir = Path(path).parent
        entry = base_dir / "node_modules" / "@tencent-ai" / "codebuddy-code" / "bin" / "codebuddy"
        node = shutil.which("node") or str(base_dir / "node.exe")
        if entry.exists():
            return [node, str(entry)]
        # A shell shim would interpret characters in the prompt instead of passing argv.
        return None
    return [path]


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
    cli_available = _cli_base() is not None
    return AgentStatus(
        enabled=settings.agent_enabled,
        model=settings.agent_model,
        cli_available=cli_available,
        key_configured=key_configured,
        connection_ok=None,
        error=None,
    )


_NO_TOOLS = ["--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}']
_MAX_PROMPT_CHARS = 10_000


def test_connection(model: str | None = None) -> dict:
    if not settings.codebuddy_api_key:
        return {"ok": False, "error": "No API key configured. Set CODEBUDDY_API_KEY in .env or via settings."}
    base = _cli_base()
    if not base:
        return {"ok": False, "error": "CodeBuddy CLI not found. Install it and ensure it is on PATH."}

    chosen_model = model or settings.agent_model
    model_id = MODELS.get(chosen_model, {}).get("verified_id") or chosen_model
    try:
        result = subprocess.run(
            base + ["-p", "--model", model_id, "--output-format", "text", *_NO_TOOLS,
                    "Reply with exactly: WORKLEDGER_OK"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            env=_cli_env(), check=False,
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
    except OSError:
        return {"ok": False, "error": "CodeBuddy CLI could not start.", "model": model_id}


def _cli_env() -> dict:
    env = os.environ.copy()
    env["CODEBUDDY_API_KEY"] = settings.codebuddy_api_key
    return env


MODELS = {
    "deepseek-flash": {"display": "DeepSeek Flash", "verified_id": "deepseek-v4.1-flash"},
    "hy4-flash": {"display": "HY4 Flash", "verified_id": "hy4-preview"},
}


def _model_id(model: str | None = None) -> str:
    chosen = model or settings.agent_model
    return MODELS.get(chosen, {}).get("verified_id") or chosen


def _run_cli(prompt: str, *, json_schema: dict | None = None, model: str | None = None, timeout: int = 90) -> dict:
    """Run CodeBuddy CLI in print mode, return {ok, text, error}. text is the assistant output."""
    if not settings.agent_enabled:
        return {"ok": False, "error": "Built-in AI is disabled. Set AGENT_ENABLED=true to use CodeBuddy."}
    if not settings.codebuddy_api_key:
        return {"ok": False, "error": "No API key configured. Agent features need CODEBUDDY_API_KEY."}
    if len(prompt.encode("utf-16-le")) // 2 > _MAX_PROMPT_CHARS:
        return {"ok": False, "error": "Input is too long for CodeBuddy. Shorten it or continue manually."}
    base = _cli_base()
    if not base:
        return {"ok": False, "error": "CodeBuddy CLI not found on PATH."}
    cmd = base + ["-p", "--model", _model_id(model), "--output-format", "json", *_NO_TOOLS]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]
    cmd.append(prompt)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=_cli_env(), check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"CLI timed out ({timeout}s)."}
    except OSError:
        return {"ok": False, "error": "CodeBuddy CLI could not start. Check the installation and retry."}
    if result.returncode != 0:
        return {"ok": False, "error": f"CLI exited {result.returncode}: {result.stderr[:300]}"}
    try:
        messages = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "CLI output was not valid JSON."}
    text = ""
    structured = None
    if not isinstance(messages, list):
        return {"ok": False, "error": "CodeBuddy returned an unexpected response."}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "result" and msg.get("structured_output") is not None:
            structured = msg["structured_output"]
        if msg.get("type") == "message" and msg.get("role") == "assistant":
            for c in msg.get("content", []):
                if c.get("type") == "output_text":
                    text = c.get("text", "")
    ok = structured is not None or bool(text)
    return {"ok": ok, "text": text, "structured": structured, "error": None if ok else "Empty model response."}


_EVENT_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "enum": ["pr_created", "review_finding", "comment_analysis", "fix", "verification", "reply_drafted", "reply_published", "manual"]},
                    "summary": {"type": "string"},
                    "repo": {"type": ["string", "null"]},
                    "pr_number": {"type": ["integer", "null"]},
                    "comment_id": {"type": ["string", "null"]},
                    "jira_key": {"type": ["string", "null"]},
                    "detail": {"type": ["string", "null"]},
                    "evidence_url": {"type": ["string", "null"]},
                    "root_cause": {"type": ["string", "null"]},
                    "root_cause_confirmed": {"type": "boolean"},
                    "reply_status": {"type": ["string", "null"], "enum": ["draft", "published", None]},
                },
                "required": ["event_type", "summary"],
            },
        }
    },
    "required": ["events"],
}


def structure_note(raw_text: str, *, model: str | None = None) -> dict:
    """Use the LLM to parse a natural-language note into structured event drafts. No regex intent matching."""
    prompt = (
        "Parse this work note into one or more work events. Set event_type and a short summary for each. "
        "Fill repo, pr_number, comment_id, root_cause, reply_status when the note states them. "
        "Note: " + raw_text
    )
    for _ in range(2):
        res = _run_cli(prompt, json_schema=_EVENT_DRAFT_SCHEMA, model=model)
        if not res["ok"]:
            return res
        parsed = res.get("structured")
        if parsed is None:
            try:
                parsed = json.loads(res["text"])
            except json.JSONDecodeError:
                continue
        events = parsed.get("events") if isinstance(parsed, dict) else None
        if isinstance(events, list) and events and all(isinstance(event, dict) for event in events):
            return {"ok": True, "events": events}
    return {"ok": False, "error": "Model returned no events after retry."}


def expand_query(question: str, *, model: str | None = None) -> dict:
    """Rewrite a vague question into FTS5 search keywords + optional filters."""
    schema = {
        "type": "object",
        "properties": {
            "keywords": {"type": "string"},
            "repo": {"type": ["string", "null"]},
            "event_type": {"type": ["string", "null"]},
        },
        "required": ["keywords"],
    }
    prompt = (
        "Extract 2-6 full-text search keywords from this question about past work. "
        "Keep Chinese terms. Put them in the keywords field. Question: " + question
    )
    for _ in range(2):
        res = _run_cli(prompt, json_schema=schema, model=model)
        if not res["ok"]:
            return res
        parsed = res.get("structured")
        if parsed is None:
            try:
                parsed = json.loads(res["text"])
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict) and isinstance(parsed.get("keywords"), str) and parsed["keywords"].strip():
            return {"ok": True, **parsed}
    return {"ok": False, "error": "Model returned no keywords after retry."}


def synthesize_narrative(records_markdown: str, period: str, *, model: str | None = None) -> dict:
    """Synthesize a retrospective narrative grounded only in the provided records."""
    prompt = (
        f"Write a concise {period} work retrospective in plain prose only, no tools, no headings. "
        "Base it ONLY on the records below. Highlight meaningful accomplishments and lessons. "
        "If coverage is sparse, say so explicitly; do not fabricate. Records:\n\n" + records_markdown
    )
    res = _run_cli(prompt, model=model, timeout=120)
    if not res["ok"]:
        return res
    if not res["text"].strip():
        return {"ok": False, "error": "CodeBuddy returned an empty narrative. Retry or export Markdown."}
    return {"ok": True, "narrative": res["text"]}
