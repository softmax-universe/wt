"""Opener for https://cmux.com terminal.

Built from cmux's **documented** primitives — `new-workspace --cwd --name
--command --focus`, then `new-surface` / `new-split` + `send`/`send-key` for
additional surfaces. It deliberately does **not** use `cmux --layout`: that field
is undocumented/unvalidated and a multi-surface-per-pane layout hangs the app
(see `wt destroy`/LESSONS). All cmux calls use one subprocess transport boundary.

- **availability**: `cmux_available()` requires both the binary and
  `$CMUX_WORKSPACE_ID` (we must run inside cmux for `new-workspace` to have a
  caller window). If a cmux opener is selected and cmux is unavailable, `open`
  errors — no silent fallback.
- **idempotent**: `open` matches an existing workspace by `current_directory`
  (realpath) and selects it instead of duplicating.
- **destroy**: `close` finds-and-closes the workspace; it no-ops when cmux is
  unavailable, so `destroy` stays safe everywhere."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from softmaxwt.config import CmuxOpenerConfig, OpenerConfig
from softmaxwt.opener.common import build_surface_commands

# Map a profile layout to the cmux split direction for surfaces after the first.
# "tabs" adds surfaces to the same pane instead of splitting.
_SPLIT_DIRECTION = {"horizontal": "right", "vertical": "down"}


# Refs are NEVER scraped from a mutating command's stdout — the CLI contract only
# guarantees stable output for --json commands. New surfaces are discovered by
# diffing `list-panes --json` state, and the new workspace by its cwd.


def cmux_available() -> bool:
    """True only when cmux is installed AND we're running inside a cmux terminal
    (so new-workspace has a caller window). $CMUX_WORKSPACE_ID is auto-set there."""
    return bool(shutil.which("cmux")) and bool(os.environ.get("CMUX_WORKSPACE_ID"))


def _run(*args: str) -> str:
    """Run a cmux subcommand, returning stripped stdout."""
    result = subprocess.run(["cmux", *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _list_workspaces() -> list[dict]:
    return json.loads(_run("--json", "list-workspaces"))["workspaces"]


def _list_panes(workspace: str) -> list[dict]:
    return json.loads(_run("--json", "list-panes", "--workspace", workspace))["panes"]


def _surface_refs(workspace: str) -> set[str]:
    """Every surface ref across every pane in the workspace."""
    return {ref for pane in _list_panes(workspace) for ref in pane["surface_refs"]}


def _find_workspace(worktree_path: Path) -> str | None:
    """The cmux workspace whose cwd is this worktree, or None."""
    target = os.path.realpath(worktree_path)
    for ws in _list_workspaces():
        # This assumes that the user didn't cd into some other dir.
        # I'm not sure how reliable that is.
        if os.path.realpath(ws["current_directory"]) == target:
            return ws["ref"]
    return None


# The workspace returns after opening and surfaces are first-class, so a
# background init just rides along as one more surface running the command.
hosts_background_init: bool = True


def open(
    root: Path,
    worktree_path: Path,
    name: str,
    config: OpenerConfig,
    init: str | None = None,
    surface_init: str | None = None,
) -> None:
    assert isinstance(config, CmuxOpenerConfig)
    if not cmux_available():
        sys.exit("cmux is not available — run wt from inside a cmux terminal, or pick another opener.")

    existing = _find_workspace(worktree_path)
    if existing is not None:
        if config.focus:
            _run("select-workspace", "--workspace", existing)
        print(f"cmux workspace for {name} already open ({existing}).")
        return

    commands = [
        shlex.join(command)
        for command in build_surface_commands(root, worktree_path, name, config.surfaces, surface_init)
    ]
    # Each extra surface is (command, tab_title). A background init rides as one
    # more surface, tagged so the tab name makes clear what it's running.
    extra_surfaces: list[tuple[str, str | None]] = [(c, None) for c in commands[1:]]
    if init is not None:
        extra_surfaces.append((init, "init"))
    _run(
        "new-workspace",
        "--cwd",
        str(worktree_path),
        "--name",
        name,
        "--command",
        commands[0],
        "--focus",
        str(config.focus).lower(),
    )
    workspace = _find_workspace(worktree_path)
    if workspace is None:
        sys.exit(f"cmux created no workspace for {worktree_path}")

    # new-workspace --command starts with exactly one surface in one pane.
    (pane,) = _list_panes(workspace)
    pane_ref, anchor = pane["ref"], pane["surface_refs"][0]
    direction = _SPLIT_DIRECTION.get(config.layout)

    for command, title in extra_surfaces:
        before = _surface_refs(workspace)
        if direction is None:  # tabs: same pane
            _run("new-surface", "--workspace", workspace, "--pane", pane_ref, "--focus", "false")
        else:
            _run("new-split", direction, "--workspace", workspace, "--surface", anchor, "--focus", "false")
        # The one ref that appeared is the surface we just made.
        (surface,) = _surface_refs(workspace) - before
        if title is not None:
            _run("rename-tab", "--workspace", workspace, "--surface", surface, title)
        # send types the command; send-key submits it with a named key (no escape-
        # sequence guessing). UNVERIFIED end to end — confirm during manual testing.
        _run("send", "--workspace", workspace, "--surface", surface, command)
        _run("send-key", "--workspace", workspace, "--surface", surface, "Enter")
        anchor = surface

    print(f"Opened cmux workspace {name} ({workspace}).")


def close(root: Path, worktree_path: Path, name: str) -> None:
    if not cmux_available():
        return
    workspace = _find_workspace(worktree_path)
    if workspace is not None:
        _run("close-workspace", "--workspace", workspace)
