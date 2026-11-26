from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from workledger.db import get_connection
from workledger.routers import sync as sync_router
from workledger.services import sync, sync_state


@pytest.fixture()
def client(monkeypatch, db_path):
    app = FastAPI()
    app.include_router(sync_router.router, prefix="/api")
    monkeypatch.setattr(sync_router, "_conn", lambda: get_connection(db_path))
    with TestClient(app) as c:
        yield c


def test_health_ok_with_stale_sync(client, db_path):
    conn = get_connection(db_path)
    sync_state.record_success(conn, "jira", {})
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] >= 10
    assert body["sync"]["jira"]["stale"] is False
    assert body["sync"]["jira"]["last_sync_at"] is not None


def test_sync_status_lists_sources(client, db_path):
    conn = get_connection(db_path)
    sync_state.record_error(conn, "bitbucket:transfinderorg/core", "boom")
    body = client.get("/api/sync/status").json()
    assert body["bitbucket:transfinderorg/core"]["last_error"] == "boom"
    assert body["bitbucket:transfinderorg/core"]["stale"] is True


def test_trigger_jira_success_and_failure(client, monkeypatch):
    monkeypatch.setattr(sync.sync_jira, "sync_jira", lambda conn, **kw: {"source": "jira", "ok": True, "created": 1})
    assert client.post("/api/sync/jira").json()["created"] == 1
    monkeypatch.setattr(sync.sync_jira, "sync_jira", lambda conn, **kw: {"source": "jira", "ok": False, "error": "twg down"})
    response = client.post("/api/sync/jira")
    assert response.status_code == 502


def test_trigger_busy_returns_409(client):
    lock = sync._lock("jira")
    lock.acquire()
    try:
        assert client.post("/api/sync/jira").status_code == 409
    finally:
        lock.release()


def test_sync_all_busy_returns_409(client, monkeypatch):
    monkeypatch.setattr(sync.sync_bitbucket, "sync_bitbucket", lambda conn, **kw: {"ok": True, "repos": {}})
    lock = sync._lock("jira")
    lock.acquire()
    try:
        assert client.post("/api/sync").status_code == 409
    finally:
        lock.release()


def test_background_loop_uses_worker_thread_connection_and_survives_failure(tmp_path, monkeypatch):
    import asyncio

    from workledger import app as web

    monkeypatch.setattr(web.settings, "workledger_data_dir", str(tmp_path / "loop"))
    monkeypatch.setattr(web.settings, "sync_interval_minutes", 1)
    calls = []

    def fake_sync_all(conn):
        conn.execute("SELECT 1")  # worker 线程连接必须可用（跨线程会 ProgrammingError）
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return {"ok": True}

    monkeypatch.setattr(sync, "sync_all", fake_sync_all)
    real_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        fast_sleep.n += 1
        if fast_sleep.n >= 3:
            raise asyncio.CancelledError
        await real_sleep(0)
    fast_sleep.n = 0
    monkeypatch.setattr(web.asyncio, "sleep", fast_sleep)

    async def run():
        task = asyncio.create_task(web._sync_loop())
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    assert len(calls) == 2  # 第一次失败后循环存活并完成第二次
