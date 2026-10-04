ALTER TABLE leads ADD COLUMN consent_email INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN subject TEXT NOT NULL DEFAULT '';
ALTER TABLE pilot_settings ADD COLUMN email_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE pilot_settings ADD COLUMN email_from TEXT NOT NULL DEFAULT '';
ALTER TABLE pilot_settings ADD COLUMN email_from_name TEXT NOT NULL DEFAULT '';
ALTER TABLE pilot_settings ADD COLUMN daily_email_limit INTEGER NOT NULL DEFAULT 200;
CREATE TABLE templates(id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,name TEXT NOT NULL,channel TEXT NOT NULL,subject TEXT NOT NULL DEFAULT '',body TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX templates_tenant ON templates(tenant_id,channel,name);
