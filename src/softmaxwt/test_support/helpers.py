import os
import subprocess
import sys
from pathlib import Path


def wt_run(*args: str, cwd: Path, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Keep the current package dependencies available after changing into a fixture repository."""
    env = {**os.environ, "SHELL": "/usr/bin/true", "PYTHONPATH": os.pathsep.join(sys.path)}
    return subprocess.run(
        [sys.executable, "-m", "softmaxwt.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
        input=stdin,
        timeout=30,
    )


def invoke(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    result = wt_run(*args, cwd=cwd)
    if result.returncode != 0:
        raise AssertionError(f"exit code {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}")
    return result
