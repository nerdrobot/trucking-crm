"""Run the separate frontend and local Worker, including scheduled follow-ups."""

import os
import shutil
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "services" / "agent-followup"
FRONTEND = ROOT / "apps" / "web"


def uv_command():
    local = BACKEND / ".venv" / "bin" / "uv"
    installed = str(local) if local.exists() else shutil.which("uv")
    if not installed:
        raise SystemExit("Install uv 0.12.3+ first: https://docs.astral.sh/uv/")
    return installed


def cron_loop(stopped):
    url = "http://127.0.0.1:8787/cdn-cgi/handler/scheduled?cron=%2A+%2A+%2A+%2A+%2A"
    ready = False
    while not stopped.wait(15):
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                if response.status != 200:
                    print("Local scheduler returned an unexpected status.", file=sys.stderr)
                elif not ready:
                    print("Local follow-up scheduler is running every 15 seconds.", flush=True)
                    ready = True
        except (urllib.error.URLError, TimeoutError):
            if ready:
                print("Local scheduler could not reach the backend; retrying.", file=sys.stderr)


def main():
    if not (BACKEND / ".dev.vars").exists():
        raise SystemExit("Run the local setup command first; see README.md.")
    uv = uv_command()
    if not shutil.which("npm"):
        raise SystemExit("Node.js 22+ and npm are required.")
    children = []
    stopped = threading.Event()

    def stop(*_):
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    env = {**os.environ, "WRANGLER_SEND_METRICS": "false"}
    # pywrangler invokes uv again internally; prefer the working project-local tool.
    env["PATH"] = str(Path(uv).parent) + os.pathsep + env.get("PATH", "")
    try:
        subprocess.run(
            [uv, "run", "pywrangler", "d1", "migrations", "apply", "DB", "--local"],
            cwd=BACKEND, env=env, check=True,
        )
        commands = [
            (BACKEND, [uv, "run", "pywrangler", "dev", "--ip", "127.0.0.1",
                       "--port", "8787", "--test-scheduled"]),
            (FRONTEND, ["npm", "run", "dev", "--", "--host", "127.0.0.1"]),
        ]
        for directory, command in commands:
            children.append(subprocess.Popen(command, cwd=directory, env=env, start_new_session=True))
        threading.Thread(target=cron_loop, args=(stopped,), daemon=True).start()
        print("Dashboard: http://127.0.0.1:5173 | API: http://127.0.0.1:8787", flush=True)
        print("Use your generated local agent access key to sign in. Ctrl-C stops both services.")
        while not stopped.wait(1):
            for child in children:
                if child.poll() is not None:
                    raise RuntimeError(f"A development process exited with code {child.returncode}.")
    finally:
        stopped.set()
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
