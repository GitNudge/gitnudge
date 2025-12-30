"""Command-line interface for GitNudge."""

from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table

from gitnudge import __version__
from gitnudge.config import CONFIG_FILE, Config, ConfigError
from gitnudge.core import GitNudge, GitNudgeError
from gitnudge.git import GitError, RebaseState

console = Console()
error_console = Console(stderr=True)


def get_console(config: Config | None = None) -> Console:
    """Get console with color settings applied."""
    if config and not config.ui.color:
        return Console(force_terminal=False, no_color=True)
    return console


@click.group()
@click.version_option(version=__version__)
@click.option("--no-color", is_flag=True, help="Disable colored output")
@click.pass_context
def main(ctx: click.Context, no_color: bool) -> None:
    """GitNudge - AI-Powered Git Rebase Assistant

    Use Claude AI to help with git rebase operations, conflict resolution,
    and understanding complex merges.
    """
    ctx.ensure_object(dict)
    ctx.obj["no_color"] = no_color


@main.command()
@click.argument("target")
@click.option("-i", "--interactive", is_flag=True, help="Start interactive rebase")
@click.option("--auto", is_flag=True, help="Auto-resolve conflicts with AI")
@click.option("--dry-run", is_flag=True, help="Analyze without performing rebase")
@click.pass_context
def rebase(
    ctx: click.Context,
    target: str,
    interactive: bool,
    auto: bool,
    dry_run: bool,
) -> None:
    """Start an AI-assisted rebase onto TARGET.

    Examples:

        gitnudge rebase main

        gitnudge rebase -i HEAD~5

        gitnudge rebase --dry-run main
    """
    try:
        config = Config.load()
        if ctx.obj.get("no_color"):
            config.ui.color = False

        nudge = GitNudge(config)
        cons = get_console(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=cons,
        ) as progress:
            progress.add_task(f"Analyzing rebase onto {target}...", total=None)
            analysis = nudge.analyze(target)

        cons.print()
        cons.print(Panel(
            f"[bold]Branch:[/bold] {analysis.current_branch} → {analysis.target_branch}\n"
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
                    conflict["file"],
                    conflict["commit"],
                    conflict["message"][:50],
                )

            cons.print(table)

        if dry_run:
            cons.print("\n[yellow]Dry run - no changes made[/yellow]")
            return

        if not auto and analysis.potential_conflicts:
            if not click.confirm("\nProceed with rebase?"):
                cons.print("[yellow]Aborted[/yellow]")
                return

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=cons,
        ) as progress:
            progress.add_task("Rebasing...", total=None)
            result = nudge.rebase(target, interactive, auto_resolve=auto)

        if result.success:
            cons.print(f"\n[green]✅ {result.message}[/green]")
        else:
            cons.print(f"\n[yellow]⚠️  {result.message}[/yellow]")

            if result.conflicts:
                cons.print("\n[bold]Conflicted files:[/bold]")
                for conflict_file in result.conflicts:
                    cons.print(f"  • {conflict_file.path}")

                cons.print("\n[dim]Use 'gitnudge resolve' for AI assistance[/dim]")

    except (GitError, GitNudgeError, ConfigError) as e:
        error_console.print(f"[red]Error:[/red] {e}")
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
        config = Config.load()
        if ctx.obj.get("no_color"):
            config.ui.color = False

        nudge = GitNudge(config)
        cons = get_console(config)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=cons,
        ) as progress:
            progress.add_task(f"Analyzing rebase onto {target}...", total=None)
            analysis = nudge.analyze(target)

        cons.print(Panel(
            f"[bold]Current branch:[/bold] {analysis.current_branch}\n"
            f"[bold]Target branch:[/bold] {analysis.target_branch}\n"
            f"[bold]Merge base:[/bold] {analysis.merge_base[:8]}\n"
            f"[bold]Commits to rebase:[/bold] {len(analysis.commits_to_rebase)}",
            title="📊 Rebase Analysis",
        ))

        if analysis.commits_to_rebase:
            table = Table(title="Commits to Rebase")
            table.add_column("SHA", style="yellow", width=8)
            table.add_column("Message", style="white")
            table.add_column("Files", style="dim")

            for commit in analysis.commits_to_rebase[:15]:
                table.add_row(
                    commit.short_sha,
                    commit.message[:60],
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
                    conflict["file"],
                    conflict["commit"],
                    f"Modified in {conflict['message'][:40]}",
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
                f"[bold]Analysis:[/bold]\n{recommendation.explanation}\n\n"
                f"[bold]Suggested Approach:[/bold]\n{recommendation.suggested_approach}",
                title="🤖 AI Recommendation",
            ))

            if recommendation.warnings:
                cons.print("\n[yellow]⚠️  Warnings:[/yellow]")
                for warning in recommendation.warnings:
                    cons.print(f"  • {warning}")

    except (GitError, GitNudgeError, ConfigError) as e:
        error_console.print(f"[red]Error:[/red] {e}")
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
        config = Config.load()
        if ctx.obj.get("no_color"):
            config.ui.color = False

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

        files_to_resolve = conflicted if resolve_all else (
            [Path(file)] if file else [conflicted[0]]
        )

        for conflict_path in files_to_resolve:
            cons.print(f"\n[bold]Analyzing conflict in {conflict_path}...[/bold]")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=cons,
            ) as progress:
                progress.add_task("Getting AI analysis...", total=None)
                resolution = nudge.resolve_conflict(conflict_path)

            if not resolution:
                cons.print(f"[yellow]Could not analyze {conflict_path}[/yellow]")
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
                f"[bold]Explanation:[/bold]\n{resolution.explanation}\n\n"
                f"[bold]Changes:[/bold]\n{resolution.changes_summary}",
                title=f"🤖 Resolution for {conflict_path.name}",
            ))

            if config.behavior.show_previews and not auto:
                cons.print("\n[bold]Resolved content preview:[/bold]")
                syntax = Syntax(
                    resolution.resolved_content[:2000],
                    conflict_path.suffix.lstrip(".") or "text",
                    line_numbers=True,
                )
                cons.print(syntax)

            if auto or click.confirm("\nApply this resolution?"):
                nudge.apply_resolution(resolution)
                cons.print(f"[green]✅ Applied resolution to {conflict_path}[/green]")
            else:
                cons.print("[yellow]Skipped[/yellow]")

        remaining = nudge.git.get_conflicted_files()
        if remaining:
            cons.print(f"\n[yellow]{len(remaining)} conflicts remaining[/yellow]")
        else:
            cons.print("\n[green]All conflicts resolved! Run 'gitnudge continue'[/green]")

    except (GitError, GitNudgeError, ConfigError) as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@main.command("continue")
@click.option("--ai-verify", is_flag=True, help="Verify resolution with AI first")
@click.pass_context
def continue_rebase(ctx: click.Context, ai_verify: bool) -> None:
    """Continue the rebase after resolving conflicts.

    Examples:

        gitnudge continue

        gitnudge continue --ai-verify
    """
    try:
        config = Config.load()
        if ctx.obj.get("no_color"):
            config.ui.color = False

        nudge = GitNudge(config)
        cons = get_console(config)

        result = nudge.continue_rebase(ai_verify)

        if result.success:
            cons.print(f"[green]✅ {result.message}[/green]")
        else:
            cons.print(f"[yellow]⚠️  {result.message}[/yellow]")

            if result.conflicts:
                for conflict in result.conflicts:
                    cons.print(f"  • {conflict.path}")

    except (GitError, GitNudgeError, ConfigError) as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.pass_context
def abort(ctx: click.Context) -> None:
    """Abort the current rebase operation.

    Examples:

        gitnudge abort
    """
    try:
        config = Config.load()
        if ctx.obj.get("no_color"):
            config.ui.color = False

        nudge = GitNudge(config)
        cons = get_console(config)

        if click.confirm("Are you sure you want to abort the rebase?"):
            nudge.abort_rebase()
            cons.print("[green]✅ Rebase aborted[/green]")
        else:
            cons.print("[yellow]Cancelled[/yellow]")

    except (GitError, GitNudgeError, ConfigError) as e:
        error_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current GitNudge status.

    Examples:

        gitnudge status
    """
    try:
        config = Config.load()
        if ctx.obj.get("no_color"):
            config.ui.color = False

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
        cons.print(Panel(
            f"[bold]Branch:[/bold] {status_info['current_branch']}\n"
            f"[bold]Rebase state:[/bold] [{state_color}]{rebase_state}[/{state_color}]\n"
            f"[bold]Config valid:[/bold] {config_valid}",
            title="📋 GitNudge Status",
        ))

        if status_info["conflicted_files"]:
            cons.print("\n[bold]Conflicted files:[/bold]")
            for f in status_info["conflicted_files"]:
                cons.print(f"  • {f}")

    except (GitError, GitNudgeError, ConfigError) as e:
        error_console.print(f"[red]Error:[/red] {e}")
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

        gitnudge config --model claude-sonnet-4-20250514
    """
    cons = console

    if reset:
        if click.confirm("Reset configuration to defaults?"):
            cfg = Config()
            cfg.save()
            cons.print("[green]✅ Configuration reset[/green]")
        return

    if set_key:
        api_key = getpass("Enter your Anthropic API key: ")
        if api_key:
            try:
                cfg = Config.load()
            except ConfigError:
                cfg = Config()
            cfg.api.api_key = api_key
            cfg.save()
            cons.print(f"[green]✅ API key saved to {CONFIG_FILE}[/green]")
        return

    if model:
        try:
            cfg = Config.load()
        except ConfigError:
            cfg = Config()
        cfg.api.model = model
        cfg.save()
        cons.print(f"[green]✅ Model set to {model}[/green]")
        return

    try:
        cfg = Config.load()
    except ConfigError as e:
        cons.print(f"[yellow]Could not load config: {e}[/yellow]")
        cfg = Config()

    masked_key = "****" + cfg.api.api_key[-4:] if cfg.api.api_key else "(not set)"

    cons.print(Panel(
        f"[bold]API Key:[/bold] {masked_key}\n"
        f"[bold]Model:[/bold] {cfg.api.model}\n"
        f"[bold]Max Tokens:[/bold] {cfg.api.max_tokens}\n\n"
        f"[bold]Auto Stage:[/bold] {cfg.behavior.auto_stage}\n"
        f"[bold]Show Previews:[/bold] {cfg.behavior.show_previews}\n"
        f"[bold]Max Context Lines:[/bold] {cfg.behavior.max_context_lines}\n\n"
        f"[bold]Color:[/bold] {cfg.ui.color}\n"
        f"[bold]Verbosity:[/bold] {cfg.ui.verbosity}\n\n"
        f"[dim]Config file: {CONFIG_FILE}[/dim]",
        title="⚙️  Configuration",
    ))

    errors = cfg.validate()
    if errors:
        cons.print("\n[yellow]⚠️  Configuration issues:[/yellow]")
        for error in errors:
            cons.print(f"  • {error}")


if __name__ == "__main__":
    main()
