-- ==========================================================
--  SortedCV Job Portal — Clean Schema Migration
--  Safe to run on existing DB (uses IF NOT EXISTS / ALTER)
-- ==========================================================

-- ── USERS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id                  SERIAL PRIMARY KEY,
  name                VARCHAR(255)        NOT NULL,
  email               VARCHAR(255) UNIQUE NOT NULL,
  password            TEXT                NOT NULL,
  role                VARCHAR(20)         NOT NULL CHECK (role IN ('candidate','employer','admin')),
  plan                VARCHAR(50)         DEFAULT 'FREE',
  blocked             BOOLEAN             DEFAULT FALSE,
  email_digest        BOOLEAN             DEFAULT TRUE,
  referral_code       VARCHAR(50),
  referred_by         VARCHAR(50),
  reset_token         TEXT,
  reset_token_expiry  TIMESTAMP,
  created_at          TIMESTAMP           DEFAULT NOW()
);

-- ── CANDIDATE_PROFILE ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS candidate_profile (
  user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  contact        VARCHAR(20),
  location       VARCHAR(255),
  current_ctc    VARCHAR(100),
  summary        TEXT,
  headline       VARCHAR(255),
  photo          TEXT,
  education      JSONB  DEFAULT '[]',
  experience     JSONB  DEFAULT '[]',
  skills         JSONB  DEFAULT '[]',
  languages      JSONB  DEFAULT '[]',
  certifications JSONB  DEFAULT '[]',
  linkedin       TEXT,
  github         TEXT,
  portfolio      TEXT,
  resume_url     TEXT,          -- full URL e.g. http://localhost:5000/uploads/resumes/resume_3_xxx.pdf
  resume_name    VARCHAR(255),  -- original filename for download label
  updated_at     TIMESTAMP      DEFAULT NOW()
);

-- Migrate old 'resume' JSON column to resume_url/resume_name if it exists
DO $$
BEGIN
  -- Add resume_url if missing
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='candidate_profile' AND column_name='resume_url'
  ) THEN
    ALTER TABLE candidate_profile ADD COLUMN resume_url TEXT;
  END IF;

  -- Add resume_name if missing
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='candidate_profile' AND column_name='resume_name'
  ) THEN
    ALTER TABLE candidate_profile ADD COLUMN resume_name VARCHAR(255);
  END IF;

  -- Add headline if missing
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='candidate_profile' AND column_name='headline'
  ) THEN
    ALTER TABLE candidate_profile ADD COLUMN headline VARCHAR(255);
  END IF;

  -- Add languages if missing
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='candidate_profile' AND column_name='languages'
  ) THEN
    ALTER TABLE candidate_profile ADD COLUMN languages JSONB DEFAULT '[]';
  END IF;

  -- Add certifications if missing
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='candidate_profile' AND column_name='certifications'
  ) THEN
    ALTER TABLE candidate_profile ADD COLUMN certifications JSONB DEFAULT '[]';
  END IF;

  -- Migrate old 'resume' JSON blob -> resume_url + resume_name
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='candidate_profile' AND column_name='resume'
  ) THEN
    UPDATE candidate_profile
    SET
      resume_url  = COALESCE(resume_url,  (resume::jsonb)->>'url'),
      resume_name = COALESCE(resume_name, (resume::jsonb)->>'name')
    WHERE resume IS NOT NULL AND resume_url IS NULL;
  END IF;
END $$;

-- ── EMPLOYER_PROFILE ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS employer_profile (
  employer_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  company_name           VARCHAR(255),
  phone                  VARCHAR(20),
  website                TEXT,
  location               VARCHAR(255),
  industry               VARCHAR(100),
  company_size           VARCHAR(50),
  founded_year           INTEGER,
  gst_number             VARCHAR(50),
  about_company          TEXT,
  logo                   TEXT,
  linkedin               TEXT,
  twitter                TEXT,
  verified               BOOLEAN   DEFAULT FALSE,
  verification_requested BOOLEAN   DEFAULT FALSE,
  plan_request           VARCHAR(50),
  created_at             TIMESTAMP DEFAULT NOW(),
  updated_at             TIMESTAMP DEFAULT NOW()
);

-- ── JOBS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS jobs (
  id            SERIAL PRIMARY KEY,
  employer_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title         VARCHAR(255) NOT NULL,
  description   TEXT,
  location      VARCHAR(255),
  work_mode     VARCHAR(50),
  salary        VARCHAR(100),
  experience    VARCHAR(100),
  skills        JSONB  DEFAULT '[]',
  questions     JSONB  DEFAULT '[]',
  status        VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  created_at    TIMESTAMP DEFAULT NOW()
);

-- ── APPLICATIONS ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS applications (
  id                SERIAL PRIMARY KEY,
  job_id            INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status            VARCHAR(50) DEFAULT 'applied',
  stage             VARCHAR(50) DEFAULT 'applied',
  stage_updated_at  TIMESTAMP  DEFAULT NOW(),
  stage_history     JSONB      DEFAULT '[]',
  answers           JSONB      DEFAULT '[]',
  hired_at          TIMESTAMP,
  applied_at        TIMESTAMP  DEFAULT NOW(),
  UNIQUE(job_id, user_id)
);

-- Add missing columns to applications if upgrading from old schema
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='applications' AND column_name='stage') THEN
    ALTER TABLE applications ADD COLUMN stage VARCHAR(50) DEFAULT 'applied';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='applications' AND column_name='stage_updated_at') THEN
    ALTER TABLE applications ADD COLUMN stage_updated_at TIMESTAMP DEFAULT NOW();
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='applications' AND column_name='stage_history') THEN
    ALTER TABLE applications ADD COLUMN stage_history JSONB DEFAULT '[]';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='applications' AND column_name='answers') THEN
    ALTER TABLE applications ADD COLUMN answers JSONB DEFAULT '[]';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='applications' AND column_name='hired_at') THEN
    ALTER TABLE applications ADD COLUMN hired_at TIMESTAMP;
  END IF;
END $$;

-- ── SAVED JOBS ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS saved_jobs (
  id         SERIAL PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id     INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  saved_at   TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id, job_id)
);

-- ── BLOGS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS blogs (
  id         SERIAL PRIMARY KEY,
  title      VARCHAR(255) NOT NULL,
  content    TEXT,
  image_url  TEXT,
  author     VARCHAR(255) DEFAULT 'Admin',
  created_at TIMESTAMP DEFAULT NOW()
);

-- ── CONTACT QUERIES ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS contact_queries (
  id          SERIAL PRIMARY KEY,
  user_type   VARCHAR(100),
  email       VARCHAR(255),
  phone       VARCHAR(30),
  description TEXT,
  created_at  TIMESTAMP DEFAULT NOW()
);

-- Migration: rename old columns if upgrading from initial schema
DO $$
BEGIN
  -- Add user_type if missing (old schema had 'name')
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='contact_queries' AND column_name='user_type') THEN
    ALTER TABLE contact_queries ADD COLUMN user_type VARCHAR(100);
  END IF;
  -- Add phone if missing
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='contact_queries' AND column_name='phone') THEN
    ALTER TABLE contact_queries ADD COLUMN phone VARCHAR(30);
  END IF;
  -- Add description if missing (old schema had 'message')
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='contact_queries' AND column_name='description') THEN
    ALTER TABLE contact_queries ADD COLUMN description TEXT;
    -- Copy old message data if it existed
    UPDATE contact_queries SET description = message WHERE description IS NULL AND message IS NOT NULL;
  END IF;
END $$;


-- ── EMAIL OTPs ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_otps (
  id         SERIAL PRIMARY KEY,
  email      VARCHAR(255) NOT NULL,
  otp        VARCHAR(10)  NOT NULL,
  expires_at TIMESTAMP    NOT NULL,
  created_at TIMESTAMP    DEFAULT NOW()
);

-- Auto-clean expired OTPs index
CREATE INDEX IF NOT EXISTS idx_email_otps_email ON email_otps(email);

-- ── INDEXES ────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_applications_user_id ON applications(user_id);
CREATE INDEX IF NOT EXISTS idx_applications_job_id  ON applications(job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_employer_id     ON jobs(employer_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status          ON jobs(status);

-- ==========================================================
--  AI Resume Shortlisting — additional tables
--  These are used by the FastAPI scoring service (main.py).
--  They do NOT conflict with the job portal tables above.
-- ==========================================================

-- ── AI SERVICE USERS ───────────────────────────────────────
-- Mirrors the auth layer in main.py (UUID primary key to match
-- the existing string-based id format used in JWTs).
CREATE TABLE IF NOT EXISTS ai_users (
  id          TEXT PRIMARY KEY,
  name        TEXT        NOT NULL,
  email       TEXT UNIQUE NOT NULL,
  password    TEXT        NOT NULL,
  role        TEXT        NOT NULL CHECK (role IN ('candidate', 'employer', 'admin')),
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── AI FEEDBACK ────────────────────────────────────────────
-- Raw employer corrections submitted via POST /feedback.
CREATE TABLE IF NOT EXISTS ai_feedback (
  id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  jd_id                TEXT        NOT NULL,
  resume_id            TEXT,
  resume_name          TEXT,
  ai_total_score       FLOAT       NOT NULL DEFAULT 0,
  employer_total_score FLOAT       NOT NULL DEFAULT 0,
  ai_flag              TEXT,
  employer_flag        TEXT,
  created_at           TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_feedback_jd_id ON ai_feedback(jd_id);

-- ── AI JOB CALIBRATION ─────────────────────────────────────
-- Per-JD aggregated calibration state (recomputed on each feedback).
CREATE TABLE IF NOT EXISTS ai_job_calibration (
  jd_id                  TEXT        PRIMARY KEY,
  feedback_count         INT         NOT NULL DEFAULT 0,
  feedback_alignment_pct FLOAT       NOT NULL DEFAULT 100.0,
  calibration_offset     FLOAT       NOT NULL DEFAULT 0.0,
  last_recalibrated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── AI SERVICE JOBS ────────────────────────────────────────
-- Job postings created via the AI scoring service.
CREATE TABLE IF NOT EXISTS ai_service_jobs (
  id          TEXT PRIMARY KEY,
  employer_id TEXT NOT NULL,
  title       TEXT NOT NULL,
  jd_text     TEXT NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_service_jobs_employer ON ai_service_jobs(employer_id);

-- ── AI SERVICE RESUMES ─────────────────────────────────────
-- Parsed resumes uploaded by candidates.
CREATE TABLE IF NOT EXISTS ai_service_resumes (
  id             TEXT        PRIMARY KEY,
  user_id        TEXT        NOT NULL,
  candidate_name TEXT,
  file_name      TEXT,
  parsed         JSONB       NOT NULL DEFAULT '{}',
  uploaded_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_service_resumes_user ON ai_service_resumes(user_id);

-- ── AI SERVICE RANKINGS ────────────────────────────────────
-- AI-generated ranking results, one row per job.
CREATE TABLE IF NOT EXISTS ai_service_rankings (
  job_id       TEXT        PRIMARY KEY,
  generated_by TEXT,
  results      JSONB       NOT NULL DEFAULT '[]',
  errors       JSONB       NOT NULL DEFAULT '[]',
  generated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── VECTOR STORE: JD CHUNKS ────────────────────────────────
-- JD text chunks with their float4 embeddings.
-- No pgvector extension required; cosine similarity computed in Python.
CREATE TABLE IF NOT EXISTS jd_chunks (
  jd_hash     TEXT    NOT NULL,
  chunk_index INT     NOT NULL,
  content     TEXT    NOT NULL,
  embedding   FLOAT4[] NOT NULL,
  weight      FLOAT4  NOT NULL DEFAULT 0.8,
  PRIMARY KEY (jd_hash, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_jd_chunks_hash ON jd_chunks(jd_hash);

-- ── VECTOR STORE: RESUME CHUNKS ────────────────────────────
-- Resume field embeddings, re-indexed on each upload.
CREATE TABLE IF NOT EXISTS resume_chunks (
  resume_hash TEXT    NOT NULL,
  chunk_index INT     NOT NULL,
  content     TEXT    NOT NULL,
  embedding   FLOAT4[] NOT NULL,
  category    TEXT    NOT NULL DEFAULT 'skill',
  PRIMARY KEY (resume_hash, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_resume_chunks_hash ON resume_chunks(resume_hash);

