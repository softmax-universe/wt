import shutil
import subprocess
from pathlib import Path

from softmaxwt.config import Config, Hooks, InplaceOpenerConfig, NoopOpenerConfig, Profile
from softmaxwt.test_support.helpers import invoke, wt_run


def _write_init_profile(init: str | None, background_init: str | None = None) -> None:
    config = Config()
    config.profiles["setup"] = Profile(
        opener=NoopOpenerConfig(), hooks=Hooks(init=init, background_init=background_init)
    )
    config.save()


def test_create_runs_init_in_the_new_worktree(git_repo: Path) -> None:
    _write_init_profile("echo test > init-file")
    invoke("create", "foo", "--profile", "setup", cwd=git_repo)
    assert (git_repo / ".worktrees" / "foo" / "init-file").read_text().strip() == "test"


def test_failed_init_returns_its_exit_status(git_repo: Path) -> None:
    _write_init_profile("exit 3")
    result = wt_run("create", "foo", "--profile", "setup", cwd=git_repo)
    assert result.returncode == 3


def test_sync_init_prepares_background_fallback(git_repo: Path) -> None:
    _write_init_profile("echo prepared > prerequisite", background_init="cat prerequisite > result")
    invoke("create", "foo", "--profile", "setup", cwd=git_repo)
    assert (git_repo / ".worktrees" / "foo" / "result").read_text().strip() == "prepared"


def test_create_runs_a_stored_v1_profile(git_repo: Path) -> None:
    config_file = git_repo / "xdg_config" / "wt" / "config.yml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(
        "version: 1\nprofiles:\n  setup:\n    init: echo migrated > result\n    init_background: true\n"
        "    opener:\n      type: noop\n"
    )
    invoke("create", "foo", "--profile", "setup", cwd=git_repo)
    assert (git_repo / ".worktrees" / "foo" / "result").read_text().strip() == "migrated"


def test_duplicate_create_preserves_the_existing_worktree(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    sentinel = git_repo / ".worktrees" / "foo" / "work.txt"
    sentinel.write_text("uncommitted work")
    result = wt_run("create", "foo", "--opener", "noop", cwd=git_repo)
    assert result.returncode != 0
    assert sentinel.read_text() == "uncommitted work"


def test_open_runs_surface_init(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    config = Config()
    config.profiles["dev"] = Profile(
        opener=InplaceOpenerConfig(), hooks=Hooks(surface_init="echo opened > surface-result")
    )
    config.save()
    invoke("open", "foo", "--profile", "dev", cwd=git_repo)
    assert (git_repo / ".worktrees" / "foo" / "surface-result").read_text().strip() == "opened"


def test_destroy_removes_a_disposable_worktree_and_branch(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    invoke("destroy", "foo", cwd=git_repo)
    assert not (git_repo / ".worktrees" / "foo").exists()
    assert subprocess.check_output(["git", "branch", "--list", "wt/foo"], cwd=git_repo, text=True) == ""


def test_declined_destroy_preserves_uncommitted_work(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    sentinel = git_repo / ".worktrees" / "foo" / "work.txt"
    sentinel.write_text("uncommitted work")
    result = wt_run("destroy", "foo", cwd=git_repo, stdin="no\n")
    assert result.returncode != 0
    assert sentinel.read_text() == "uncommitted work"


def test_declined_destroy_preserves_a_local_commit(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    wt_path = git_repo / ".worktrees" / "foo"
    (wt_path / "work.txt").write_text("committed work")
    subprocess.run(["git", "add", "work.txt"], cwd=wt_path, check=True)
    subprocess.run(["git", "commit", "-m", "local work"], cwd=wt_path, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt_path, text=True)
    result = wt_run("destroy", "foo", cwd=git_repo, stdin="no\n")
    assert result.returncode != 0
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt_path, text=True) == commit


def test_declined_destroy_preserves_a_branch_with_a_missing_directory(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    wt_path = git_repo / ".worktrees" / "foo"
    (wt_path / "work.txt").write_text("committed work")
    subprocess.run(["git", "add", "work.txt"], cwd=wt_path, check=True)
    subprocess.run(["git", "commit", "-m", "local work"], cwd=wt_path, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "wt/foo"], cwd=git_repo, text=True)
    shutil.rmtree(wt_path)
    result = wt_run("destroy", "foo", cwd=git_repo, stdin="no\n")
    assert result.returncode != 0
    assert subprocess.check_output(["git", "rev-parse", "wt/foo"], cwd=git_repo, text=True) == commit


def test_destroy_removes_read_only_build_artifacts(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    wt_path = git_repo / ".worktrees" / "foo"
    bazel_dir = wt_path / "bazel-out" / "some-target"
    bazel_dir.mkdir(parents=True)
    locked_file = bazel_dir / "locked.o"
    locked_file.write_text("data")
    locked_file.chmod(0o000)
    bazel_dir.chmod(0o500)
    invoke("destroy", "foo", "-y", cwd=git_repo)
    assert not wt_path.exists()


def test_gc_removes_a_disposable_worktree(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    result = wt_run("gc", cwd=git_repo, stdin="y\n")
    assert result.returncode == 0
    assert not (git_repo / ".worktrees" / "foo").exists()


def test_gc_preserves_uncommitted_work(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    sentinel = git_repo / ".worktrees" / "foo" / "work.txt"
    sentinel.write_text("uncommitted work")
    result = wt_run("gc", cwd=git_repo, stdin="y\n")
    assert result.returncode == 0
    assert sentinel.read_text() == "uncommitted work"


def test_gc_preserves_a_local_commit(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    wt_path = git_repo / ".worktrees" / "foo"
    (wt_path / "work.txt").write_text("committed work")
    subprocess.run(["git", "add", "work.txt"], cwd=wt_path, check=True)
    subprocess.run(["git", "commit", "-m", "local work"], cwd=wt_path, check=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt_path, text=True)
    result = wt_run("gc", cwd=git_repo, stdin="y\n")
    assert result.returncode == 0
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=wt_path, text=True) == commit


def test_self_destroy_removes_the_current_worktree_and_branch(git_repo: Path) -> None:
    invoke("create", "foo", "--opener", "noop", cwd=git_repo)
    wt_path = git_repo / ".worktrees" / "foo"
    invoke("self-destroy", cwd=wt_path)
    assert not wt_path.exists()
    assert subprocess.check_output(["git", "branch", "--list", "wt/foo"], cwd=git_repo, text=True) == ""


def test_self_destroy_refuses_the_main_checkout(git_repo: Path) -> None:
    sentinel = git_repo / "work.txt"
    sentinel.write_text("main checkout work")
    result = wt_run("self-destroy", cwd=git_repo)
    assert result.returncode != 0
    assert sentinel.read_text() == "main checkout work"
