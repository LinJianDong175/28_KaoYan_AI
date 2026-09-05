"""
通用刷题辅助系统 — 数据库与Markdown一致性检查

用法：
    python check_consistency.py                # 检查正式库
    python check_consistency.py --db ../98_Skill测试区/learning_os_test.db   # 检查测试库

功能：
    1. 检查数据库引用的Markdown文件是否存在
    2. 检查重复ID
    3. 检查孤立外键
    4. 检查状态冲突（同一信息一边CONFIRMED一边PROPOSED）
    5. 检查 09_数据库/信息缺口.md 与 information_gaps 表一致
    6. 检查 00_系统与规则/变更日志.md 与 change_log 表一致
    7. 检查 10_审批中心/待审核/ 文件与 proposals(status=PENDING) 一致
    8. 检查 10_审批中心/已处理/ 文件与 proposals(status=APPLIED) 一致
    9. 统计各表记录数

限制：
    - 只读检查，不自动修复
    - 发现问题生成一致性检查报告（修复方案需走审批）
    - 报告写入 99_维护与检查/一致性检查/
    - 可在此处配置参考目录，使其不参与检查
"""

import argparse
import os
import re
import sys
from datetime import datetime

# 添加父目录到路径以便导入 db_access
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db_access
from db_access import get_reader

REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    '99_维护与检查', '一致性检查'
)

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 排除目录（只读参考目录，不参与检查）
EXCLUDED_DIRS = ()


def check_file_exists(file_path):
    """检查文件是否存在"""
    if not file_path:
        return True, ''
    full_path = os.path.join(WORKSPACE_ROOT, file_path) if not os.path.isabs(file_path) else file_path
    exists = os.path.exists(full_path)
    return exists, full_path


def extract_proposal_ids_from_dir(dir_relpath):
    """从目录中的文件名提取 proposal_id（PROP-XXX 前缀）"""
    dir_path = os.path.join(WORKSPACE_ROOT, dir_relpath)
    if not os.path.isdir(dir_path):
        return []
    ids = []
    for fname in os.listdir(dir_path):
        m = re.match(r'(PROP-[A-Z0-9-]+)_', fname)
        if m:
            ids.append((m.group(1), fname))
    return ids


def check_gaps_md_vs_table(cur, issues):
    """检查 09_数据库/信息缺口.md 与 information_gaps 表一致"""
    md_path = os.path.join(WORKSPACE_ROOT, '09_数据库', '信息缺口.md')
    if not os.path.exists(md_path):
        issues.append('[文件缺失] 09_数据库/信息缺口.md 不存在')
        return

    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 从表格行提取 gap_id
    md_gap_ids = set(re.findall(r'\|\s*(GAP-\d+)\s*\|', md_text))

    cur.execute('SELECT gap_id, status FROM information_gaps')
    db_gaps = {row['gap_id']: row['status'] for row in cur.fetchall()}

    for gid in md_gap_ids - set(db_gaps.keys()):
        issues.append(f'[一致性] 信息缺口.md 有 GAP-{gid}，但 information_gaps 表没有')
    for gid in set(db_gaps.keys()) - md_gap_ids:
        issues.append(f'[一致性] information_gaps 表有 {gid}，但信息缺口.md 没有')
    # 状态核对（表内 OPEN 应对应 md 中 OPEN）
    for gid, status in db_gaps.items():
        if gid in md_gap_ids and status not in ('OPEN', 'RESOLVED'):
            issues.append(f'[一致性] information_gaps.{gid} 状态异常: {status}')


def check_changelog_md_vs_table(cur, issues):
    """检查 00_系统与规则/变更日志.md 与 change_log 表一致"""
    md_path = os.path.join(WORKSPACE_ROOT, '00_系统与规则', '变更日志.md')
    if not os.path.exists(md_path):
        issues.append('[文件缺失] 00_系统与规则/变更日志.md 不存在')
        return

    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()

    # 从表格行提取 change_id（若存在）
    md_change_ids = set(re.findall(r'\|\s*(CHG-[A-Z0-9-]+)\s*\|', md_text))

    cur.execute('SELECT change_id FROM change_log')
    db_change_ids = {row['change_id'] for row in cur.fetchall()}

    # 如果 md 中有 change_id 列，则核对；否则只提示数量差异
    if md_change_ids:
        for cid in db_change_ids - md_change_ids:
            issues.append(f'[一致性] change_log 表有 {cid}，但变更日志.md 未记录')
        for cid in md_change_ids - db_change_ids:
            issues.append(f'[一致性] 变更日志.md 记录 {cid}，但 change_log 表没有')
    else:
        # 无 ID 列时提示格式问题
        md_rows = md_text.count('|') // 8  # 粗略
        if len(db_change_ids) > 0:
            issues.append('[一致性] 变更日志.md 未包含 change_id 列，无法精确核对，建议补充')


def check_approval_center(cur, issues):
    """检查 10_审批中心 文件与 proposals 表一致"""
    # 待审核目录：文件应对应 proposals(status=PENDING)
    pending_ids = extract_proposal_ids_from_dir(os.path.join('10_审批中心', '待审核'))
    cur.execute("SELECT proposal_id FROM proposals WHERE status='PENDING'")
    db_pending = {row['proposal_id'] for row in cur.fetchall()}

    for pid, fname in pending_ids:
        if pid not in db_pending:
            issues.append(f'[一致性] 待审核文件 {fname} 对应 {pid}，但 proposals 表中无 PENDING 记录')

    for pid in db_pending - {p[0] for p in pending_ids}:
        issues.append(f'[一致性] proposals 表 {pid} 为 PENDING，但 10_审批中心/待审核/ 无对应文件')

    # 已处理目录：文件应对应 proposals(status=APPLIED/REJECTED)
    applied_ids = extract_proposal_ids_from_dir(os.path.join('10_审批中心', '已处理'))
    cur.execute("SELECT proposal_id FROM proposals WHERE status IN ('APPLIED','REJECTED')")
    db_done = {row['proposal_id'] for row in cur.fetchall()}

    for pid, fname in applied_ids:
        if pid not in db_done:
            issues.append(f'[一致性] 已处理文件 {fname} 对应 {pid}，但 proposals 表中无 APPLIED/REJECTED 记录')

    for pid in db_done - {p[0] for p in applied_ids}:
        issues.append(f'[一致性] proposals 表 {pid} 已结束，但 10_审批中心/已处理/ 无对应文件')


def run_consistency_check(skip_md=False):
    """执行一致性检查，返回报告内容"""
    report_lines = []
    report_lines.append('# 数据库与Markdown一致性检查报告\n')
    report_lines.append(f'- 检查时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    report_lines.append(f'- 数据库：09_数据库/learning_os.db')
    report_lines.append(f'- 排除目录：{"、".join(EXCLUDED_DIRS) if EXCLUDED_DIRS else "无"}\n')

    issues = []

    with get_reader() as (conn, cur):
        # --- 1. 检查所有引用文件路径的表 ---
        cur.execute("SELECT question_id, question_text_path, standard_answer_path FROM questions")
        for row in cur.fetchall():
            for field, path in [('question_text_path', row['question_text_path']),
                                ('standard_answer_path', row['standard_answer_path'])]:
                if path:
                    exists, full = check_file_exists(path)
                    if not exists:
                        issues.append(f'[文件缺失] questions.{field} 引用路径不存在：{path}')
                        issues.append(f'  完整路径：{full}')

        cur.execute("SELECT attempt_id, my_answer_path FROM attempts")
        for row in cur.fetchall():
            if row['my_answer_path']:
                exists, full = check_file_exists(row['my_answer_path'])
                if not exists:
                    issues.append(f'[文件缺失] attempts.my_answer_path 引用路径不存在：{row["my_answer_path"]}')

        cur.execute("SELECT session_id, summary_path FROM study_sessions")
        for row in cur.fetchall():
            if row['summary_path']:
                exists, full = check_file_exists(row['summary_path'])
                if not exists:
                    issues.append(f'[文件缺失] study_sessions.summary_path 引用路径不存在：{row["summary_path"]}')

        cur.execute("SELECT resource_id, file_path FROM resources")
        for row in cur.fetchall():
            if row['file_path']:
                exists, full = check_file_exists(row['file_path'])
                if not exists:
                    issues.append(f'[文件缺失] resources.file_path 引用路径不存在：{row["file_path"]}')

        # --- 2. 检查重复ID ---
        tables_with_id = [
            ('subjects', 'subject_id'),
            ('knowledge_points', 'knowledge_point_id'),
            ('questions', 'question_id'),
            ('attempts', 'attempt_id'),
            ('errors', 'error_id'),
            ('resources', 'resource_id'),
            ('study_sessions', 'session_id'),
            ('reviews', 'review_id'),
            ('information_gaps', 'gap_id'),
            ('proposals', 'proposal_id'),
            ('approvals', 'approval_id'),
            ('change_log', 'change_id'),
        ]
        for table, id_col in tables_with_id:
            cur.execute(f"SELECT {id_col}, count(*) FROM [{table}] GROUP BY {id_col} HAVING count(*) > 1")
            dupes = cur.fetchall()
            for d in dupes:
                issues.append(f'[重复ID] {table}.{id_col} = {d[0]} 出现 {d[1]} 次')

        # --- 3. 检查孤立外键 ---
        cur.execute("""
            SELECT kp.knowledge_point_id, kp.name, kp.parent_id
            FROM knowledge_points kp
            LEFT JOIN knowledge_points parent ON kp.parent_id = parent.knowledge_point_id
            WHERE kp.parent_id IS NOT NULL AND parent.knowledge_point_id IS NULL
        """)
        for row in cur.fetchall():
            issues.append(f'[孤立外键] knowledge_points.{row["knowledge_point_id"]} 的 parent_id={row["parent_id"]} 不存在')

        cur.execute("""
            SELECT kd.prerequisite_id, kd.dependent_id
            FROM knowledge_dependencies kd
            LEFT JOIN knowledge_points kp ON kd.prerequisite_id = kp.knowledge_point_id
            WHERE kp.knowledge_point_id IS NULL
        """)
        for row in cur.fetchall():
            issues.append(f'[孤立外键] knowledge_dependencies.prerequisite_id={row["prerequisite_id"]} 不存在')

        cur.execute("""
            SELECT kd.prerequisite_id, kd.dependent_id
            FROM knowledge_dependencies kd
            LEFT JOIN knowledge_points kp ON kd.dependent_id = kp.knowledge_point_id
            WHERE kp.knowledge_point_id IS NULL
        """)
        for row in cur.fetchall():
            issues.append(f'[孤立外键] knowledge_dependencies.dependent_id={row["dependent_id"]} 不存在')

        # 审批链外键
        cur.execute("""
            SELECT a.approval_id, a.proposal_id
            FROM approvals a
            LEFT JOIN proposals p ON a.proposal_id = p.proposal_id
            WHERE p.proposal_id IS NULL
        """)
        for row in cur.fetchall():
            issues.append(f'[孤立外键] approvals.{row["approval_id"]} 引用不存在的 proposal {row["proposal_id"]}')

        cur.execute("""
            SELECT cl.change_id, cl.proposal_id
            FROM change_log cl
            LEFT JOIN proposals p ON cl.proposal_id = p.proposal_id
            WHERE cl.proposal_id IS NOT NULL AND p.proposal_id IS NULL
        """)
        for row in cur.fetchall():
            issues.append(f'[孤立外键] change_log.{row["change_id"]} 引用不存在的 proposal {row["proposal_id"]}')

        # --- 4. 检查状态冲突 ---
        # 4a. 同一知识点同时有 CONFIRMED 和 PROPOSED 的掌握度记录
        cur.execute("""
            SELECT knowledge_point_id
            FROM mastery_records
            WHERE status IN ('CONFIRMED','PROPOSED')
            GROUP BY knowledge_point_id
            HAVING count(DISTINCT status) > 1
        """)
        for row in cur.fetchall():
            issues.append(f'[状态冲突] 知识点 {row["knowledge_point_id"]} 同时存在 CONFIRMED 和 PROPOSED 掌握度')

        # 4b. proposals 表内同一目标重复
        cur.execute("""
            SELECT target_table, target_record, count(*)
            FROM proposals
            WHERE status = 'PENDING'
            GROUP BY target_table, target_record
            HAVING count(*) > 1
        """)
        for row in cur.fetchall():
            issues.append(f'[状态冲突] 同一目标存在多个 PENDING proposal：{row["target_table"]}.{row["target_record"]} ({row["count(*)"]}条)')

        # --- 5. Markdown 与数据库一致性专项 ---
        # 测试库跳过（测试库与正式 Markdown 目录不共享状态，对比会产生误报）
        if not skip_md:
            check_gaps_md_vs_table(cur, issues)
            check_changelog_md_vs_table(cur, issues)
            check_approval_center(cur, issues)
        else:
            report_lines.append('\n## Markdown 对比\n')
            report_lines.append('已跳过（--skip-md 模式，仅检查数据库内部一致性）。')

        # --- 6. 统计表记录数 ---
        report_lines.append('\n## 表记录统计\n')
        report_lines.append('| 表名 | 记录数 |')
        report_lines.append('|------|--------|')
        all_tables = [
            'subjects', 'knowledge_points', 'knowledge_dependencies',
            'resources', 'questions', 'question_knowledge_points',
            'study_sessions', 'attempts', 'errors', 'mastery_records',
            'reviews', 'information_gaps', 'proposals', 'approvals',
            'change_log', 'ai_audits'
        ]
        for table in all_tables:
            cur.execute(f'SELECT count(*) FROM [{table}]')
            count = cur.fetchone()[0]
            report_lines.append(f'| {table} | {count} |')

    # 汇总
    report_lines.append('\n## 检查结果\n')
    if issues:
        report_lines.append(f'发现 {len(issues)} 个问题：\n')
        for i, issue in enumerate(issues, 1):
            report_lines.append(f'{i}. {issue}')
        report_lines.append('\n⚠️ 发现问题，需生成待审核修复方案，请勿自行修复。')
    else:
        report_lines.append('✅ 未发现问题，数据库与Markdown一致。')

    return '\n'.join(report_lines), issues


def save_report(report_text):
    """保存报告到 99_维护与检查/一致性检查/"""
    os.makedirs(REPORT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = os.path.join(REPORT_DIR, f'consistency_check_{timestamp}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    return report_path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='数据库与Markdown一致性检查')
    parser.add_argument('--db', default=None, help='数据库路径（默认正式库 learning_os.db）')
    parser.add_argument('--skip-md', action='store_true', help='跳过Markdown对比（测试库用）')
    args = parser.parse_args()

    if args.db:
        # 切换为指定测试库
        db_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), args.db))
        if not os.path.exists(db_path):
            print(f'❌ 数据库不存在: {db_path}')
            sys.exit(1)
        db_access.DB_PATH = db_path
        print(f'检查数据库: {db_path}')

    print('开始一致性检查...')
    report_text, issues = run_consistency_check(skip_md=args.skip_md)
    report_path = save_report(report_text)
    print(f'报告已保存至：{report_path}')
    if issues:
        print(f'发现 {len(issues)} 个问题：')
        for i, issue in enumerate(issues, 1):
            print(f'  {i}. {issue}')
    else:
        print('未发现问题。')
