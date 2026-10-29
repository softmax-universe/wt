from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from softmaxwt.isolation.registry import get_isolation_backend
from softmaxwt.shells import combine_scripts

if TYPE_CHECKING:
    from softmaxwt.config import CmuxSurface, OpenerConfig, ZellijSurface


class OpenerName(str, Enum):
    """How a worktree is presented once created."""

    inplace = "inplace"
    cmux = "cmux"
    zellij = "zellij"
    noop = "noop"


class Opener(Protocol):
    """Controls how a worktree is presented to the user once created.

    When the opener can tell a worktree is already open, `open` may behave
    idempotently — reattach instead of duplicating. See the cmux opener.
    """

    # True if this opener can run a profile's `background_init` snippet
    # concurrently with opening (e.g. in its own cmux surface). Openers that exec
    # away (inplace) or surface nothing (noop) can't, so `create` runs it
    # synchronously for them.
    hosts_background_init: bool

    def open(
        self,
        root: Path,
        worktree_path: Path,
        name: str,
        config: OpenerConfig,
        init: str | None = None,
        surface_init: str | None = None,
    ) -> None:
        """Open the worktree.

        `init` is a background init command this opener has agreed to host (only
        ever passed on create, when `hosts_background_init` is set). `surface_init`
        is the profile's `hooks.surface_init` script, run inside every surface
        before its command — on create and open alike."""

    def close(self, root: Path, worktree_path: Path, name: str) -> None: ...


def build_surface_commands(
    root: Path,
    worktree_path: Path,
    name: str,
    surfaces: list[CmuxSurface] | list[ZellijSurface],
    surface_init: str | None = None,
) -> list[list[str]]:
    """Argv per surface, with profile init before its own init inside isolation.

    Openers choose how to transport this argv: cmux needs a shell string, while
    zellij accepts argv after --.
    """
    return [
        get_isolation_backend(surface.mode).enter_command(
            root, worktree_path, name, surface.shell, init=combine_scripts(surface_init, surface.init)
        )
        for surface in surfaces
    ]
