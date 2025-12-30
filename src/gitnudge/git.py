"""Git operations wrapper for GitNudge."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


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


class GitError(Exception):
    """Git operation error."""
    pass


class Git:
    """Git operations wrapper."""

    def __init__(self, repo_path: Path | None = None):
        """Initialize Git wrapper.

        Args:
            repo_path: Path to the git repository. If None, uses current directory.
        """
        self.repo_path = repo_path or Path.cwd()
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
        """Run a git command.

        Args:
            args: Git command arguments (without 'git').
            check: Whether to raise on non-zero exit code.
            capture_output: Whether to capture stdout/stderr.

        Returns:
            CompletedProcess instance.

        Raises:
            GitError: If command fails and check=True.
        """
        cmd = ["git", "-C", str(self.repo_path)] + args

        try:
            result = subprocess.run(
                cmd,
                check=check,
                capture_output=capture_output,
                text=True,
            )
            return result
        except subprocess.CalledProcessError as e:
            raise GitError(f"Git command failed: {' '.join(cmd)}\n{e.stderr}") from e

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        result = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
        return str(result.stdout.strip())

    def get_rebase_state(self) -> RebaseState:
        """Get the current rebase state."""
        git_dir = self.repo_path / ".git"

        if (git_dir / "rebase-merge").exists():
            if self.get_conflicted_files():
                return RebaseState.CONFLICT
            return RebaseState.IN_PROGRESS

        if (git_dir / "rebase-apply").exists():
            if self.get_conflicted_files():
                return RebaseState.CONFLICT
            return RebaseState.IN_PROGRESS

        return RebaseState.NONE

    def get_conflicted_files(self) -> list[Path]:
        """Get list of files with unresolved conflicts."""
        result = self._run(["diff", "--name-only", "--diff-filter=U"], check=False)
        if result.returncode != 0:
            return []

        files = []
        for line in result.stdout.strip().split("\n"):
            if line:
                files.append(self.repo_path / line)
        return files

    def get_conflict_details(self, file_path: Path) -> ConflictFile:
        """Get detailed conflict information for a file.

        Args:
            file_path: Path to the conflicted file.

        Returns:
            ConflictFile with conflict details.
        """
        ours = self._run(["show", f":2:{file_path.name}"], check=False).stdout
        theirs = self._run(["show", f":3:{file_path.name}"], check=False).stdout
        base = self._run(["show", f":1:{file_path.name}"], check=False).stdout

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
        except OSError:
            pass

        return ConflictFile(
            path=file_path,
            ours_content=ours,
            theirs_content=theirs,
            base_content=base,
            conflict_markers=conflict_markers,
        )

    def get_commits_between(self, base: str, head: str = "HEAD") -> list[Commit]:
        """Get commits between base and head.

        Args:
            base: Base reference (e.g., branch name, commit SHA).
            head: Head reference (default: HEAD).

        Returns:
            List of Commit objects.
        """
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

        commits = []
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
        result = self._run(["merge-base", ref1, ref2])
        return str(result.stdout.strip())

    def analyze_rebase(self, target: str) -> RebaseAnalysis:
        """Analyze a potential rebase operation.

        Args:
            target: Target branch/reference to rebase onto.

        Returns:
            RebaseAnalysis with details about the rebase.
        """
        current = self.get_current_branch()
        merge_base = self.get_merge_base(target)
        commits = self.get_commits_between(target)

        potential_conflicts = []

        target_files_result = self._run([
            "diff",
            "--name-only",
            f"{merge_base}..{target}",
        ])
        target_files = set(target_files_result.stdout.strip().split("\n"))

        for commit in commits:
            overlapping = set(commit.files_changed) & target_files
            if overlapping:
                for file in overlapping:
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
        )

    def start_rebase(self, target: str, interactive: bool = False) -> bool:
        """Start a rebase operation.

        Args:
            target: Target branch/reference to rebase onto.
            interactive: Whether to start an interactive rebase.

        Returns:
            True if rebase completed, False if stopped (e.g., conflicts).
        """
        args = ["rebase"]
        if interactive:
            args.append("-i")
        args.append(target)

        result = self._run(args, check=False)
        return result.returncode == 0

    def continue_rebase(self) -> bool:
        """Continue a rebase after resolving conflicts.

        Returns:
            True if rebase completed, False if more conflicts.
        """
        result = self._run(["rebase", "--continue"], check=False)
        return result.returncode == 0

    def abort_rebase(self) -> None:
        """Abort the current rebase operation."""
        self._run(["rebase", "--abort"])

    def stage_file(self, file_path: Path) -> None:
        """Stage a file for commit."""
        self._run(["add", str(file_path)])

    def get_file_content(self, path: str, ref: str = "HEAD") -> str:
        """Get file content at a specific reference.

        Args:
            path: Path to the file.
            ref: Git reference (default: HEAD).

        Returns:
            File content as string.
        """
        result = self._run(["show", f"{ref}:{path}"], check=False)
        return result.stdout if result.returncode == 0 else ""

    def get_diff(self, ref1: str, ref2: str = "HEAD", file_path: str | None = None) -> str:
        """Get diff between two references.

        Args:
            ref1: First reference.
            ref2: Second reference.
            file_path: Optional specific file to diff.

        Returns:
            Diff output as string.
        """
        args = ["diff", ref1, ref2]
        if file_path:
            args.extend(["--", file_path])

        result = self._run(args)
        return str(result.stdout)
