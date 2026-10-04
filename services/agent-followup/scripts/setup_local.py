"""Generate a local demo with separate named access keys; never print keys."""

import argparse
import hashlib
import json
import os
import secrets
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    config = ROOT / ".dev.vars"
    keyfile = ROOT / ".local-pilot-keys.json"
    if config.exists() and not args.force:
        parser.error(".dev.vars exists; use --force to back it up and replace it")
    if config.exists():
        backup = config.with_name(".dev.vars.backup-" + secrets.token_hex(4))
        shutil.copy2(config, backup)
        os.chmod(backup, 0o600)
    keys = {"admin": secrets.token_urlsafe(36), "agent": secrets.token_urlsafe(36)}
    users = [
        {
            "id": role,
            "name": "Pilot " + role.title(),
            "role": role,
            "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
        }
        for role, token in keys.items()
    ]
    config.write_text(
        "PILOT_MODE=demo\nPILOT_TENANT_ID=local-pilot\nENABLE_LIVE_SEND=false\nFRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173\nPILOT_USERS_JSON="
        + "'"
        + json.dumps(users)
        + "'"
        + "\n"
    )
    os.chmod(config, 0o600)
    keyfile.write_text(json.dumps(keys, indent=2) + "\n")
    os.chmod(keyfile, 0o600)
    print("Created " + str(config))
    print("Access keys saved in " + str(keyfile))


if __name__ == "__main__":
    main()
