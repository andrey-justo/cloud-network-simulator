"""Launch the packaged dashboard with the current Python interpreter."""

from __future__ import annotations

import json
from http.client import HTTPConnection
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def launch_ui(workspace: Path, *, parameters: dict[str, Any] | None = None, execute: bool = False) -> int:
    node = shutil.which("node")
    if not node:
        raise ValueError("The dashboard requires Node.js 22 or newer on PATH.")
    command = [node, str(Path(__file__).with_name("web") / "server.mjs")]
    with subprocess.Popen(command, cwd=workspace, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps({
            "workspace": str(workspace), "python": sys.executable,
            "parameters": parameters, "execute": execute,
        }))
        process.stdin.close()
        url = None
        try:
            line = process.stdout.readline()
            if not line:
                raise ValueError(f"Dashboard failed to start (exit code {process.wait()}).")
            url = json.loads(line)["url"]
            print(f"Study dashboard: {url}\nStatic-only controls enabled. Ctrl+C stops this UI and interrupts its managed worker.", flush=True)
            try:
                if not webbrowser.open(url):
                    print("No browser opened automatically; open the URL above.", file=sys.stderr)
            except (OSError, webbrowser.Error) as error:
                print(f"Browser could not open: {error}. Open the URL above.", file=sys.stderr)
            return process.wait()
        except KeyboardInterrupt:
            if url is None:
                process.terminate()
                process.wait()
                print("Dashboard startup interrupted; inspect execution checkpoints before resuming.", file=sys.stderr)
                return 130
            target = urlsplit(url)
            connection = HTTPConnection("127.0.0.1", target.port, timeout=5)
            try:
                connection.request("POST", "/api/shutdown", body="{}", headers={
                    "Origin": url, "Content-Type": "application/json",
                })
                response = connection.getresponse()
                response.read()
                if response.status != 200:
                    raise ValueError(f"Dashboard shutdown returned HTTP {response.status}.")
                process.wait(timeout=10)
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                print(f"Graceful dashboard shutdown failed: {error}. Check the execution lock before resuming.", file=sys.stderr)
                process.terminate()
                process.wait()
            finally:
                connection.close()
            return 130
        except (OSError, ValueError, KeyError):
            if process.poll() is None:
                process.terminate()
                process.wait()
            raise
