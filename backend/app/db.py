"""极简 SQLite 访问层（无 ORM）。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # backend/
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.environ.get(
    "CRC_DB_PATH", os.path.join(DATA_DIR, "clarifier.db")
)
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        script = f.read()
    with get_connection() as conn:
        conn.executescript(script)
        # 最小迁移：老库补 confirmed_at 列（澄清闭环新增字段）
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(requirements)")}
        if "confirmed_at" not in cols:
            conn.execute("ALTER TABLE requirements ADD COLUMN confirmed_at TEXT")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return {} if default is None else default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {} if default is None else default
