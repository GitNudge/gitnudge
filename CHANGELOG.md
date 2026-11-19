# Changelog

All notable changes to GitNudge are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-11-19

CI-only release. No code, API, or config changes.

### Fixed
- **Test pipeline failed on Python 3.9.** GitHub's `ubuntu-latest` runner moved
  to Ubuntu 26.04, which has no Python 3.9 build, so the `ubuntu-latest / 3.9`
  job failed at `setup-python` before any test ran. The 3.9 job now runs on
  `ubuntu-24.04`; all other jobs stay on `ubuntu-latest` / `macos-latest`
  (same 8-job matrix).

### Changed
- The version test now checks that `pyproject.toml`, the top CHANGELOG entry,
  and the README version badge / install tag agree, instead of a hardcoded
  version number.

## [0.4.0] - 2026-11-19

Safety and correctness release from a full code review. Fixes are covered by
regression tests (most run against real git repositories).

### Changed
- **Default model is now `claude-sonnet-5-5`** (was `claude-sonnet-4-20250514`,
  retired on 2026-06-15, which made every AI command fail out of the box).
- **Default `api.max_tokens` raised from 4096 to 16000.** Existing config
  files keep their saved value.
- **Retired model IDs are replaced automatically.** `config.save()` always
  wrote the model, so most existing config files pin
  `claude-sonnet-4-20250514`; known-retired IDs (from the file or
  `GITNUDGE_MODEL`) now fall back to the default with a warning. Run
  `gitnudge config --model claude-sonnet-5-5` to update the file.
- **Claude API calls now stream** (`messages.stream` + `get_final_message`).
  Large `max_tokens` values no longer fail with the SDK's "streaming is
  required" `ValueError`.
- **Recovery snapshot lifetime is consistent:** it is kept after a rebase
  completes (direct, `continue`, or `skip`) so `gitnudge recover` can undo it,
  is cleared by `abort`, and is replaced by the next rebase. `gitnudge status`
  shows the safety SHA only while a rebase is in progress.
- **`--verbose` / `--quiet` and `ui.verbosity` now take effect:** verbose sets
  gitnudge logs to INFO (DEBUG if `GITNUDGE_LOG_LEVEL=DEBUG`); quiet hides
  spinners and shows errors only.
- **`behavior.auto_resolve = true` now enables `rebase --auto`** (the setting
  was previously ignored). `gitnudge config` shows it.
- **`resolve --auto` skips low-confidence resolutions** instead of applying them.
- **`resolve --all` keeps going when one file fails** (API error, binary file,
  …), reports the error, and exits with status 1 at the end.
- **`rebase --force` refuses to run while a rebase is already in progress**, so
  it can no longer overwrite the recovery snapshot.
- **Commit counts exclude merge commits**, matching what `git rebase` replays.
- **"Up to date" now means the target is already in HEAD's history.** A branch
  that is behind its target is fast-forwarded instead of being reported as up
  to date. Interactive rebases are never short-circuited (`rebase -i HEAD~5`).

### Fixed
- **AI output could overwrite files with truncated or wrong content:**
  - responses cut off at `max_tokens` (or refused) now raise an error and
    nothing is written;
  - a missing `CONFIDENCE` or unclosed code fence is treated as `low`
    (never auto-applied);
  - files larger than the context limit are refused instead of being silently
    truncated before being sent to Claude;
  - a code fence inside the resolved file no longer ends the block early;
  - header-like lines inside the file (`warnings:`, `confidence:` …) no longer
    cut the resolved content;
  - the file's trailing newline is preserved.
- **API errors crashed with a traceback;** `AIError` is now handled by every
  command.
- **Running from a subdirectory broke paths** (`sub/sub/f.txt`); GitNudge now
  anchors to the repository root and resolves user-supplied paths from the
  current directory.
- **Binary or non-UTF-8 conflicts crashed** with `UnicodeDecodeError`; git
  output is decoded with replacement, and binary conflicts are refused for AI
  resolve/explain with a manual-resolution hint. Non-UTF-8 reflog entries no
  longer crash `recover`.
- **False success reports:** a rebase git refused to start (e.g. `--force` on
  a dirty tree) or an `--auto` rebase whose `continue` failed is now reported
  as failed, with git's error message.
- **`git rebase` / `continue` / `skip` errors were swallowed;** their stderr is
  now shown in the result message.
- **`config --model` / `--set-key` wrote environment values to disk**
  (including `ANTHROPIC_API_KEY`); edits now load the config file only.
- **`Config.save()` ignored `GITNUDGE_CONFIG`** while `load()` honoured it.
- **Invalid values (`GITNUDGE_MODEL="  "`, `config --model "  "`) crashed with
  a pydantic traceback;** they now produce a clean error.
- **Rich markup in commit messages, file names, git errors or AI output**
  (e.g. `fix [/] parser`) crashed or hid text; all dynamic text is escaped.
- **`rebase -i` hid the editor** behind captured output and a spinner; the
  editor now gets the terminal.
- **Non-ASCII file names** were returned quoted (`"\303\251.txt"`); paths are
  read with `-z` and `core.quotePath=false`.
- **A `|` in a commit subject** broke commit parsing; fields are now split on
  an unprintable separator.
- **The snapshot file was not validated;** it is now a pydantic `Snapshot`
  model (hex `head`), and invalid files are ignored with a warning.
- **Binary-file filtering in `analyze` never worked** (it compared the working
  tree to HEAD); it now checks the merge-base..target range.
- **Symlink conflicts were resolved through the link**, overwriting and staging
  the link's target file; symlink conflicts now require manual resolution and
  `apply_resolution` refuses to write through a symlink.
- **Annotated tags were mis-detected** (tag object SHA compared to commit SHA),
  so `rebase <tag>` could report "Fast-forwarded" when nothing changed.
- **`continue` / `skip` commit counts were off by one:** the commit that was
  stopped on is now counted as applied/remaining (and `edit` stops, where it is
  already applied, are handled).
- **`--auto` stopped with an exception on AI errors** (too large, API failure,
  truncated reply); it now stops cleanly with the conflicts, safety SHA and the
  reason in the warnings.
- **Oversized "ours"/"theirs" versions were silently truncated** before being
  sent to Claude; they are now refused like an oversized working file.
- **Four-backtick code fences** (used when the file itself contains ```) were
  not recognised as the closing fence.
- **Resolved files were written in the locale encoding;** they are now written
  as UTF-8.
- **`--no-color` did not apply to error output.**
- **The resolution preview silently showed only the first 2000 characters;** it
  now says when the preview is shortened.

## [0.3.1] - 2026-06-06

Bug-fix release. No API or config changes.

### Fixed
- **`AIAssistant._call_api` now reads all text blocks** instead of only
  `response.content[0]`. Responses whose first block is non-text (e.g. a
  thinking block) no longer come back empty.
- **`--auto` rebase loop now checks `git rebase --continue`'s result.** If a
  continue fails without producing new conflicts, it records a warning and
  stops instead of looping until the iteration cap and reporting false success.
- **`Git.get_rebase_progress`** reads the rebase `message` file once instead of
  three times.
- **Landing-page worker** now returns a real `404` for unknown paths instead of
  serving the homepage with `200`; the homepage is served only for `/`.

## [0.3.0] - 2026-04-26

Hardening release. Still Beta — CLI surface and config schema may change
before 1.0.0. See the v1.0 tracking issue for remaining blockers.

### Added
- **`gitnudge explain [file]`** command — asks Claude for a plain-language
  explanation of a conflict without proposing a resolution.
- **Global `--verbose` / `-v` and `--quiet` / `-q` flags** on the root CLI,
  wired into `config.ui.verbosity`. `--verbose` and `--quiet` are mutually
  exclusive and exit with code 2.
- **`python -m gitnudge`** entry point (`gitnudge/__main__.py`) mirroring the
  `gitnudge` console script.
- **`RebaseResult.applied_resolutions`** — during `--auto` rebases, each AI
  auto-applied resolution is recorded with its file, confidence, and change
  summary. `gitnudge rebase --auto` now prints this list so the user can see
  what Claude actually changed.

### Changed
- **Single-sourced version**: `gitnudge.__version__` is now derived from
  installed package metadata via `importlib.metadata`, eliminating drift
  between `pyproject.toml` and `__init__.py`.
- **`continue_rebase` applied-commit count is now accurate when the rebase
  finishes in the same call**. Previously the count collapsed to `1` because
  the post-continue progress file had been removed. It now uses the pre-call
  `total - done` when completion is detected.
- **Stricter ref validator** (`_is_safe_ref`): now rejects `..`, `//`, `@{`,
  leading `:` or `/`, and `.lock` / trailing-`.` / trailing-`/` suffixes on
  top of the prior flag-injection and whitespace rules. Common refs
  (`HEAD`, `HEAD~5`, `origin/main`, `v0.3.0`, SHAs, etc.) continue to pass.
- **Safety snapshot write is now atomic** (`tempfile` + `os.replace`),
  matching `Config.save`. A crash or OS error mid-write leaves no partial
  `.git/gitnudge-snapshot.json` behind.
- **Log redaction filter** now also scrubs secrets out of `record.args`, not
  just the rendered message, and no longer silently passes through records
  whose args don't match the format string.
- `--ai-verify` help text on `gitnudge continue` corrected to "Refuse to
  continue if any staged file still contains conflict markers" (was the
  misleading "Verify resolution with AI first").
- `GitNudge.analyze` no longer accepts the unused `detailed=` kwarg.
- `AIAssistant.analyze_conflict` now reads `conflict.full_content` once
  instead of re-reading the file via the property.
- Internal: repeated `if ctx.obj.get("no_color")` blocks in each CLI command
  consolidated into a single `_apply_cli_overrides` helper.

### Fixed
- `gitnudge continue` message no longer reports "applied 1 more commits" when
  2+ commits were applied in the final continuation.
- `gitnudge skip` "N remaining" was off-by-one — it did not count the new
  current commit. Now reports the correct count including the commit about
  to be applied.
- **`AIAssistant._extract_section` header match is now line-anchored.**
  Previously a lowercase `"explanation:"` appearing in the model's prose
  could be matched before the real `EXPLANATION:` header, causing the
  wrong text to be parsed into the section body.
- **`SHOULD_PROCEED` parsing** now accepts natural phrasings like
  `"Yes, with caveats"` and `"No."` (was only literal `yes`/`true`/`proceed`).
- **`_is_safe_ref` now rejects trailing `/`** (e.g. `foo/` — git rejects these
  too). Valid refs like `refs/heads/main` still pass.
- **`confidence` and `risk_level` normalizers** strip trailing punctuation
  so `"high."` / `" HIGH!!"` / `"medium,"` all round-trip to the canonical
  value instead of silently defaulting to `medium`.
- **`gitnudge resolve <file>` and `gitnudge explain <file>`** now verify the
  requested file is in the current conflicted set before invoking the AI,
  instead of silently sending an empty index payload to Claude.
- **`ConflictFile.full_content`** now logs a warning when the on-disk file
  cannot be read, instead of silently returning `""`.

### Security
- `gitnudge config --set-key` now prints a visible note that the key is
  stored in plaintext (chmod 0600) and recommends `ANTHROPIC_API_KEY` for
  shared machines.

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

[0.3.1]: https://github.com/GitNudge/gitnudge/releases/tag/v0.3.1
[0.3.0]: https://github.com/GitNudge/gitnudge/releases/tag/v0.3.0
[0.2.0]: https://github.com/GitNudge/gitnudge/releases/tag/v0.2.0
[0.1.0]: https://github.com/GitNudge/gitnudge/releases/tag/v0.1.0
