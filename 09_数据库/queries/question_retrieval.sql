-- query: confirmed_candidates
SELECT
    q.question_id,
    q.subject_id,
    q.source_resource_id,
    q.question_type,
    q.difficulty,
    q.question_text_path,
    q.standard_answer_path,
    r.title AS resource_title,
    qkp.knowledge_point_id,
    kp.name AS knowledge_point_name,
    qkp.weight AS knowledge_point_weight,
    a.attempt_id,
    a.attempt_time,
    a.my_answer_path,
    a.is_correct,
    a.score,
    a.duration_seconds,
    a.hint_count,
    a.independent,
    a.viewed_answer,
    e.error_id,
    e.surface_error,
    e.direct_cause,
    e.root_cause,
    e.correction_action,
    e.confidence AS error_confidence,
    e.resolved AS error_resolved
FROM questions q
LEFT JOIN resources r
    ON r.resource_id = q.source_resource_id
   AND r.status = 'CONFIRMED'
LEFT JOIN question_knowledge_points qkp
    ON qkp.question_id = q.question_id
   AND qkp.status = 'CONFIRMED'
LEFT JOIN knowledge_points kp
    ON kp.knowledge_point_id = qkp.knowledge_point_id
   AND kp.subject_id = q.subject_id
   AND kp.status = 'CONFIRMED'
LEFT JOIN attempts a
    ON a.question_id = q.question_id
   AND a.status = 'CONFIRMED'
LEFT JOIN errors e
    ON e.attempt_id = a.attempt_id
   AND e.status = 'CONFIRMED'
WHERE q.subject_id = :subject_id
  AND q.status = 'CONFIRMED'
  AND (
      :knowledge_point_id IS NULL
      OR EXISTS (
          SELECT 1
          FROM question_knowledge_points qkp_filter
          JOIN knowledge_points kp_filter
            ON kp_filter.knowledge_point_id = qkp_filter.knowledge_point_id
           AND kp_filter.subject_id = q.subject_id
           AND kp_filter.status = 'CONFIRMED'
          WHERE qkp_filter.question_id = q.question_id
            AND qkp_filter.knowledge_point_id = :knowledge_point_id
            AND qkp_filter.status = 'CONFIRMED'
      )
  )
  AND (
      :error_only = 0
      OR EXISTS (
          SELECT 1
          FROM attempts a_filter
          JOIN errors e_filter ON e_filter.attempt_id = a_filter.attempt_id
          WHERE a_filter.question_id = q.question_id
            AND a_filter.status = 'CONFIRMED'
            AND e_filter.status = 'CONFIRMED'
      )
  )
ORDER BY q.question_id, a.attempt_time DESC, e.error_id;

-- query: proposed_notices
SELECT
    'QUESTION_KNOWLEDGE_POINT' AS notice_type,
    q.question_id,
    qkp.knowledge_point_id AS reference_id,
    kp.name AS reference_name,
    '题目与知识点关联待审核' AS detail,
    qkp.status
FROM questions q
JOIN question_knowledge_points qkp ON qkp.question_id = q.question_id
LEFT JOIN knowledge_points kp ON kp.knowledge_point_id = qkp.knowledge_point_id
WHERE q.subject_id = :subject_id
  AND q.status = 'CONFIRMED'
  AND qkp.status = 'PROPOSED'
  AND (kp.subject_id IS NULL OR kp.subject_id = q.subject_id)
  AND (:knowledge_point_id IS NULL OR qkp.knowledge_point_id = :knowledge_point_id)
UNION ALL
SELECT
    'ERROR' AS notice_type,
    q.question_id,
    e.error_id AS reference_id,
    NULL AS reference_name,
    COALESCE(e.surface_error, e.direct_cause, e.root_cause, '错误诊断待审核') AS detail,
    e.status
FROM questions q
JOIN attempts a ON a.question_id = q.question_id
JOIN errors e ON e.attempt_id = a.attempt_id
WHERE q.subject_id = :subject_id
  AND q.status = 'CONFIRMED'
  AND a.status = 'CONFIRMED'
  AND e.status = 'PROPOSED'
  AND (
      :knowledge_point_id IS NULL
      OR EXISTS (
          SELECT 1
          FROM question_knowledge_points qkp_filter
          WHERE qkp_filter.question_id = q.question_id
            AND qkp_filter.knowledge_point_id = :knowledge_point_id
            AND qkp_filter.status IN ('CONFIRMED', 'PROPOSED')
      )
  )
ORDER BY 2, 1, 3;
