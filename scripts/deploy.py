#!/usr/bin/env python3
"""Plan or explicitly apply independent Cloudflare pilot deployments."""

import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services/agent-followup"
WEB = ROOT / "apps/web"
CONFIG = SERVICE / ".wrangler.deploy.jsonc"
SECRET_KEYS = frozenset(
    {
        "PILOT_TENANT_ID",
        "PILOT_USERS_JSON",
        "TELNYX_API_KEY",
        "TELNYX_PUBLIC_KEY",
        "TELNYX_FROM_NUMBER",
        "TELNYX_MESSAGING_PROFILE_ID",
        "TELNYX_ASSISTANT_ID",
        "TELNYX_CONNECTION_ID",
        "TELNYX_MAX_CALL_SECONDS",
        "TELNYX_EMAIL_FROM",
        "TELNYX_EMAIL_FROM_NAME",
        "VOICE_OUTCOME_SECRET",
    }
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "account-id",
        "database-id",
        "worker-name",
        "pages-project",
        "api-origin",
        "frontend-origin",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--mode", choices=["demo", "live"], default="demo")
    parser.add_argument(
        "--target", choices=["all", "backend", "frontend"], default="all"
    )
    parser.add_argument("--secrets-file", type=Path)
    parser.add_argument(
        "--enable-live-send",
        action="store_true",
        help="Explicitly enable real paid outreach; requires live mode and provider secrets",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Execute plan against existing cloud resources",
    )
    return parser.parse_args(argv)


def validate(args):
    if not re.fullmatch("[0-9a-fA-F]{32}", args.account_id):
        raise ValueError("Account ID must be 32 hexadecimal characters")
    if not UUID(args.database_id).int:
        raise ValueError("An existing non-placeholder D1 UUID is required")
    for value in (args.worker_name, args.pages_project):
        if not re.fullmatch("[a-z0-9][a-z0-9-]{0,61}[a-z0-9]|[a-z0-9]", value):
            raise ValueError(
                "Resource names must contain lowercase letters, digits and hyphens"
            )
    for value in (args.api_origin, args.frontend_origin):
        origin = urlsplit(value)
        if (
            origin.scheme != "https"
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path
            or origin.query
            or origin.fragment
            or origin.port not in (None, 443)
        ):
            raise ValueError(
                "Origins must be HTTPS origins with no credentials, path or query"
            )
    if args.enable_live_send and args.mode != "live":
        raise ValueError(
            "Live sending requires both --mode live and --enable-live-send"
        )


def read_secrets(path, args):
    try:
        payload = json.loads(path.read_text())
        if (
            not isinstance(payload, dict)
            or not set(payload) <= SECRET_KEYS
            or any(not isinstance(v, str) or not v.strip() for v in payload.values())
        ):
            raise ValueError()
        if not payload.get("PILOT_TENANT_ID"):
            raise ValueError()
        users = json.loads(payload.get("PILOT_USERS_JSON", "null"))
        if (
            not isinstance(users, list)
            or not users
            or not any(u.get("role") == "admin" for u in users)
        ):
            raise ValueError()
        ids = [u["id"] for u in users]
        if len(set(ids)) != len(ids):
            raise ValueError()
        for user in users:
            if (
                not user["id"]
                or not user["name"]
                or user["role"] not in {"agent", "admin"}
                or not re.fullmatch("[0-9a-f]{64}", user["token_sha256"])
            ):
                raise ValueError()
        if args.enable_live_send:
            # A messaging profile is optional: voice-only pilots keep SMS switched off.
            required = SECRET_KEYS - {
                "TELNYX_MAX_CALL_SECONDS",
                "TELNYX_MESSAGING_PROFILE_ID",
                "TELNYX_EMAIL_FROM",
                "TELNYX_EMAIL_FROM_NAME",
            }
            if not required <= payload.keys():
                raise ValueError()
            if len(payload["VOICE_OUTCOME_SECRET"]) < 32:
                raise ValueError()
            if len(base64.b64decode(payload["TELNYX_PUBLIC_KEY"], validate=True)) != 32:
                raise ValueError()
            if not re.fullmatch(r"\+[1-9][0-9]{7,14}", payload["TELNYX_FROM_NUMBER"]):
                raise ValueError()
        if (
            "TELNYX_MAX_CALL_SECONDS" in payload
            and not 30 <= int(payload["TELNYX_MAX_CALL_SECONDS"]) <= 300
        ):
            raise ValueError()
        return payload
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError(
            "Invalid secret file: check the deployment runbook; values are redacted"
        ) from None


def config_for(args, base):
    host = urlsplit(args.api_origin).hostname
    # A custom API hostname is attached as a Worker custom domain on every deploy.
    routes = (
        {}
        if host.endswith(".workers.dev")
        else {"routes": [{"pattern": host, "custom_domain": True}]}
    )
    return {
        **base,
        **routes,
        "name": args.worker_name,
        "account_id": args.account_id,
        "workers_dev": True,
        "vars": {
            "PILOT_MODE": args.mode,
            "FRONTEND_ORIGINS": args.frontend_origin,
            "ENABLE_LIVE_SEND": str(args.enable_live_send).lower(),
        },
        "d1_databases": [
            {
                "binding": "DB",
                "database_name": args.worker_name,
                "database_id": args.database_id,
                "migrations_dir": "migrations",
            }
        ],
    }


def commands_for(args, secrets_file):
    cli = ["uv", "run", "--locked", "pywrangler"]
    config = ["--config", str(CONFIG)]
    backend = [
        (SERVICE, [*cli, "d1", "migrations", "apply", "DB", "--remote", *config], {}),
        (SERVICE, [*cli, "deploy", *config], {}),
        (
            SERVICE,
            [
                *cli,
                "secret",
                "bulk",
                str(secrets_file or "<secret-json-file>"),
                *config,
            ],
            {},
        ),
    ]
    frontend = [
        (WEB, ["npm", "run", "build"], {"VITE_API_BASE_URL": args.api_origin}),
        (
            WEB,
            [
                "uv",
                "run",
                "--project",
                str(SERVICE),
                "--locked",
                "pywrangler",
                "pages",
                "deploy",
                str(WEB / "dist"),
                "--project-name",
                args.pages_project,
                "--branch",
                "main",
            ],
            {},
        ),
    ]
    return (backend if args.target != "frontend" else []) + (
        frontend if args.target != "backend" else []
    )


def run_command(cwd, command, env):
    try:
        subprocess.run(
            command, cwd=cwd, env=env, check=True, capture_output=True, text=True
        )
    except (subprocess.CalledProcessError, OSError):
        raise ValueError(
            "Deployment command failed; output redacted. Inspect Cloudflare deployment status before retrying."
        ) from None


def execute(args):
    validate(args)
    secrets_file = args.secrets_file.resolve() if args.secrets_file else None
    if secrets_file:
        read_secrets(secrets_file, args)
    if args.apply and not os.environ.get("CLOUDFLARE_API_TOKEN"):
        raise ValueError("Set CLOUDFLARE_API_TOKEN before applying")
    if args.apply and args.target != "frontend" and not secrets_file:
        raise ValueError("--secrets-file is required for backend apply")
    base = json.loads((SERVICE / "wrangler.jsonc").read_text())
    config = config_for(args, base)
    commands = commands_for(args, secrets_file)
    print(
        "APPLY to existing resources"
        if args.apply
        else "PLAN ONLY: no files written or commands executed"
    )
    if args.apply and args.target != "frontend":
        # Publish fail-closed first; only enable sending after all secrets upload successfully.
        CONFIG.write_text(
            json.dumps(
                {**config, "vars": {**config["vars"], "ENABLE_LIVE_SEND": "false"}},
                indent=2,
            )
            + "\n"
        )
    env = {**os.environ, "CLOUDFLARE_ACCOUNT_ID": args.account_id, "CI": "true"}
    for cwd, command, extra in commands:
        print(f"{cwd.relative_to(ROOT)}: {shlex.join(command)}")
        if args.apply:
            run_command(cwd, command, {**env, **extra})
    if args.enable_live_send and args.target != "frontend":
        print(
            "Final step: explicitly enable live sending after successful secret upload."
        )
        if args.apply:
            CONFIG.write_text(json.dumps(config, indent=2) + "\n")
            run_command(
                SERVICE,
                [
                    "uv",
                    "run",
                    "--locked",
                    "pywrangler",
                    "deploy",
                    "--config",
                    str(CONFIG),
                ],
                env,
            )
    return 0


def main():
    try:
        return execute(parse_args())
    except (ValueError, OSError):
        print(
            "Deployment stopped: invalid configuration or failed command. Check inputs and cloud status; no secrets logged.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
