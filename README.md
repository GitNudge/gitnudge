# 🚀 GitNudge

**AI-Powered Git Rebase Assistant**

[![Lint](https://github.com/GitNudge/gitnudge/actions/workflows/ruff.yml/badge.svg)](https://github.com/GitNudge/gitnudge/actions/workflows/ruff.yml)
[![Test](https://github.com/GitNudge/gitnudge/actions/workflows/test.yml/badge.svg)](https://github.com/GitNudge/gitnudge/actions/workflows/test.yml)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/GitNudge/gitnudge/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

GitNudge is an open-source CLI tool that helps you perform git rebases with the assistance of Claude AI. It analyzes conflicts, suggests resolutions, and guides you through complex rebase operations.

## Features

- 🤖 **AI-Assisted Conflict Resolution** - Claude analyzes merge conflicts and suggests intelligent resolutions
- 📊 **Rebase Planning** - Get AI recommendations on the best rebase strategy
- 🔍 **Conflict Explanation** - Understand why conflicts occurred and how to resolve them
- 🛡️ **Safe Operations** - Preview changes before applying, with easy abort options
- 💻 **Cross-Platform** - Works on macOS and Linux
- 🔧 **Configurable** - Customize behavior via config file or environment variables

## Installation

### From GitHub (latest development version)

```bash
# Install directly from GitHub
pip install git+https://github.com/GitNudge/gitnudge.git

# Install a specific tag/release
pip install git+https://github.com/GitNudge/gitnudge.git@v0.1.0
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

Start an AI-assisted rebase onto the target branch.

```bash
gitnudge rebase main              # Rebase onto main
gitnudge rebase -i HEAD~3         # Interactive rebase last 3 commits
gitnudge rebase --dry-run main    # Preview what would happen
```

### `gitnudge analyze <target>`

Analyze potential conflicts before rebasing.

```bash
gitnudge analyze main             # Analyze conflicts with main
gitnudge analyze --detailed main  # Get detailed conflict breakdown
```

### `gitnudge resolve`

Get AI help resolving current conflicts during a rebase.

```bash
gitnudge resolve                  # Analyze all conflicts
gitnudge resolve path/to/file.py  # Analyze specific file
gitnudge resolve --auto           # Auto-resolve with AI suggestions
```

### `gitnudge continue`

Continue the rebase after resolving conflicts.

```bash
gitnudge continue                 # Continue rebase
gitnudge continue --ai-verify     # Verify resolution with AI first
```

### `gitnudge abort`

Abort the current rebase operation.

```bash
gitnudge abort                    # Abort and return to original state
```

### `gitnudge config`

Manage GitNudge configuration.

```bash
gitnudge config --show            # Show current config
gitnudge config --set-key         # Set API key interactively
gitnudge config --model claude-sonnet-4-20250514  # Set model
```

## Configuration

GitNudge can be configured via:

1. **Environment variables**
2. **Config file** (`~/.config/gitnudge/config.toml`)
3. **Command line arguments**

### Config File Example

```toml
# ~/.config/gitnudge/config.toml

[api]
# Your Anthropic API key (or use ANTHROPIC_API_KEY env var)
api_key = "sk-ant-..."

# Model to use (default: claude-sonnet-4-20250514)
model = "claude-sonnet-4-20250514"

[behavior]
# Automatically stage resolved files
auto_stage = true

# Show diff previews before applying
show_previews = true

# Maximum context lines to send to AI
max_context_lines = 500

[ui]
# Enable colored output
color = true

# Verbosity level: quiet, normal, verbose
verbosity = "normal"
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GITNUDGE_MODEL` | Claude model to use |
| `GITNUDGE_CONFIG` | Path to config file |
| `GITNUDGE_NO_COLOR` | Disable colored output |

## Usage Examples

### Example 1: Simple Rebase with Conflict Resolution

```bash
$ gitnudge rebase main

🔍 Analyzing rebase from feature-branch onto main...
📊 Found 3 commits to rebase
⚠️  Potential conflicts detected in 2 files

Starting rebase...

❌ Conflict in src/utils.py

🤖 AI Analysis:
   The conflict is in the `parse_config` function. Your branch added
   input validation, while main refactored the return type.

   Suggested resolution: Keep both changes by adding validation
   to the new return structure.

Would you like me to apply the suggested resolution? [y/n/show diff]: y

✅ Resolved src/utils.py
✅ Rebase complete! 3 commits applied.
```

### Example 2: Pre-Rebase Analysis

```bash
$ gitnudge analyze main --detailed

📊 Rebase Analysis: feature-branch → main

Commits to rebase: 5
Files modified: 12

Potential Conflicts:
┌─────────────────────┬──────────┬─────────────────────────────────┐
│ File                │ Severity │ Reason                          │
├─────────────────────┼──────────┼─────────────────────────────────┤
│ src/api/handler.py  │ High     │ Both branches modified lines    │
│                     │          │ 45-67                           │
│ src/utils.py        │ Medium   │ Function signature changed in   │
│                     │          │ main                            │
│ config/settings.py  │ Low      │ Adjacent line changes           │
└─────────────────────┴──────────┴─────────────────────────────────┘

🤖 AI Recommendation:
   Consider rebasing in smaller chunks. Start with commits 1-2,
   resolve conflicts, then continue with remaining commits.

   Run: gitnudge rebase main --commits 2
```

## How It Works

1. **Analysis Phase**: GitNudge examines your branch and target, identifying potential conflicts using git's merge-base and diff tools.

2. **AI Context Building**: Relevant code context, commit messages, and file history are sent to Claude for analysis.

3. **Conflict Resolution**: When conflicts occur, Claude analyzes both versions and suggests intelligent merges based on:
   - Code semantics and intent
   - Commit message context
   - Project patterns and conventions

4. **Safe Application**: All AI suggestions are previewed before application, giving you full control.

## Security

- API keys are stored securely in your config file with restricted permissions
- Code is sent to Anthropic's API only during active operations
- No data is stored or logged beyond your local machine
- You can use `--dry-run` to preview without sending code

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
# Setup development environment
git clone https://github.com/GitNudge/gitnudge.git
cd gitnudge
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Run linting
ruff check .
```

## License

MIT License - see [LICENSE](LICENSE) for details.
