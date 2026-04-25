CREATE TABLE IF NOT EXISTS repo_cache (
    id SERIAL PRIMARY KEY,
    repo_url TEXT NOT NULL UNIQUE,
    result JSONB,
    run_count INTEGER DEFAULT 1 CHECK (run_count >= 1),
    last_analyzed TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_repo_cache_lower
ON repo_cache (LOWER(repo_url));