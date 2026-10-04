ALTER TABLE pilot_settings ADD COLUMN max_numbers INTEGER NOT NULL DEFAULT 2;
CREATE TABLE ordered_numbers(tenant_id TEXT NOT NULL,phone_number TEXT NOT NULL,order_id TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,PRIMARY KEY(tenant_id,phone_number));
CREATE TABLE webrtc_credentials(tenant_id TEXT NOT NULL,user_id TEXT NOT NULL,credential_id TEXT NOT NULL,sip_username TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(tenant_id,user_id));
