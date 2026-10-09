-- Customer Requirement Clarifier
-- 最小数据库：项目 + 技术需求
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    client_name TEXT    NOT NULL DEFAULT '',
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS requirements (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id         INTEGER NOT NULL,
    name               TEXT    NOT NULL,
    type               TEXT    NOT NULL,
    original_request   TEXT    NOT NULL DEFAULT '',
    structured_data    TEXT    NOT NULL DEFAULT '{}',  -- JSON 文本
    status             TEXT    NOT NULL DEFAULT 'incomplete'
                       CHECK (status IN ('incomplete', 'ready', 'confirmed')),
    check_result       TEXT,                            -- 最近一次检查结果 JSON
    confirmed_at       TEXT,                            -- 售前人工确认时间
    created_at         TEXT    NOT NULL,
    updated_at         TEXT    NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_requirements_project ON requirements (project_id);
