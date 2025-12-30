"""Core GitNudge functionality."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from gitnudge.ai import AIAssistant, ConflictResolution, RebaseRecommendation
from gitnudge.config import Config
from gitnudge.git import Git, RebaseState

if TYPE_CHECKING:
    from gitnudge.git import ConflictFile, RebaseAnalysis


@dataclass
class RebaseResult:
    """Result of a rebase operation."""

    success: bool
    commits_applied: int
    conflicts_resolved: int
    message: str
    conflicts: list[ConflictFile] | None = None


class GitNudge:
    """Main GitNudge class coordinating git operations and AI assistance."""

    def __init__(self, config: Config | None = None, repo_path: Path | None = None):
        """Initialize GitNudge.

        Args:
            config: Configuration object. If None, loads from default locations.
            repo_path: Path to the git repository. If None, uses current directory.
        """
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

    def analyze(self, target: str, detailed: bool = False) -> RebaseAnalysis:
        """Analyze a potential rebase operation.

        Args:
            target: Target branch to rebase onto.
            detailed: Whether to include detailed conflict analysis.

        Returns:
            RebaseAnalysis with details and potential conflicts.
        """
        return self.git.analyze_rebase(target)

    def get_ai_recommendation(self, target: str) -> RebaseRecommendation:
        """Get AI recommendation for a rebase.

        Args:
            target: Target branch to rebase onto.

        Returns:
            RebaseRecommendation with advice.
        """
        analysis = self.analyze(target)
        return self.ai.analyze_rebase(analysis)

    def rebase(
        self,
        target: str,
        interactive: bool = False,
        auto_resolve: bool = False,
        dry_run: bool = False,
    ) -> RebaseResult:
        """Perform a rebase with AI assistance.

        Args:
            target: Target branch to rebase onto.
            interactive: Whether to use interactive rebase.
            auto_resolve: Whether to automatically apply AI resolutions.
            dry_run: If True, only analyze without performing rebase.

        Returns:
            RebaseResult with operation outcome.
        """
        state = self.git.get_rebase_state()
        if state != RebaseState.NONE:
            raise GitNudgeError(
                "Rebase already in progress. Use 'gitnudge continue' or 'gitnudge abort'."
            )

        analysis = self.analyze(target)

        if dry_run:
            commits_count = len(analysis.commits_to_rebase)
            return RebaseResult(
                success=True,
                commits_applied=0,
                conflicts_resolved=0,
                message=f"Dry run: Would rebase {commits_count} commits onto {target}",
            )

        commits_to_apply = len(analysis.commits_to_rebase)
        success = self.git.start_rebase(target, interactive)

        if success:
            return RebaseResult(
                success=True,
                commits_applied=commits_to_apply,
                conflicts_resolved=0,
                message=f"Successfully rebased {commits_to_apply} commits onto {target}",
            )

        conflicts_resolved = 0
        while self.git.get_rebase_state() == RebaseState.CONFLICT:
            conflicted_files = self.git.get_conflicted_files()

            if not conflicted_files:
                break

            if auto_resolve:
                for conflict_path in conflicted_files:
                    resolution = self.resolve_conflict(conflict_path)
                    if resolution and resolution.confidence in ("high", "medium"):
                        self.apply_resolution(resolution)
                        conflicts_resolved += 1
                    else:
                        return RebaseResult(
                            success=False,
                            commits_applied=commits_to_apply - len(analysis.commits_to_rebase),
                            conflicts_resolved=conflicts_resolved,
                            message="Stopped at conflict requiring manual resolution",
                            conflicts=[self.git.get_conflict_details(p) for p in conflicted_files],
                        )

                if not self.git.continue_rebase():
                    continue
            else:
                return RebaseResult(
                    success=False,
                    commits_applied=0,
                    conflicts_resolved=0,
                    message="Conflicts detected. Use 'gitnudge resolve' for AI assistance.",
                    conflicts=[self.git.get_conflict_details(p) for p in conflicted_files],
                )

        message = (
            f"Rebased {commits_to_apply} commits with "
            f"{conflicts_resolved} AI-resolved conflicts"
        )
        return RebaseResult(
            success=True,
            commits_applied=commits_to_apply,
            conflicts_resolved=conflicts_resolved,
            message=message,
        )

    def resolve_conflict(
        self,
        file_path: Path | None = None,
        context: str = "",
    ) -> ConflictResolution | None:
        """Get AI resolution for a conflict.

        Args:
            file_path: Specific file to resolve. If None, resolves first conflict.
            context: Additional context for the AI.

        Returns:
            ConflictResolution with suggested fix, or None if no conflicts.
        """
        if file_path is None:
            conflicted = self.git.get_conflicted_files()
            if not conflicted:
                return None
            file_path = conflicted[0]

        conflict = self.git.get_conflict_details(file_path)
        return self.ai.analyze_conflict(conflict, context)

    def explain_conflict(self, file_path: Path | None = None) -> str:
        """Get a plain-language explanation of a conflict.

        Args:
            file_path: Specific file to explain. If None, explains first conflict.

        Returns:
            Human-readable explanation.
        """
        if file_path is None:
            conflicted = self.git.get_conflicted_files()
            if not conflicted:
                return "No conflicts found."
            file_path = conflicted[0]

        conflict = self.git.get_conflict_details(file_path)
        return self.ai.explain_conflict(conflict)

    def apply_resolution(self, resolution: ConflictResolution) -> None:
        """Apply a conflict resolution.

        Args:
            resolution: The resolution to apply.
        """
        file_path = Path(resolution.file_path)

        file_path.write_text(resolution.resolved_content)

        if self.config.behavior.auto_stage:
            self.git.stage_file(file_path)

    def continue_rebase(self, ai_verify: bool = False) -> RebaseResult:
        """Continue a rebase after resolving conflicts.

        Args:
            ai_verify: Whether to verify resolutions with AI first.

        Returns:
            RebaseResult with operation outcome.
        """
        state = self.git.get_rebase_state()
        if state == RebaseState.NONE:
            raise GitNudgeError("No rebase in progress.")

        conflicted = self.git.get_conflicted_files()
        if conflicted:
            raise GitNudgeError(
                f"Unresolved conflicts in: {', '.join(str(f) for f in conflicted)}"
            )

        success = self.git.continue_rebase()

        if success:
            return RebaseResult(
                success=True,
                commits_applied=0,
                conflicts_resolved=0,
                message="Rebase continued successfully",
            )

        new_conflicts = self.git.get_conflicted_files()
        return RebaseResult(
            success=False,
            commits_applied=0,
            conflicts_resolved=0,
            message="New conflicts encountered",
            conflicts=[self.git.get_conflict_details(p) for p in new_conflicts],
        )

    def abort_rebase(self) -> None:
        """Abort the current rebase operation."""
        state = self.git.get_rebase_state()
        if state == RebaseState.NONE:
            raise GitNudgeError("No rebase in progress.")

        self.git.abort_rebase()

    def get_status(self) -> dict[str, Any]:
        """Get current GitNudge status.

        Returns:
            Dictionary with status information.
        """
        state = self.git.get_rebase_state()
        conflicted = self.git.get_conflicted_files() if state != RebaseState.NONE else []

        return {
            "current_branch": self.git.get_current_branch(),
            "rebase_state": state.value,
            "conflicted_files": [str(f) for f in conflicted],
            "config_valid": len(self.config.validate()) == 0,
        }


class GitNudgeError(Exception):
    """GitNudge operation error."""
    pass
