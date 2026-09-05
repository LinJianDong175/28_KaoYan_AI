PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS subjects (
  subject_id TEXT PRIMARY KEY,
  subject_name TEXT NOT NULL,
  exam_type TEXT,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
);

CREATE TABLE IF NOT EXISTS knowledge_points (
  knowledge_point_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  parent_id TEXT,
  name TEXT NOT NULL,
  description TEXT,
  importance INTEGER DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
  difficulty INTEGER DEFAULT 3 CHECK (difficulty BETWEEN 1 AND 5),
  status TEXT NOT NULL DEFAULT 'CONFIRMED',
  FOREIGN KEY(subject_id) REFERENCES subjects(subject_id),
  FOREIGN KEY(parent_id) REFERENCES knowledge_points(knowledge_point_id)
);

CREATE TABLE IF NOT EXISTS knowledge_dependencies (
  prerequisite_id TEXT NOT NULL,
  dependent_id TEXT NOT NULL,
  relation_type TEXT NOT NULL DEFAULT 'PREREQUISITE',
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  PRIMARY KEY(prerequisite_id, dependent_id, relation_type),
  FOREIGN KEY(prerequisite_id) REFERENCES knowledge_points(knowledge_point_id),
  FOREIGN KEY(dependent_id) REFERENCES knowledge_points(knowledge_point_id)
);

CREATE TABLE IF NOT EXISTS resources (
  resource_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  type TEXT,
  subject_id TEXT,
  author_or_publisher TEXT,
  edition_or_year TEXT,
  file_path TEXT,
  source_url TEXT,
  reliability_level INTEGER CHECK (reliability_level BETWEEN 1 AND 5),
  verified INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
);

CREATE TABLE IF NOT EXISTS questions (
  question_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL,
  source_resource_id TEXT,
  question_type TEXT,
  difficulty INTEGER CHECK (difficulty BETWEEN 1 AND 5),
  question_text_path TEXT,
  standard_answer_path TEXT,
  status TEXT NOT NULL DEFAULT 'CONFIRMED',
  FOREIGN KEY(subject_id) REFERENCES subjects(subject_id),
  FOREIGN KEY(source_resource_id) REFERENCES resources(resource_id)
);

CREATE TABLE IF NOT EXISTS question_knowledge_points (
  question_id TEXT NOT NULL,
  knowledge_point_id TEXT NOT NULL,
  weight REAL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  PRIMARY KEY(question_id, knowledge_point_id),
  FOREIGN KEY(question_id) REFERENCES questions(question_id),
  FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_points(knowledge_point_id)
);

CREATE TABLE IF NOT EXISTS study_sessions (
  session_id TEXT PRIMARY KEY,
  subject_id TEXT,
  start_time TEXT,
  end_time TEXT,
  activity_type TEXT,
  summary_path TEXT,
  energy_level INTEGER CHECK (energy_level BETWEEN 1 AND 4),
  focus_level INTEGER CHECK (focus_level BETWEEN 1 AND 5),
  status TEXT NOT NULL DEFAULT 'CONFIRMED',
  FOREIGN KEY(subject_id) REFERENCES subjects(subject_id)
);

CREATE TABLE IF NOT EXISTS attempts (
  attempt_id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL,
  session_id TEXT,
  attempt_time TEXT NOT NULL,
  my_answer_path TEXT,
  is_correct INTEGER,
  score REAL,
  duration_seconds INTEGER,
  hint_count INTEGER DEFAULT 0,
  independent INTEGER,
  viewed_answer INTEGER,
  confidence_before INTEGER CHECK (confidence_before BETWEEN 1 AND 5),
  confidence_after INTEGER CHECK (confidence_after BETWEEN 1 AND 5),
  status TEXT NOT NULL DEFAULT 'CONFIRMED',
  FOREIGN KEY(question_id) REFERENCES questions(question_id),
  FOREIGN KEY(session_id) REFERENCES study_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS errors (
  error_id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL,
  surface_error TEXT,
  direct_cause TEXT,
  root_cause TEXT,
  correction_action TEXT,
  confidence REAL,
  resolved INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  FOREIGN KEY(attempt_id) REFERENCES attempts(attempt_id)
);

CREATE TABLE IF NOT EXISTS mastery_records (
  mastery_record_id TEXT PRIMARY KEY,
  knowledge_point_id TEXT NOT NULL,
  assessment_time TEXT NOT NULL,
  mastery_level INTEGER NOT NULL CHECK (mastery_level BETWEEN 0 AND 5),
  evidence_type TEXT,
  evidence_score REAL,
  independent INTEGER,
  delayed_retest INTEGER,
  transfer_success INTEGER,
  confidence REAL,
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_points(knowledge_point_id)
);

CREATE TABLE IF NOT EXISTS reviews (
  review_id TEXT PRIMARY KEY,
  knowledge_point_id TEXT NOT NULL,
  scheduled_date TEXT,
  actual_date TEXT,
  review_type TEXT,
  result TEXT,
  response_time_seconds INTEGER,
  next_review_date TEXT,
  status TEXT NOT NULL DEFAULT 'PROPOSED',
  FOREIGN KEY(knowledge_point_id) REFERENCES knowledge_points(knowledge_point_id)
);

CREATE TABLE IF NOT EXISTS information_gaps (
  gap_id TEXT PRIMARY KEY,
  gap_type TEXT NOT NULL,
  description TEXT NOT NULL,
  importance INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
  source_record TEXT,
  can_auto_resolve INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'OPEN',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS proposals (
  proposal_id TEXT PRIMARY KEY,
  proposal_type TEXT NOT NULL,
  target_table TEXT,
  target_record TEXT,
  old_value TEXT,
  proposed_value TEXT NOT NULL,
  reason TEXT,
  evidence TEXT,
  source_ids TEXT,
  confidence REAL,
  impact TEXT,
  rollback_plan TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY,
  proposal_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  user_comment TEXT,
  approved_value TEXT,
  reviewed_at TEXT NOT NULL,
  FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
);

CREATE TABLE IF NOT EXISTS ai_audits (
  audit_id TEXT PRIMARY KEY,
  session_id TEXT,
  answer_path TEXT,
  condition_check TEXT,
  formula_check TEXT,
  calculation_check TEXT,
  source_check TEXT,
  uncertainties TEXT,
  final_status TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY(session_id) REFERENCES study_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS change_log (
  change_id TEXT PRIMARY KEY,
  table_name TEXT NOT NULL,
  record_id TEXT NOT NULL,
  before_value TEXT,
  after_value TEXT,
  change_reason TEXT,
  proposal_id TEXT,
  approved_by_user INTEGER NOT NULL DEFAULT 0,
  changed_at TEXT NOT NULL,
  reversible INTEGER NOT NULL DEFAULT 1,
  FOREIGN KEY(proposal_id) REFERENCES proposals(proposal_id)
);

CREATE INDEX IF NOT EXISTS idx_reviews_due ON reviews(status, next_review_date);
CREATE INDEX IF NOT EXISTS idx_attempts_question ON attempts(question_id, attempt_time);
CREATE INDEX IF NOT EXISTS idx_mastery_kp ON mastery_records(knowledge_point_id, assessment_time);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status, created_at);
