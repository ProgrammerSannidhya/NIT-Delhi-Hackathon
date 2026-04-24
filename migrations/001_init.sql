-- ================= USERS =================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,

    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,

    role TEXT NOT NULL DEFAULT 'user'
        CHECK (role IN ('user', 'admin')),

    failed_attempts INTEGER DEFAULT 0,
    lock_until TIMESTAMP,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ================= REFRESH TOKENS =================
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id SERIAL PRIMARY KEY,

    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,

    token TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ================= ANALYSES =================
CREATE TABLE IF NOT EXISTS analyses (
    id SERIAL PRIMARY KEY,

    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    repo_url TEXT NOT NULL,

    status TEXT DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),

    result JSONB,

    created_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- ================= REPO CACHE =================
CREATE TABLE IF NOT EXISTS repo_cache (
    id SERIAL PRIMARY KEY,

    repo_url TEXT NOT NULL UNIQUE,

    result JSONB,

    run_count INTEGER DEFAULT 1
        CHECK (run_count >= 1),

    last_analyzed TIMESTAMP DEFAULT NOW()
);

-- ================= INDEXES =================

-- USERS
CREATE INDEX IF NOT EXISTS idx_users_username
ON users(username);

-- ANALYSES
CREATE INDEX IF NOT EXISTS idx_analyses_user
ON analyses(user_id);

CREATE INDEX IF NOT EXISTS idx_analyses_status
ON analyses(status);

-- CACHE
CREATE INDEX IF NOT EXISTS idx_repo_cache_url
ON repo_cache(repo_url);

-- prevent duplicate repo urls with case differences
CREATE UNIQUE INDEX IF NOT EXISTS idx_repo_cache_lower
ON repo_cache (LOWER(repo_url));