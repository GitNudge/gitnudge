"""Tests for GitNudge."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gitnudge.ai import ConflictResolution, RebaseRecommendation
from gitnudge.config import APIConfig, BehaviorConfig, Config, ConfigError, UIConfig
from gitnudge.core import GitNudge, GitNudgeError
from gitnudge.git import Commit, ConflictFile, Git, GitError, RebaseAnalysis, RebaseState


class TestConfig:
    """Tests for configuration management."""

    def test_default_config(self):
        """Test default configuration values."""
        config = Config()

        assert config.api.api_key == ""
        assert config.api.model == "claude-sonnet-4-20250514"
        assert config.api.max_tokens == 4096
        assert config.behavior.auto_stage is True
        assert config.behavior.show_previews is True
        assert config.behavior.max_context_lines == 500
        assert config.behavior.auto_resolve is False
        assert config.ui.color is True
        assert config.ui.verbosity == "normal"

    def test_config_validation_missing_key(self):
        """Test validation catches missing API key."""
        config = Config()
        errors = config.validate()

        assert len(errors) > 0
        assert any("API key" in e for e in errors)

    def test_config_validation_valid(self):
        """Test validation passes with valid config."""
        config = Config()
        config.api.api_key = "sk-ant-test123"
        errors = config.validate()

        assert len(errors) == 0

    def test_config_validation_invalid_verbosity(self):
        """Pydantic rejects invalid verbosity at assignment time."""
        from pydantic import ValidationError

        config = Config()
        config.api.api_key = "test-key"
        with pytest.raises(ValidationError):
            config.ui.verbosity = "invalid"

    def test_config_validation_max_context_lines_too_low(self):
        """Pydantic rejects max_context_lines < 10 at assignment time."""
        from pydantic import ValidationError

        config = Config()
        config.api.api_key = "test-key"
        with pytest.raises(ValidationError):
            config.behavior.max_context_lines = 5

    def test_config_to_dict(self):
        """Test config serialization to dict."""
        config = Config()
        config.api.api_key = "test-key"

        data = config.to_dict()

        assert "api" in data
        assert "behavior" in data
        assert "ui" in data
        assert data["api"]["api_key"] == "test-key"
        assert data["api"]["model"] == "claude-sonnet-4-20250514"
        assert data["behavior"]["auto_stage"] is True

    def test_config_to_dict_no_api_key(self):
        """Test config serialization excludes empty API key."""
        config = Config()

        api_dict = config.api.to_dict()

        assert "api_key" not in api_dict or api_dict["api_key"] == ""

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "env-key"})
    def test_env_var_override(self):
        """Test environment variable overrides config."""
        config = Config()
        config = Config._apply_env_vars(config)

        assert config.api.api_key == "env-key"

    @patch.dict("os.environ", {"GITNUDGE_MODEL": "claude-opus-3"})
    def test_env_var_model_override(self):
        """Test GITNUDGE_MODEL environment variable."""
        config = Config()
        config = Config._apply_env_vars(config)

        assert config.api.model == "claude-opus-3"

    @patch.dict("os.environ", {"GITNUDGE_NO_COLOR": "1"})
    def test_env_var_no_color(self):
        """Test GITNUDGE_NO_COLOR environment variable."""
        config = Config()
        config.ui.color = True
        config = Config._apply_env_vars(config)

        assert config.ui.color is False

    @patch.dict("os.environ", {"NO_COLOR": "1"})
    def test_env_var_no_color_standard(self):
        """Test NO_COLOR environment variable."""
        config = Config()
        config.ui.color = True
        config = Config._apply_env_vars(config)

        assert config.ui.color is False

    def test_config_load_from_file(self):
        """Test loading config from TOML file."""
        toml_content = """[api]
api_key = "file-key"
model = "claude-test"
max_tokens = 2048

[behavior]
auto_stage = false
show_previews = false
max_context_lines = 1000

[ui]
color = false
verbosity = "verbose"
"""

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(toml_content)

            config = Config.load(config_path)

            assert config.api.api_key == "file-key"
            assert config.api.model == "claude-test"
            assert config.api.max_tokens == 2048
            assert config.behavior.auto_stage is False
            assert config.behavior.show_previews is False
            assert config.behavior.max_context_lines == 1000
            assert config.ui.color is False
            assert config.ui.verbosity == "verbose"

    def test_config_load_invalid_file(self):
        """Test loading invalid config file raises error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text("invalid toml content {")

            with pytest.raises(ConfigError):
                Config.load(config_path)

    def test_config_save(self):
        """Test saving config to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config = Config()
            config.api.api_key = "save-test-key"
            config.api.model = "claude-save"
            config.behavior.auto_stage = False

            config.save(config_path)

            assert config_path.exists()
            assert config_path.stat().st_mode & 0o600 == 0o600

            loaded = Config.load(config_path)
            assert loaded.api.api_key == "save-test-key"
            assert loaded.api.model == "claude-save"
            assert loaded.behavior.auto_stage is False

    def test_config_save_no_api_key(self):
        """Test saving config without API key doesn't include it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config = Config()

            config.save(config_path)

            loaded = Config.load(config_path)
            assert loaded.api.api_key == ""

    def test_api_config_to_dict(self):
        """Test APIConfig serialization."""
        api_config = APIConfig()
        api_config.api_key = "test"
        api_config.model = "model-test"
        api_config.max_tokens = 8192

        data = api_config.to_dict()

        assert data["api_key"] == "test"
        assert data["model"] == "model-test"
        assert data["max_tokens"] == 8192

    def test_behavior_config_to_dict(self):
        """Test BehaviorConfig serialization."""
        beh_config = BehaviorConfig()
        beh_config.auto_stage = False
        beh_config.show_previews = False
        beh_config.max_context_lines = 200
        beh_config.auto_resolve = True

        data = beh_config.to_dict()

        assert data["auto_stage"] is False
        assert data["show_previews"] is False
        assert data["max_context_lines"] == 200
        assert data["auto_resolve"] is True

    def test_ui_config_to_dict(self):
        """Test UIConfig serialization."""
        ui_config = UIConfig()
        ui_config.color = False
        ui_config.verbosity = "quiet"

        data = ui_config.to_dict()

        assert data["color"] is False
        assert data["verbosity"] == "quiet"


class TestGit:
    """Tests for Git operations."""

    @patch("subprocess.run")
    def test_get_current_branch(self, mock_run):
        """Test getting current branch name."""
        mock_run.return_value = MagicMock(
            stdout="feature-branch\n",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            branch = git.get_current_branch()

        assert branch == "feature-branch"

    @patch("subprocess.run")
    def test_rebase_state_none(self, mock_run):
        """Test detecting no rebase in progress."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            with patch("pathlib.Path.exists", return_value=False):
                git = Git()
                state = git.get_rebase_state()

        assert state == RebaseState.NONE

    @patch("subprocess.run")
    def test_rebase_state_in_progress(self, mock_run):
        """Test detecting rebase in progress."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            original_exists = Path.exists
            def mock_exists(self):
                path_str = str(self)
                if "rebase-merge" in path_str:
                    return True
                if "rebase-apply" in path_str:
                    return False
                return original_exists(self)

            with patch.object(Path, "exists", mock_exists):
                with patch.object(git, "get_conflicted_files", return_value=[]):
                    state = git.get_rebase_state()

            assert state == RebaseState.IN_PROGRESS

    @patch("subprocess.run")
    def test_rebase_state_conflict(self, mock_run):
        """Test detecting rebase conflict."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            original_exists = Path.exists
            def mock_exists(self):
                path_str = str(self)
                if "rebase-merge" in path_str:
                    return True
                if "rebase-apply" in path_str:
                    return False
                return original_exists(self)

            with patch.object(Path, "exists", mock_exists):
                with patch.object(git, "get_conflicted_files", return_value=[Path("test.py")]):
                    state = git.get_rebase_state()

            assert state == RebaseState.CONFLICT

    @patch("subprocess.run")
    def test_get_conflicted_files(self, mock_run):
        """Test getting conflicted files."""
        mock_run.return_value = MagicMock(
            stdout="file1.py\nfile2.py\n",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            git.repo_path = Path("/test/repo")
            files = git.get_conflicted_files()

        assert len(files) == 2
        assert files[0].name == "file1.py"
        assert files[1].name == "file2.py"

    @patch("subprocess.run")
    def test_get_conflicted_files_empty(self, mock_run):
        """Test getting conflicted files when none exist."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=1,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            files = git.get_conflicted_files()

        assert files == []

    @patch("subprocess.run")
    def test_get_conflict_details(self, mock_run):
        """Test getting conflict details (file must be inside repo)."""
        mock_run.side_effect = [
            MagicMock(stdout="ours content", returncode=0),
            MagicMock(stdout="theirs content", returncode=0),
            MagicMock(stdout="base content", returncode=0),
        ]

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                repo_path = Path(tmpdir).resolve()
                file_path = repo_path / "conflict.py"
                file_path.write_text("""<<<<<<< HEAD
ours code
=======
theirs code
>>>>>>> branch
""")

                git = Git()
                git.repo_path = repo_path
                conflict = git.get_conflict_details(file_path)

                assert conflict.ours_content == "ours content"
                assert conflict.theirs_content == "theirs content"
                assert conflict.base_content == "base content"
                assert len(conflict.conflict_markers) == 1

    @patch("subprocess.run")
    def test_get_commits_between(self, mock_run):
        """Test getting commits between references."""
        mock_run.side_effect = [
            MagicMock(stdout="base123\n", returncode=0),
            MagicMock(stdout="abc123|abc123|Message|Author|2024-01-01\n", returncode=0),
            MagicMock(stdout="file1.py\nfile2.py\n", returncode=0),
        ]

        with patch.object(Git, "_verify_repo"):
            git = Git()
            commits = git.get_commits_between("main", "HEAD")

        assert len(commits) == 1
        assert commits[0].sha == "abc123"
        assert commits[0].message == "Message"
        assert len(commits[0].files_changed) == 2

    @patch("subprocess.run")
    def test_get_commits_between_no_merge_base(self, mock_run):
        """Test getting commits when no merge base exists."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=1,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            commits = git.get_commits_between("main", "HEAD")

        assert commits == []

    @patch("subprocess.run")
    def test_get_merge_base(self, mock_run):
        """Test getting merge base."""
        mock_run.return_value = MagicMock(
            stdout="abc123def456\n",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            base = git.get_merge_base("main", "HEAD")

        assert base == "abc123def456"

    @patch("subprocess.run")
    def test_analyze_rebase(self, mock_run):
        """Test analyzing rebase."""
        mock_run.side_effect = [
            MagicMock(stdout="feature\n", returncode=0),
            MagicMock(stdout="abc123def\n", returncode=0),
            MagicMock(stdout="base123\n", returncode=0),
            MagicMock(stdout="head456\n", returncode=0),
            MagicMock(stdout="target789\n", returncode=0),
            MagicMock(stdout="base123\n", returncode=0),
            MagicMock(stdout="abc123|abc123|Message|Author|2024-01-01\n", returncode=0),
            MagicMock(stdout="file1.py\n", returncode=0),
            MagicMock(stdout="file1.py\nfile2.py\n", returncode=0),
            MagicMock(stdout="0\t0\tfile1.py\n", returncode=0),
            MagicMock(stdout="", returncode=0),
        ]

        with patch.object(Git, "_verify_repo"):
            git = Git()
            analysis = git.analyze_rebase("main")

        assert analysis.current_branch == "feature"
        assert analysis.target_branch == "main"
        assert analysis.merge_base == "base123"
        assert len(analysis.commits_to_rebase) >= 1

    @patch("subprocess.run")
    def test_start_rebase(self, mock_run):
        """Test starting rebase."""
        mock_run.return_value = MagicMock(
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            success = git.start_rebase("main")

        assert success is True

    @patch("subprocess.run")
    def test_start_rebase_interactive(self, mock_run):
        """Test starting interactive rebase."""
        mock_run.return_value = MagicMock(
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            success = git.start_rebase("main", interactive=True)

        assert success is True
        assert "-i" in mock_run.call_args[0][0]

    @patch("subprocess.run")
    def test_start_rebase_fails(self, mock_run):
        """Test starting rebase that fails."""
        mock_run.return_value = MagicMock(
            returncode=1,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            success = git.start_rebase("main")

        assert success is False

    @patch("subprocess.run")
    def test_continue_rebase(self, mock_run):
        """Test continuing rebase."""
        mock_run.return_value = MagicMock(
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            success = git.continue_rebase()

        assert success is True

    @patch("subprocess.run")
    def test_continue_rebase_fails(self, mock_run):
        """Test continuing rebase that fails."""
        mock_run.return_value = MagicMock(
            returncode=1,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            success = git.continue_rebase()

        assert success is False

    @patch("subprocess.run")
    def test_abort_rebase(self, mock_run):
        """Test aborting rebase."""
        mock_run.return_value = MagicMock(
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            git.abort_rebase()

        assert mock_run.called

    @patch("subprocess.run")
    def test_stage_file(self, mock_run):
        """Test staging file."""
        mock_run.return_value = MagicMock(
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            git.stage_file(Path("test.py"))

        assert mock_run.called

    @patch("subprocess.run")
    def test_get_file_content(self, mock_run):
        """Test getting file content."""
        mock_run.return_value = MagicMock(
            stdout="file content",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            content = git.get_file_content("test.py", "HEAD")

        assert content == "file content"

    @patch("subprocess.run")
    def test_get_file_content_not_found(self, mock_run):
        """Test getting file content when file doesn't exist."""
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=1,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            content = git.get_file_content("test.py", "HEAD")

        assert content == ""

    @patch("subprocess.run")
    def test_get_diff(self, mock_run):
        """Test getting diff."""
        mock_run.return_value = MagicMock(
            stdout="diff output",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            diff = git.get_diff("main", "HEAD")

        assert diff == "diff output"

    @patch("subprocess.run")
    def test_get_diff_with_file(self, mock_run):
        """Test getting diff for specific file."""
        mock_run.return_value = MagicMock(
            stdout="diff output",
            returncode=0,
        )

        with patch.object(Git, "_verify_repo"):
            git = Git()
            diff = git.get_diff("main", "HEAD", "test.py")

        assert diff == "diff output"
        assert "--" in mock_run.call_args[0][0]
        assert "test.py" in mock_run.call_args[0][0]

    @patch("subprocess.run")
    def test_verify_repo_fails(self, mock_run):
        """Test verifying repo when not in git repo."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="error")

        with pytest.raises(GitError):
            Git()

    @patch("subprocess.run")
    def test_run_command_raises_error(self, mock_run):
        """Test git command raises error."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git", stderr="error")

        with patch.object(Git, "_verify_repo"):
            git = Git()
            with pytest.raises(GitError):
                git.get_current_branch()

    def test_conflict_file_dataclass(self):
        """Test ConflictFile dataclass."""
        conflict = ConflictFile(
            path=Path("/test/file.py"),
            ours_content="our code",
            theirs_content="their code",
            base_content="base code",
            conflict_markers=[(10, 20)],
        )

        assert conflict.path == Path("/test/file.py")
        assert len(conflict.conflict_markers) == 1
        assert conflict.ours_content == "our code"
        assert conflict.theirs_content == "their code"
        assert conflict.base_content == "base code"

    def test_conflict_file_full_content(self):
        """Test ConflictFile full_content property."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
            f.write("file content")
            f.flush()
            file_path = Path(f.name)

            conflict = ConflictFile(
                path=file_path,
                ours_content="",
                theirs_content="",
                base_content="",
                conflict_markers=[],
            )

            assert conflict.full_content == "file content"
            file_path.unlink()

    def test_commit_dataclass(self):
        """Test Commit dataclass."""
        commit = Commit(
            sha="abc123def456",
            short_sha="abc123d",
            message="Fix bug in parser",
            author="Test Author",
            date="2024-01-15",
            files_changed=["src/parser.py", "tests/test_parser.py"],
        )

        assert commit.short_sha == "abc123d"
        assert commit.sha == "abc123def456"
        assert commit.message == "Fix bug in parser"
        assert len(commit.files_changed) == 2

    def test_rebase_analysis_dataclass(self):
        """Test RebaseAnalysis dataclass."""
        commits = [Commit("sha1", "s1", "msg1", "author", "date", ["f1"])]
        conflicts = [{"file": "f1", "commit": "s1", "message": "msg1"}]

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=commits,
            potential_conflicts=conflicts,
            merge_base="base123",
        )

        assert analysis.current_branch == "feature"
        assert analysis.target_branch == "main"
        assert len(analysis.commits_to_rebase) == 1
        assert len(analysis.potential_conflicts) == 1
        assert analysis.merge_base == "base123"


class TestGitNudge:
    """Tests for core GitNudge functionality."""

    def test_init_with_config(self):
        """Test GitNudge initialization with config."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)

        assert nudge.config.api.api_key == "test-key"

    def test_init_without_config(self):
        """Test GitNudge initialization without config."""
        with patch.object(Git, "_verify_repo"):
            with patch.object(Config, "load", return_value=Config()):
                nudge = GitNudge()

        assert nudge.config is not None

    def test_init_with_repo_path(self):
        """Test GitNudge initialization with repo path."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config, repo_path=Path("/test/repo"))

        assert nudge.git.repo_path == Path("/test/repo")

    def test_ai_lazy_loading(self):
        """Test AI assistant lazy loading."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)

        assert nudge._ai is None

        with patch("anthropic.Anthropic"):
            ai = nudge.ai

        assert ai is not None
        assert nudge._ai is not None

    def test_ai_lazy_loading_config_error(self):
        """Test AI assistant raises error on invalid config."""
        config = Config()

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)

        with patch("anthropic.Anthropic"):
            with pytest.raises(GitNudgeError):
                _ = nudge.ai

    def test_analyze(self):
        """Test analyze method."""
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[],
            potential_conflicts=[],
            merge_base="base123",
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                result = nudge.analyze("main")

        assert result.current_branch == "feature"
        assert result.target_branch == "main"

    def test_get_ai_recommendation(self):
        """Test getting AI recommendation."""
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[],
            potential_conflicts=[],
            merge_base="base123",
        )

        recommendation = RebaseRecommendation(
            should_proceed=True,
            risk_level="low",
            explanation="Safe to proceed",
            suggested_approach="Standard rebase",
            warnings=[],
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                mock_ai = MagicMock()
                mock_ai.analyze_rebase.return_value = recommendation
                nudge._ai = mock_ai
                result = nudge.get_ai_recommendation("main")

        assert result.should_proceed is True
        assert result.risk_level == "low"

    def test_rebase_dry_run(self):
        """Test rebase dry run."""
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[Commit("sha1", "s1", "msg", "author", "date", [])],
            potential_conflicts=[],
            merge_base="base123",
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.NONE):
                with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                    result = nudge.rebase("main", dry_run=True)

        assert result.success is True
        assert result.commits_applied == 0

    def test_rebase_already_in_progress(self):
        """Test rebase when already in progress."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.IN_PROGRESS):
                with pytest.raises(GitNudgeError):
                    nudge.rebase("main")

    def test_rebase_success(self):
        """Test successful rebase."""
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[Commit("sha1", "s1", "msg", "author", "date", [])],
            potential_conflicts=[],
            merge_base="base123",
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge, "preflight", return_value=[]):
                with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.NONE):
                    with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                        with patch.object(nudge.git, "get_head_sha", return_value="safe123"):
                            with patch.object(nudge.git, "start_rebase", return_value=True):
                                with patch.object(nudge, "_save_snapshot"):
                                    result = nudge.rebase("main")

        assert result.success is True
        assert result.commits_applied == 1
        assert result.safety_sha == "safe123"

    def test_rebase_with_conflicts(self):
        """Test rebase with conflicts."""
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[Commit("sha1", "s1", "msg", "author", "date", [])],
            potential_conflicts=[],
            merge_base="base123",
        )

        conflict_file = ConflictFile(
            path=Path("test.py"),
            ours_content="ours",
            theirs_content="theirs",
            base_content="base",
            conflict_markers=[],
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            states = [RebaseState.CONFLICT]
            with patch.object(nudge, "preflight", return_value=[]):
                with patch.object(nudge.git, "get_rebase_state", side_effect=states):
                    with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                        with patch.object(nudge.git, "get_head_sha", return_value="safe123"):
                            with patch.object(nudge.git, "start_rebase", return_value=False):
                                with patch.object(nudge, "_save_snapshot"):
                                    conflicted = [Path("test.py")]
                                    get_conflicted = patch.object(
                                        nudge.git, "get_conflicted_files",
                                        return_value=conflicted,
                                    )
                                    get_details = patch.object(
                                        nudge.git, "get_conflict_details",
                                        return_value=conflict_file,
                                    )
                                    with get_conflicted, get_details:
                                        result = nudge.rebase("main")

        assert result.success is False
        assert result.conflicts is not None

    def test_rebase_auto_resolve(self):
        """Test rebase with auto resolve."""
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[Commit("sha1", "s1", "msg", "author", "date", [])],
            potential_conflicts=[],
            merge_base="base123",
        )

        conflict_file = ConflictFile(
            path=Path("test.py"),
            ours_content="ours",
            theirs_content="theirs",
            base_content="base",
            conflict_markers=[],
        )

        resolution = ConflictResolution(
            file_path="test.py",
            resolved_content="resolved",
            explanation="explanation",
            confidence="high",
            changes_summary="summary",
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            states = [RebaseState.CONFLICT, RebaseState.NONE]
            conflicted_calls = [[Path("test.py")], []]
            with patch.object(nudge, "preflight", return_value=[]):
                with patch.object(nudge.git, "get_rebase_state", side_effect=states):
                    with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                        with patch.object(nudge.git, "get_head_sha", return_value="safe"):
                            with patch.object(nudge.git, "start_rebase", return_value=False):
                                with patch.object(nudge, "_save_snapshot"):
                                    get_conflicted = patch.object(
                                        nudge.git, "get_conflicted_files",
                                        side_effect=conflicted_calls,
                                    )
                                    get_details = patch.object(
                                        nudge.git, "get_conflict_details",
                                        return_value=conflict_file,
                                    )
                                    resolve = patch.object(
                                        nudge, "resolve_conflict",
                                        return_value=resolution,
                                    )
                                    cont = patch.object(
                                        nudge.git, "continue_rebase", return_value=True
                                    )
                                    with get_conflicted, get_details, resolve, cont:
                                        with patch.object(nudge, "apply_resolution"):
                                            result = nudge.rebase(
                                                "main", auto_resolve=True
                                            )

        assert result.success is True
        assert result.conflicts_resolved == 1

    def test_resolve_conflict(self):
        """Test resolving conflict."""
        config = Config()
        config.api.api_key = "test-key"

        conflict_file = ConflictFile(
            path=Path("test.py"),
            ours_content="ours",
            theirs_content="theirs",
            base_content="base",
            conflict_markers=[],
        )

        resolution = ConflictResolution(
            file_path="test.py",
            resolved_content="resolved",
            explanation="explanation",
            confidence="high",
            changes_summary="summary",
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_conflicted_files", return_value=[Path("test.py")]):
                with patch.object(nudge.git, "get_conflict_details", return_value=conflict_file):
                    mock_ai = MagicMock()
                    mock_ai.analyze_conflict.return_value = resolution
                    nudge._ai = mock_ai
                    result = nudge.resolve_conflict()

        assert result is not None
        assert result.confidence == "high"

    def test_resolve_conflict_no_conflicts(self):
        """Test resolving conflict when none exist."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_conflicted_files", return_value=[]):
                result = nudge.resolve_conflict()

        assert result is None

    def test_resolve_conflict_with_file_path(self):
        """Test resolving conflict with specific file."""
        config = Config()
        config.api.api_key = "test-key"

        conflict_file = ConflictFile(
            path=Path("test.py"),
            ours_content="ours",
            theirs_content="theirs",
            base_content="base",
            conflict_markers=[],
        )

        resolution = ConflictResolution(
            file_path="test.py",
            resolved_content="resolved",
            explanation="explanation",
            confidence="high",
            changes_summary="summary",
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_conflict_details", return_value=conflict_file):
                mock_ai = MagicMock()
                mock_ai.analyze_conflict.return_value = resolution
                nudge._ai = mock_ai
                result = nudge.resolve_conflict(Path("test.py"))

        assert result is not None

    def test_explain_conflict(self):
        """Test explaining conflict."""
        config = Config()
        config.api.api_key = "test-key"

        conflict_file = ConflictFile(
            path=Path("test.py"),
            ours_content="ours",
            theirs_content="theirs",
            base_content="base",
            conflict_markers=[],
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_conflicted_files", return_value=[Path("test.py")]):
                with patch.object(nudge.git, "get_conflict_details", return_value=conflict_file):
                    mock_ai = MagicMock()
                    mock_ai.explain_conflict.return_value = "explanation"
                    nudge._ai = mock_ai
                    result = nudge.explain_conflict()

        assert result == "explanation"

    def test_explain_conflict_no_conflicts(self):
        """Test explaining conflict when none exist."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_conflicted_files", return_value=[]):
                result = nudge.explain_conflict()

        assert result == "No conflicts found."

    def test_apply_resolution(self):
        """Test applying resolution."""
        config = Config()
        config.api.api_key = "test-key"
        config.behavior.auto_stage = True

        resolution = ConflictResolution(
            file_path="test.py",
            resolved_content="resolved content",
            explanation="explanation",
            confidence="high",
            changes_summary="summary",
        )

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                file_path = Path(tmpdir) / "test.py"
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                resolution.file_path = str(file_path)
                with patch.object(nudge.git, "stage_file"):
                    nudge.apply_resolution(resolution)

                assert file_path.read_text() == "resolved content"

    def test_apply_resolution_no_auto_stage(self):
        """Test applying resolution without auto stage."""
        config = Config()
        config.api.api_key = "test-key"
        config.behavior.auto_stage = False

        resolution = ConflictResolution(
            file_path="test.py",
            resolved_content="resolved content",
            explanation="explanation",
            confidence="high",
            changes_summary="summary",
        )

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                file_path = Path(tmpdir) / "test.py"
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                resolution.file_path = str(file_path)
                nudge.apply_resolution(resolution)

                assert file_path.read_text() == "resolved content"

    def test_continue_rebase(self):
        """Test continuing rebase."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.IN_PROGRESS):
                with patch.object(nudge.git, "get_conflicted_files", return_value=[]):
                    with patch.object(nudge.git, "continue_rebase", return_value=True):
                        result = nudge.continue_rebase()

        assert result.success is True

    def test_continue_rebase_no_rebase(self):
        """Test continuing rebase when none in progress."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.NONE):
                with pytest.raises(GitNudgeError):
                    nudge.continue_rebase()

    def test_continue_rebase_with_conflicts(self):
        """Test continuing rebase with unresolved conflicts."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.CONFLICT):
                conflicted = [Path("test.py")]
                with patch.object(nudge.git, "get_conflicted_files", return_value=conflicted):
                    with pytest.raises(GitNudgeError):
                        nudge.continue_rebase()

    def test_continue_rebase_new_conflicts(self):
        """Test continuing rebase with new conflicts."""
        config = Config()
        config.api.api_key = "test-key"

        conflict_file = ConflictFile(
            path=Path("test.py"),
            ours_content="ours",
            theirs_content="theirs",
            base_content="base",
            conflict_markers=[],
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.IN_PROGRESS):
                conflicted_side_effect = [[], [Path("test.py")]]
                get_conflicted = patch.object(
                    nudge.git, "get_conflicted_files", side_effect=conflicted_side_effect
                )
                with get_conflicted:
                    with patch.object(nudge.git, "continue_rebase", return_value=False):
                        get_details = patch.object(
                            nudge.git, "get_conflict_details", return_value=conflict_file
                        )
                        with get_details:
                            result = nudge.continue_rebase()

        assert result.success is False
        assert result.conflicts is not None

    def test_abort_rebase(self):
        """Test aborting rebase."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.IN_PROGRESS):
                with patch.object(nudge.git, "abort_rebase"):
                    nudge.abort_rebase()

        assert True

    def test_abort_rebase_no_rebase(self):
        """Test aborting rebase when none in progress."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.NONE):
                with pytest.raises(GitNudgeError):
                    nudge.abort_rebase()

    def test_get_status(self):
        """Test getting status."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_current_branch", return_value="main"):
                with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.NONE):
                    with patch.object(nudge.git, "get_conflicted_files", return_value=[]):
                        status = nudge.get_status()

        assert status["current_branch"] == "main"
        assert status["rebase_state"] == "none"
        assert status["config_valid"] is True
        assert status["conflicted_files"] == []

    def test_get_status_with_conflicts(self):
        """Test getting status with conflicts."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_current_branch", return_value="main"):
                with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.CONFLICT):
                    conflicted = [Path("test.py")]
                    with patch.object(nudge.git, "get_conflicted_files", return_value=conflicted):
                        status = nudge.get_status()

        assert status["rebase_state"] == "conflict"
        assert len(status["conflicted_files"]) == 1


class TestAIIntegration:
    """Tests for AI integration (mocked)."""

    def test_parse_conflict_response(self):
        """Test parsing AI response for conflict resolution."""
        from gitnudge.ai import AIAssistant  # noqa: F811  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        response = """EXPLANATION:
The conflict occurred because both branches modified the same function.

RESOLVED_CONTENT:
```python
def hello():
    return "Hello, World!"
```

CONFIDENCE: high

CHANGES_SUMMARY:
Combined both changes by keeping the function name from ours and the implementation from theirs."""

        with patch("anthropic.Anthropic"):
            assistant = AIAssistant(config)
            resolution = assistant._parse_conflict_response("test.py", response)

        assert resolution.confidence == "high"
        assert "hello" in resolution.resolved_content
        assert "conflict" in resolution.explanation.lower()

    def test_init(self):
        """Test AIAssistant initialization."""
        from gitnudge.ai import AIAssistant  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"
        config.api.model = "claude-test"
        config.api.max_tokens = 2048

        with patch("anthropic.Anthropic") as mock_anthropic:
            assistant = AIAssistant(config)

        assert assistant.config == config
        assert assistant.model == "claude-test"
        assert assistant.max_tokens == 2048
        mock_anthropic.assert_called_once_with(api_key="test-key")

    def test_parse_conflict_response_invalid_confidence(self):
        """Test parsing conflict response with invalid confidence."""
        from gitnudge.ai import AIAssistant  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        response = """EXPLANATION:
Test explanation

RESOLVED_CONTENT:
```python
code
```
```

CONFIDENCE: invalid

CHANGES_SUMMARY:
Summary"""

        with patch("anthropic.Anthropic"):
            assistant = AIAssistant(config)
            resolution = assistant._parse_conflict_response("test.py", response)

        assert resolution.confidence == "medium"

    def test_parse_rebase_response(self):
        """Test parsing rebase recommendation response."""
        from gitnudge.ai import AIAssistant  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        response = """SHOULD_PROCEED: yes

RISK_LEVEL: low

EXPLANATION:
Safe to proceed

SUGGESTED_APPROACH:
Standard rebase

WARNINGS:
None"""

        with patch("anthropic.Anthropic"):
            assistant = AIAssistant(config)
            recommendation = assistant._parse_rebase_response(response)

        assert recommendation.should_proceed is True
        assert recommendation.risk_level == "low"
        assert len(recommendation.warnings) == 0

    def test_parse_rebase_response_with_warnings(self):
        """Test parsing rebase response with warnings."""
        from gitnudge.ai import AIAssistant  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        response = """SHOULD_PROCEED: no

RISK_LEVEL: high

EXPLANATION:
Risky operation

SUGGESTED_APPROACH:
Be careful

WARNINGS:
- Warning 1
- Warning 2"""

        with patch("anthropic.Anthropic"):
            assistant = AIAssistant(config)
            recommendation = assistant._parse_rebase_response(response)

        assert recommendation.should_proceed is False
        assert recommendation.risk_level == "high"
        assert len(recommendation.warnings) == 2

    def test_extract_section(self):
        """Test extracting section from response."""
        from gitnudge.ai import AIAssistant  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        text = """EXPLANATION:
This is the explanation text.

CONFIDENCE:
high"""

        with patch("anthropic.Anthropic"):
            assistant = AIAssistant(config)
            result = assistant._extract_section(text, "EXPLANATION:")

        assert "explanation text" in result.lower()

    def test_extract_code_block(self):
        """Test extracting code block."""
        from gitnudge.ai import AIAssistant  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        text = """```python
def hello():
    return "world"
```"""

        with patch("anthropic.Anthropic"):
            assistant = AIAssistant(config)
            result = assistant._extract_code_block(text)

        assert "def hello" in result
        assert "```" not in result

    def test_analyze_conflict(self):
        """Test analyzing conflict."""
        from gitnudge.ai import AIAssistant  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        conflict = ConflictFile(
            path=Path("test.py"),
            ours_content="ours",
            theirs_content="theirs",
            base_content="base",
            conflict_markers=[],
        )

        mock_response = MagicMock()
        response_text = (
            "EXPLANATION:\nTest\n\nRESOLVED_CONTENT:\n```\ncode\n```\n\n"
            "CONFIDENCE: high\n\nCHANGES_SUMMARY:\nSummary"
        )
        mock_response.content = [MagicMock(text=response_text)]

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_response
            mock_anthropic.return_value = mock_client

            assistant = AIAssistant(config)
            resolution = assistant.analyze_conflict(conflict)

        assert resolution is not None
        assert resolution.file_path == "test.py"

    def test_call_api_error(self):
        """Test API call error handling."""
        from gitnudge.ai import AIAssistant, AIError  # noqa: F811

        config = Config()
        config.api.api_key = "test-key"

        class MockAPIError(Exception):
            pass

        with patch("anthropic.Anthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create.side_effect = MockAPIError("API Error")
            mock_anthropic.return_value = mock_client

            with patch("gitnudge.ai.anthropic.APIError", MockAPIError):
                assistant = AIAssistant(config)
                with pytest.raises(AIError):
                    assistant._call_api("test prompt")


class TestPydanticValidation:
    """Tests for pydantic-based config validation."""

    def test_max_tokens_too_low(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            APIConfig(max_tokens=0)

    def test_max_tokens_too_high(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            APIConfig(max_tokens=10**7)

    def test_empty_model_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            APIConfig(model="")

    def test_api_key_stripped(self):
        cfg = APIConfig(api_key="  sk-ant-abc  ")
        assert cfg.api_key == "sk-ant-abc"

    def test_max_context_lines_validated(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            BehaviorConfig(max_context_lines=5)
        with pytest.raises(ValidationError):
            BehaviorConfig(max_context_lines=10**6)

    def test_conflict_resolution_normalizes_invalid_confidence(self):
        r = ConflictResolution(file_path="x", resolved_content="", confidence="bogus")
        assert r.confidence == "medium"

    def test_rebase_recommendation_normalizes_risk(self):
        r = RebaseRecommendation(should_proceed=True, risk_level="bogus")
        assert r.risk_level == "medium"


class TestSecurityAndBugFixes:
    """Tests for security fixes and bug fixes."""

    def test_apply_resolution_rejects_path_traversal(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                resolution = ConflictResolution(
                    file_path="/etc/passwd",
                    resolved_content="hacked",
                )
                with pytest.raises(GitNudgeError):
                    nudge.apply_resolution(resolution)

    def test_apply_resolution_relative_path_inside_repo(self):
        config = Config()
        config.api.api_key = "test-key"
        config.behavior.auto_stage = False

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                resolution = ConflictResolution(
                    file_path="sub/file.py",
                    resolved_content="ok",
                )
                (Path(tmpdir) / "sub").mkdir()
                nudge.apply_resolution(resolution)
                assert (Path(tmpdir) / "sub" / "file.py").read_text() == "ok"

    def test_invalid_ref_rejected(self):
        with patch.object(Git, "_verify_repo"):
            git = Git()
            with pytest.raises(GitError):
                git.get_merge_base("--evil-flag")
            with pytest.raises(GitError):
                git.start_rebase("--upstream=evil")
            with pytest.raises(GitError):
                git.analyze_rebase("ref with spaces")

    def test_get_conflict_details_uses_full_repo_path(self):
        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                repo_path = Path(tmpdir).resolve()
                sub = repo_path / "src" / "deep"
                sub.mkdir(parents=True)
                f = sub / "x.py"
                f.write_text("no markers")

                git = Git()
                git.repo_path = repo_path
                with patch.object(Git, "_run") as mock_run:
                    mock_run.return_value = MagicMock(stdout="", returncode=0)
                    git.get_conflict_details(f)
                    show_calls = [
                        c for c in mock_run.call_args_list
                        if c.args and c.args[0][0] == "show"
                    ]
                    assert show_calls
                    for c in show_calls:
                        spec = c.args[0][1]
                        assert spec.endswith("src/deep/x.py")


class TestCLI:
    """Smoke tests for the CLI."""

    def test_cli_version(self):
        from click.testing import CliRunner

        from gitnudge.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "." in result.output

    def test_cli_version_matches_package(self):
        from click.testing import CliRunner

        from gitnudge import __version__
        from gitnudge.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_cli_help(self):
        from click.testing import CliRunner

        from gitnudge.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "rebase" in result.output
        assert "config" in result.output
        assert "explain" in result.output

    def test_cli_explain_no_rebase(self):
        from click.testing import CliRunner

        from gitnudge.cli import main
        runner = CliRunner()
        cfg = Config()
        cfg.api.api_key = "test-key"
        with patch("gitnudge.cli.Config.load", return_value=cfg):
            with patch.object(Git, "_verify_repo"):
                with patch.object(Git, "get_rebase_state", return_value=RebaseState.NONE):
                    result = runner.invoke(main, ["explain"])
            assert result.exit_code == 0
            assert "No rebase" in result.output

    def test_cli_verbose_and_quiet_conflict(self):
        from click.testing import CliRunner

        from gitnudge.cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["--verbose", "--quiet", "status"])
        assert result.exit_code == 2
        assert "mutually exclusive" in (result.output + (result.stderr or ""))

    def test_cli_verbose_sets_verbosity(self):
        from click.testing import CliRunner

        from gitnudge.cli import main
        runner = CliRunner()
        cfg = Config()
        cfg.api.api_key = "test-key"
        with patch("gitnudge.cli.Config.load", return_value=cfg):
            with patch.object(Git, "_verify_repo"):
                with patch.object(Git, "get_current_branch", return_value="main"):
                    with patch.object(Git, "get_rebase_state", return_value=RebaseState.NONE):
                        with patch.object(Git, "get_conflicted_files", return_value=[]):
                            result = runner.invoke(main, ["--verbose", "status"])
            assert result.exit_code == 0
            assert cfg.ui.verbosity == "verbose"

    def test_cli_status_smoke(self):
        from click.testing import CliRunner

        from gitnudge.cli import main
        runner = CliRunner()
        cfg = Config()
        cfg.api.api_key = "test-key"
        with patch("gitnudge.cli.Config.load", return_value=cfg):
            with patch.object(Git, "_verify_repo"):
                with patch.object(Git, "get_current_branch", return_value="main"):
                    with patch.object(Git, "get_rebase_state", return_value=RebaseState.NONE):
                        with patch.object(Git, "get_conflicted_files", return_value=[]):
                            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0

    def test_python_dash_m_entrypoint(self):
        """`python -m gitnudge` should be importable and expose main."""
        import importlib

        mod = importlib.import_module("gitnudge.__main__")
        assert hasattr(mod, "main")


class TestRebaseFeatures:
    """Tests for real-rebase improvements: pre-flight, snapshot, markers, skip."""

    def test_preflight_dirty_tree(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "ref_exists", return_value=True):
                with patch.object(nudge.git, "is_detached_head", return_value=False):
                    with patch.object(nudge.git, "has_uncommitted_changes", return_value=True):
                        with patch.object(
                            nudge.git, "get_rebase_state", return_value=RebaseState.NONE
                        ):
                            errors = nudge.preflight("main")

        assert any("uncommitted" in e for e in errors)

    def test_preflight_target_missing(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "ref_exists", return_value=False):
                errors = nudge.preflight("nope")

        assert any("does not exist" in e for e in errors)

    def test_preflight_detached_head(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "ref_exists", return_value=True):
                with patch.object(nudge.git, "is_detached_head", return_value=True):
                    with patch.object(nudge.git, "has_uncommitted_changes", return_value=False):
                        with patch.object(
                            nudge.git, "get_rebase_state", return_value=RebaseState.NONE
                        ):
                            errors = nudge.preflight("main")

        assert any("detached" in e.lower() for e in errors)

    def test_apply_resolution_rejects_conflict_markers(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                resolution = ConflictResolution(
                    file_path="x.py",
                    resolved_content="ok\n<<<<<<< HEAD\nstill bad\n=======\nworse\n>>>>>>> br\n",
                )
                with pytest.raises(GitNudgeError):
                    nudge.apply_resolution(resolution)

    def test_rebase_already_up_to_date(self):
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[],
            potential_conflicts=[],
            merge_base="base",
            is_up_to_date=True,
            has_merge_base=True,
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge, "preflight", return_value=[]):
                with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                    result = nudge.rebase("main")

        assert result.success is True
        assert "up to date" in result.message.lower()

    def test_rebase_no_merge_base(self):
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[],
            potential_conflicts=[],
            merge_base="",
            has_merge_base=False,
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge, "preflight", return_value=[]):
                with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                    with pytest.raises(GitNudgeError):
                        nudge.rebase("main")

    def test_skip_rebase(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            states = [RebaseState.CONFLICT, RebaseState.NONE]
            with patch.object(nudge.git, "get_rebase_state", side_effect=states):
                with patch.object(nudge.git, "skip_rebase", return_value=True):
                    with patch.object(nudge, "_clear_snapshot"):
                        result = nudge.skip_rebase()

        assert result.success is True

    def test_skip_rebase_no_rebase(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.NONE):
                with pytest.raises(GitNudgeError):
                    nudge.skip_rebase()

    def test_snapshot_save_and_clear(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                git_dir = Path(tmpdir) / ".git"
                git_dir.mkdir()
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                with patch.object(nudge.git, "_git_dir", return_value=git_dir):
                    with patch.object(nudge.git, "get_current_branch", return_value="feat"):
                        nudge._save_snapshot(target="main", head="abcdef")

                    snap = nudge._load_snapshot()
                    assert snap is not None
                    assert snap["head"] == "abcdef"
                    assert snap["target"] == "main"

                    nudge._clear_snapshot()
                    assert nudge._load_snapshot() is None

    def test_recovery_info(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                git_dir = Path(tmpdir) / ".git"
                git_dir.mkdir()
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                with patch.object(nudge.git, "_git_dir", return_value=git_dir):
                    with patch.object(nudge.git, "get_current_branch", return_value="feat"):
                        nudge._save_snapshot(target="main", head="abc123")
                    with patch.object(nudge.git, "_run") as mock_run:
                        mock_run.return_value = MagicMock(
                            stdout="abc123 HEAD@{0} commit: msg\n", returncode=0
                        )
                        with patch.object(nudge.git, "get_head_sha", return_value="def456"):
                            with patch.object(
                                nudge.git, "get_current_branch", return_value="feat"
                            ):
                                info = nudge.get_recovery_info()

                assert info["snapshot"]["head"] == "abc123"
                assert "abc123" in info["reflog"]
                assert info["current_head"] == "def456"

    def test_status_includes_progress(self):
        config = Config()
        config.api.api_key = "test-key"

        from gitnudge.git import RebaseProgress
        prog = RebaseProgress(current=2, total=5, current_subject="fix bug", current_sha="abc")

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                with patch.object(
                    nudge.git, "get_rebase_state", return_value=RebaseState.IN_PROGRESS
                ):
                    with patch.object(
                        nudge.git, "get_current_branch", return_value="feat"
                    ):
                        with patch.object(
                            nudge.git, "get_conflicted_files", return_value=[]
                        ):
                            with patch.object(
                                nudge.git, "get_rebase_progress", return_value=prog
                            ):
                                status = nudge.get_status()

        assert status["progress"] == {
            "current": 2, "total": 5, "subject": "fix bug", "sha": "abc"
        }

    def test_continue_rebase_applied_count_on_completion(self):
        """Applied count at rebase completion = before_total - before_done."""
        from gitnudge.git import RebaseProgress
        config = Config()
        config.api.api_key = "test-key"

        before = RebaseProgress(current=2, total=5, current_subject="x", current_sha="a")

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                git_dir = Path(tmpdir) / ".git"
                git_dir.mkdir()
                nudge = GitNudge(config, repo_path=Path(tmpdir))

                state_calls = [RebaseState.IN_PROGRESS, RebaseState.NONE]
                progress_calls = [before, None]
                with patch.object(nudge.git, "_git_dir", return_value=git_dir):
                    with patch.object(
                        nudge.git, "get_rebase_state", side_effect=state_calls
                    ):
                        with patch.object(nudge.git, "get_conflicted_files", return_value=[]):
                            with patch.object(
                                nudge.git, "get_rebase_progress", side_effect=progress_calls
                            ):
                                with patch.object(
                                    nudge.git, "continue_rebase", return_value=True
                                ):
                                    result = nudge.continue_rebase()

        assert result.success is True
        assert result.commits_applied == 3
        assert "applied 3 more" in result.message

    def test_continue_rebase_ai_verify_rejects_markers(self):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                bad = Path(tmpdir) / "bad.py"
                bad.write_text("a\n<<<<<<< HEAD\nb\n=======\nc\n>>>>>>> x\n")
                nudge = GitNudge(config, repo_path=Path(tmpdir))
                with patch.object(
                    nudge.git, "get_rebase_state", return_value=RebaseState.IN_PROGRESS
                ):
                    with patch.object(nudge.git, "get_conflicted_files", return_value=[]):
                        with patch.object(nudge.git, "_run") as mock_run:
                            mock_run.return_value = MagicMock(
                                stdout="bad.py\n", returncode=0
                            )
                            with pytest.raises(GitNudgeError):
                                nudge.continue_rebase(ai_verify=True)


class TestV1Fixes:
    """Tests for the 0.3.0 hardening round: ref validator, snapshot atomicity, skip off-by-one."""

    def test_ref_validator_rejects_double_dot(self):
        from gitnudge.git import _is_safe_ref
        assert not _is_safe_ref("..main")
        assert not _is_safe_ref("main..other")

    def test_ref_validator_rejects_at_brace(self):
        from gitnudge.git import _is_safe_ref
        assert not _is_safe_ref("HEAD@{upstream}")

    def test_ref_validator_rejects_leading_slash_or_colon(self):
        from gitnudge.git import _is_safe_ref
        assert not _is_safe_ref("/etc/passwd")
        assert not _is_safe_ref(":refs/heads/main")

    def test_ref_validator_rejects_lock_suffix(self):
        from gitnudge.git import _is_safe_ref
        assert not _is_safe_ref("main.lock")
        assert not _is_safe_ref("main.")

    def test_ref_validator_accepts_common_refs(self):
        from gitnudge.git import _is_safe_ref
        assert _is_safe_ref("main")
        assert _is_safe_ref("HEAD")
        assert _is_safe_ref("HEAD~5")
        assert _is_safe_ref("HEAD^")
        assert _is_safe_ref("origin/main")
        assert _is_safe_ref("feature/x-y-z")
        assert _is_safe_ref("v1.0.0")
        assert _is_safe_ref("abc123def456")

    def test_save_snapshot_atomic_no_partial_on_crash(self, tmp_path):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            git_dir = tmp_path / ".git"
            git_dir.mkdir()
            nudge = GitNudge(config, repo_path=tmp_path)

            with patch.object(nudge.git, "_git_dir", return_value=git_dir):
                with patch.object(nudge.git, "get_current_branch", return_value="feat"):
                    with patch(
                        "gitnudge.core.os.replace",
                        side_effect=OSError("disk full"),
                    ):
                        nudge._save_snapshot(target="main", head="abc123")

            snap = git_dir / GitNudge.SNAPSHOT_NAME
            assert not snap.exists()
            tmps = list(git_dir.glob(".gitnudge-snapshot.*.tmp"))
            assert tmps == []

    def test_save_snapshot_atomic_success(self, tmp_path):
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            git_dir = tmp_path / ".git"
            git_dir.mkdir()
            nudge = GitNudge(config, repo_path=tmp_path)

            with patch.object(nudge.git, "_git_dir", return_value=git_dir):
                with patch.object(nudge.git, "get_current_branch", return_value="feat"):
                    nudge._save_snapshot(target="main", head="abcdef0123456789")

            snap_path = git_dir / GitNudge.SNAPSHOT_NAME
            assert snap_path.exists()
            import json as _json
            loaded = _json.loads(snap_path.read_text())
            assert loaded["head"] == "abcdef0123456789"
            assert loaded["target"] == "main"
            assert loaded["branch"] == "feat"
            assert "timestamp" in loaded

    def test_skip_rebase_remaining_not_off_by_one(self):
        """Remaining count must include the new current commit."""
        from gitnudge.git import RebaseProgress
        config = Config()
        config.api.api_key = "test-key"

        prog = RebaseProgress(current=3, total=5, current_subject="x", current_sha="a")

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            state_calls = [RebaseState.CONFLICT, RebaseState.IN_PROGRESS]
            with patch.object(nudge.git, "get_rebase_state", side_effect=state_calls):
                with patch.object(nudge.git, "skip_rebase", return_value=True):
                    with patch.object(nudge.git, "get_rebase_progress", return_value=prog):
                        result = nudge.skip_rebase()

        assert result.success is True
        assert "3 remaining" in result.message

    def test_redacting_filter_scrubs_args(self, caplog):
        import logging

        from gitnudge.logging_utils import _RedactingFilter
        logger = logging.getLogger("gitnudge.test_redact")
        logger.addFilter(_RedactingFilter())
        logger.setLevel(logging.INFO)

        with caplog.at_level(logging.INFO, logger="gitnudge.test_redact"):
            logger.info("key=%s", "sk-ant-api03-ABCDEFGHIJKLMNOP")
            logger.info("plain sk-ant-api03-XYZ12345 text")

        all_msgs = [r.getMessage() for r in caplog.records]
        for m in all_msgs:
            assert "sk-ant-api03-ABCDEFGHIJKLMNOP" not in m
            assert "sk-ant-api03-XYZ12345" not in m
            assert "REDACTED" in m

    def test_redacting_filter_survives_bad_args(self):
        import logging

        from gitnudge.logging_utils import _RedactingFilter
        rec = logging.LogRecord(
            name="x", level=logging.INFO, pathname="", lineno=1,
            msg="bad %s %s", args=("only-one",), exc_info=None,
        )
        f = _RedactingFilter()
        assert f.filter(rec) is True

    def test_analyze_no_longer_accepts_detailed_kwarg(self):
        """The dead 'detailed' kwarg on GitNudge.analyze was removed."""
        config = Config()
        config.api.api_key = "test-key"

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            with patch.object(nudge.git, "analyze_rebase") as m:
                m.return_value = RebaseAnalysis(
                    current_branch="f", target_branch="main",
                    commits_to_rebase=[], potential_conflicts=[],
                    merge_base="b",
                )
                with pytest.raises(TypeError):
                    nudge.analyze("main", detailed=True)  # type: ignore[call-arg]

    def test_rebase_result_has_applied_resolutions_field(self):
        from gitnudge.core import RebaseResult
        r = RebaseResult(success=True, commits_applied=0, conflicts_resolved=0, message="ok")
        assert r.applied_resolutions == []

    def test_auto_resolve_records_applied_resolutions(self):
        config = Config()
        config.api.api_key = "test-key"

        analysis = RebaseAnalysis(
            current_branch="feature",
            target_branch="main",
            commits_to_rebase=[Commit("sha1", "s1", "msg", "author", "date", [])],
            potential_conflicts=[],
            merge_base="base123",
        )
        conflict_file = ConflictFile(
            path=Path("test.py"), ours_content="o", theirs_content="t",
            base_content="b", conflict_markers=[],
        )
        resolution = ConflictResolution(
            file_path="test.py", resolved_content="resolved",
            explanation="e", confidence="high", changes_summary="merged both sides",
        )

        with patch.object(Git, "_verify_repo"):
            nudge = GitNudge(config)
            states = [RebaseState.CONFLICT, RebaseState.NONE]
            conflicted_calls = [[Path("test.py")], []]
            with patch.object(nudge, "preflight", return_value=[]):
                with patch.object(nudge.git, "get_rebase_state", side_effect=states):
                    with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                        with patch.object(nudge.git, "get_head_sha", return_value="safe"):
                            with patch.object(nudge.git, "start_rebase", return_value=False):
                                with patch.object(nudge, "_save_snapshot"):
                                    with patch.object(
                                        nudge.git, "get_conflicted_files",
                                        side_effect=conflicted_calls,
                                    ):
                                        with patch.object(
                                            nudge.git, "get_conflict_details",
                                            return_value=conflict_file,
                                        ):
                                            with patch.object(
                                                nudge, "resolve_conflict",
                                                return_value=resolution,
                                            ):
                                                with patch.object(
                                                    nudge.git, "continue_rebase",
                                                    return_value=True,
                                                ):
                                                    with patch.object(nudge, "apply_resolution"):
                                                        result = nudge.rebase(
                                                            "main", auto_resolve=True
                                                        )

        assert result.success is True
        assert len(result.applied_resolutions) == 1
        entry = result.applied_resolutions[0]
        assert entry["confidence"] == "high"
        assert "merged" in entry["summary"]


class TestV1Regressions:
    """Tests for issues found during the v0.3.0 re-review (#21-#30)."""

    def _bare_ai(self):
        from gitnudge.ai import AIAssistant
        return object.__new__(AIAssistant)

    def test_extract_section_line_anchored(self):
        """#21: header must be at line start; prose 'explanation:' must not match."""
        from gitnudge.ai import AIAssistant
        ai = self._bare_ai()
        text = (
            "Some intro with an explanation: lower-case prose.\n"
            "EXPLANATION:\n"
            "This is the real body.\n"
            "CONFIDENCE: high\n"
        )
        out = AIAssistant._extract_section.__get__(ai)(text, "EXPLANATION:")
        assert out == "This is the real body."

    def test_parse_rebase_should_proceed_yes_with_caveats(self):
        """#22: 'Yes, with caveats' should be parsed as True."""
        from gitnudge.ai import AIAssistant
        ai = self._bare_ai()
        text = (
            "SHOULD_PROCEED: Yes, with caveats\n"
            "RISK_LEVEL: medium\n"
            "EXPLANATION: x\n"
            "SUGGESTED_APPROACH: y\n"
            "WARNINGS: none\n"
        )
        rec = AIAssistant._parse_rebase_response.__get__(ai)(text)
        assert rec.should_proceed is True

    def test_parse_rebase_should_proceed_no_period(self):
        """#22: 'No.' should be parsed as False."""
        from gitnudge.ai import AIAssistant
        ai = self._bare_ai()
        text = (
            "SHOULD_PROCEED: No.\n"
            "RISK_LEVEL: high\n"
            "EXPLANATION: x\n"
            "SUGGESTED_APPROACH: y\n"
            "WARNINGS: none\n"
        )
        rec = AIAssistant._parse_rebase_response.__get__(ai)(text)
        assert rec.should_proceed is False

    def test_is_safe_ref_trailing_slash_rejected(self):
        """#23: 'foo/' must be rejected (git rejects trailing slash)."""
        from gitnudge.git import _is_safe_ref
        assert _is_safe_ref("foo/") is False
        assert _is_safe_ref("refs/heads/") is False
        assert _is_safe_ref("refs/heads/main") is True

    def test_confidence_trailing_punctuation(self):
        """#27: 'high.' should normalize to 'high'."""
        from gitnudge.ai import ConflictResolution
        r = ConflictResolution(file_path="x", resolved_content="x", confidence="high.")
        assert r.confidence == "high"
        r = ConflictResolution(file_path="x", resolved_content="x", confidence=" HIGH!!")
        assert r.confidence == "high"

    def test_risk_level_trailing_punctuation(self):
        """#27: 'medium.' should normalize to 'medium'."""
        from gitnudge.ai import RebaseRecommendation
        r = RebaseRecommendation(risk_level="medium.")
        assert r.risk_level == "medium"
        r = RebaseRecommendation(risk_level=" LOW,")
        assert r.risk_level == "low"

    def test_full_content_logs_os_error(self, caplog):
        """#29: missing conflict file should log a warning, not return silently."""
        import logging
        from pathlib import Path

        from gitnudge.git import ConflictFile
        cf = ConflictFile(
            path=Path("/nonexistent/definitely/not/here.xyz"),
            ours_content="", theirs_content="", base_content="",
            conflict_markers=[],
        )
        logger = logging.getLogger("gitnudge.git")
        logger.propagate = True
        with caplog.at_level(logging.WARNING, logger="gitnudge.git"):
            out = cf.full_content
        assert out == ""
        assert any("Could not read conflict file" in rec.message for rec in caplog.records)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
