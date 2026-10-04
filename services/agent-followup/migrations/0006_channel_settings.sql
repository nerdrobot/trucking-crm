ALTER TABLE pilot_settings ADD COLUMN sms_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE pilot_settings ADD COLUMN voice_enabled INTEGER NOT NULL DEFAULT 1;
ALTER TABLE pilot_settings ADD COLUMN messaging_profile_id TEXT NOT NULL DEFAULT '';
ALTER TABLE pilot_settings ADD COLUMN connection_id TEXT NOT NULL DEFAULT '';
ALTER TABLE pilot_settings ADD COLUMN assistant_id TEXT NOT NULL DEFAULT '';
