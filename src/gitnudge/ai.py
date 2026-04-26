"""AI integration module using Claude API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field, field_validator

from gitnudge.logging_utils import get_logger, redact_secrets

if TYPE_CHECKING:
    from gitnudge.config import Config
    from gitnudge.git import ConflictFile, RebaseAnalysis

log = get_logger(__name__)

Confidence = Literal["high", "medium", "low"]
RiskLevel = Literal["low", "medium", "high"]


class ConflictResolution(BaseModel):
    """Suggested resolution for a conflict."""

    model_config = ConfigDict(validate_assignment=True)

    file_path: str
    resolved_content: str
    explanation: str = ""
    confidence: Confidence = "medium"
    changes_summary: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, v: object) -> str:
        s = str(v or "").strip().lower().strip(".,;:!?\"'`*")
        s = s.split(None, 1)[0] if s else ""
        return s if s in ("high", "medium", "low") else "medium"


class RebaseRecommendation(BaseModel):
    """AI recommendation for a rebase operation."""

    model_config = ConfigDict(validate_assignment=True)

    should_proceed: bool = False
    risk_level: RiskLevel = "medium"
    explanation: str = ""
    suggested_approach: str = ""
    warnings: list[str] = Field(default_factory=list)

    @field_validator("risk_level", mode="before")
    @classmethod
    def _normalize_risk(cls, v: object) -> str:
        s = str(v or "").strip().lower().strip(".,;:!?\"'`*")
        s = s.split(None, 1)[0] if s else ""
        return s if s in ("low", "medium", "high") else "medium"


class AIAssistant:
    """AI assistant for git operations using Claude."""

    SYSTEM_PROMPT = (
        "You are GitNudge, an AI assistant specialized in helping "
        "developers with git rebase operations. Your role is to:\n\n"
        "1. Analyze merge conflicts and suggest intelligent resolutions\n"
        "2. Explain why conflicts occurred based on the code changes\n"
        "3. Recommend the best approach for complex rebases\n"
        "4. Help developers understand git operations\n\n"
        "When analyzing conflicts:\n"
        "- Consider the semantic meaning of code changes, not just textual differences\n"
        "- Look at commit messages for context on intent\n"
        "- Preserve functionality from both branches when possible\n"
        "- Flag cases where human judgment is needed\n\n"
        "When suggesting resolutions:\n"
        "- Provide complete, working code\n"
        "- Explain your reasoning\n"
        "- Rate your confidence (high/medium/low)\n"
        "- Warn about potential issues\n\n"
        "Always be helpful, clear, and focused on helping the developer "
        "succeed with their rebase."
    )

    def __init__(self, config: Config):
        """Initialize the AI assistant."""
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.api.api_key)
        self.model = config.api.model
        self.max_tokens = config.api.max_tokens

    @staticmethod
    def _truncate(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n... [truncated]"

    def analyze_conflict(self, conflict: ConflictFile, context: str = "") -> ConflictResolution:
        """Analyze a conflict and suggest a resolution."""
        max_chars = max(self.config.behavior.max_context_lines, 10) * 80
        full_content = conflict.full_content
        prompt = f"""Analyze this git merge conflict and suggest a resolution.

## File: {conflict.path.name}

### Base version (common ancestor):
```
{self._truncate(conflict.base_content, max_chars)}
```

### Our version (current branch):
```
{self._truncate(conflict.ours_content, max_chars)}
```

### Their version (incoming changes):
```
{self._truncate(conflict.theirs_content, max_chars)}
```

### Current file with conflict markers:
```
{self._truncate(full_content, max_chars)}
```

{f"### Additional context:{chr(10)}{context}" if context else ""}

Please provide:
1. A brief explanation of what caused this conflict
2. The resolved file content (complete, ready to save)
3. Your confidence level (high/medium/low)
4. A summary of the changes you made

Format your response as:

EXPLANATION:
[Your explanation here]

RESOLVED_CONTENT:
```
[Complete resolved file content here]
```

CONFIDENCE: [high/medium/low]

CHANGES_SUMMARY:
[Summary of changes made]"""

        response = self._call_api(prompt)
        return self._parse_conflict_response(str(conflict.path), response)

    def analyze_rebase(self, analysis: RebaseAnalysis) -> RebaseRecommendation:
        """Analyze a potential rebase and provide recommendations."""
        commits_text = "\n".join([
            f"- {c.short_sha}: {c.message} (files: {', '.join(c.files_changed[:5])})"
            for c in analysis.commits_to_rebase[:20]
        ])

        conflicts_text = "\n".join([
            f"- {c['file']} (modified in commit {c['commit']}: {c['message']})"
            for c in analysis.potential_conflicts[:20]
        ])

        prompt = f"""Analyze this potential git rebase operation and provide recommendations.

## Rebase Details
- Current branch: {analysis.current_branch}
- Target branch: {analysis.target_branch}
- Merge base: {analysis.merge_base[:8]}
- Number of commits to rebase: {len(analysis.commits_to_rebase)}

## Commits to be rebased:
{commits_text}

## Potential conflict files:
{conflicts_text if conflicts_text else "No obvious conflicts detected"}

Please analyze this rebase and provide:
1. Whether to proceed (yes/no)
2. Risk level (low/medium/high)
3. Explanation of your assessment
4. Suggested approach for this rebase
5. Any warnings or things to watch out for

Format your response as:

SHOULD_PROCEED: [yes/no]

RISK_LEVEL: [low/medium/high]

EXPLANATION:
[Your explanation here]

SUGGESTED_APPROACH:
[Your suggested approach here]

WARNINGS:
- [Warning 1]
- [Warning 2]
(or "None" if no warnings)"""

        response = self._call_api(prompt)
        return self._parse_rebase_response(response)

    def explain_conflict(self, conflict: ConflictFile) -> str:
        """Get a plain-language explanation of a conflict."""
        prompt = f"""Explain this git merge conflict in plain language for a developer.

## File: {conflict.path.name}

### Our version (current branch):
```
{self._truncate(conflict.ours_content, 2000)}
```

### Their version (incoming changes):
```
{self._truncate(conflict.theirs_content, 2000)}
```

Provide a brief, clear explanation of:
1. What each side changed
2. Why these changes conflict
3. What the developer needs to decide

Keep your explanation concise and actionable."""

        return self._call_api(prompt)

    def _call_api(self, prompt: str) -> str:
        """Make an API call to Claude."""
        try:
            log.debug("Calling Claude model=%s max_tokens=%d", self.model, self.max_tokens)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            if response.content and len(response.content) > 0:
                first_block = response.content[0]
                if hasattr(first_block, "text"):
                    text = getattr(first_block, "text", "")
                    return str(text)
            return ""

        except anthropic.APIError as e:
            log.error("Claude API call failed: %s", redact_secrets(e))
            raise AIError(f"API call failed: {e}") from e

    def _parse_conflict_response(self, file_path: str, response: str) -> ConflictResolution:
        """Parse the AI response for conflict resolution."""
        explanation = self._extract_section(response, "EXPLANATION:")
        resolved = self._extract_code_block(
            self._extract_section(response, "RESOLVED_CONTENT:")
        )
        confidence = self._extract_section(response, "CONFIDENCE:").strip().lower()
        summary = self._extract_section(response, "CHANGES_SUMMARY:")

        return ConflictResolution(
            file_path=file_path,
            resolved_content=resolved,
            explanation=explanation,
            confidence=confidence,  # type: ignore[arg-type]
            changes_summary=summary,
        )

    def _parse_rebase_response(self, response: str) -> RebaseRecommendation:
        """Parse the AI response for rebase recommendation."""
        sp_text = self._extract_section(response, "SHOULD_PROCEED:").strip().lower()
        first_token = sp_text.split(None, 1)[0].strip(".,;:!?") if sp_text else ""
        should_proceed = first_token in ("yes", "true", "proceed", "y")

        risk_level = self._extract_section(response, "RISK_LEVEL:").strip().lower()
        explanation = self._extract_section(response, "EXPLANATION:")
        approach = self._extract_section(response, "SUGGESTED_APPROACH:")

        warnings_text = self._extract_section(response, "WARNINGS:")
        if warnings_text.strip().lower() == "none":
            warnings: list[str] = []
        else:
            warnings = [
                w.strip().lstrip("- ").strip()
                for w in warnings_text.strip().split("\n")
                if w.strip() and w.strip() != "-"
            ]
            warnings = [w for w in warnings if w]

        return RebaseRecommendation(
            should_proceed=should_proceed,
            risk_level=risk_level,  # type: ignore[arg-type]
            explanation=explanation,
            suggested_approach=approach,
            warnings=warnings,
        )

    _ALL_HEADERS = (
        "EXPLANATION:",
        "RESOLVED_CONTENT:",
        "CONFIDENCE:",
        "CHANGES_SUMMARY:",
        "SHOULD_PROCEED:",
        "RISK_LEVEL:",
        "SUGGESTED_APPROACH:",
        "WARNINGS:",
    )

    @staticmethod
    def _find_header(text_lower: str, header_lower: str) -> int:
        """Find a header only at the start of a line (prevents prose-word collisions)."""
        pos = 0
        n = len(text_lower)
        while pos < n:
            idx = text_lower.find(header_lower, pos)
            if idx == -1:
                return -1
            if idx == 0 or text_lower[idx - 1] in ("\n", "\r"):
                return idx
            pos = idx + 1
        return -1

    def _extract_section(self, text: str, header: str) -> str:
        """Extract a section from the response text (case-insensitive, line-anchored)."""
        header_lower = header.lower()
        text_lower = text.lower()

        start = self._find_header(text_lower, header_lower)
        if start == -1:
            return ""

        body_start = start + len(header)

        end = len(text)
        for next_header in self._ALL_HEADERS:
            nh_lower = next_header.lower()
            if nh_lower == header_lower:
                continue
            pos = self._find_header(text_lower[body_start:], nh_lower)
            if pos != -1:
                abs_pos = body_start + pos
                if abs_pos < end:
                    end = abs_pos

        return text[body_start:end].strip()

    @staticmethod
    def _extract_code_block(text: str) -> str:
        """Extract code from a markdown code block."""
        start = text.find("```")
        if start == -1:
            return text.strip()

        nl = text.find("\n", start)
        if nl == -1:
            return text.strip()
        body_start = nl + 1

        end = text.find("```", body_start)
        if end == -1:
            return text[body_start:].strip()

        return text[body_start:end].strip()


class AIError(Exception):
    """AI operation error."""
    pass
