"""
Display utilities — Rich-powered terminal output for Debug2Learn Game Edition.

Provides consistent, game-themed terminal formatting for all 6 agents:
🧭 Explorer, 🔐 Decoder, 🧩 Solver, 🎯 Tracker, 📚 Librarian, 👑 Master.
Ensures code tokens like '[x]' are properly escaped and preserved across displays.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Custom theme for Debug2Learn
THEME = Theme({
    "info": "cyan",
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "master": "bold magenta",
    "developer": "bold cyan",
    "hint": "italic yellow",
    "step": "bold magenta",
    "concept": "italic green",
})

console = Console(theme=THEME)


def print_banner():
    """Print the Debug2Learn game banner."""
    title_text = Text()
    title_text.append("🎮 DEBUG2LEARN ", style="bold bright_white on magenta")
    title_text.append(" — AI Debugging Quest & Mentor\n", style="bold cyan")
    title_text.append("Level up your debugging skills with 6 specialized AI companions:", style="dim")
    
    agents_table = Table.grid(padding=(0, 2))
    agents_table.add_column(style="bold")
    agents_table.add_column(style="dim")
    
    agents_table.add_row("🧭 Explorer", "Scans & maps relevant project files")
    agents_table.add_row("🔐 Decoder", "Decodes bug reports & tracebacks without sanitizing tokens")
    agents_table.add_row("🧩 Solver", "Diagnoses root cause & plans debugging quest")
    agents_table.add_row("🎯 Tracker", "Monitors & evaluates code changes")
    agents_table.add_row("📚 Librarian", "Dispatches curated docs & concept resources")
    agents_table.add_row("👑 Master", "Guides you with Socratic questions & hints")

    console.print()
    console.print(Panel(
        agents_table,
        title=title_text,
        title_align="center",
        border_style="magenta",
        padding=(1, 2),
    ))


def print_success(message: str):
    console.print(f"  [success]✓[/success] {escape(str(message))}")


def print_error(message: str):
    console.print(f"  [error]✗[/error] {escape(str(message))}")


def print_warning(message: str):
    console.print(f"  [warning]⚠[/warning] {escape(str(message))}")


def print_info(message: str):
    console.print(f"  [info]ℹ[/info] {escape(str(message))}")


def print_agent_action(agent_name: str, emoji: str, action: str, color: str = "cyan"):
    """Display an agent action notification."""
    console.print(f"  [{color}]{emoji} [{agent_name}][/{color}] {escape(str(action))}")


def print_step(step_num: int, title: str, description: str = ""):
    """Print a debugging step."""
    console.print(f"\n  [step]Quest Step {step_num}:[/step] [bold]{escape(title)}[/bold]")
    if description:
        console.print(f"    {escape(description)}", style="dim")


def print_master(message: str, title: str = "👑 Master"):
    """Print a Master message in a styled panel."""
    console.print()
    console.print(Panel(
        Markdown(message),
        title=title,
        title_align="left",
        border_style="magenta",
        padding=(1, 2),
    ))


# Backwards compatibility
def print_teacher(message: str):
    print_master(message)


def print_hint(message: str, level: str = ""):
    """Print a progressive hint."""
    level_labels = {
        "conceptual": ("💭", "Level 1: Nudge"),
        "directional": ("🧭", "Level 2: Clue"),
        "specific": ("🔍", "Level 3: Direct Clue"),
        "very_specific": ("🎯", "Level 3: Direct Clue"),
    }
    emoji, label = level_labels.get(level, ("💡", "Hint"))
    console.print()
    console.print(Panel(
        Markdown(message),
        title=f"{emoji} {label}",
        title_align="left",
        border_style="yellow",
        padding=(1, 2),
    ))


def print_diff(diff_text: str):
    """Display a colored diff."""
    if not diff_text.strip():
        return
    syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=False)
    console.print(Panel(syntax, title="🎯 Code Changes", border_style="green", padding=(0, 1)))


def print_changes(changes: list[Any]):
    """Print detected code changes in a table."""
    if not changes:
        console.print("  [dim]No changes detected in relevant files.[/dim]")
        return

    table = Table(show_header=True, border_style="green", padding=(0, 1))
    table.add_column("File", style="cyan")
    table.add_column("Change", style="yellow")
    table.add_column("Symbol / Description", style="green")

    for c in changes:
        if hasattr(c, "file_path"):
            table.add_row(
                str(c.file_path),
                str(getattr(c.change_type, "value", c.change_type)),
                str(c.symbol or c.description or "—"),
            )
        elif isinstance(c, dict):
            table.add_row(
                c.get("file_path", ""),
                c.get("change_type", ""),
                c.get("symbol", "—"),
            )

    console.print(table)


def print_resources(resources: list[Any]):
    """Print learning resources from the Librarian."""
    if not resources:
        return

    table = Table(title="📚 Librarian's Reading Desk", border_style="blue", show_header=True)
    table.add_column("Resource", style="bold white")
    table.add_column("Concept / Relevance", style="dim")
    table.add_column("URL", style="cyan")

    for r in resources:
        table.add_row(
            getattr(r, "title", "Resource"),
            getattr(r, "relevance", getattr(r, "concept", "")),
            getattr(r, "url", ""),
        )

    console.print()
    console.print(table)


def print_plan_overview(plan: Any):
    """Print a debugging plan overview with clear failure vs root-cause separation."""
    console.print()
    
    parts = []
    if getattr(plan, "failure_location", None):
        parts.append(f"[bold]Failure Detected By:[/bold] {escape(plan.failure_location)}")
    
    root_loc = getattr(plan, "root_cause_location", None) or plan.bug_location
    parts.append(f"[bold]Suspected Root Cause:[/bold] {escape(root_loc)}")
    
    if getattr(plan, "relevant_logic", None):
        parts.append(f"[bold]Relevant Logic:[/bold] {escape(plan.relevant_logic)}")
        
    parts.append(f"[bold]Hypothesis:[/bold] {escape(plan.hypothesis)}")
    parts.append(f"[bold]Core Concept:[/bold] {escape(plan.concept)}")
    parts.append(f"[bold]Confidence:[/bold] {int(getattr(plan, 'confidence', 0.8) * 100)}%")
    parts.append(f"[bold]Total Steps:[/bold] {len(plan.steps)}")

    body = "\n".join(parts)
    console.print(Panel(
        body,
        title="🧩 Solver's Debugging Plan",
        title_align="left",
        border_style="cyan",
        padding=(1, 2),
    ))

    for step in plan.steps:
        status_icon = "✓" if getattr(step, "completed", False) else "○"
        console.print(f"  [dim]{status_icon}[/dim] [bold]Step {step.step_number}:[/bold] {escape(step.title)}")


def prompt_input(prompt_text: str = "Your move") -> str:
    """Prompt user for interactive input."""
    console.print()
    return console.input(f"  [developer]💬 {prompt_text}:[/developer] ")


def print_test_summary(result: Any):
    """Display test validation summary panel."""
    passed = getattr(result, "passed", 0)
    failed = getattr(result, "failed", 0)
    errors = getattr(result, "errors", 0)
    total = getattr(result, "total", passed + failed + errors)
    all_passed = getattr(result, "all_passed", (failed == 0 and errors == 0 and passed > 0))

    if all_passed:
        title = "🧪 Test Validation: PASSED"
        style = "green"
        summary_text = f"[bold green]✓ All tests passed ({passed}/{total})[/bold green]\n"
    else:
        title = "🧪 Test Validation: FAILED"
        style = "red"
        summary_text = f"[bold red]✗ Failures detected: {failed} failed, {passed} passed, {errors} errors (total {total})[/bold red]\n"

    stdout = getattr(result, "stdout", "")
    if stdout:
        truncated_out = stdout if len(stdout) < 1000 else stdout[:1000] + "\n... [truncated]"
        summary_text += f"\n[dim]{escape(truncated_out)}[/dim]"

    console.print()
    console.print(Panel(
        summary_text,
        title=title,
        title_align="left",
        border_style=style,
        padding=(1, 2),
    ))

