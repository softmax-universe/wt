import sqlite3
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class GraphiteStatus(str, Enum):
    merged = "merged"
    merging = "merging"
    open = "open"
    no_pr = "no pr"


@dataclass
class GraphiteInfo:
    status: GraphiteStatus
    pr_url: str | None = None


# Graphite keeps its whole local state in the shared .git dir: which branches it
# tracks (the `branch_metadata` SQLite table) and the PR/merge status of each
# (`.graphite_pr_info`). `gt log` reads from exactly this cache — it makes no
# network call — so parsing the files reproduces what `gt log` prints while
# skipping the ~0.6s graphite subprocess. The format is graphite's private
# interface; if a `gt` upgrade changes it this parser is what needs updating.


class _PrInfo(BaseModel):
    headRefName: str
    prNumber: int
    state: str  # "OPEN" | "MERGED" | ...
    url: str | None = None


class _Mergeability(BaseModel):
    prNumber: int
    mergeabilityStatus: str  # "MERGED" | "QUEUED_TO_MERGE" | "DRAFT" | "OPEN" | ...


class _PrInfoFile(BaseModel):
    prInfos: list[_PrInfo] = []
    mergeabilityStatuses: list[_Mergeability] = []


def _classify(pr: _PrInfo, mergeability: str) -> GraphiteStatus:
    if pr.state == "MERGED" or mergeability == "MERGED":
        return GraphiteStatus.merged
    if "QUEUE" in mergeability or "MERGING" in mergeability:
        return GraphiteStatus.merging
    return GraphiteStatus.open


def fetch_all_graphite_info() -> dict[str, GraphiteInfo]:
    """Per-branch graphite info, keyed by branch name, read from the on-disk cache.

    Tracked branches without a PR map to `no_pr`; branches absent from the result
    are untracked by graphite. Replaces a per-worktree `gt branch info` (and the
    earlier single `gt log`) with plain file reads.
    """
    result = subprocess.run(["git", "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    result.check_returncode()
    git_dir = Path(result.stdout.strip()).absolute()
    db = git_dir / ".graphite_metadata.db"
    if not db.exists():
        return {}
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("PRAGMA busy_timeout = 1000")
    try:
        tracked = {row[0] for row in con.execute("SELECT branch_name FROM branch_metadata").fetchall()}
    finally:
        con.close()
    if not tracked:
        return {}
    path = git_dir / ".graphite_pr_info"
    pr_info = {}
    if path.exists():
        parsed = _PrInfoFile.model_validate_json(path.read_text())
        mergeability = {item.prNumber: item.mergeabilityStatus for item in parsed.mergeabilityStatuses}
        pr_info = {
            pr.headRefName: GraphiteInfo(status=_classify(pr, mergeability.get(pr.prNumber, "")), pr_url=pr.url)
            for pr in parsed.prInfos
        }
    return {branch: pr_info.get(branch, GraphiteInfo(status=GraphiteStatus.no_pr)) for branch in tracked}
