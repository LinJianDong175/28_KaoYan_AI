"""Read-only retrieval of historical questions and confirmed evidence."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from db_access import get_reader
from subject_routing import (
    WORKSPACE_ROOT,
    resolve_subject,
    subject_path_status,
)


DB_DIR = Path(__file__).resolve().parent
QUERY_PATH = DB_DIR / "queries" / "question_retrieval.sql"
EXCLUDED_TOP_LEVEL: set[str] = set()
TEST_TOP_LEVEL = "98_Skill测试区"
READABLE_TEXT_SUFFIXES = {".md", ".txt"}
MAX_TEXT_BYTES = 2 * 1024 * 1024
EXPECTED_QUERIES = {"confirmed_candidates", "proposed_notices"}


def load_queries(path: Path = QUERY_PATH) -> dict[str, str]:
    """Load SQL blocks marked with ``-- query: name``."""
    text = path.read_text(encoding="utf-8")
    marker = re.compile(r"^-- query:\s*([a-z_][a-z0-9_]*)\s*$", re.MULTILINE)
    matches = list(marker.finditer(text))
    queries: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sql = text[start:end].strip()
        if sql:
            queries[match.group(1)] = sql

    missing = EXPECTED_QUERIES - set(queries)
    if missing:
        raise ValueError(f"SQL query blocks missing: {', '.join(sorted(missing))}")
    return queries


@contextmanager
def open_reader(db_path: str | None = None) -> Iterator[sqlite3.Connection]:
    """Open the formal database through db_access, or a workspace test DB read-only."""
    if db_path is None:
        with get_reader() as (conn, cur):
            cur.execute("PRAGMA query_only = ON")
            yield conn
        return

    resolved = Path(db_path).expanduser().resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError as exc:
        raise ValueError("--db must point to a database inside the workspace") from exc
    if not resolved.is_file():
        raise FileNotFoundError(f"database not found: {resolved}")

    uri = f"{resolved.as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA query_only = ON")
        yield conn
    finally:
        conn.close()


def _path_status(
    path_value: str | None,
    subject_id: str | None = None,
    allow_test_data: bool = False,
) -> tuple[Path | None, str]:
    """Classify a referenced path before any file content is read."""
    if not path_value:
        return None, "empty"

    path = Path(path_value)
    if not path.is_absolute():
        path = WORKSPACE_ROOT / path
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(WORKSPACE_ROOT)
    except (OSError, ValueError):
        return None, "outside_workspace"

    if relative.parts and relative.parts[0] in EXCLUDED_TOP_LEVEL:
        return resolved, "excluded"
    if relative.parts and relative.parts[0] == TEST_TOP_LEVEL:
        if not allow_test_data:
            return resolved, "test_data_not_allowed"
        in_scope = True
    else:
        in_scope = False
    if resolved.suffix.lower() not in READABLE_TEXT_SUFFIXES:
        return resolved, "unsupported"
    if not resolved.is_file():
        return resolved, "missing"
    if subject_id and not in_scope:
        route_status = subject_path_status(resolved, subject_id)
        if route_status != "ok":
            return resolved, route_status
    try:
        if resolved.stat().st_size > MAX_TEXT_BYTES:
            return resolved, "too_large"
        return resolved, "ok"
    except (OSError, UnicodeError):
        return resolved, "read_error"


def _safe_text(
    path_value: str | None,
    subject_id: str | None = None,
    allow_test_data: bool = False,
) -> tuple[str, str]:
    """Read a referenced Markdown/TXT file only after path checks pass."""
    resolved, status = _path_status(path_value, subject_id, allow_test_data)
    if status != "ok" or resolved is None:
        return "", status
    try:
        return resolved.read_text(encoding="utf-8"), "ok"
    except (OSError, UnicodeError):
        return "", "read_error"


def _normalise(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").casefold()).strip()


def _terms(query_text: str) -> list[str]:
    terms = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]{2,}", _normalise(query_text))
    return list(dict.fromkeys(terms))


def _text_score(query_text: str, fields: list[str | None]) -> tuple[int, list[str]]:
    query = _normalise(query_text)
    if not query:
        return 0, []

    haystack = "\n".join(_normalise(field) for field in fields if field)
    compact_query = re.sub(r"\s+", "", query)
    compact_haystack = re.sub(r"\s+", "", haystack)
    reasons: list[str] = []
    score = 0
    if query in haystack or (compact_query and compact_query in compact_haystack):
        score += 30
        reasons.append("题目文本完整命中")

    matched_terms = [term for term in _terms(query) if term in haystack]
    if matched_terms:
        score += min(20, 5 * len(matched_terms))
        reasons.append("关键词命中:" + ",".join(matched_terms[:4]))
    return score, reasons


def _new_question(
    row: sqlite3.Row,
    subject_id: str,
    allow_test_data: bool,
) -> dict[str, Any]:
    question_text, text_status = _safe_text(
        row["question_text_path"], subject_id, allow_test_data
    )
    return {
        "question_id": row["question_id"],
        "subject_id": row["subject_id"],
        "source_resource_id": row["source_resource_id"],
        "resource_title": row["resource_title"],
        "question_type": row["question_type"],
        "difficulty": row["difficulty"],
        "question_text_path": row["question_text_path"],
        "standard_answer_path": row["standard_answer_path"],
        "question_text_status": text_status,
        "standard_answer_path_status": _path_status(
            row["standard_answer_path"], subject_id, allow_test_data
        )[1],
        "_question_text": question_text,
        "knowledge_points": {},
        "attempts": {},
        "errors": {},
    }


def _aggregate(
    rows: list[sqlite3.Row],
    subject_id: str,
    allow_test_data: bool,
) -> list[dict[str, Any]]:
    questions: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = questions.get(row["question_id"])
        if item is None:
            item = _new_question(row, subject_id, allow_test_data)
            questions[row["question_id"]] = item

        if row["knowledge_point_id"]:
            item["knowledge_points"][row["knowledge_point_id"]] = {
                "knowledge_point_id": row["knowledge_point_id"],
                "name": row["knowledge_point_name"],
                "weight": row["knowledge_point_weight"],
                "status": "CONFIRMED",
            }
        if row["attempt_id"]:
            item["attempts"][row["attempt_id"]] = {
                "attempt_id": row["attempt_id"],
                "attempt_time": row["attempt_time"],
                "my_answer_path": row["my_answer_path"],
                "my_answer_path_status": _path_status(
                    row["my_answer_path"], subject_id, allow_test_data
                )[1],
                "is_correct": row["is_correct"],
                "score": row["score"],
                "duration_seconds": row["duration_seconds"],
                "hint_count": row["hint_count"],
                "independent": row["independent"],
                "viewed_answer": row["viewed_answer"],
                "status": "CONFIRMED",
            }
        if row["error_id"]:
            item["errors"][row["error_id"]] = {
                "error_id": row["error_id"],
                "attempt_id": row["attempt_id"],
                "surface_error": row["surface_error"],
                "direct_cause": row["direct_cause"],
                "root_cause": row["root_cause"],
                "correction_action": row["correction_action"],
                "confidence": row["error_confidence"],
                "resolved": bool(row["error_resolved"]),
                "status": "CONFIRMED",
            }
    return list(questions.values())


def _rank(
    questions: list[dict[str, Any]],
    knowledge_point_id: str | None,
    query_text: str,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for item in questions:
        score = 0
        reasons: list[str] = []
        knowledge_points = list(item["knowledge_points"].values())
        errors = list(item["errors"].values())

        if knowledge_point_id and knowledge_point_id in item["knowledge_points"]:
            score += 100
            reasons.append("相同CONFIRMED知识点")

        unresolved = sum(1 for error in errors if not error["resolved"])
        resolved = len(errors) - unresolved
        if unresolved:
            score += 40
            reasons.append(f"{unresolved}个未解决CONFIRMED错误")
        elif resolved:
            score += 15
            reasons.append(f"{resolved}个已解决CONFIRMED错误")

        text_fields = [item.pop("_question_text")]
        text_fields.extend(kp["name"] for kp in knowledge_points)
        for error in errors:
            text_fields.extend(
                [error["surface_error"], error["direct_cause"], error["root_cause"]]
            )
        text_score, text_reasons = _text_score(query_text, text_fields)
        score += text_score
        reasons.extend(text_reasons)

        if query_text and not knowledge_point_id and text_score == 0:
            continue

        attempts = sorted(
            item["attempts"].values(),
            key=lambda value: value["attempt_time"] or "",
            reverse=True,
        )
        item["knowledge_points"] = knowledge_points
        item["attempts"] = attempts
        item["errors"] = errors
        item["score"] = score
        item["match_reasons"] = reasons or ["科目内历史题目"]
        item["evidence_status"] = "CONFIRMED"
        item["latest_attempt_time"] = attempts[0]["attempt_time"] if attempts else None
        ranked.append(item)

    ranked.sort(
        key=lambda item: (item["score"], item["latest_attempt_time"] or "", item["question_id"]),
        reverse=True,
    )
    return ranked


def retrieve_from_connection(
    conn: sqlite3.Connection,
    subject_id: str,
    knowledge_point_id: str | None = None,
    query_text: str = "",
    error_only: bool = False,
    limit: int = 10,
    allow_test_data: bool = False,
) -> dict[str, Any]:
    """Retrieve and rank confirmed history from an existing read-only connection."""
    if not subject_id or not subject_id.strip():
        raise ValueError("subject_id is required")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    conn.row_factory = sqlite3.Row
    subject = resolve_subject(conn, subject_id)
    queries = load_queries()
    params = {
        "subject_id": subject["subject_id"],
        "knowledge_point_id": knowledge_point_id or None,
        "error_only": int(error_only),
    }
    confirmed_rows = conn.execute(queries["confirmed_candidates"], params).fetchall()
    notice_rows = conn.execute(queries["proposed_notices"], params).fetchall()
    ranked = _rank(
        _aggregate(confirmed_rows, subject["subject_id"], allow_test_data),
        knowledge_point_id,
        query_text,
    )[:limit]

    notices = [dict(row) for row in notice_rows]
    if query_text and not knowledge_point_id:
        relevant_question_ids = {item["question_id"] for item in ranked}
        notices = [
            notice for notice in notices if notice["question_id"] in relevant_question_ids
        ]
    return {
        "query": {
            "subject_id": subject["subject_id"],
            "subject_name": subject["subject_name"],
            "subject_status": subject["status"],
            "subject_directory": subject["directory"],
            "knowledge_point_id": knowledge_point_id,
            "query_text": query_text,
            "error_only": error_only,
            "limit": limit,
        },
        "summary": {
            "confirmed_results": len(ranked),
            "proposed_notices": len(notices),
            "message": "检索完成" if ranked else "暂无相关个人历史证据",
        },
        "results": ranked,
        "proposed_notices": notices,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "database_mode": "read_only",
        "subject_route": subject,
    }


def retrieve_questions(
    subject_id: str,
    knowledge_point_id: str | None = None,
    query_text: str = "",
    error_only: bool = False,
    limit: int = 10,
    db_path: str | None = None,
) -> dict[str, Any]:
    allow_test_data = False
    if db_path is not None:
        resolved_db = Path(db_path).expanduser().resolve()
        try:
            relative_db = resolved_db.relative_to(WORKSPACE_ROOT)
            allow_test_data = bool(relative_db.parts and relative_db.parts[0] == TEST_TOP_LEVEL)
        except ValueError:
            pass
    with open_reader(db_path) as conn:
        return retrieve_from_connection(
            conn,
            subject_id=subject_id,
            knowledge_point_id=knowledge_point_id,
            query_text=query_text,
            error_only=error_only,
            limit=limit,
            allow_test_data=allow_test_data,
        )


def to_markdown(payload: dict[str, Any]) -> str:
    query = payload["query"]
    lines = [
        "# 题目与知识点检索结果",
        "",
        f"- 科目：{query['subject_name']}（{query['subject_id']}）",
        f"- 科目状态：{query['subject_status']}",
        f"- 科目目录：{query['subject_directory']}",
        f"- 知识点：{query['knowledge_point_id'] or '未指定'}",
        f"- 查询文本：{query['query_text'] or '未指定'}",
        f"- 结果：{payload['summary']['message']}",
        "",
    ]
    for index, item in enumerate(payload["results"], 1):
        lines.extend(
            [
                f"## {index}. {item['question_id']}（{item['score']}分）",
                "",
                f"- 命中原因：{'；'.join(item['match_reasons'])}",
                f"- 题目路径：{item['question_text_path'] or '无'}",
                f"- 文本状态：{item['question_text_status']}",
                f"- 标准答案路径状态：{item['standard_answer_path_status']}",
                f"- CONFIRMED知识点：{', '.join(kp['name'] or kp['knowledge_point_id'] for kp in item['knowledge_points']) or '无'}",
                f"- CONFIRMED作答：{len(item['attempts'])} 条",
                f"- CONFIRMED错误：{len(item['errors'])} 条",
                "",
            ]
        )
    if payload["proposed_notices"]:
        lines.extend(["## 待审核提醒", ""])
        for notice in payload["proposed_notices"]:
            lines.append(
                f"- {notice['question_id']} / {notice['notice_type']} / "
                f"{notice['reference_id']}：{notice['detail']}（PROPOSED，不作为事实）"
            )
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="只读检索历史题目与已确认证据")
    parser.add_argument("--subject", required=True, help="subject_id，例如 math1")
    parser.add_argument("--knowledge-point", default=None, help="可选 knowledge_point_id")
    parser.add_argument("--text", default="", help="当前题目的关键词、公式或题型描述")
    parser.add_argument("--error-only", action="store_true", help="仅返回带 CONFIRMED 错误的题目")
    parser.add_argument("--limit", type=int, default=10, help="返回数量，1-100")
    parser.add_argument("--db", default=None, help="工作区内测试数据库路径；省略时使用正式库")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args()

    try:
        result = retrieve_questions(
            subject_id=args.subject,
            knowledge_point_id=args.knowledge_point,
            query_text=args.text,
            error_only=args.error_only,
            limit=args.limit,
            db_path=args.db,
        )
    except (FileNotFoundError, ValueError, sqlite3.Error) as exc:
        parser.exit(2, f"检索失败：{exc}\n")

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(to_markdown(result), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
