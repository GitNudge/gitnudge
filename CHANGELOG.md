# Changelog

All notable changes to GitNudge are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-04-18

### Added
- **Pre-flight safety checks** for `gitnudge rebase`: refuses to start when target ref does not exist, HEAD is detached, working tree is dirty, or a rebase is already in progress. New `--force` flag to bypass.
- **Recovery snapshot**: pre-rebase HEAD is saved to `.git/gitnudge-snapshot.json` before every rebase, and surfaced in `gitnudge rebase` and `gitnudge status` output.
- **`gitnudge recover`** command — prints the saved pre-rebase SHA, recent reflog, and the exact `git reset --hard <sha>` command to undo a rebase.
- **`gitnudge skip`** command and `Git.skip_rebase()` wrapping `git rebase --skip`.
- **Live rebase progress** in `gitnudge status`: shows `commit X/Y` and `Applying: <subject>` parsed from `.git/rebase-merge` / `.git/rebase-apply`.
- **`--ai-verify`** on `gitnudge continue` is now functional: rejects continue if any staged file still contains conflict markers.
- **Conflict-marker guard** in `apply_resolution` and the auto-resolve loop: refuses any AI output containing `<<<<<<<`, `=======`, `>>>>>>>`, or `|||||||`.
- **Smarter `analyze`**: new fields `is_up_to_date`, `is_fast_forward`, `has_merge_base`. Refuses unrelated histories. Reports "Already up to date" instead of "Rebased 0 commits".
- **Binary-file filtering** in conflict analysis (via `git diff --numstat` and `git check-attr binary`).
- **Pydantic models** for `Config`, `APIConfig`, `BehaviorConfig`, `UIConfig`, `ConflictResolution`, `RebaseRecommendation` with strict bounds (`max_tokens` 1–200_000, `max_context_lines` 10–10_000), enum verbosity, and assignment-time validation.
- **Structured logging** module (`gitnudge.logging_utils`) with API-key redaction filter; controlled by `GITNUDGE_LOG_LEVEL` env var.
- **Ref/argument validation** (`_is_safe_ref`) on every git ref the CLI passes, blocking refs starting with `-` or containing whitespace/odd characters.
- **Path-traversal protection** on `apply_resolution`: refuses to write outside the repository.
- **Atomic, permission-restricted config save** (`tempfile + os.replace`, `0o600` on file, `0o700` on parent).
- New `Git` helpers: `is_detached_head`, `get_head_sha`, `ref_exists`, `has_uncommitted_changes`, `get_untracked_files`, `is_binary_path`, `get_rebase_progress`, `skip_rebase`.
- New tests: 26 added (108 total) covering pre-flight, snapshot/recovery, marker rejection, skip, pydantic validation, security fixes, and CLI smoke.

### Changed
- `gitnudge rebase` now records a safety SHA and prints the recovery command on completion.
- `gitnudge continue` now reports applied/remaining commit counts based on the rebase state files.
- `gitnudge status` panel includes progress and safety-SHA lines when a rebase is in progress.
- `Git._git_dir()` resolves the actual git directory via `git rev-parse --git-dir` (worktree- and `.git`-file-aware).
- `Git.get_conflict_details()` uses the **full repo-relative path** for `git show :N:path` (was using basename — broke on subdirectories).
- `git rebase` invocations now include the `--` separator before the target ref.
- `git rebase --continue` runs with `GIT_EDITOR=true` to prevent the commit-message editor from blocking.
- CI workflows (`lint.yml`, `test.yml`) restructured: trigger directly on `push`/`pull_request` (replaced the broken `workflow_run` chain), added Python 3.9–3.12 matrix on Ubuntu + macOS, added pip caching, scoped `permissions: read`, added concurrency cancellation.
- `publish.yml` rebuilt around a `pyproject.toml`-path-triggered tag job with `github-actions[bot]` author.

### Fixed
- **Critical**: `Git.get_conflict_details` used the file basename for `git show`, which silently returned empty content for any file inside a subdirectory. Now uses the repo-relative path.
- **Critical**: `core.GitNudge.rebase` auto-resolve loop had broken accounting (`commits_to_apply - len(analysis.commits_to_rebase)` always evaluated to 0) and inverted continue logic. Rewritten with iteration cap.
- `Git._git_dir` was hard-coded to `repo/.git` and broke for git worktrees and submodules.
- `ai._extract_section` performed a case-insensitive header search but used the original-case header for the next-section delimiter scan, occasionally pulling in trailing sections.
- `cli.resolve` passed bare `Path(file)` ignoring repo root; now resolved against `nudge.git.repo_path`.
- API-key masking in `cli.config --show` was unsafe for short keys.

### Security
- API keys are scrubbed from log output (`sk-...` pattern) via `_RedactingFilter`.
- All ref-taking git commands validate input against an allow-list regex; refs starting with `-` are rejected to prevent argv-flag injection.
- `apply_resolution` validates the resolved path is inside the repository before writing.
- Config file is now saved atomically with `0o600` permissions, parent dir `0o700`.

## [0.1.0] - 2024-12-30

### Added
- Initial public release.
- CLI commands: `rebase`, `analyze`, `resolve`, `continue`, `abort`, `status`, `config`.
- Claude AI integration via the `anthropic` SDK for conflict analysis, conflict resolution, and rebase recommendations.
- Configuration via TOML file (`~/.config/gitnudge/config.toml`) and environment variables (`ANTHROPIC_API_KEY`, `GITNUDGE_MODEL`, `GITNUDGE_CONFIG`, `GITNUDGE_NO_COLOR`, `NO_COLOR`).
- Rich-based terminal UI with panels, tables, syntax highlighting, and progress spinners.
- `--dry-run` flag for previewing rebases without changing state.
- `--auto` flag for automatic AI conflict resolution during rebase.
- Lazy-loaded `AIAssistant` so commands not requiring the API never instantiate the client.
- Test suite (82 tests) and CI on GitHub Actions (lint + test).

[0.2.0]: https://github.com/GitNudge/gitnudge/releases/tag/v0.2.0
[0.1.0]: https://github.com/GitNudge/gitnudge/releases/tag/v0.1.0
