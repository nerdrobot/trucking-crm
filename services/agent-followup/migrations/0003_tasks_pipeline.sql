ALTER TABLE leads ADD COLUMN stage TEXT NOT NULL DEFAULT 'new';
CREATE TABLE tasks(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,lead_id TEXT NOT NULL,title TEXT NOT NULL,due_at TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',source TEXT NOT NULL DEFAULT 'manual',created_at TEXT NOT NULL,completed_at TEXT);
CREATE INDEX tasks_open ON tasks(tenant_id,status,due_at);
CREATE INDEX tasks_lead ON tasks(tenant_id,lead_id);
