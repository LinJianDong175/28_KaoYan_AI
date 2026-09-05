-- 通用刷题辅助系统 - 当前题目个人历史查询
-- 用法：通过 db_access.get_reader() 逐条执行
-- 必需参数：:subject_id 和 :knowledge_point_id
-- 说明：knowledge_point_id 是当前分析得到的候选值；查询结果为空时不得推断用户水平。

-- 1. 核对候选知识点是否为该科目的 CONFIRMED 记录
SELECT
    kp.knowledge_point_id,
    kp.subject_id,
    kp.parent_id,
    kp.name,
    kp.description,
    kp.status
FROM knowledge_points kp
WHERE kp.knowledge_point_id = :knowledge_point_id
  AND kp.subject_id = :subject_id
  AND kp.status = 'CONFIRMED';

-- 2. 当前知识点的已确认掌握证据
SELECT
    m.mastery_record_id,
    m.mastery_level,
    m.evidence_type,
    m.evidence_score,
    m.independent,
    m.delayed_retest,
    m.transfer_success,
    m.confidence,
    m.assessment_time
FROM mastery_records m
WHERE m.knowledge_point_id = :knowledge_point_id
  AND m.status = 'CONFIRMED'
ORDER BY m.assessment_time DESC
LIMIT 5;

-- 3. 相同知识点上的历史题目和客观作答证据
SELECT
    q.question_id,
    q.question_type,
    q.difficulty,
    q.question_text_path,
    q.standard_answer_path,
    a.attempt_id,
    a.attempt_time,
    a.my_answer_path,
    a.is_correct,
    a.score,
    a.duration_seconds,
    a.hint_count,
    a.independent,
    a.viewed_answer,
    a.confidence_before,
    a.confidence_after
FROM question_knowledge_points qkp
JOIN questions q ON q.question_id = qkp.question_id
JOIN attempts a ON a.question_id = q.question_id
WHERE qkp.knowledge_point_id = :knowledge_point_id
  AND qkp.status = 'CONFIRMED'
  AND q.status = 'CONFIRMED'
  AND a.status = 'CONFIRMED'
ORDER BY a.attempt_time DESC
LIMIT 20;

-- 4. 相同知识点上的已确认错误；resolved 同时返回，避免把已解决问题说成未解决
SELECT
    q.question_id,
    q.question_text_path,
    a.attempt_id,
    a.attempt_time,
    e.error_id,
    e.surface_error,
    e.direct_cause,
    e.root_cause,
    e.correction_action,
    e.confidence,
    e.resolved
FROM errors e
JOIN attempts a ON a.attempt_id = e.attempt_id
JOIN questions q ON q.question_id = a.question_id
JOIN question_knowledge_points qkp ON qkp.question_id = q.question_id
WHERE qkp.knowledge_point_id = :knowledge_point_id
  AND qkp.status = 'CONFIRMED'
  AND e.status = 'CONFIRMED'
ORDER BY e.resolved ASC, a.attempt_time DESC;

-- 5. 已确认的前置和后续知识关系，以及每个相关知识点最近一次 CONFIRMED 掌握证据
SELECT
    'PREREQUISITE' AS relation_to_current,
    kp.knowledge_point_id,
    kp.name,
    m.mastery_level,
    m.assessment_time
FROM knowledge_dependencies kd
JOIN knowledge_points kp ON kp.knowledge_point_id = kd.prerequisite_id
LEFT JOIN mastery_records m ON m.mastery_record_id = (
    SELECT m2.mastery_record_id
    FROM mastery_records m2
    WHERE m2.knowledge_point_id = kp.knowledge_point_id
      AND m2.status = 'CONFIRMED'
    ORDER BY m2.assessment_time DESC
    LIMIT 1
)
WHERE kd.dependent_id = :knowledge_point_id
  AND kd.status = 'CONFIRMED'
  AND kp.status = 'CONFIRMED'
UNION ALL
SELECT
    'DEPENDENT' AS relation_to_current,
    kp.knowledge_point_id,
    kp.name,
    m.mastery_level,
    m.assessment_time
FROM knowledge_dependencies kd
JOIN knowledge_points kp ON kp.knowledge_point_id = kd.dependent_id
LEFT JOIN mastery_records m ON m.mastery_record_id = (
    SELECT m2.mastery_record_id
    FROM mastery_records m2
    WHERE m2.knowledge_point_id = kp.knowledge_point_id
      AND m2.status = 'CONFIRMED'
    ORDER BY m2.assessment_time DESC
    LIMIT 1
)
WHERE kd.prerequisite_id = :knowledge_point_id
  AND kd.status = 'CONFIRMED'
  AND kp.status = 'CONFIRMED';

-- 6. 待审核事项：只用于提示存在候选判断，不得作为个人事实
SELECT
    p.proposal_id,
    p.proposal_type,
    p.target_table,
    p.target_record,
    p.proposed_value,
    p.reason,
    p.evidence,
    p.confidence
FROM proposals p
WHERE p.target_record = :knowledge_point_id
  AND p.status = 'PENDING'
ORDER BY p.created_at DESC;

-- 7. 可选查询：仅在用户明确要求复习、复测或错题整理时执行
SELECT
    r.review_id,
    r.actual_date,
    r.review_type,
    r.result,
    r.response_time_seconds,
    r.scheduled_date,
    r.next_review_date
FROM reviews r
WHERE r.knowledge_point_id = :knowledge_point_id
  AND r.status = 'CONFIRMED'
ORDER BY COALESCE(r.actual_date, r.scheduled_date) DESC
LIMIT 10;
