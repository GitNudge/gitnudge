"""Git operations wrapper for GitNudge."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from gitnudge.logging_utils import get_logger

log = get_logger(__name__)

_REF_RE = re.compile(r"^[A-Za-z0-9_./\-@~^{}:+]+$")


def _is_safe_ref(ref: str) -> bool:
    """Conservative ref/branch name validator to prevent argv injection-like surprises."""
    if not ref or ref.startswith("-"):
        return False
    if any(c.isspace() for c in ref):
        return False
    return bool(_REF_RE.match(ref))


class RebaseState(Enum):
    """Current state of a rebase operation."""

    NONE = "none"
    IN_PROGRESS = "in_progress"
    CONFLICT = "conflict"
    STOPPED = "stopped"


@dataclass
class ConflictFile:
    """Represents a file with merge conflicts."""

    path: Path
    ours_content: str
    theirs_content: str
    base_content: str
    conflict_markers: list[tuple[int, int]]

    @property
    def full_content(self) -> str:
        """Get the full file content with conflict markers."""
        try:
            return self.path.read_text()
        except OSError:
            return ""


@dataclass
class Commit:
    """Represents a git commit."""

    sha: str
    short_sha: str
    message: str
    author: str
    date: str
    files_changed: list[str]


@dataclass
class RebaseAnalysis:
    """Analysis of a potential rebase operation."""

    current_branch: str
    target_branch: str
    commits_to_rebase: list[Commit]
    potential_conflicts: list[dict[str, Any]]
    merge_base: str
    is_up_to_date: bool = False
    is_fast_forward: bool = False
    has_merge_base: bool = True


@dataclass
class RebaseProgress:
    """Progress info for an in-progress rebase."""

    current: int
    total: int
    current_subject: str
    current_sha: str


class GitError(Exception):
    """Git operation error."""
    pass


class Git:
    """Git operations wrapper."""

    def __init__(self, repo_path: Path | None = None):
        """Initialize Git wrapper."""
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self._verify_repo()

    def _verify_repo(self) -> None:
        """Verify that we're in a git repository."""
        try:
            self._run(["rev-parse", "--git-dir"])
        except GitError as e:
            raise GitError(f"Not a git repository: {self.repo_path}") from e

    def _run(
        self,
        args: list[str],
        check: bool = True,
        capture_output: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command."""
        cmd = ["git", "-C", str(self.repo_path), *args]
        log.debug("git exec: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                check=check,
                capture_output=capture_output,
                text=True,
            )
            return result
        except subprocess.CalledProcessError as e:
            raise GitError(
                f"Git command failed: {' '.join(cmd)}\n{e.stderr or ''}"
            ) from e

    def _git_dir(self) -> Path:
        """Resolve the actual .git directory (handles worktrees and .git files)."""
        try:
            result = self._run(["rev-parse", "--git-dir"])
            git_dir = Path(result.stdout.strip())
            if not git_dir.is_absolute():
                git_dir = (self.repo_path / git_dir).resolve()
            return git_dir
        except GitError:
            return self.repo_path / ".git"

    def get_current_branch(self) -> str:
        """Get the current branch name (or 'HEAD' if detached)."""
        result = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
        return str(result.stdout.strip())

    def is_detached_head(self) -> bool:
        """Return True if HEAD is detached."""
        return self.get_current_branch() == "HEAD"

    def get_head_sha(self) -> str:
        """Return the commit SHA pointed to by HEAD."""
        result = self._run(["rev-parse", "HEAD"])
        return str(result.stdout.strip())

    def ref_exists(self, ref: str) -> bool:
        """Return True if the given ref/branch/commit exists."""
        if not _is_safe_ref(ref):
            return False
        result = self._run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], check=False)
        return result.returncode == 0

    def has_uncommitted_changes(self) -> bool:
        """Return True if there are unstaged or staged changes."""
        result = self._run(["status", "--porcelain"], check=False)
        for line in result.stdout.splitlines():
            if not line:
                continue
            code = line[:2]
            if code == "??":
                continue
            return True
        return False

    def get_untracked_files(self) -> list[str]:
        """Return list of untracked, unignored files."""
        result = self._run(
            ["ls-files", "--others", "--exclude-standard"], check=False
        )
        return [ln for ln in result.stdout.splitlines() if ln.strip()]

    def is_binary_path(self, path: str) -> bool:
        """Return True if path is a binary file in the index/HEAD."""
        result = self._run(
            ["diff", "--numstat", "HEAD", "--", path], check=False
        )
        for line in result.stdout.splitlines():
            parts = line.split("\t", 2)
            if len(parts) >= 1 and parts[0] == "-":
                return True
        attr = self._run(["check-attr", "binary", "--", path], check=False)
        if "binary: set" in attr.stdout:
            return True
        return False

    def get_rebase_progress(self) -> RebaseProgress | None:
        """Return progress for an in-progress rebase, or None."""
        git_dir = self._git_dir()

        for sub in ("rebase-merge", "rebase-apply"):
            base = git_dir / sub
            if not base.exists():
                continue
            try:
                msgnum_file = base / ("msgnum" if sub == "rebase-merge" else "next")
                end_file = base / ("end" if sub == "rebase-merge" else "last")
                current = int(msgnum_file.read_text().strip()) if msgnum_file.exists() else 0
                total = int(end_file.read_text().strip()) if end_file.exists() else 0

                subject = ""
                sha = ""
                msg_file = base / "message"
                if msg_file.exists():
                    subject = msg_file.read_text().splitlines()[0] if msg_file.read_text() else ""
                head_name = base / "stopped-sha"
                if head_name.exists():
                    sha = head_name.read_text().strip()

                return RebaseProgress(
                    current=current,
                    total=total,
                    current_subject=subject,
                    current_sha=sha,
                )
            except (OSError, ValueError) as e:
                log.debug("Could not parse rebase progress: %s", e)
                return None
        return None

    def get_rebase_state(self) -> RebaseState:
        """Get the current rebase state."""
        git_dir = self._git_dir()

        if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
            if self.get_conflicted_files():
                return RebaseState.CONFLICT
            return RebaseState.IN_PROGRESS

        return RebaseState.NONE

    def get_conflicted_files(self) -> list[Path]:
        """Get list of files with unresolved conflicts as repo-relative paths."""
        result = self._run(["diff", "--name-only", "--diff-filter=U"], check=False)
        if result.returncode != 0:
            return []

        files: list[Path] = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                files.append(self.repo_path / line)
        return files

    def _to_repo_relative(self, file_path: Path) -> str:
        """Convert a path to a repo-relative string (POSIX-style)."""
        p = Path(file_path)
        if p.is_absolute():
            try:
                rel = p.resolve().relative_to(self.repo_path)
            except ValueError as e:
                raise GitError(
                    f"Path {file_path} is outside repository {self.repo_path}"
                ) from e
            return rel.as_posix()
        return p.as_posix()

    def get_conflict_details(self, file_path: Path) -> ConflictFile:
        """Get detailed conflict information for a file."""
        rel = self._to_repo_relative(file_path)

        ours = self._run(["show", f":2:{rel}"], check=False).stdout
        theirs = self._run(["show", f":3:{rel}"], check=False).stdout
        base = self._run(["show", f":1:{rel}"], check=False).stdout

        conflict_markers = []
        try:
            content = file_path.read_text()
            lines = content.split("\n")
            start = None
            for i, line in enumerate(lines):
                if line.startswith("<<<<<<<"):
                    start = i
                elif line.startswith(">>>>>>>") and start is not None:
                    conflict_markers.append((start, i))
                    start = None
        except OSError as e:
            log.warning("Could not read conflict markers from %s: %s", file_path, e)

        return ConflictFile(
            path=file_path,
            ours_content=ours,
            theirs_content=theirs,
            base_content=base,
            conflict_markers=conflict_markers,
        )

    def get_commits_between(self, base: str, head: str = "HEAD") -> list[Commit]:
        """Get commits between base and head."""
        if not _is_safe_ref(base) or not _is_safe_ref(head):
            raise GitError(f"Invalid git reference: {base!r} or {head!r}")

        merge_base_result = self._run(["merge-base", base, head], check=False)
        if merge_base_result.returncode != 0:
            return []
        merge_base = merge_base_result.stdout.strip()

        format_str = "%H|%h|%s|%an|%ai"
        result = self._run([
            "log",
            "--format=" + format_str,
            f"{merge_base}..{head}",
        ])

        commits: list[Commit] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 4)
            if len(parts) >= 5:
                sha, short_sha, message, author, date = parts

                files_result = self._run([
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "-r",
                    sha,
                ])
                files = [f for f in files_result.stdout.strip().split("\n") if f]

                commits.append(Commit(
                    sha=sha,
                    short_sha=short_sha,
                    message=message,
                    author=author,
                    date=date,
                    files_changed=files,
                ))

        return commits

    def get_merge_base(self, ref1: str, ref2: str = "HEAD") -> str:
        """Get the merge base between two references."""
        if not _is_safe_ref(ref1) or not _is_safe_ref(ref2):
            raise GitError(f"Invalid git reference: {ref1!r} or {ref2!r}")
        result = self._run(["merge-base", ref1, ref2])
        return str(result.stdout.strip())

    def analyze_rebase(self, target: str) -> RebaseAnalysis:
        """Analyze a potential rebase operation."""
        if not _is_safe_ref(target):
            raise GitError(f"Invalid target reference: {target!r}")

        current = self.get_current_branch()

        if not self.ref_exists(target):
            raise GitError(f"Target ref does not exist: {target}")

        merge_base_result = self._run(["merge-base", target, "HEAD"], check=False)
        if merge_base_result.returncode != 0:
            return RebaseAnalysis(
                current_branch=current,
                target_branch=target,
                commits_to_rebase=[],
                potential_conflicts=[],
                merge_base="",
                has_merge_base=False,
            )
        merge_base = merge_base_result.stdout.strip()

        head_sha = self.get_head_sha()
        target_sha_result = self._run(["rev-parse", target], check=False)
        target_sha = target_sha_result.stdout.strip() if target_sha_result.returncode == 0 else ""

        is_up_to_date = bool(target_sha) and merge_base == head_sha
        is_fast_forward = bool(target_sha) and merge_base == head_sha and target_sha != head_sha

        commits = self.get_commits_between(target)

        potential_conflicts: list[dict[str, Any]] = []

        target_files_result = self._run([
            "diff", "--name-only", f"{merge_base}..{target}",
        ], check=False)
        target_files = {
            f for f in target_files_result.stdout.strip().split("\n") if f
        }

        binary_cache: dict[str, bool] = {}
        for commit in commits:
            overlapping = set(commit.files_changed) & target_files
            for file in overlapping:
                if file not in binary_cache:
                    binary_cache[file] = self.is_binary_path(file)
                if binary_cache[file]:
                    continue
                potential_conflicts.append({
                    "file": file,
                    "commit": commit.short_sha,
                    "message": commit.message,
                })

        return RebaseAnalysis(
            current_branch=current,
            target_branch=target,
            commits_to_rebase=commits,
            potential_conflicts=potential_conflicts,
            merge_base=merge_base,
            is_up_to_date=is_up_to_date,
            is_fast_forward=is_fast_forward,
            has_merge_base=True,
        )

    def start_rebase(self, target: str, interactive: bool = False) -> bool:
        """Start a rebase operation."""
        if not _is_safe_ref(target):
            raise GitError(f"Invalid target reference: {target!r}")

        args = ["rebase"]
        if interactive:
            args.append("-i")
        args.append("--")
        args.append(target)

        result = self._run(args, check=False)
        return result.returncode == 0

    def continue_rebase(self) -> bool:
        """Continue a rebase after resolving conflicts."""
        env = {"GIT_EDITOR": "true"}
        result = self._run_with_env(["rebase", "--continue"], env, check=False)
        return result.returncode == 0

    def skip_rebase(self) -> bool:
        """Skip the current commit during a rebase."""
        result = self._run(["rebase", "--skip"], check=False)
        return result.returncode == 0

    def abort_rebase(self) -> None:
        """Abort the current rebase operation."""
        self._run(["rebase", "--abort"])

    def _run_with_env(
        self,
        args: list[str],
        env: dict[str, str],
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a git command with extra env vars merged into the parent env."""
        import os
        cmd = ["git", "-C", str(self.repo_path), *args]
        merged = {**os.environ, **env}
        log.debug("git exec (env=%s): %s", list(env.keys()), " ".join(cmd))
        try:
            return subprocess.run(
                cmd, check=check, capture_output=True, text=True, env=merged
            )
        except subprocess.CalledProcessError as e:
            raise GitError(
                f"Git command failed: {' '.join(cmd)}\n{e.stderr or ''}"
            ) from e

    def stage_file(self, file_path: Path) -> None:
        """Stage a file for commit."""
        rel = self._to_repo_relative(file_path)
        self._run(["add", "--", rel])

    def get_file_content(self, path: str, ref: str = "HEAD") -> str:
        """Get file content at a specific reference."""
        if not _is_safe_ref(ref):
            raise GitError(f"Invalid git reference: {ref!r}")
        result = self._run(["show", f"{ref}:{path}"], check=False)
        return result.stdout if result.returncode == 0 else ""

    def get_diff(self, ref1: str, ref2: str = "HEAD", file_path: str | None = None) -> str:
        """Get diff between two references."""
        if not _is_safe_ref(ref1) or not _is_safe_ref(ref2):
            raise GitError(f"Invalid git reference: {ref1!r} or {ref2!r}")

        args = ["diff", ref1, ref2]
        if file_path:
            args.extend(["--", file_path])

        result = self._run(args)
        return str(result.stdout)
