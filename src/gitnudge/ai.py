"""AI integration module using Claude API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import anthropic

if TYPE_CHECKING:
    from gitnudge.config import Config
    from gitnudge.git import ConflictFile, RebaseAnalysis


@dataclass
class ConflictResolution:
    """Suggested resolution for a conflict."""

    file_path: str
    resolved_content: str
    explanation: str
    confidence: str
    changes_summary: str


@dataclass
class RebaseRecommendation:
    """AI recommendation for a rebase operation."""

    should_proceed: bool
    risk_level: str
    explanation: str
    suggested_approach: str
    warnings: list[str]


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
        """Initialize the AI assistant.

        Args:
            config: GitNudge configuration.
        """
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.api.api_key)
        self.model = config.api.model
        self.max_tokens = config.api.max_tokens

    def analyze_conflict(self, conflict: ConflictFile, context: str = "") -> ConflictResolution:
        """Analyze a conflict and suggest a resolution.

        Args:
            conflict: The conflict file to analyze.
            context: Additional context (commit messages, etc.).

        Returns:
            ConflictResolution with suggested fix.
        """
        prompt = f"""Analyze this git merge conflict and suggest a resolution.

## File: {conflict.path.name}

### Base version (common ancestor):
```
{conflict.base_content[:self.config.behavior.max_context_lines * 80]}
```

### Our version (current branch):
```
{conflict.ours_content[:self.config.behavior.max_context_lines * 80]}
```

### Their version (incoming changes):
```
{conflict.theirs_content[:self.config.behavior.max_context_lines * 80]}
```

### Current file with conflict markers:
```
{conflict.full_content[:self.config.behavior.max_context_lines * 80]}
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
        """Analyze a potential rebase and provide recommendations.

        Args:
            analysis: The rebase analysis from git.

        Returns:
            RebaseRecommendation with advice.
        """
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
        """Get a plain-language explanation of a conflict.

        Args:
            conflict: The conflict to explain.

        Returns:
            Human-readable explanation.
        """
        prompt = f"""Explain this git merge conflict in plain language for a developer.

## File: {conflict.path.name}

### Our version (current branch):
```
{conflict.ours_content[:2000]}
```

### Their version (incoming changes):
```
{conflict.theirs_content[:2000]}
```

Provide a brief, clear explanation of:
1. What each side changed
2. Why these changes conflict
3. What the developer needs to decide

Keep your explanation concise and actionable."""

        response = self._call_api(prompt)
        return response

    def _call_api(self, prompt: str) -> str:
        """Make an API call to Claude.

        Args:
            prompt: The prompt to send.

        Returns:
            Response text.
        """
        try:
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
            raise AIError(f"API call failed: {e}") from e

    def _parse_conflict_response(self, file_path: str, response: str) -> ConflictResolution:
        """Parse the AI response for conflict resolution."""
        explanation = self._extract_section(response, "EXPLANATION:")
        resolved = self._extract_code_block(
            self._extract_section(response, "RESOLVED_CONTENT:")
        )
        confidence = self._extract_section(response, "CONFIDENCE:").strip().lower()
        summary = self._extract_section(response, "CHANGES_SUMMARY:")

        if confidence not in ("high", "medium", "low"):
            confidence = "medium"

        return ConflictResolution(
            file_path=file_path,
            resolved_content=resolved,
            explanation=explanation,
            confidence=confidence,
            changes_summary=summary,
        )

    def _parse_rebase_response(self, response: str) -> RebaseRecommendation:
        """Parse the AI response for rebase recommendation."""
        should_proceed_text = self._extract_section(response, "SHOULD_PROCEED:").strip().lower()
        should_proceed = should_proceed_text in ("yes", "true", "proceed")

        risk_level = self._extract_section(response, "RISK_LEVEL:").strip().lower()
        if risk_level not in ("low", "medium", "high"):
            risk_level = "medium"

        explanation = self._extract_section(response, "EXPLANATION:")
        approach = self._extract_section(response, "SUGGESTED_APPROACH:")

        warnings_text = self._extract_section(response, "WARNINGS:")
        if warnings_text.strip().lower() == "none":
            warnings = []
        else:
            warnings = [
                w.strip().lstrip("- ")
                for w in warnings_text.strip().split("\n")
                if w.strip() and w.strip() != "-"
            ]

        return RebaseRecommendation(
            should_proceed=should_proceed,
            risk_level=risk_level,
            explanation=explanation,
            suggested_approach=approach,
            warnings=warnings,
        )

    def _extract_section(self, text: str, header: str) -> str:
        """Extract a section from the response text."""
        header_lower = header.lower()
        text_lower = text.lower()

        start = text_lower.find(header_lower)
        if start == -1:
            return ""

        start += len(header)

        next_headers = ["EXPLANATION:", "RESOLVED_CONTENT:", "CONFIDENCE:",
                       "CHANGES_SUMMARY:", "SHOULD_PROCEED:", "RISK_LEVEL:",
                       "SUGGESTED_APPROACH:", "WARNINGS:"]

        end = len(text)
        for next_header in next_headers:
            if next_header.lower() == header_lower:
                continue
            pos = text_lower.find(next_header.lower(), start)
            if pos != -1 and pos < end:
                end = pos

        return text[start:end].strip()

    def _extract_code_block(self, text: str) -> str:
        """Extract code from a markdown code block."""
        start = text.find("```")
        if start == -1:
            return text.strip()

        start = text.find("\n", start)
        if start == -1:
            return text.strip()
        start += 1

        end = text.find("```", start)
        if end == -1:
            return text[start:].strip()

        return text[start:end].strip()


class AIError(Exception):
    """AI operation error."""
    pass
