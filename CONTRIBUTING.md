# Contributing to GitNudge

Thank you for your interest in contributing to GitNudge! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and constructive in all interactions. We welcome contributors of all backgrounds and experience levels.

## Getting Started

### Development Setup

1. Fork and clone the repository:
   ```bash
   git clone https://github.com/GitNudge/gitnudge.git
   cd gitnudge
   ```

2. Create a virtual environment:
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   ```

3. Install in development mode with dev dependencies:
   ```bash
   pip install -e ".[dev]"
   ```

4. Set up your Anthropic API key for testing:
   ```bash
   export ANTHROPIC_API_KEY="your-api-key"
   ```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=gitnudge --cov-report=html

# Run specific test file
pytest tests/test_gitnudge.py -v
```

### Code Quality

We use `ruff` for linting and `mypy` for type checking:

```bash
# Linting
ruff check .
ruff check --fix .

# Type checking
mypy src/gitnudge --ignore-missing-imports
```

### Validation

All request/response models and configuration are validated with **pydantic v2**. When adding new config fields or AI output structures, prefer extending the existing `BaseModel` classes (`Config`, `APIConfig`, `BehaviorConfig`, `UIConfig`, `ConflictResolution`, `RebaseRecommendation`) rather than introducing free-form dicts.

## How to Contribute

### Reporting Bugs

1. Check existing issues to avoid duplicates
2. Use the bug report template
3. Include:
   - GitNudge version (`gitnudge --version`)
   - Python version
   - Operating system
   - Steps to reproduce
   - Expected vs actual behavior
   - Relevant logs/output

### Suggesting Features

1. Check existing issues and discussions
2. Use the feature request template
3. Explain the use case and benefit
4. Consider implementation complexity

### Pull Requests

1. Create a branch from `main`:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes following our code style

3. Add tests for new functionality

4. Ensure all tests pass:
   ```bash
   pytest
   ruff check .
   mypy src/gitnudge
   ```

5. Update documentation if needed

6. Commit with clear messages:
   ```bash
   git commit -m "feat: add support for interactive conflict resolution"
   ```

7. Push and create a pull request

### Commit Message Format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` New features
- `fix:` Bug fixes
- `docs:` Documentation changes
- `test:` Test additions/changes
- `refactor:` Code refactoring
- `chore:` Maintenance tasks

## Code Style

### Python

- Follow PEP 8
- Use type hints for all functions
- Maximum line length: 100 characters
- Use descriptive variable names
- Add docstrings to all public functions/classes

### Example

```python
def analyze_conflict(
    self,
    conflict: ConflictFile,
    context: str = "",
) -> ConflictResolution:
    """Analyze a conflict and suggest a resolution.

    Args:
        conflict: The conflict file to analyze.
        context: Additional context (commit messages, etc.).

    Returns:
        ConflictResolution with suggested fix.

    Raises:
        AIError: If the API call fails.
    """
```

## Project Structure

```
gitnudge/
├── src/gitnudge/
│   ├── __init__.py         # Package init; __version__ sourced from package metadata
│   ├── __main__.py         # Enables `python -m gitnudge`
│   ├── cli.py              # Command-line interface (click) + global --verbose/--quiet
│   ├── config.py           # Pydantic configuration models + atomic load/save
│   ├── core.py             # Main GitNudge class (rebase orchestration, snapshot, recovery)
│   ├── git.py              # Git operations wrapper (ref validation, progress, skip, etc.)
│   ├── ai.py               # Claude integration + pydantic AI response models
│   └── logging_utils.py    # Structured logging with API-key redaction
├── tests/
│   └── test_gitnudge.py    # 134 unit tests
├── .github/workflows/
│   ├── lint.yml            # ruff + mypy on push & PR
│   ├── test.yml            # pytest on Python 3.9–3.12, ubuntu + macos
│   └── publish.yml         # Auto-tag on pyproject.toml version bump
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE
└── CONTRIBUTING.md
```

## Bump and release

1. Update `version` in `pyproject.toml` (`__version__` is read from package metadata, no other file to edit).
2. Add a new section at the top of `CHANGELOG.md` (Added / Changed / Fixed / Security).
3. Open a PR. Once merged to `main`, the `publish.yml` workflow tags the release automatically.

## Areas for Contribution

### Good First Issues

Look for issues labeled `good first issue`:
- Documentation improvements
- Adding more tests
- Small bug fixes

### Larger Projects

- Support for more git operations (cherry-pick, merge)
- Integration with VS Code extension
- Web UI for conflict resolution
- Support for other AI providers

## Questions?

- Open a GitHub Discussion for questions
- Email maintainers for sensitive issues

Thank you for contributing to GitNudge! 🚀
