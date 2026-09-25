from concurrent.futures import ThreadPoolExecutor

import typer
from rich.console import Console
from rich.table import Table

from softmaxwt.app import app
from softmaxwt.claude import list_claude_agents
from softmaxwt.graphite import GraphiteStatus, fetch_all_graphite_info
from softmaxwt.isolation.registry import all_isolation_backends
from softmaxwt.worktree import Worktree, list_worktrees


def _sync_col(wt: Worktree) -> str:
    info = wt.graphite_info
    if info is None:
        return "[dim]untracked[/]"
    match info.status:
        case GraphiteStatus.merged:
            return "[green]merged[/]"
        case GraphiteStatus.merging:
            return "[cyan]merging[/]"
        case GraphiteStatus.open:
            return f"[link={info.pr_url}][blue underline]PR open[/][/link]"
        case GraphiteStatus.no_pr:
            return "[yellow]no PR[/]"


@app.command()
def ls(
    sessions: bool = typer.Option(
        False,
        "--sessions/--no-sessions",
        help="Show the live sessions column.",
    ),
):
    """List current worktrees and their status."""
    worktrees = list_worktrees()

    if not worktrees:
        typer.echo("No worktrees found.")
        return

    # Graphite status comes from the on-disk cache (one read), not a subprocess.
    graphite_info = fetch_all_graphite_info()
    for wt in worktrees:
        wt.set_graphite_info(graphite_info.get(wt.branch))

    # The dirty/unpushed columns each shell out to git per worktree; those queries
    # are independent and I/O-bound, so run them across worktrees concurrently.
    # Removed worktrees get blank columns (the row renders as REMOVED below).
    def _git_cols(wt: Worktree) -> tuple[str, str]:
        if not wt.path.exists():
            return "", ""
        stats = wt.uncommitted_diff_stats()
        dirty = "[dim]-[/]"
        if stats is not None:
            dirty = f"[bold]{stats.files} files[/] [green]+{stats.insertions}[/]/[red]-{stats.deletions}[/]"
        if wt.has_no_upstream():
            local = wt.unmerged_commits()
        else:
            local = wt.unpushed_commits()
        unpushed = "[dim]-[/]"
        if local:
            unpushed = f"[yellow]{len(local)} commit{'s' if len(local) > 1 else ''}[/]"
        return dirty, unpushed

    with ThreadPoolExecutor(max_workers=len(worktrees)) as pool:
        git_cols = list(pool.map(_git_cols, worktrees))

    # The Sessions column costs a `claude agents` + per-backend session query, so
    # it's opt-in: by default we skip that work and drop the column entirely.
    if sessions:
        claude_agents = list_claude_agents()
        backends = all_isolation_backends()

    table = Table(box=None, pad_edge=False)
    table.add_column("Name", style="bold")
    table.add_column("Branch", style="cyan")
    table.add_column("Dirty")
    table.add_column("Unpushed")
    table.add_column("Sync")
    if sessions:
        table.add_column("Sessions")

    for wt, (dirty, unpushed) in zip(worktrees, git_cols, strict=True):
        if not wt.path.exists():
            row = [wt.path.name, wt.branch, "[red]REMOVED[/]", "", ""]
        else:
            row = [wt.path.name, wt.branch, dirty, unpushed, _sync_col(wt)]
        if sessions and wt.path.exists():
            cells = [
                s.description() for backend in backends for s in backend.list_sessions(wt.path) if s.status == "running"
            ]
            for agent in claude_agents:
                if agent.is_inside(wt.path):
                    label = f"{agent.label} ({agent.activity})"
                    cells.append(f"[green]{label}[/]" if agent.is_active else label)
            row.append(", ".join(cells) if cells else "[dim]-[/]")
        elif sessions:
            row.append("")
        table.add_row(*row)

    Console().print(table)
