# 🚀 GitNudge

**AI-Powered Git Rebase Assistant**

[![Lint](https://github.com/GitNudge/gitnudge/actions/workflows/lint.yml/badge.svg)](https://github.com/GitNudge/gitnudge/actions/workflows/lint.yml)
[![Test](https://github.com/GitNudge/gitnudge/actions/workflows/test.yml/badge.svg)](https://github.com/GitNudge/gitnudge/actions/workflows/test.yml)
[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](https://github.com/GitNudge/gitnudge/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

GitNudge is an open-source CLI tool that helps you perform git rebases with the assistance of Claude AI. It runs pre-flight safety checks, snapshots your pre-rebase HEAD for easy recovery, analyzes conflicts, suggests resolutions, and guides you through complex rebase operations.

## Features

- 🛡️ **Pre-flight Safety Checks** — Refuses to start when the working tree is dirty, HEAD is detached, or the target ref is missing
- 🛟 **Recovery Snapshot** — Pre-rebase HEAD is saved to `.git/gitnudge-snapshot.json`; `gitnudge recover` shows the exact undo command
- 🤖 **AI-Assisted Conflict Resolution** — Claude analyzes merge conflicts and suggests intelligent resolutions
- 🚫 **Conflict-Marker Guard** — Refuses to apply AI output that still contains `<<<<<<<` / `=======` / `>>>>>>>` markers
- 📊 **Rebase Planning** — Up-to-date / fast-forward / unrelated-history detection, binary-file filtering, AI risk recommendations
- 📈 **Live Progress** — `gitnudge status` shows `commit X/Y` and the subject of the commit currently being applied
- ⏭️ **Full Rebase Verbs** — `continue`, `skip`, and `abort`, just like raw git
- 🔒 **Secure** — Pydantic-validated config, atomic `0o600` config saves, API-key redaction in logs, ref-injection protection
- 💻 **Cross-Platform** — Works on macOS and Linux
- 🔧 **Configurable** — Customize behavior via config file or environment variables

## Installation

### From GitHub (latest development version)

```bash
# Install directly from GitHub
pip install git+https://github.com/GitNudge/gitnudge.git

# Install a specific tag/release
pip install git+https://github.com/GitNudge/gitnudge.git@v0.2.0
```

### From source

```bash
git clone https://github.com/GitNudge/gitnudge.git
cd gitnudge
pip install -e .
```

## Quick Start

### 1. Configure your Anthropic API key

```bash
# Option A: Set environment variable
export ANTHROPIC_API_KEY="your-api-key"

# Option B: Use the config command
gitnudge config --set-key
```

### 2. Start an interactive rebase with AI assistance

```bash
# Rebase current branch onto main with AI help
gitnudge rebase main

# Rebase last 5 commits interactively
gitnudge rebase -i HEAD~5

# Get AI analysis before rebasing
gitnudge analyze main
```

## Commands

### `gitnudge rebase <target>`

Start an AI-assisted rebase onto the target branch. Runs pre-flight safety checks and writes a recovery snapshot.

```bash
gitnudge rebase main              # Rebase onto main
gitnudge rebase -i HEAD~3         # Interactive rebase last 3 commits
gitnudge rebase --dry-run main    # Preview what would happen, no changes
gitnudge rebase --auto main       # Auto-apply high/medium-confidence AI resolutions
gitnudge rebase --force main      # Skip pre-flight checks (NOT recommended)
```

### `gitnudge analyze <target>`

Analyze potential conflicts before rebasing.

```bash
gitnudge analyze main             # Analyze conflicts with main
gitnudge analyze --detailed main  # Get detailed AI risk recommendation
```

### `gitnudge resolve [file]`

Get AI help resolving current conflicts during a rebase.

```bash
gitnudge resolve                  # Resolve the first conflict
gitnudge resolve src/utils.py     # Resolve a specific file
gitnudge resolve --all            # Walk through all conflicts
gitnudge resolve --auto           # Auto-apply suggestions without confirmation
```

### `gitnudge continue`

Continue the rebase after resolving conflicts. Reports applied/remaining commit counts.

```bash
gitnudge continue                 # Continue rebase
gitnudge continue --ai-verify     # Refuse to continue if any staged file still has conflict markers
```

### `gitnudge skip`

Skip the current commit during a rebase (equivalent to `git rebase --skip`).

```bash
gitnudge skip
```

### `gitnudge abort`

Abort the current rebase operation and clear the recovery snapshot.

```bash
gitnudge abort
```

### `gitnudge recover`

Show the saved pre-rebase HEAD and the exact `git reset --hard <sha>` command to undo. Also prints the recent reflog.

```bash
gitnudge recover
```

### `gitnudge status`

Show the current branch, rebase state, conflicted files, live progress (`commit X/Y`), and the safety snapshot SHA.

```bash
gitnudge status
```

### `gitnudge config`

Manage GitNudge configuration.

```bash
gitnudge config --show            # Show current config
gitnudge config --set-key         # Set API key interactively
gitnudge config --model claude-sonnet-4-20250514  # Set model
gitnudge config --reset           # Reset to defaults
```

## Configuration

GitNudge can be configured via:

1. **Environment variables**
2. **Config file** (`~/.config/gitnudge/config.toml`, saved with `0o600` permissions)
3. **Command line arguments**

### Config File Example

```toml
# ~/.config/gitnudge/config.toml

[api]
# Your Anthropic API key (or use ANTHROPIC_API_KEY env var)
api_key = "sk-ant-..."

# Model to use (default: claude-sonnet-4-20250514)
model = "claude-sonnet-4-20250514"

# Max tokens per Claude response (1 - 200000)
max_tokens = 4096

[behavior]
# Automatically stage resolved files
auto_stage = true

# Show diff previews before applying
show_previews = true

# Maximum context lines sent to AI (10 - 10000)
max_context_lines = 500

# Auto-apply high/medium-confidence resolutions during rebase
auto_resolve = false

[ui]
# Enable colored output
color = true

# Verbosity level: quiet, normal, verbose
verbosity = "normal"
```

All values are validated by pydantic; invalid values are rejected at load and assignment time.

### Environment Variables

| Variable             | Description                                                  |
|----------------------|--------------------------------------------------------------|
| `ANTHROPIC_API_KEY`  | Your Anthropic API key (overrides config file)               |
| `GITNUDGE_MODEL`     | Claude model to use (overrides config file)                  |
| `GITNUDGE_CONFIG`    | Path to config file (default: `~/.config/gitnudge/config.toml`) |
| `GITNUDGE_NO_COLOR`  | Disable colored output                                       |
| `NO_COLOR`           | Standard no-color flag (also disables colored output)        |
| `GITNUDGE_LOG_LEVEL` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `WARNING`) |

## Usage Examples

### Example 1: Safe rebase with auto-resolve

```bash
$ gitnudge rebase main --auto

Analyzing rebase onto main...

📊 Rebase Analysis
Branch: feature-branch → main
Commits to rebase: 3
Potential conflicts: 2

Safety: pre-rebase HEAD = 7fb48462ab12
Recover with: git reset --hard 7fb48462ab12

✅ Rebased 3 commits with 2 AI-resolved conflicts
```

### Example 2: Recovering from a bad rebase

```bash
$ gitnudge recover

🛟  Recovery Snapshot
Pre-rebase HEAD: 7fb48462ab12cdef...
Branch: feature-branch
Target: main

Recover with:
  git reset --hard 7fb48462ab12

Recent reflog (last 20):
abc1234 HEAD@{0} commit: WIP
7fb4846 HEAD@{1} rebase (start)
...
```

### Example 3: Live status during a rebase

```bash
$ gitnudge status

📋 GitNudge Status
Branch: feature-branch
Rebase state: conflict
Config valid: ✅
Progress: commit 2/5
Applying: refactor: extract config loader
Safety SHA: 7fb48462ab12 (run 'gitnudge recover')

Conflicted files:
  • src/utils.py
```

## How It Works

1. **Pre-flight**: GitNudge checks the target ref exists, HEAD is on a branch, the working tree is clean, and no rebase is already in progress.
2. **Snapshot**: The current HEAD is saved to `.git/gitnudge-snapshot.json` so you can always undo with `gitnudge recover`.
3. **Analysis**: It examines your branch and target using git's merge-base and diff tools, filtering binaries and detecting fast-forward / up-to-date / unrelated-history cases.
4. **AI Context Building**: Relevant code context, commit messages, and file history are sent to Claude.
5. **Conflict Resolution**: Claude analyzes both versions and suggests intelligent merges. AI output is rejected if it still contains conflict markers.
6. **Safe Application**: With `--auto`, only high/medium-confidence resolutions are applied; otherwise you preview and confirm.

## Security

- Config file is saved atomically with `0o600` permissions (parent dir `0o700`).
- API keys are redacted from log output (any `sk-...` pattern).
- All git ref arguments are validated against an allow-list regex; refs starting with `-` are rejected to prevent argv-flag injection.
- `apply_resolution` validates the target path is inside the repository (no `../` traversal).
- AI output containing conflict markers is refused before write.
- Code is sent to Anthropic's API only during active operations.
- You can use `--dry-run` to preview without sending code.

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
# Setup development environment
git clone https://github.com/GitNudge/gitnudge.git
cd gitnudge
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run tests + lint + type-check
pytest
ruff check .
mypy src/gitnudge --ignore-missing-imports
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full history.

## License

MIT License - see [LICENSE](LICENSE) for details.
