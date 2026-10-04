"""Deployment safety tests; never contact Cloudflare."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "deploy", Path(__file__).parents[1] / "scripts/deploy.py"
)
deploy = importlib.util.module_from_spec(SPEC)
if SPEC.loader:
    SPEC.loader.exec_module(deploy)


class DeploymentTests(unittest.TestCase):
    def args(self, *extra):
        return deploy.parse_args(
            [
                "--account-id",
                "a" * 32,
                "--database-id",
                "12345678-1234-1234-1234-123456789abc",
                "--worker-name",
                "followup-pilot",
                "--pages-project",
                "followup-web",
                "--api-origin",
                "https://followup-pilot.example.workers.dev",
                "--frontend-origin",
                "https://followup-web.pages.dev",
                *extra,
            ]
        )

    def test_defaults_are_demo_dry_run(self):
        args = self.args()
        self.assertEqual(args.mode, "demo")
        self.assertFalse(args.apply)
        with patch.object(deploy.subprocess, "run") as run:
            self.assertEqual(deploy.execute(args), 0)
        run.assert_not_called()

    def test_origin_and_identifier_validation(self):
        for extra in [
            ("--account-id", "bad"),
            ("--worker-name", "../bad"),
            ("--database-id", "00000000-0000-0000-0000-000000000000"),
            ("--api-origin", "http://evil.test"),
            ("--frontend-origin", "https://user:pass@example.com"),
            ("--frontend-origin", "https://example.com/path"),
        ]:
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                deploy.validate(self.args(*extra))

    def test_live_mode_does_not_enable_sending(self):
        config = deploy.config_for(self.args("--mode", "live"), {"main": "src/main.py"})
        self.assertEqual(config["vars"]["ENABLE_LIVE_SEND"], "false")
        self.assertEqual(config["vars"]["PILOT_MODE"], "live")

    def test_allow_live_requires_both_mode_and_secret_opt_in(self):
        with self.assertRaises(ValueError):
            deploy.validate(self.args("--enable-live-send"))
        config = deploy.config_for(
            self.args("--mode", "live", "--enable-live-send"), {}
        )
        self.assertEqual(config["vars"]["ENABLE_LIVE_SEND"], "true")

    def test_secret_validation_and_no_secret_printing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.json"
            for payload in [
                {"UNKNOWN": "secret"},
                {"PILOT_USERS_JSON": []},
                {"ENABLE_LIVE_SEND": "true"},
                {"PILOT_TENANT_ID": "tenant"},
            ]:
                path.write_text(json.dumps(payload))
                with self.assertRaises(ValueError):
                    deploy.read_secrets(path, self.args())
            users = json.dumps(
                [
                    {
                        "id": "admin",
                        "name": "Admin",
                        "role": "admin",
                        "token_sha256": "a" * 64,
                    }
                ]
            )
            path.write_text(
                json.dumps({"PILOT_TENANT_ID": "tenant", "PILOT_USERS_JSON": users})
            )
            self.assertEqual(
                deploy.read_secrets(path, self.args())["PILOT_TENANT_ID"], "tenant"
            )

    def test_custom_api_domain_is_attached_and_workers_dev_is_not(self):
        self.assertNotIn("routes", deploy.config_for(self.args(), {}))
        config = deploy.config_for(
            self.args("--api-origin", "https://api.followhearth.com"), {}
        )
        self.assertEqual(
            config["routes"],
            [{"pattern": "api.followhearth.com", "custom_domain": True}],
        )

    def test_live_secret_requirements_and_call_limit(self):
        args = self.args("--mode", "live", "--enable-live-send")
        users = json.dumps(
            [
                {
                    "id": "admin",
                    "name": "Admin",
                    "role": "admin",
                    "token_sha256": "a" * 64,
                }
            ]
        )
        valid = {
            "PILOT_TENANT_ID": "pilot",
            "PILOT_USERS_JSON": users,
            "TELNYX_API_KEY": "test-provider-key",
            "TELNYX_PUBLIC_KEY": deploy.base64.b64encode(b"x" * 32).decode(),
            "TELNYX_FROM_NUMBER": "+12025550123",
            "TELNYX_MESSAGING_PROFILE_ID": "test-profile",
            "TELNYX_ASSISTANT_ID": "test-assistant",
            "TELNYX_CONNECTION_ID": "test-connection",
            "VOICE_OUTCOME_SECRET": "x" * 32,
            "TELNYX_MAX_CALL_SECONDS": "120",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secrets.json"
            path.write_text(json.dumps(valid))
            self.assertEqual(deploy.read_secrets(path, args), valid)
            # Voice-only pilots may go live without a messaging profile.
            voice_only = {
                k: v for k, v in valid.items() if k != "TELNYX_MESSAGING_PROFILE_ID"
            }
            path.write_text(json.dumps(voice_only))
            self.assertEqual(deploy.read_secrets(path, args), voice_only)
            # The caller number can be chosen in the dashboard instead.
            no_number = {k: v for k, v in valid.items() if k != "TELNYX_FROM_NUMBER"}
            path.write_text(json.dumps(no_number))
            self.assertEqual(deploy.read_secrets(path, args), no_number)
            for boundary in ("30", "300"):
                payload = {**valid, "TELNYX_MAX_CALL_SECONDS": boundary}
                path.write_text(json.dumps(payload))
                self.assertEqual(deploy.read_secrets(path, args), payload)
            for key, value in (
                ("VOICE_OUTCOME_SECRET", "short"),
                ("TELNYX_PUBLIC_KEY", "invalid"),
                ("TELNYX_FROM_NUMBER", "123"),
                ("TELNYX_MAX_CALL_SECONDS", "999"),
                ("TELNYX_MAX_CALL_SECONDS", "29"),
                ("TELNYX_MAX_CALL_SECONDS", "301"),
            ):
                path.write_text(json.dumps({**valid, key: value}))
                with self.subTest(key=key), self.assertRaises(ValueError):
                    deploy.read_secrets(path, args)

    def test_commands_use_argument_arrays_and_separate_frontend_build(self):
        commands = deploy.commands_for(self.args(), Path("/tmp/secrets.json"))
        self.assertTrue(all(isinstance(command, list) for _, command, _ in commands))
        text = str(commands)
        self.assertIn("--remote", text)
        self.assertIn("secret", text)
        self.assertIn("bulk", text)
        self.assertIn("VITE_API_BASE_URL", text)
        frontend = deploy.commands_for(self.args("--target", "frontend"), None)
        self.assertEqual(len(frontend), 2)
        self.assertNotIn("--remote", str(frontend))

    def test_apply_requires_token_and_secrets_before_any_command(self):
        with (
            patch.dict(deploy.os.environ, {}, clear=True),
            patch.object(deploy.subprocess, "run") as run,
            self.assertRaises(ValueError),
        ):
            deploy.execute(self.args("--apply"))
        run.assert_not_called()

    def test_successful_apply_starts_closed_and_enables_live_last(self):
        args = self.args(
            "--apply",
            "--mode",
            "live",
            "--enable-live-send",
            "--target",
            "backend",
            "--secrets-file",
            "/tmp/pilot.json",
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(deploy.os.environ, {"CLOUDFLARE_API_TOKEN": "cloud-secret"}),
            patch.object(deploy, "read_secrets", return_value={}),
            patch.object(deploy, "CONFIG", Path(directory) / "config.json"),
            patch.object(deploy, "run_command") as run,
        ):
            gates = []
            run.side_effect = lambda *_: gates.append(
                json.loads(deploy.CONFIG.read_text())["vars"]["ENABLE_LIVE_SEND"]
            )
            deploy.execute(args)
            self.assertEqual(gates, ["false", "false", "false", "true"])
            self.assertNotIn("cloud-secret", deploy.CONFIG.read_text())

    def test_subprocess_failure_is_sanitized(self):
        with (
            patch.dict(deploy.os.environ, {"CLOUDFLARE_API_TOKEN": "cloud-secret"}),
            patch.object(
                deploy.subprocess,
                "run",
                side_effect=deploy.subprocess.CalledProcessError(
                    1, ["cmd"], stderr="secret"
                ),
            ),
            self.assertRaisesRegex(ValueError, "Deployment command failed"),
        ):
            deploy.execute(self.args("--apply", "--target", "frontend"))


if __name__ == "__main__":
    unittest.main()
