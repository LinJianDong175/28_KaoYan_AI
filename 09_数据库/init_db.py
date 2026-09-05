"""Create a local SQLite database from schema.sql.

The database is intentionally generated locally and is ignored by Git.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DB_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DB_DIR / "schema.sql"
DEFAULT_DB_PATH = DB_DIR / "learning_os.db"
SUBJECT_CONFIG_PATH = DB_DIR.parent / "config" / "subjects.json"


def initialise(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        routes = json.loads(SUBJECT_CONFIG_PATH.read_text(encoding="utf-8"))
        for subject_id, route in routes.items():
            conn.execute(
                """INSERT OR IGNORE INTO subjects
                   (subject_id, subject_name, exam_type, status)
                   VALUES (?, ?, ?, ?)""",
                (
                    subject_id,
                    route["name"],
                    route.get("exam_type", ""),
                    route.get("status", "PROVISIONAL"),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="从 schema.sql 初始化本地数据库")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="数据库输出路径")
    args = parser.parse_args()
    db_path = args.db.expanduser().resolve()
    initialise(db_path)
    print(f"数据库已初始化：{db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
