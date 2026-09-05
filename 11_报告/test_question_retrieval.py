"""Acceptance tests using only generated databases and synthetic text."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
DB_DIR = WORKSPACE_ROOT / "09_数据库"
SCHEMA_PATH = DB_DIR / "schema.sql"
TEST_DIR = WORKSPACE_ROOT / "98_Skill测试区" / "临时"
SYNTHETIC_QUESTION = "98_Skill测试区/测试数据/Q-TEST-001_极限_第一个重要极限.md"
sys.path.insert(0, str(DB_DIR))

from question_retrieval import retrieve_from_connection, retrieve_questions  # noqa: E402


class QuestionRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_DIR.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix="retrieval_", suffix=".db", dir=TEST_DIR)
        os.close(handle)
        self.db_path = Path(name)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(
            f"""
            INSERT INTO subjects VALUES ('math1', '数学一', '统考', 'PROVISIONAL');
            INSERT INTO subjects VALUES ('english1', '英语一', '统考', 'PROVISIONAL');
            INSERT INTO subjects VALUES ('major_pending', '专业课（待确定）', '自命题', 'PENDING');
            INSERT INTO knowledge_points
                (knowledge_point_id, subject_id, name, status)
            VALUES ('KP-M', 'math1', '重要极限', 'CONFIRMED');
            INSERT INTO questions
                (question_id, subject_id, question_text_path, status)
            VALUES ('Q-TEST-001', 'math1', '{SYNTHETIC_QUESTION}', 'CONFIRMED');
            INSERT INTO question_knowledge_points
                (question_id, knowledge_point_id, status)
            VALUES ('Q-TEST-001', 'KP-M', 'CONFIRMED');
            INSERT INTO attempts
                (attempt_id, question_id, attempt_time, my_answer_path, status)
            VALUES ('ATT-TEST-001', 'Q-TEST-001', '2026-01-01 12:00:00',
                    '98_Skill测试区/测试数据/MY-ANSWER-TEST-001.md', 'CONFIRMED');
            INSERT INTO errors
                (error_id, attempt_id, surface_error, status)
            VALUES ('ERR-TEST-001', 'ATT-TEST-001', '测试错误', 'CONFIRMED');
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.db_path.unlink(missing_ok=True)

    def test_retrieves_confirmed_history(self):
        payload = retrieve_questions("math1", knowledge_point_id="KP-M", db_path=str(self.db_path))
        self.assertEqual(["Q-TEST-001"], [item["question_id"] for item in payload["results"]])
        self.assertEqual("CONFIRMED", payload["results"][0]["evidence_status"])
        self.assertEqual(1, len(payload["results"][0]["attempts"]))
        self.assertEqual(1, len(payload["results"][0]["errors"]))

    def test_text_retrieval_and_subject_alias(self):
        by_id = retrieve_questions("math1", query_text="重要极限", db_path=str(self.db_path))
        by_name = retrieve_questions("数学一", query_text="sin x / x", db_path=str(self.db_path))
        self.assertEqual("Q-TEST-001", by_id["results"][0]["question_id"])
        self.assertEqual("Q-TEST-001", by_name["results"][0]["question_id"])
        self.assertEqual("数学一", by_name["query"]["subject_name"])

    def test_subject_filter_prevents_cross_subject_results(self):
        conn = self._memory_db()
        try:
            conn.executescript(
                """
                INSERT INTO subjects VALUES ('math1', '数学一', '统考', 'PROVISIONAL');
                INSERT INTO subjects VALUES ('english1', '英语一', '统考', 'PROVISIONAL');
                INSERT INTO questions (question_id, subject_id, status)
                VALUES ('Q-M', 'math1', 'CONFIRMED'), ('Q-E', 'english1', 'CONFIRMED');
                """
            )
            self.assertEqual(["Q-M"], [x["question_id"] for x in retrieve_from_connection(conn, "math1")["results"]])
            self.assertEqual(["Q-E"], [x["question_id"] for x in retrieve_from_connection(conn, "english1")["results"]])
        finally:
            conn.close()

    def test_pending_subject_has_placeholder_route(self):
        payload = retrieve_questions("专业课", db_path=str(self.db_path))
        self.assertEqual("major_pending", payload["query"]["subject_id"])
        self.assertEqual("专业课_待确定", payload["query"]["subject_directory"])
        self.assertEqual([], payload["results"])

    def test_proposed_error_is_notice_only(self):
        conn = self._memory_db()
        try:
            conn.executescript(
                """
                INSERT INTO subjects VALUES ('math1', '数学一', '统考', 'PROVISIONAL');
                INSERT INTO questions (question_id, subject_id, status)
                VALUES ('Q-1', 'math1', 'CONFIRMED');
                INSERT INTO attempts (attempt_id, question_id, attempt_time, status)
                VALUES ('ATT-1', 'Q-1', '2026-01-01', 'CONFIRMED');
                INSERT INTO errors (error_id, attempt_id, surface_error, status)
                VALUES ('ERR-PROP', 'ATT-1', '候选错误', 'PROPOSED');
                """
            )
            payload = retrieve_from_connection(conn, "math1")
            self.assertEqual([], payload["results"][0]["errors"])
            self.assertEqual("ERR-PROP", payload["proposed_notices"][0]["reference_id"])
        finally:
            conn.close()

    def test_unknown_subject_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知科目"):
            retrieve_questions("物理", db_path=str(self.db_path))

    def test_database_and_outside_paths_are_not_read(self):
        conn = self._memory_db()
        try:
            conn.executescript(
                """
                INSERT INTO subjects VALUES ('math1', '数学一', '统考', 'PROVISIONAL');
                INSERT INTO questions
                    (question_id, subject_id, question_text_path, status)
                VALUES
                    ('Q-DB', 'math1', '09_数据库/learning_os.db', 'CONFIRMED'),
                    ('Q-OUT', 'math1', 'C:/Windows/System32/drivers/etc/hosts', 'CONFIRMED');
                """
            )
            payload = retrieve_from_connection(conn, "math1")
            statuses = {x["question_id"]: x["question_text_status"] for x in payload["results"]}
            self.assertEqual("unsupported", statuses["Q-DB"])
            self.assertEqual("outside_workspace", statuses["Q-OUT"])
        finally:
            conn.close()

    def test_external_database_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "inside the workspace"):
            retrieve_questions("math1", db_path="C:/not-a-workspace-db.db")

    @staticmethod
    def _memory_db() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn


if __name__ == "__main__":
    unittest.main(verbosity=2)
