"""Canonical subject routing shared by subject-aware tools."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


DB_DIR = Path(__file__).resolve().parent
WORKSPACE_ROOT = DB_DIR.parent

SUBJECT_CONFIG_PATH = WORKSPACE_ROOT / "config" / "subjects.json"


def _load_subject_routes() -> dict[str, dict[str, Any]]:
    """Load user-editable subject routes without embedding a user's subjects in code."""
    if not SUBJECT_CONFIG_PATH.is_file():
        raise FileNotFoundError(f"subject configuration not found: {SUBJECT_CONFIG_PATH}")
    raw = json.loads(SUBJECT_CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise ValueError("subjects.json must contain a non-empty object")

    routes: dict[str, dict[str, Any]] = {}
    for subject_id, value in raw.items():
        if not isinstance(subject_id, str) or not isinstance(value, dict):
            raise ValueError("each subject route must be an object keyed by subject_id")
        name = value.get("name")
        directory = value.get("directory")
        aliases = value.get("aliases", [subject_id])
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"subject {subject_id!r} needs a non-empty name")
        if not isinstance(directory, str) or not directory.strip():
            raise ValueError(f"subject {subject_id!r} needs a non-empty directory")
        if not isinstance(aliases, list) or not all(isinstance(item, str) for item in aliases):
            raise ValueError(f"subject {subject_id!r} aliases must be a string list")
        routes[subject_id] = {
            "name": name,
            "directory": directory,
            "exam_type": value.get("exam_type", ""),
            "status": value.get("status", "PROVISIONAL"),
            "aliases": tuple(dict.fromkeys([subject_id, *aliases])),
        }
    return routes


SUBJECT_ROUTES = _load_subject_routes()

SUBJECT_PATH_BASES = (
    Path("02_知识地图"),
    Path("03_学习记录") / "每日",
    Path("04_题库与作答"),
    Path("05_错误与复测"),
    Path("06_复习队列"),
    Path("07_资料库"),
)


def _normalise(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def canonical_subject_id(value: str) -> str:
    """Resolve a subject id or registered display alias without guessing."""
    needle = _normalise(value)
    for subject_id, route in SUBJECT_ROUTES.items():
        if needle in {_normalise(alias) for alias in route["aliases"]}:
            return subject_id
    raise ValueError(
        f"未知科目: {value!r}；可用值为 "
        + ", ".join(sorted(SUBJECT_ROUTES))
    )


def resolve_subject(conn: sqlite3.Connection, value: str) -> dict[str, Any]:
    """Resolve an alias and verify the subject exists in the current database."""
    subject_id = canonical_subject_id(value)
    row = conn.execute(
        "SELECT subject_id, subject_name, exam_type, status "
        "FROM subjects WHERE subject_id = ?",
        (subject_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"科目未登记在当前数据库: {subject_id}")
    route = SUBJECT_ROUTES[subject_id]
    if row["subject_name"] != route["name"]:
        raise ValueError(
            f"科目名称与路由配置不一致: {subject_id} -> {row['subject_name']!r}"
        )
    return {
        "subject_id": row["subject_id"],
        "subject_name": row["subject_name"],
        "exam_type": row["exam_type"],
        "status": row["status"],
        "directory": route["directory"],
    }


def subject_path_status(path: Path, subject_id: str) -> str:
    """Return whether a workspace path belongs to the requested subject."""
    route = SUBJECT_ROUTES[subject_id]
    for base in SUBJECT_PATH_BASES:
        expected = WORKSPACE_ROOT / base / route["directory"]
        try:
            path.relative_to(expected)
            return "ok"
        except ValueError:
            continue

    for base in SUBJECT_PATH_BASES:
        subject_root = WORKSPACE_ROOT / base
        try:
            relative = path.relative_to(subject_root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] in {
            item["directory"] for item in SUBJECT_ROUTES.values()
        }:
            return "wrong_subject"
    return "unrouted"


def route_summary(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return registered subjects with their canonical workspace directories."""
    rows = conn.execute(
        "SELECT subject_id, subject_name, exam_type, status "
        "FROM subjects ORDER BY subject_id"
    ).fetchall()
    summaries = []
    for row in rows:
        route = SUBJECT_ROUTES.get(row["subject_id"])
        summaries.append(
            {
                "subject_id": row["subject_id"],
                "subject_name": row["subject_name"],
                "exam_type": row["exam_type"],
                "status": row["status"],
                "directory": route["directory"] if route else None,
                "route_status": "configured" if route else "unconfigured",
            }
        )
    return summaries
