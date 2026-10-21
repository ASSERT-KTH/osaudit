"""The few git queries the audit needs."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    except OSError as e:
        raise GitError(f"git: {e}") from e
    if r.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout


def head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


def dirty(root: Path) -> list[str]:
    """Tracked files modified, staged or deleted, relative to `root` (untracked do not count)."""
    return _git(root, "diff", "--name-only", "--relative", "HEAD").splitlines()


def has_commit(root: Path, commit: str) -> bool:
    try:
        _git(root, "cat-file", "-e", f"{commit}^{{commit}}")
    except GitError:
        return False
    return True


def show(root: Path, commit: str, path: str) -> str | None:
    """The text of `path` (relative to `root`) at `commit`, or None when absent there."""
    try:
        return _git(root, "show", f"{commit}:./{path}")
    except GitError:
        return None


def first_commit(root: Path, path: str) -> str | None:
    """The oldest commit that touched `path`, or None when never committed."""
    out = _git(root, "log", "--format=%H", "--", path).split()
    return out[-1] if out else None


def tracked(root: Path, path: str) -> bool:
    return bool(_git(root, "ls-files", "--", path).strip())


def changed_since(root: Path, commit: str, paths: list[str]) -> list[str]:
    """Of `paths`, those that differ between `commit` and the working tree."""
    if not paths:
        return []
    out = _git(root, "diff", "--name-only", "--relative", commit, "--", *paths)
    return out.splitlines()
