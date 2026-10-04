CREATE TABLE leads (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'new'
);
CREATE INDEX leads_tenant ON leads(tenant_id, id);
CREATE TABLE dispatches (
  provider_id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL REFERENCES leads(id),
  tenant_id TEXT NOT NULL
);
CREATE TABLE webhook_events (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL REFERENCES dispatches(provider_id)
);
