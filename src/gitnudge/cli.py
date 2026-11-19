"""Command-line interface for GitNudge."""

from __future__ import annotations

import logging
import os
import sys
from getpass import getpass
from pathlib import Path

import click
from pydantic import ValidationError
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

from gitnudge import __version__
from gitnudge.ai import AIError
from gitnudge.config import Config, ConfigError, default_config_path
from gitnudge.core import GitNudge, GitNudgeError
from gitnudge.git import GitError, RebaseState
from gitnudge.logging_utils import set_log_level

console = Console()
error_console = Console(stderr=True)

HANDLED_ERRORS = (GitError, GitNudgeError, ConfigError, AIError)


def _e(value: object) -> str:
    """Escape dynamic text for safe rich markup output."""
    return escape(str(value))


def _quiet(config: Config) -> bool:
    """Return True when output should be minimal."""
    return config.ui.verbosity == "quiet"


def _apply_verbosity(config: Config) -> None:
    """Map ui.verbosity onto gitnudge log levels."""
    if config.ui.verbosity == "verbose":
        env_level = os.environ.get("GITNUDGE_LOG_LEVEL", "").upper()
        set_log_level(logging.DEBUG if env_level == "DEBUG" else logging.INFO)
    elif config.ui.verbosity == "quiet":
        set_log_level(logging.ERROR)


def _cwd_path(file: str) -> Path:
    """Resolve a user-supplied path relative to the current directory."""
    p = Path(file)
    return p if p.is_absolute() else Path.cwd() / p


def get_console(config: Config | None = None) -> Console:
    """Get console with color settings applied."""
    if config and not config.ui.color:
        return Console(force_terminal=False, no_color=True)
    return console


@click.group()
@click.version_option(version=__version__)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.option("-v", "--verbose", is_flag=True, help="Verbose output (sets verbosity=verbose)")
@click.option("-q", "--quiet", is_flag=True, help="Quiet output (sets verbosity=quiet)")
@click.pass_context
def main(ctx: click.Context, no_color: bool, verbose: bool, quiet: bool) -> None:
    """GitNudge - AI-Powered Git Rebase Assistant

    Use Claude AI to help with git rebase operations, conflict resolution,
    and understanding complex merges.
    """
    if verbose and quiet:
        error_console.print("[red]Error:[/red] --verbose and --quiet are mutually exclusive")
        sys.exit(2)

    ctx.ensure_object(dict)
    ctx.obj["no_color"] = no_color
    ctx.obj["verbosity"] = "verbose" if verbose else ("quiet" if quiet else None)


def _apply_cli_overrides(ctx: click.Context, config: Config) -> Config:
    """Apply global CLI flags onto the loaded config."""
    if ctx.obj.get("no_color"):
        config.ui.color = False
    if not config.ui.color:
        error_console.no_color = True
    verbosity = ctx.obj.get("verbosity")
    if verbosity:
        config.ui.verbosity = verbosity
    _apply_verbosity(config)
    return config


@main.command()
@click.argument("target")
@click.option("-i", "--interactive", is_flag=True, help="Start interactive rebase")
@click.option(
    "--auto", is_flag=True,
    help="Auto-resolve conflicts with AI (also enabled by behavior.auto_resolve)",
)
@click.option("--dry-run", is_flag=True, help="Analyze without performing rebase")
@click.option("--force", is_flag=True, help="Skip pre-flight safety checks (NOT recommended)")
@click.pass_context
def rebase(
    ctx: click.Context,
    target: str,
    interactive: bool,
    auto: bool,
    dry_run: bool,
    force: bool,
) -> None:
    """Start an AI-assisted rebase onto TARGET.

    Examples:

        gitnudge rebase main

        gitnudge rebase -i HEAD~5

        gitnudge rebase --dry-run main
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)
        auto = auto or config.behavior.auto_resolve

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=cons,
            disable=_quiet(config),
        ) as progress:
            progress.add_task(f"Analyzing rebase onto {_e(target)}...", total=None)
            analysis = nudge.analyze(target)

        cons.print()
        cons.print(Panel(
            f"[bold]Branch:[/bold] {_e(analysis.current_branch)} → "
            f"{_e(analysis.target_branch)}\n"
            f"[bold]Commits to rebase:[/bold] {len(analysis.commits_to_rebase)}\n"
            f"[bold]Potential conflicts:[/bold] {len(analysis.potential_conflicts)}",
            title="📊 Rebase Analysis",
        ))

        if analysis.potential_conflicts:
            table = Table(title="Potential Conflicts")
            table.add_column("File", style="cyan")
            table.add_column("Commit", style="yellow")
            table.add_column("Message", style="white")

            for conflict in analysis.potential_conflicts[:10]:
                table.add_row(
                    _e(conflict["file"]),
                    _e(conflict["commit"]),
                    _e(conflict["message"][:50]),
                )

            cons.print(table)

        if dry_run:
            cons.print("\n[yellow]Dry run - no changes made[/yellow]")
            return

        if not auto and analysis.potential_conflicts:
            if not click.confirm("\nProceed with rebase?"):
                cons.print("[yellow]Aborted[/yellow]")
                return

        if interactive:
            result = nudge.rebase(
                target, interactive, auto_resolve=auto, dry_run=dry_run, force=force
            )
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=cons,
                disable=_quiet(config),
            ) as progress:
                progress.add_task("Rebasing...", total=None)
                result = nudge.rebase(
                    target, interactive, auto_resolve=auto, dry_run=dry_run, force=force
                )

        if result.safety_sha:
            cons.print(f"\n[dim]Safety: pre-rebase HEAD = {_e(result.safety_sha[:12])}[/dim]")
            cons.print(
                f"[dim]Recover with: git reset --hard {_e(result.safety_sha[:12])}[/dim]"
            )

        if result.success:
            cons.print(f"\n[green]✅ {_e(result.message)}[/green]")
        else:
            cons.print(f"\n[yellow]⚠️  {_e(result.message)}[/yellow]")

            if result.conflicts:
                cons.print("\n[bold]Conflicted files:[/bold]")
                for conflict_file in result.conflicts:
                    cons.print(f"  • {_e(conflict_file.path)}")

                cons.print("\n[dim]Use 'gitnudge resolve' for AI assistance[/dim]")

        if result.applied_resolutions:
            cons.print("\n[bold]AI-resolved conflicts:[/bold]")
            for entry in result.applied_resolutions:
                summary = entry.get("summary") or "(no summary)"
                cons.print(
                    f"  • [cyan]{_e(entry['file'])}[/cyan] "
                    f"[dim]({_e(entry.get('confidence', '?'))})[/dim] — {_e(summary)}"
                )

        for w in result.warnings:
            cons.print(f"[yellow]⚠️  {_e(w)}[/yellow]")

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.argument("target")
@click.option("--detailed", is_flag=True, help="Show detailed analysis")
@click.pass_context
def analyze(ctx: click.Context, target: str, detailed: bool) -> None:
    """Analyze potential conflicts before rebasing onto TARGET.

    Examples:

        gitnudge analyze main

        gitnudge analyze --detailed feature-branch
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=cons,
            disable=_quiet(config),
        ) as progress:
            progress.add_task(f"Analyzing rebase onto {_e(target)}...", total=None)
            analysis = nudge.analyze(target)

        if not analysis.has_merge_base:
            cons.print(Panel(
                f"[red]No common ancestor between {_e(analysis.current_branch)} "
                f"and {_e(analysis.target_branch)}.[/red]\n"
                "Refusing to analyze unrelated histories.",
                title="📊 Rebase Analysis",
            ))
            return

        status_line = ""
        if analysis.is_up_to_date:
            status_line = "\n[green]Already up to date with target.[/green]"
        elif analysis.is_fast_forward:
            status_line = "\n[cyan]Fast-forward possible (no rewrite needed).[/cyan]"

        cons.print(Panel(
            f"[bold]Current branch:[/bold] {_e(analysis.current_branch)}\n"
            f"[bold]Target branch:[/bold] {_e(analysis.target_branch)}\n"
            f"[bold]Merge base:[/bold] {_e(analysis.merge_base[:8])}\n"
            f"[bold]Commits to rebase:[/bold] {len(analysis.commits_to_rebase)}"
            f"{status_line}",
            title="📊 Rebase Analysis",
        ))

        if analysis.commits_to_rebase:
            table = Table(title="Commits to Rebase")
            table.add_column("SHA", style="yellow", width=8)
            table.add_column("Message", style="white")
            table.add_column("Files", style="dim")

            for commit in analysis.commits_to_rebase[:15]:
                table.add_row(
                    _e(commit.short_sha),
                    _e(commit.message[:60]),
                    str(len(commit.files_changed)),
                )

            if len(analysis.commits_to_rebase) > 15:
                table.add_row("...", f"({len(analysis.commits_to_rebase) - 15} more)", "")

            cons.print(table)

        if analysis.potential_conflicts:
            table = Table(title="⚠️  Potential Conflicts")
            table.add_column("File", style="cyan")
            table.add_column("Commit", style="yellow")
            table.add_column("Reason", style="white")

            for conflict in analysis.potential_conflicts[:15]:
                table.add_row(
                    _e(conflict["file"]),
                    _e(conflict["commit"]),
                    f"Modified in {_e(conflict['message'][:40])}",
                )

            cons.print(table)
        else:
            cons.print("\n[green]✅ No obvious conflicts detected[/green]")

        if detailed:
            cons.print()
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=cons,
                disable=_quiet(config),
            ) as progress:
                progress.add_task("Getting AI recommendation...", total=None)
                recommendation = nudge.get_ai_recommendation(target)

            risk_color = {
                "low": "green",
                "medium": "yellow",
                "high": "red",
            }.get(recommendation.risk_level, "white")

            risk_level_text = recommendation.risk_level.upper()
            cons.print(Panel(
                f"[bold]Proceed:[/bold] {'Yes' if recommendation.should_proceed else 'No'}\n"
                f"[bold]Risk Level:[/bold] [{risk_color}]{risk_level_text}[/{risk_color}]\n\n"
                f"[bold]Analysis:[/bold]\n{_e(recommendation.explanation)}\n\n"
                f"[bold]Suggested Approach:[/bold]\n{_e(recommendation.suggested_approach)}",
                title="🤖 AI Recommendation",
            ))

            if recommendation.warnings:
                cons.print("\n[yellow]⚠️  Warnings:[/yellow]")
                for warning in recommendation.warnings:
                    cons.print(f"  • {_e(warning)}")

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.argument("file", required=False)
@click.option("--auto", is_flag=True, help="Auto-apply AI resolution")
@click.option("--all", "resolve_all", is_flag=True, help="Resolve all conflicts")
@click.pass_context
def resolve(
    ctx: click.Context,
    file: str | None,
    auto: bool,
    resolve_all: bool,
) -> None:
    """Get AI help resolving conflicts.

    Examples:

        gitnudge resolve

        gitnudge resolve src/utils.py

        gitnudge resolve --auto --all
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        state = nudge.git.get_rebase_state()
        if state == RebaseState.NONE:
            cons.print("[yellow]No rebase in progress[/yellow]")
            return

        conflicted = nudge.git.get_conflicted_files()
        if not conflicted:
            cons.print("[green]No conflicts to resolve[/green]")
            return

        if resolve_all:
            files_to_resolve = conflicted
        elif file:
            requested = _cwd_path(file)
            try:
                requested_resolved = requested.resolve()
            except OSError:
                requested_resolved = requested
            conflicted_resolved = {c.resolve() for c in conflicted}
            if requested_resolved not in conflicted_resolved:
                error_console.print(
                    f"[red]Error:[/red] {_e(file)} is not in the conflicted file list. "
                    f"Run 'gitnudge status' to see current conflicts."
                )
                sys.exit(1)
            files_to_resolve = [requested]
        else:
            files_to_resolve = [conflicted[0]]

        failures = 0
        for conflict_path in files_to_resolve:
            cons.print(f"\n[bold]Analyzing conflict in {_e(conflict_path)}...[/bold]")

            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=cons,
                    disable=_quiet(config),
                ) as progress:
                    progress.add_task("Getting AI analysis...", total=None)
                    resolution = nudge.resolve_conflict(conflict_path)
            except (GitNudgeError, AIError) as e:
                failures += 1
                error_console.print(f"[red]Error:[/red] {_e(e)}")
                continue

            if not resolution:
                cons.print(f"[yellow]Could not analyze {_e(conflict_path)}[/yellow]")
                continue

            confidence_color = {
                "high": "green",
                "medium": "yellow",
                "low": "red",
            }.get(resolution.confidence, "white")

            confidence_text = resolution.confidence.upper()
            confidence_line = (
                f"[bold]Confidence:[/bold] [{confidence_color}]{confidence_text}"
                f"[/{confidence_color}]\n\n"
            )
            cons.print(Panel(
                f"{confidence_line}"
                f"[bold]Explanation:[/bold]\n{_e(resolution.explanation)}\n\n"
                f"[bold]Changes:[/bold]\n{_e(resolution.changes_summary)}",
                title=f"🤖 Resolution for {_e(conflict_path.name)}",
            ))

            if config.behavior.show_previews and not auto:
                cons.print("\n[bold]Resolved content preview:[/bold]")
                syntax = Syntax(
                    resolution.resolved_content[:2000],
                    conflict_path.suffix.lstrip(".") or "text",
                    line_numbers=True,
                )
                cons.print(syntax)
                total_chars = len(resolution.resolved_content)
                if total_chars > 2000:
                    cons.print(
                        f"[dim](preview shows the first 2000 of {total_chars} characters)[/dim]"
                    )

            if auto and resolution.confidence == "low":
                cons.print(
                    f"[yellow]Skipped {_e(conflict_path)}: low-confidence resolution. "
                    "Run without --auto to review it.[/yellow]"
                )
                continue

            if auto or click.confirm("\nApply this resolution?"):
                nudge.apply_resolution(resolution)
                cons.print(f"[green]✅ Applied resolution to {_e(conflict_path)}[/green]")
            else:
                cons.print("[yellow]Skipped[/yellow]")

        remaining = nudge.git.get_conflicted_files()
        if remaining:
            cons.print(f"\n[yellow]{len(remaining)} conflicts remaining[/yellow]")
        else:
            cons.print("\n[green]All conflicts resolved! Run 'gitnudge continue'[/green]")
        if failures:
            sys.exit(1)

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.argument("file", required=False)
@click.pass_context
def explain(ctx: click.Context, file: str | None) -> None:
    """Ask Claude to explain a conflict in plain language.

    Examples:

        gitnudge explain

        gitnudge explain src/utils.py
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        state = nudge.git.get_rebase_state()
        if state == RebaseState.NONE:
            cons.print("[yellow]No rebase in progress[/yellow]")
            return

        conflicted = nudge.git.get_conflicted_files()
        if not conflicted:
            cons.print("[green]No conflicts to explain[/green]")
            return

        if file:
            target_file = _cwd_path(file)
            try:
                target_resolved = target_file.resolve()
            except OSError:
                target_resolved = target_file
            conflicted_resolved = {c.resolve() for c in conflicted}
            if target_resolved not in conflicted_resolved:
                error_console.print(
                    f"[red]Error:[/red] {_e(file)} is not in the conflicted file list."
                )
                sys.exit(1)
        else:
            target_file = conflicted[0]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=cons,
            disable=_quiet(config),
        ) as progress:
            progress.add_task(f"Asking Claude about {_e(target_file.name)}...", total=None)
            explanation = nudge.explain_conflict(target_file)

        cons.print(Panel(_e(explanation), title=f"🤖 Conflict in {_e(target_file.name)}"))

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command("continue")
@click.option(
    "--ai-verify",
    is_flag=True,
    help="Refuse to continue if any staged file still contains conflict markers",
)
@click.pass_context
def continue_rebase(ctx: click.Context, ai_verify: bool) -> None:
    """Continue the rebase after resolving conflicts.

    Examples:

        gitnudge continue

        gitnudge continue --ai-verify
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        result = nudge.continue_rebase(ai_verify)

        if result.success:
            cons.print(f"[green]✅ {_e(result.message)}[/green]")
        else:
            cons.print(f"[yellow]⚠️  {_e(result.message)}[/yellow]")

            if result.conflicts:
                for conflict in result.conflicts:
                    cons.print(f"  • {_e(conflict.path)}")

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.pass_context
def skip(ctx: click.Context) -> None:
    """Skip the current commit during a rebase.

    Examples:

        gitnudge skip
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        if not click.confirm("Skip the current commit?"):
            cons.print("[yellow]Cancelled[/yellow]")
            return

        result = nudge.skip_rebase()
        if result.success:
            cons.print(f"[green]✅ {_e(result.message)}[/green]")
        else:
            cons.print(f"[yellow]⚠️  {_e(result.message)}[/yellow]")
            if result.conflicts:
                for conflict in result.conflicts:
                    cons.print(f"  • {_e(conflict.path)}")

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.pass_context
def recover(ctx: click.Context) -> None:
    """Show how to recover the pre-rebase state.

    Examples:

        gitnudge recover
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        info = nudge.get_recovery_info()
        snapshot = info.get("snapshot")

        if snapshot:
            head = str(snapshot.get("head", "?"))
            cons.print(Panel(
                f"[bold]Pre-rebase HEAD:[/bold] {_e(head)}\n"
                f"[bold]Branch:[/bold] {_e(snapshot.get('branch', '?'))}\n"
                f"[bold]Target:[/bold] {_e(snapshot.get('target', '?'))}\n\n"
                f"[bold]Recover with:[/bold]\n"
                f"  git reset --hard {_e(head[:12])}",
                title="🛟  Recovery Snapshot",
            ))
        else:
            cons.print("[yellow]No GitNudge snapshot found[/yellow]")

        cons.print("\n[bold]Recent reflog (last 20):[/bold]")
        cons.print(_e(info.get("reflog", "").strip() or "(empty)"))

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.pass_context
def abort(ctx: click.Context) -> None:
    """Abort the current rebase operation.

    Examples:

        gitnudge abort
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        if click.confirm("Are you sure you want to abort the rebase?"):
            nudge.abort_rebase()
            cons.print("[green]✅ Rebase aborted[/green]")
        else:
            cons.print("[yellow]Cancelled[/yellow]")

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current GitNudge status.

    Examples:

        gitnudge status
    """
    try:
        config = _apply_cli_overrides(ctx, Config.load())

        nudge = GitNudge(config)
        cons = get_console(config)

        status_info = nudge.get_status()

        state_color = {
            "none": "green",
            "in_progress": "yellow",
            "conflict": "red",
            "stopped": "yellow",
        }.get(status_info["rebase_state"], "white")

        rebase_state = status_info['rebase_state']
        config_valid = '✅' if status_info['config_valid'] else '❌'

        body = (
            f"[bold]Branch:[/bold] {_e(status_info['current_branch'])}\n"
            f"[bold]Rebase state:[/bold] [{state_color}]{_e(rebase_state)}[/{state_color}]\n"
            f"[bold]Config valid:[/bold] {config_valid}"
        )

        progress_info = status_info.get("progress")
        if progress_info:
            body += (
                f"\n[bold]Progress:[/bold] commit "
                f"{progress_info['current']}/{progress_info['total']}"
            )
            if progress_info.get("subject"):
                body += f"\n[bold]Applying:[/bold] {_e(progress_info['subject'][:80])}"

        safety = status_info.get("safety_sha")
        if safety:
            body += f"\n[bold]Safety SHA:[/bold] {_e(safety[:12])} (run 'gitnudge recover')"

        cons.print(Panel(body, title="📋 GitNudge Status"))

        if status_info["conflicted_files"]:
            cons.print("\n[bold]Conflicted files:[/bold]")
            for f in status_info["conflicted_files"]:
                cons.print(f"  • {_e(f)}")

    except HANDLED_ERRORS as e:
        error_console.print(f"[red]Error:[/red] {_e(e)}")
        sys.exit(1)


@main.command()
@click.option("--show", is_flag=True, help="Show current configuration")
@click.option("--set-key", is_flag=True, help="Set API key interactively")
@click.option("--model", help="Set Claude model to use")
@click.option("--reset", is_flag=True, help="Reset to default configuration")
@click.pass_context
def config(
    ctx: click.Context,
    show: bool,
    set_key: bool,
    model: str | None,
    reset: bool,
) -> None:
    """Manage GitNudge configuration.

    Examples:

        gitnudge config --show

        gitnudge config --set-key

        gitnudge config --model claude-sonnet-5-5
    """
    cons = console
    config_path = default_config_path()

    try:
        if reset:
            if click.confirm("Reset configuration to defaults?"):
                cfg = Config()
                cfg.save(config_path)
                cons.print("[green]✅ Configuration reset[/green]")
            return

        if set_key:
            api_key = getpass("Enter your Anthropic API key: ")
            if api_key:
                try:
                    cfg = Config.load(config_path, apply_env=False)
                except ConfigError:
                    cfg = Config()
                cfg.api.api_key = api_key
                cfg.save(config_path)
                cons.print(f"[green]✅ API key saved to {_e(config_path)}[/green]")
                cons.print(
                    "[dim]Note: key is stored in plaintext (file chmod 0600). "
                    "Prefer setting ANTHROPIC_API_KEY env var for shared machines.[/dim]"
                )
            return

        if model:
            try:
                cfg = Config.load(config_path, apply_env=False)
            except ConfigError:
                cfg = Config()
            cfg.api.model = model
            cfg.save(config_path)
            cons.print(f"[green]✅ Model set to {_e(cfg.api.model)}[/green]")
            return
    except ValidationError as e:
        msg = e.errors()[0].get("msg", str(e)) if e.errors() else str(e)
        error_console.print(f"[red]Error:[/red] Invalid value: {_e(msg)}")
        sys.exit(1)
    except OSError as e:
        error_console.print(f"[red]Error:[/red] Could not save config: {_e(e)}")
        sys.exit(1)

    try:
        cfg = Config.load(config_path)
    except ConfigError as e:
        cons.print(f"[yellow]Could not load config: {_e(e)}[/yellow]")
        cfg = Config()

    if cfg.api.api_key:
        suffix = cfg.api.api_key[-4:] if len(cfg.api.api_key) >= 8 else ""
        masked_key = "****" + suffix if suffix else "**** (set)"
    else:
        masked_key = "(not set)"

    cons.print(Panel(
        f"[bold]API Key:[/bold] {_e(masked_key)}\n"
        f"[bold]Model:[/bold] {_e(cfg.api.model)}\n"
        f"[bold]Max Tokens:[/bold] {cfg.api.max_tokens}\n\n"
        f"[bold]Auto Stage:[/bold] {cfg.behavior.auto_stage}\n"
        f"[bold]Show Previews:[/bold] {cfg.behavior.show_previews}\n"
        f"[bold]Max Context Lines:[/bold] {cfg.behavior.max_context_lines}\n"
        f"[bold]Auto Resolve:[/bold] {cfg.behavior.auto_resolve}\n\n"
        f"[bold]Color:[/bold] {cfg.ui.color}\n"
        f"[bold]Verbosity:[/bold] {cfg.ui.verbosity}\n\n"
        f"[dim]Config file: {_e(config_path)}[/dim]",
        title="⚙️  Configuration",
    ))

    errors = cfg.validate()
    if errors:
        cons.print("\n[yellow]⚠️  Configuration issues:[/yellow]")
        for error in errors:
            cons.print(f"  • {_e(error)}")


if __name__ == "__main__":
    main()
