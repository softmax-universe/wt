"""Create the worktree and stop — open nothing."""

from pathlib import Path

from softmaxwt.config import NoopOpenerConfig, OpenerConfig

hosts_background_init: bool = False


def open(
    root: Path,
    worktree_path: Path,
    name: str,
    config: OpenerConfig,
    init: str | None = None,
    surface_init: str | None = None,
) -> None:
    assert isinstance(config, NoopOpenerConfig)
    assert init is None  # noop opens nothing; nowhere to host background init.


def close(root: Path, worktree_path: Path, name: str) -> None:
    return None
