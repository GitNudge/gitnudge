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
        """Test validation catches invalid verbosity."""
        config = Config()
        config.api.api_key = "test-key"
        config.ui.verbosity = "invalid"
        errors = config.validate()

        assert len(errors) > 0
        assert any("verbosity" in e.lower() for e in errors)

    def test_config_validation_max_context_lines_too_low(self):
        """Test validation catches max_context_lines < 10."""
        config = Config()
        config.api.api_key = "test-key"
        config.behavior.max_context_lines = 5
        errors = config.validate()

        assert len(errors) > 0
        assert any("max_context_lines" in e for e in errors)

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
        """Test getting conflict details."""
        mock_run.side_effect = [
            MagicMock(stdout="ours content", returncode=0),
            MagicMock(stdout="theirs content", returncode=0),
            MagicMock(stdout="base content", returncode=0),
        ]

        with patch.object(Git, "_verify_repo"):
            with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.py') as f:
                f.write("""<<<<<<< HEAD
ours code
=======
theirs code
>>>>>>> branch
""")
                f.flush()
                file_path = Path(f.name)

                git = Git()
                git.repo_path = Path("/test/repo")
                conflict = git.get_conflict_details(file_path)

                assert conflict.ours_content == "ours content"
                assert conflict.theirs_content == "theirs content"
                assert conflict.base_content == "base content"
                assert len(conflict.conflict_markers) == 1

                file_path.unlink()

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
            MagicMock(stdout="base123\n", returncode=0),
            MagicMock(stdout="base123\n", returncode=0),
            MagicMock(stdout="abc123|abc123|Message|Author|2024-01-01\n", returncode=0),
            MagicMock(stdout="file1.py\n", returncode=0),
            MagicMock(stdout="file1.py\nfile2.py\n", returncode=0),
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
            with patch.object(nudge.git, "get_rebase_state", return_value=RebaseState.NONE):
                with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                    with patch.object(nudge.git, "start_rebase", return_value=True):
                        result = nudge.rebase("main")

        assert result.success is True
        assert result.commits_applied == 1

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
            states = [RebaseState.NONE, RebaseState.CONFLICT]
            with patch.object(nudge.git, "get_rebase_state", side_effect=states):
                with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                    with patch.object(nudge.git, "start_rebase", return_value=False):
                        conflicted = [Path("test.py")]
                        get_conflicted = patch.object(
                            nudge.git, "get_conflicted_files", return_value=conflicted
                        )
                        get_details = patch.object(
                            nudge.git, "get_conflict_details", return_value=conflict_file
                        )
                        with get_conflicted:
                            with get_details:
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
            states = [RebaseState.NONE, RebaseState.CONFLICT, RebaseState.NONE]
            with patch.object(nudge.git, "get_rebase_state", side_effect=states):
                with patch.object(nudge.git, "analyze_rebase", return_value=analysis):
                    with patch.object(nudge.git, "start_rebase", return_value=False):
                        conflicted = [Path("test.py")]
                        get_conflicted = patch.object(
                            nudge.git, "get_conflicted_files", return_value=conflicted
                        )
                        get_details = patch.object(
                            nudge.git, "get_conflict_details", return_value=conflict_file
                        )
                        resolve = patch.object(nudge, "resolve_conflict", return_value=resolution)
                        with get_conflicted:
                            with get_details:
                                with resolve:
                                    with patch.object(nudge, "apply_resolution"):
                                        continue_rebase = patch.object(
                                            nudge.git, "continue_rebase", return_value=True
                                        )
                                        with continue_rebase:
                                            result = nudge.rebase("main", auto_resolve=True)

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
