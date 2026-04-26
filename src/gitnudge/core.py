"""Core GitNudge functionality."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gitnudge.ai import AIAssistant, ConflictResolution, RebaseRecommendation
from gitnudge.config import Config
from gitnudge.git import Git, RebaseState
from gitnudge.logging_utils import get_logger

if TYPE_CHECKING:
    from gitnudge.git import ConflictFile, RebaseAnalysis

log = get_logger(__name__)

CONFLICT_MARKER_PREFIXES = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")


@dataclass
class RebaseResult:
    """Result of a rebase operation."""

    success: bool
    commits_applied: int
    conflicts_resolved: int
    message: str
    conflicts: list[ConflictFile] | None = None
    safety_sha: str | None = None
    warnings: list[str] = field(default_factory=list)
    applied_resolutions: list[dict[str, str]] = field(default_factory=list)


def _has_conflict_markers(text: str) -> bool:
    for line in text.splitlines():
        if any(line.startswith(prefix) for prefix in CONFLICT_MARKER_PREFIXES):
            return True
    return False


class GitNudge:
    """Main GitNudge class coordinating git operations and AI assistance."""

    SNAPSHOT_NAME = "gitnudge-snapshot.json"

    def __init__(self, config: Config | None = None, repo_path: Path | None = None):
        """Initialize GitNudge."""
        self.config = config or Config.load()
        self.git = Git(repo_path)
        self._ai: AIAssistant | None = None

    @property
    def ai(self) -> AIAssistant:
        """Lazy-load AI assistant."""
        if self._ai is None:
            errors = self.config.validate()
            if errors:
                raise GitNudgeError(f"Configuration errors: {'; '.join(errors)}")
            self._ai = AIAssistant(self.config)
        return self._ai

    def analyze(self, target: str) -> RebaseAnalysis:
        """Analyze a potential rebase operation."""
        return self.git.analyze_rebase(target)

    def get_ai_recommendation(self, target: str) -> RebaseRecommendation:
        """Get AI recommendation for a rebase."""
        analysis = self.analyze(target)
        return self.ai.analyze_rebase(analysis)

    def preflight(self, target: str) -> list[str]:
        """Run pre-flight safety checks. Returns list of blocking errors (empty = ok)."""
        errors: list[str] = []

        if not self.git.ref_exists(target):
            errors.append(f"Target ref does not exist: {target}")
            return errors

        if self.git.is_detached_head():
            errors.append("HEAD is detached. Check out a branch before rebasing.")

        if self.git.has_uncommitted_changes():
            errors.append(
                "Working tree has uncommitted changes. "
                "Commit or stash them before rebasing."
            )

        if self.git.get_rebase_state() != RebaseState.NONE:
            errors.append(
                "Rebase already in progress. Use 'gitnudge continue', "
                "'gitnudge skip', or 'gitnudge abort'."
            )

        return errors

    def rebase(
        self,
        target: str,
        interactive: bool = False,
        auto_resolve: bool = False,
        dry_run: bool = False,
        force: bool = False,
    ) -> RebaseResult:
        """Perform a rebase with AI assistance."""
        if not dry_run and not force:
            errors = self.preflight(target)
            if errors:
                raise GitNudgeError("; ".join(errors))

        analysis = self.analyze(target)
        commits_to_apply = len(analysis.commits_to_rebase)
        warnings: list[str] = []

        if not analysis.has_merge_base:
            raise GitNudgeError(
                f"No common ancestor between HEAD and {target}. "
                "Refusing to rebase unrelated histories."
            )

        if analysis.is_up_to_date and commits_to_apply == 0:
            return RebaseResult(
                success=True,
                commits_applied=0,
                conflicts_resolved=0,
                message=(
                    f"Already up to date with {target} "
                    "(branch is fully contained in target)."
                ),
            )

        if dry_run:
            log.info("dry-run: would rebase %d commits onto %s", commits_to_apply, target)
            return RebaseResult(
                success=True,
                commits_applied=0,
                conflicts_resolved=0,
                message=f"Dry run: Would rebase {commits_to_apply} commits onto {target}",
            )

        safety_sha = self.git.get_head_sha()
        self._save_snapshot(target=target, head=safety_sha)
        log.info("snapshot saved: pre-rebase HEAD=%s", safety_sha)

        success = self.git.start_rebase(target, interactive)

        if success:
            return RebaseResult(
                success=True,
                commits_applied=commits_to_apply,
                conflicts_resolved=0,
                message=f"Successfully rebased {commits_to_apply} commits onto {target}",
                safety_sha=safety_sha,
            )

        conflicts_resolved = 0
        applied_resolutions: list[dict[str, str]] = []
        max_iterations = max(commits_to_apply * 3, 20)
        iterations = 0

        while self.git.get_rebase_state() == RebaseState.CONFLICT:
            iterations += 1
            if iterations > max_iterations:
                warnings.append(f"rebase loop hit max iterations ({max_iterations})")
                log.warning(warnings[-1])
                break

            conflicted_files = self.git.get_conflicted_files()
            if not conflicted_files:
                break

            if not auto_resolve:
                return RebaseResult(
                    success=False,
                    commits_applied=0,
                    conflicts_resolved=0,
                    message="Conflicts detected. Use 'gitnudge resolve' for AI assistance.",
                    conflicts=[self.git.get_conflict_details(p) for p in conflicted_files],
                    safety_sha=safety_sha,
                )

            stop = False
            for conflict_path in conflicted_files:
                resolution = self.resolve_conflict(conflict_path)
                if (
                    resolution
                    and resolution.confidence in ("high", "medium")
                    and not _has_conflict_markers(resolution.resolved_content)
                ):
                    self.apply_resolution(resolution)
                    conflicts_resolved += 1
                    applied_resolutions.append({
                        "file": str(conflict_path),
                        "confidence": resolution.confidence,
                        "summary": resolution.changes_summary or "",
                    })
                    log.info(
                        "auto-resolved %s (confidence=%s)",
                        conflict_path, resolution.confidence,
                    )
                else:
                    reason = "low-confidence resolution"
                    if resolution and _has_conflict_markers(resolution.resolved_content):
                        reason = "AI returned content still containing conflict markers"
                    warnings.append(f"{conflict_path}: {reason}")
                    stop = True
                    break

            if stop:
                return RebaseResult(
                    success=False,
                    commits_applied=0,
                    conflicts_resolved=conflicts_resolved,
                    message="Stopped at conflict requiring manual resolution",
                    conflicts=[
                        self.git.get_conflict_details(p)
                        for p in self.git.get_conflicted_files()
                    ],
                    safety_sha=safety_sha,
                    warnings=warnings,
                    applied_resolutions=applied_resolutions,
                )

            if self.git.get_conflicted_files():
                continue

            self.git.continue_rebase()

        message = (
            f"Rebased {commits_to_apply} commits with "
            f"{conflicts_resolved} AI-resolved conflicts"
        )
        return RebaseResult(
            success=True,
            commits_applied=commits_to_apply,
            conflicts_resolved=conflicts_resolved,
            message=message,
            safety_sha=safety_sha,
            warnings=warnings,
            applied_resolutions=applied_resolutions,
        )

    def resolve_conflict(
        self,
        file_path: Path | None = None,
        context: str = "",
    ) -> ConflictResolution | None:
        """Get AI resolution for a conflict."""
        if file_path is None:
            conflicted = self.git.get_conflicted_files()
            if not conflicted:
                return None
            file_path = conflicted[0]

        conflict = self.git.get_conflict_details(file_path)
        return self.ai.analyze_conflict(conflict, context)

    def explain_conflict(self, file_path: Path | None = None) -> str:
        """Get a plain-language explanation of a conflict."""
        if file_path is None:
            conflicted = self.git.get_conflicted_files()
            if not conflicted:
                return "No conflicts found."
            file_path = conflicted[0]

        conflict = self.git.get_conflict_details(file_path)
        return self.ai.explain_conflict(conflict)

    def apply_resolution(self, resolution: ConflictResolution) -> None:
        """Apply a conflict resolution to disk safely."""
        if _has_conflict_markers(resolution.resolved_content):
            raise GitNudgeError(
                f"Refusing to apply resolution for {resolution.file_path}: "
                "content still contains conflict markers"
            )

        file_path = Path(resolution.file_path)
        target = self._resolve_inside_repo(file_path)

        try:
            target.write_text(resolution.resolved_content)
        except OSError as e:
            log.error("Failed to write resolution for %s: %s", target, e)
            raise GitNudgeError(f"Failed to write {target}: {e}") from e

        if self.config.behavior.auto_stage:
            self.git.stage_file(target)

    def _resolve_inside_repo(self, file_path: Path) -> Path:
        """Resolve and validate file_path is inside the repo."""
        repo = self.git.repo_path.resolve()
        candidate = file_path if file_path.is_absolute() else repo / file_path
        try:
            resolved = candidate.resolve()
            resolved.relative_to(repo)
        except (ValueError, OSError) as e:
            raise GitNudgeError(
                f"Refusing to write outside repository: {file_path}"
            ) from e
        return resolved

    def continue_rebase(self, ai_verify: bool = False) -> RebaseResult:
        """Continue a rebase after resolving conflicts."""
        state = self.git.get_rebase_state()
        if state == RebaseState.NONE:
            raise GitNudgeError("No rebase in progress.")

        conflicted = self.git.get_conflicted_files()
        if conflicted:
            raise GitNudgeError(
                f"Unresolved conflicts in: {', '.join(str(f) for f in conflicted)}"
            )

        warnings: list[str] = []
        if ai_verify:
            warnings.extend(self._ai_verify_staged_resolutions())

        before_progress = self.git.get_rebase_progress()
        before_done = before_progress.current if before_progress else 0
        before_total = before_progress.total if before_progress else 0

        success = self.git.continue_rebase()

        after_progress = self.git.get_rebase_progress()
        rebase_complete = success and self.git.get_rebase_state() == RebaseState.NONE

        if rebase_complete:
            applied = max(before_total - before_done, 1)
            remaining = 0
        else:
            after_done = after_progress.current if after_progress else 0
            total = after_progress.total if after_progress else before_total
            remaining = max(total - after_done, 0)
            applied = (
                max(after_done - before_done, 1)
                if success
                else max(after_done - before_done, 0)
            )

        if rebase_complete:
            self._clear_snapshot()
            return RebaseResult(
                success=True,
                commits_applied=applied,
                conflicts_resolved=0,
                message=f"Rebase complete (applied {applied} more commits)",
                warnings=warnings,
            )

        if success:
            return RebaseResult(
                success=True,
                commits_applied=applied,
                conflicts_resolved=0,
                message=(
                    f"Continued rebase: applied {applied} more commits, "
                    f"{remaining} remaining"
                ),
                warnings=warnings,
            )

        new_conflicts = self.git.get_conflicted_files()
        return RebaseResult(
            success=False,
            commits_applied=applied,
            conflicts_resolved=0,
            message=f"New conflicts encountered ({remaining} commits remaining)",
            conflicts=[self.git.get_conflict_details(p) for p in new_conflicts],
            warnings=warnings,
        )

    def _ai_verify_staged_resolutions(self) -> list[str]:
        """Verify currently-staged files don't still have conflict markers."""
        warnings: list[str] = []
        result = self.git._run(["diff", "--cached", "--name-only"], check=False)
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                content = (self.git.repo_path / line).read_text()
            except OSError:
                continue
            if _has_conflict_markers(content):
                warnings.append(f"{line}: still contains conflict markers")
        if warnings:
            raise GitNudgeError(
                "AI verification failed: " + "; ".join(warnings)
            )
        return warnings

    def skip_rebase(self) -> RebaseResult:
        """Skip the current commit in the rebase."""
        state = self.git.get_rebase_state()
        if state == RebaseState.NONE:
            raise GitNudgeError("No rebase in progress.")

        success = self.git.skip_rebase()
        if success and self.git.get_rebase_state() == RebaseState.NONE:
            self._clear_snapshot()
            return RebaseResult(
                success=True,
                commits_applied=0,
                conflicts_resolved=0,
                message="Rebase complete after skipping commit",
            )
        if success:
            progress = self.git.get_rebase_progress()
            remaining = max(progress.total - progress.current + 1, 0) if progress else 0
            return RebaseResult(
                success=True,
                commits_applied=0,
                conflicts_resolved=0,
                message=f"Skipped commit ({remaining} remaining)",
            )

        new_conflicts = self.git.get_conflicted_files()
        return RebaseResult(
            success=False,
            commits_applied=0,
            conflicts_resolved=0,
            message="Skip produced new conflicts",
            conflicts=[self.git.get_conflict_details(p) for p in new_conflicts],
        )

    def abort_rebase(self) -> None:
        """Abort the current rebase operation."""
        state = self.git.get_rebase_state()
        if state == RebaseState.NONE:
            raise GitNudgeError("No rebase in progress.")

        self.git.abort_rebase()
        self._clear_snapshot()

    def get_status(self) -> dict[str, Any]:
        """Get current GitNudge status."""
        state = self.git.get_rebase_state()
        conflicted = self.git.get_conflicted_files() if state != RebaseState.NONE else []
        progress = self.git.get_rebase_progress() if state != RebaseState.NONE else None

        snapshot = self._load_snapshot()

        return {
            "current_branch": self.git.get_current_branch(),
            "rebase_state": state.value,
            "conflicted_files": [str(f) for f in conflicted],
            "config_valid": len(self.config.validate()) == 0,
            "progress": (
                {
                    "current": progress.current,
                    "total": progress.total,
                    "subject": progress.current_subject,
                    "sha": progress.current_sha,
                }
                if progress
                else None
            ),
            "safety_sha": snapshot.get("head") if snapshot else None,
        }

    def _snapshot_path(self) -> Path:
        return self.git._git_dir() / self.SNAPSHOT_NAME

    def _save_snapshot(self, target: str, head: str) -> None:
        """Atomically write the pre-rebase recovery snapshot."""
        path = self._snapshot_path()
        try:
            payload = json.dumps(
                {
                    "head": head,
                    "target": target,
                    "branch": self.git.get_current_branch(),
                    "timestamp": int(time.time()),
                },
                indent=2,
            )
        except (TypeError, ValueError) as e:
            log.warning("Could not serialize safety snapshot: %s", e)
            return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(
                prefix=".gitnudge-snapshot.",
                suffix=".tmp",
                dir=str(path.parent),
            )
            try:
                with os.fdopen(fd, "w") as f:
                    f.write(payload)
                os.replace(tmp_path, path)
                log.debug("snapshot written atomically to %s", path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except OSError as e:
            log.warning("Could not save safety snapshot: %s", e)

    def _load_snapshot(self) -> dict[str, Any] | None:
        path = self._snapshot_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Could not read snapshot: %s", e)
            return None

    def _clear_snapshot(self) -> None:
        path = self._snapshot_path()
        try:
            if path.exists():
                path.unlink()
        except OSError as e:
            log.warning("Could not remove snapshot: %s", e)

    def get_recovery_info(self) -> dict[str, Any]:
        """Return info needed to recover the pre-rebase state."""
        snapshot = self._load_snapshot()
        reflog = self.git._run(
            ["reflog", "-n", "20", "--format=%h %gd %gs"], check=False
        ).stdout
        return {
            "snapshot": snapshot,
            "reflog": reflog,
            "current_head": self.git.get_head_sha(),
            "current_branch": self.git.get_current_branch(),
        }


class GitNudgeError(Exception):
    """GitNudge operation error."""
    pass
