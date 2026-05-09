"""pii-scanner CLI — single-scan interface to pii-scanner.

Bypasses authentication, persistence, retention, and database access.
Reads the broker list directly from brokers/brokers.json and calls
the agent orchestration layer without any web or DB infrastructure.

Requires only OPENAI_API_KEY (and optionally OPENAI_MODEL) in the
environment or .env.cli file.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()

_BROKERS_PATH = Path(sys.prefix) / "share" / "pii-scanner" / "brokers.json"


def _load_brokers() -> list[dict]:
    """Load broker list from brokers/brokers.json."""
    if not _BROKERS_PATH.exists():
        console.print(f"[red]Brokers file not found: {_BROKERS_PATH}[/red]")
        sys.exit(1)
    raw = json.loads(_BROKERS_PATH.read_text(encoding="utf-8"))
    return raw["brokers"]


def _get_settings():
    """Load CLI settings and bridge OPENAI_API_KEY to os.environ for the SDK."""
    from src.core.config import get_cli_settings

    try:
        settings = get_cli_settings()
    except Exception as e:
        console.print(f"[red]Failed to load settings: {e}[/red]")
        console.print("[dim]Ensure .env.cli exists with OPENAI_API_KEY set.[/dim]")
        sys.exit(1)

    os.environ.setdefault(
        "OPENAI_API_KEY", settings.openai_api_key.get_secret_value()
    )
    return settings


@click.group()
def cli():
    """pii-scanner — scan data broker sites for your PII."""


@cli.group()
def brokers():
    """Manage and inspect supported data brokers."""


@brokers.command("list")
def brokers_list():
    """List all supported data brokers."""
    all_brokers = _load_brokers()

    table = Table(title="Supported Brokers")
    table.add_column("Name", style="bold")
    table.add_column("Search URL", style="dim")
    for b in all_brokers:
        table.add_row(b["name"], b["search_url"])

    console.print(table)


@cli.command()
@click.option("--email", default=None, help="Email address to search for.")
@click.option("--phone", default=None, help="Phone number to search for.")
@click.option("--name", default=None, help="Full name to search for.")
@click.option("--address", default=None, help="Street address to search for.")
@click.option(
    "--broker",
    "broker_keys",
    multiple=True,
    help="Broker key to scan (repeatable). Omit to scan all.",
)
def scan(email, phone, name, address, broker_keys):
    """Run a single PII scan against data brokers."""
    identity: dict[str, str] = {}
    if email:
        identity["email"] = email
    if phone:
        identity["phone"] = phone
    if name:
        identity["name"] = name
    if address:
        identity["address"] = address

    if not identity:
        console.print(
            "[red]Provide at least one identity field"
            " (--email, --phone, --name, --address).[/red]"
        )
        sys.exit(1)

    settings = _get_settings()

    all_brokers = _load_brokers()
    if broker_keys:
        selected = [b for b in all_brokers if b["key"] in broker_keys]
        unknown = set(broker_keys) - {b["key"] for b in all_brokers}
        if unknown:
            console.print(
                f"[red]Unknown broker keys: {', '.join(sorted(unknown))}[/red]"
            )
            sys.exit(1)
    else:
        selected = all_brokers

    # Consent prompt
    console.print()
    console.print("[bold red]  ⚠  Before we scan[/bold red]")
    console.print()
    console.print(
        "  [yellow]To check if your data appears on these broker"
        " sites, your identity[/yellow]\n"
        "  [yellow]fields will be submitted to each selected"
        " broker's search page.[/yellow]"
    )
    console.print()
    console.print("  [blue]This means:[/blue]")
    console.print()
    console.print(
        "    [cyan]->[/cyan] Your identity fields will be sent"
        " to each broker's website"
    )
    console.print(
        "    [cyan]->[/cyan] The broker will see the search query"
        " and may log it"
    )
    console.print(
        "    [cyan]->[/cyan] We check the results for your data"
        " and discard the response"
    )
    console.print()
    console.print(
        "  [green bold]Nothing is stored.[/green bold] The broker receives"
    )
    console.print(
        "  only what you would enter if you searched their site manually."
    )
    console.print()

    timeout_minutes = -(-settings.agent_timeout_seconds // 60)
    unit = "minute" if timeout_minutes == 1 else "minutes"
    console.print(
        f"  [dim]Scans can take up to {timeout_minutes} {unit} per broker.[/dim]"
    )
    console.print()

    answer = (
        console.input("[bold yellow]  Proceed? (y/n): [/bold yellow]")
        .strip()
        .lower()
    )
    if answer not in ("y", "yes"):
        console.print("Scan cancelled.")
        sys.exit(0)

    asyncio.run(_scan(identity, selected, settings))


async def _scan(identity: dict[str, str], broker_list: list[dict], settings):
    import time

    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    from src.models.scan import AuditAgentResult
    from src.services.audit.orchestrator import stream_audit_agents

    console.print()
    fields = ", ".join(f"[cyan]{k}[/cyan]" for k in identity)
    console.print(f"  Scanning for: {fields}")
    names = ", ".join(b["name"] for b in broker_list)
    console.print(f"  Brokers: {names}")
    console.print()

    results: list[AuditAgentResult] = []
    start = time.monotonic()

    with Progress(
        TextColumn("[bold cyan]Scanning..."),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.fields[status]}"),
        console=console,
    ) as progress:
        task = progress.add_task("scan", total=len(broker_list), status="")
        async for r in stream_audit_agents(
            identity=identity,
            brokers=broker_list,
            settings=settings,
        ):
            results.append(r)
            progress.update(
                task, advance=1, status=f"[dim]{r.name} completed[/dim]"
            )

    # Display results: violations first, then clear, then incomplete
    console.print()
    violations: list[str] = []
    clear_lines: list[str] = []
    incomplete_lines: list[str] = []
    for r in results:
        if r.message:
            found_fields = [
                m.identity_field for m in r.matched_inputs if m.found
            ]
            if found_fields:
                icon = "[red bold]!![/red bold]"
                detail = (
                    f"[red bold]PII DETECTED:[/red bold]"
                    f" {', '.join(found_fields)}"
                    f" [yellow]({r.message})[/yellow]"
                )
                violations.append(
                    f"  {icon} [bold]{r.name}[/bold] — {detail}"
                )
                continue
            icon = "[yellow]![/yellow]"
            detail = f"[yellow]{r.message}[/yellow]"
            incomplete_lines.append(
                f"  {icon} [bold]{r.name}[/bold] — {detail}"
            )
        elif r.matched_inputs and any(m.found for m in r.matched_inputs):
            icon = "[red bold]!![/red bold]"
            found = [m.identity_field for m in r.matched_inputs if m.found]
            detail = (
                f"[red bold]PII DETECTED:[/red bold] {', '.join(found)}"
            )
            violations.append(
                f"  {icon} [bold]{r.name}[/bold] — {detail}"
            )
        else:
            icon = "[green]✓[/green]"
            detail = "[green]clear[/green]"
            clear_lines.append(
                f"  {icon} [bold]{r.name}[/bold] — {detail}"
            )

    for line in violations + clear_lines + incomplete_lines:
        console.print(line)

    # Summary
    console.print()
    violation_count = sum(
        sum(1 for m in r.matched_inputs if m.found) for r in results
    )
    clear_count = len(clear_lines)
    incomplete_count = len(incomplete_lines)

    table = Table(title="Scan Summary")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")
    table.add_row("[red]Violations[/red]", str(violation_count))
    table.add_row("[green]Clear[/green]", str(clear_count))
    table.add_row("[yellow]Incomplete[/yellow]", str(incomplete_count))
    table.add_section()
    table.add_row("Total brokers scanned", str(len(results)))
    console.print(table)

    elapsed = time.monotonic() - start
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    if minutes > 0:
        m_label = "minutes" if minutes != 1 else "minute"
        s_label = "seconds" if seconds != 1 else "second"
        console.print(
            f"  Scan completed in {minutes} {m_label} {seconds} {s_label}."
        )
    else:
        s_label = "seconds" if seconds != 1 else "second"
        console.print(f"  Scan completed in {seconds} {s_label}.")
    console.print()
