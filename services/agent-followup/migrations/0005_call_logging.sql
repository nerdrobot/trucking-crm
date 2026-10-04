ALTER TABLE leads ADD COLUMN follow_up_at TEXT;
ALTER TABLE leads ADD COLUMN last_outcome TEXT NOT NULL DEFAULT '';
ALTER TABLE leads ADD COLUMN last_called_at TEXT;
ALTER TABLE leads ADD COLUMN assigned_at TEXT NOT NULL DEFAULT '';
UPDATE leads SET assigned_at=created_at;
CREATE INDEX leads_queue ON leads(tenant_id,agent_id,follow_up_at);
