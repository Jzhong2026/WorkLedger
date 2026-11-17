"""Shared test fixtures."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from workledger.db import close_connection, init_db


@pytest.fixture()
def db_path(tmp_path):
    path = tmp_path / "test.db"
    init_db(path)
    yield path
    close_connection(path)


@pytest.fixture()
def conn(db_path):
    from workledger.db import get_connection
    return get_connection(db_path)