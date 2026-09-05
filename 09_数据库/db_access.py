"""
通用刷题辅助系统 — 数据库统一访问入口

用法：
    from db_access import get_reader, get_writer, TransactionError

    # 只读查询
    with get_reader() as (conn, cur):
        cur.execute('SELECT ...')
        rows = cur.fetchall()

    # 写入（事务内）
    with get_writer() as (conn, cur):
        cur.execute('UPDATE ...')
        # 提交前自动执行 foreign_key_check 和 quick_check
        # 检查失败自动 ROLLBACK 并抛出 TransactionError

禁止：
    - 不包含删除数据库功能
    - 不包含重建数据库功能
    - 不创建数据库副本
    - 不创建备份
"""

import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get(
    'STUDY_ASSISTANT_DB',
    os.path.join(os.path.dirname(__file__), 'learning_os.db'),
)

PRAGMAS = """
    PRAGMA foreign_keys = ON;
    PRAGMA busy_timeout = 5000;
"""


class TransactionError(Exception):
    """事务执行失败，已回滚"""
    pass


def _get_connection():
    """获取原始连接（内部使用）"""
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(PRAGMAS)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def get_reader():
    """只读查询上下文管理器

    用法：
        with get_reader() as (conn, cur):
            cur.execute('SELECT ...')
            data = cur.fetchall()
    """
    conn = _get_connection()
    cur = conn.cursor()
    try:
        yield (conn, cur)
    finally:
        conn.close()


def _check_integrity(cur):
    """提交前完整性检查"""
    # 外键检查
    cur.execute('PRAGMA foreign_key_check')
    fk_violations = cur.fetchall()
    if fk_violations:
        raise TransactionError(
            f'外键违规：{fk_violations}'
        )

    # 快速完整性检查
    cur.execute('PRAGMA quick_check')
    result = cur.fetchone()[0]
    if result != 'ok':
        raise TransactionError(
            f'quick_check 失败：{result}'
        )


@contextmanager
def get_writer():
    """写入事务上下文管理器

    自动处理：
        - 设置 PRAGMA foreign_keys / busy_timeout
        - BEGIN / COMMIT / ROLLBACK
        - 提交前执行 foreign_key_check + quick_check
        - 检查失败自动 ROLLBACK 并抛出 TransactionError

    用法：
        with get_writer() as (conn, cur):
            cur.execute('INSERT INTO ... VALUES (...)')
            # 退出时自动检查并提交

    禁止在事务外直接调用 conn.commit()
    """
    conn = _get_connection()
    cur = conn.cursor()
    try:
        conn.execute('BEGIN')
        yield (conn, cur)
        # 检查完整性
        _check_integrity(cur)
        conn.commit()
    except TransactionError:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise TransactionError(f'写入异常，已回滚：{e}') from e
    finally:
        conn.close()
