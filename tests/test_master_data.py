"""Tests for master data: projects and sprints."""
from __future__ import annotations

import pytest

from workledger.db import DatabaseError
from workledger.services import master_data


class TestProjects:
    def test_create_and_get(self, conn):
        p = master_data.create_project(conn, name="WorkLedger", key="wl", repo="org/wl")
        assert p["key"] == "WL"  # uppercased
        assert master_data.get_project(conn, p["id"])["name"] == "WorkLedger"

    def test_duplicate_key_rejected(self, conn):
        master_data.create_project(conn, name="A", key="DUP")
        with pytest.raises(DatabaseError, match="already exists"):
            master_data.create_project(conn, name="B", key="dup")

    def test_list_excludes_archived(self, conn):
        p = master_data.create_project(conn, name="A", key="A")
        master_data.update_project(conn, p["id"], is_archived=True)
        active = master_data.list_projects(conn)
        all_p = master_data.list_projects(conn, include_archived=True)
        assert len(active) == 0
        assert len(all_p) == 1

    def test_update(self, conn):
        p = master_data.create_project(conn, name="A", key="A")
        upd = master_data.update_project(conn, p["id"], name="Renamed", color="#ff0000")
        assert upd["name"] == "Renamed"
        assert upd["color"] == "#ff0000"

    def test_delete(self, conn):
        p = master_data.create_project(conn, name="A", key="A")
        assert master_data.delete_project(conn, p["id"])
        assert master_data.get_project(conn, p["id"]) is None


class TestSprints:
    def test_create_requires_project(self, conn):
        with pytest.raises(DatabaseError, match="not found"):
            master_data.create_sprint(conn, project_id=999, name="S1", start_date="2026-11-01", end_date="2026-11-14")

    def test_create_and_list(self, conn):
        p = master_data.create_project(conn, name="A", key="A")
        s = master_data.create_sprint(conn, project_id=p["id"], name="S1", start_date="2026-11-01", end_date="2026-11-14", goal="ship")
        assert s["status"] == "planned"
        assert len(master_data.list_sprints(conn, project_id=p["id"])) == 1

    def test_activate_deactivates_others(self, conn):
        p = master_data.create_project(conn, name="A", key="A")
        s1 = master_data.create_sprint(conn, project_id=p["id"], name="S1", start_date="2026-11-01", end_date="2026-11-14", status="active")
        s2 = master_data.create_sprint(conn, project_id=p["id"], name="S2", start_date="2026-11-15", end_date="2026-11-28")
        master_data.update_sprint(conn, s2["id"], status="active")
        assert master_data.get_sprint(conn, s1["id"])["status"] == "planned"
        assert master_data.get_sprint(conn, s2["id"])["status"] == "active"

    def test_delete(self, conn):
        p = master_data.create_project(conn, name="A", key="A")
        s = master_data.create_sprint(conn, project_id=p["id"], name="S1", start_date="2026-11-01", end_date="2026-11-14")
        assert master_data.delete_sprint(conn, s["id"])
        assert master_data.get_sprint(conn, s["id"]) is None