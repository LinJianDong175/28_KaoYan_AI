"""
通用刷题辅助系统 — 数据库完整性检查

用法：
    python db_integrity_check.py                # 检查正式库
    python db_integrity_check.py --db ../98_Skill测试区/learning_os_test.db   # 检查测试库

功能：
    1. PRAGMA integrity_check（深度完整性）
    2. PRAGMA quick_check（快速完整性）
    3. PRAGMA foreign_key_check（外键违规）
    4. 生成报告到 99_维护与检查/数据库检查/

限制：
    - 只读检查，不自动修复
    - 检查失败时生成异常报告，不删除、不重建数据库
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db_access
from db_access import get_reader

REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    '99_维护与检查', '数据库检查'
)


def run_integrity_check():
    """执行完整性检查，返回 (报告文本, 是否有问题)"""
    report_lines = []
    report_lines.append('# 数据库完整性检查报告\n')
    report_lines.append(f'- 检查时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    report_lines.append('- 数据库：09_数据库/learning_os.db\n')

    problems = []

    with get_reader() as (conn, cur):
        # 1. integrity_check
        cur.execute('PRAGMA integrity_check')
        result = cur.fetchall()
        ok = all(r[0] == 'ok' for r in result)
        report_lines.append('## 1. PRAGMA integrity_check（深度完整性）\n')
        report_lines.append(f'结果：{"✅ ok" if ok else "❌ 异常"}')
        if not ok:
            for r in result:
                report_lines.append(f'- {r[0]}')
                problems.append(f'integrity_check: {r[0]}')

        # 2. quick_check
        cur.execute('PRAGMA quick_check')
        qc = cur.fetchone()[0]
        report_lines.append('\n## 2. PRAGMA quick_check（快速完整性）\n')
        report_lines.append(f'结果：{"✅ ok" if qc == "ok" else "❌ 异常"}')
        if qc != 'ok':
            problems.append(f'quick_check: {qc}')

        # 3. foreign_key_check
        cur.execute('PRAGMA foreign_key_check')
        fk = cur.fetchall()
        report_lines.append('\n## 3. PRAGMA foreign_key_check（外键违规）\n')
        if fk:
            report_lines.append(f'结果：❌ 发现 {len(fk)} 处外键违规\n')
            for row in fk:
                report_lines.append(f'- 表 {row[0]}，行 {row[1]}，外键 {row[2]}，父表 {row[3]}')
                problems.append(f'foreign_key_check: {tuple(row)}')
        else:
            report_lines.append('结果：✅ 0 处外键违规')

        # 4. 表级快速检查（可选，全部表跑 quick_check 各表）
        report_lines.append('\n## 4. 各表记录数\n')
        report_lines.append('| 表名 | 记录数 |')
        report_lines.append('|------|--------|')
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            cur.execute(f'SELECT count(*) FROM [{t}]')
            report_lines.append(f'| {t} | {cur.fetchone()[0]} |')

    report_lines.append('\n## 结论\n')
    if problems:
        report_lines.append(f'❌ 发现 {len(problems)} 个问题：')
        for i, p in enumerate(problems, 1):
            report_lines.append(f'{i}. {p}')
        report_lines.append('\n⚠️ 已停止正式写入，生成异常报告。不删除、不重建数据库。修复方案需提交待审核。')
    else:
        report_lines.append('✅ 数据库完整性正常。')

    return '\n'.join(report_lines), problems


def save_report(report_text, subdir=''):
    """保存报告到 99_维护与检查/数据库检查/"""
    target = os.path.join(REPORT_DIR, subdir) if subdir else REPORT_DIR
    os.makedirs(target, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = os.path.join(target, f'db_integrity_check_{timestamp}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    return report_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='数据库完整性检查')
    parser.add_argument('--db', default=None, help='数据库路径（默认正式库 learning_os.db）')
    args = parser.parse_args()

    if args.db:
        db_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), args.db))
        if not os.path.exists(db_path):
            print(f'❌ 数据库不存在: {db_path}')
            sys.exit(1)
        db_access.DB_PATH = db_path
        print(f'检查数据库: {db_path}')

    print('开始数据库完整性检查...')
    report_text, problems = run_integrity_check()
    report_path = save_report(report_text)
    print(f'报告已保存至：{report_path}')
    if problems:
        print(f'发现 {len(problems)} 个问题：')
        for i, p in enumerate(problems, 1):
            print(f'  {i}. {p}')
    else:
        print('数据库完整性正常。')
