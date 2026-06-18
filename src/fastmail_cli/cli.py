"""Fastmail CLI — interact with the Fastmail JMAP API from the command line."""

from __future__ import annotations

import csv
import enum
import io
import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any, Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from fastmail_cli.client import JMAPClient

app = typer.Typer(
    name="fastmail",
    help="A CLI for interacting with the Fastmail JMAP API.",
    no_args_is_help=True,
)
mail_app = typer.Typer(help="Manage emails.", no_args_is_help=True)
mailbox_app = typer.Typer(help="Manage mailboxes.", no_args_is_help=True)
masked_app = typer.Typer(help="Manage masked email addresses.", no_args_is_help=True)
label_app = typer.Typer(help="Manage labels (keywords) on emails.", no_args_is_help=True, invoke_without_command=True)

migrate_app = typer.Typer(help="Migrate masked emails to another provider.", no_args_is_help=True)
app.add_typer(mail_app, name="mail")
app.add_typer(mailbox_app, name="mailbox")
app.add_typer(masked_app, name="masked")
masked_app.add_typer(migrate_app, name="migrate")
mail_app.add_typer(label_app, name="label")

console = Console()
err_console = Console(stderr=True)


class OutputFormat(str, enum.Enum):
    """Supported output formats for list commands."""
    table = "table"
    json = "json"
    csv = "csv"


# ── Helpers ──────────────────────────────────────────────────────────────


def _get_client() -> JMAPClient:
    """Build a JMAPClient from environment variables."""
    hostname = os.environ.get("FASTMAIL_HOSTNAME", "api.fastmail.com")
    token = os.environ.get("FASTMAIL_TOKEN", "")
    username = os.environ.get("FASTMAIL_USERNAME")

    if not token:
        err_console.print(
            "[bold red]Error:[/] FASTMAIL_TOKEN environment variable is not set.\n"
            "Generate an API token at Settings → Privacy & Security → Manage API tokens."
        )
        raise typer.Exit(code=1)

    return JMAPClient(hostname=hostname, token=token, username=username)


def _format_from(from_list: list[dict] | None) -> str:
    """Format a JMAP 'from' address list into a readable string."""
    if not from_list:
        return "(unknown)"
    parts = []
    for addr in from_list:
        name = addr.get("name", "")
        email = addr.get("email", "")
        parts.append(f"{name} <{email}>" if name else email)
    return ", ".join(parts)


def _emit_output(
    rows: list[dict[str, Any]],
    columns: list[str],
    *,
    fmt: OutputFormat,
    output: Path | None,
    table: Table,
) -> None:
    """Render rows in the requested format and optionally save to a file."""
    if fmt == OutputFormat.table:
        console.print(table)
        if output:
            text_console = Console(file=io.StringIO(), width=200, no_color=True)
            text_console.print(table)
            output.write_text(text_console.file.getvalue())
            console.print(f"[dim]Saved to {output}[/]")
        return

    if fmt == OutputFormat.json:
        filtered = [{col: row.get(col, "") for col in columns} for row in rows]
        data = json.dumps(filtered, indent=2, default=str)
        if output:
            output.write_text(data)
            console.print(f"[dim]Saved JSON to {output}[/]")
        else:
            console.print(data)
        return

    if fmt == OutputFormat.csv:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        data = buf.getvalue()
        if output:
            output.write_text(data)
            console.print(f"[dim]Saved CSV to {output}[/]")
        else:
            console.print(data, highlight=False)
        return


# ── Session / whoami ─────────────────────────────────────────────────────


@app.command()
def whoami() -> None:
    """Show the authenticated account information."""
    client = _get_client()
    session = client.get_session()
    account_id = client.get_account_id()
    accounts = session.get("accounts", {})
    account = accounts.get(account_id, {})

    table = Table(title="Fastmail Account", show_header=False)
    table.add_column("Field", style="bold cyan")
    table.add_column("Value")
    table.add_row("Account ID", account_id)
    table.add_row("Name", account.get("name", "N/A"))
    table.add_row("Username", client.username or "N/A")
    table.add_row("API URL", session.get("apiUrl", "N/A"))
    console.print(table)


# ── Mailbox commands ─────────────────────────────────────────────────────


@mailbox_app.command("list")
def mailbox_list(
    fmt: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Output format: table, json, or csv.")
    ] = OutputFormat.table,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Save output to a file path.")
    ] = None,
) -> None:
    """List all mailboxes."""
    client = _get_client()
    mailboxes = client.get_mailboxes()
    mailboxes.sort(key=lambda m: m.get("sortOrder", 0))

    columns = ["Name", "Role", "Total", "Unread", "ID"]

    table = Table(title="Mailboxes")
    table.add_column("Name", style="bold")
    table.add_column("Role", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Unread", justify="right", style="yellow")
    table.add_column("ID", style="dim")

    rows: list[dict[str, Any]] = []
    for mb in mailboxes:
        row = {
            "Name": mb.get("name", ""),
            "Role": mb.get("role") or "",
            "Total": str(mb.get("totalEmails", 0)),
            "Unread": str(mb.get("unreadEmails", 0)),
            "ID": mb.get("id", ""),
        }
        rows.append(row)
        table.add_row(*[row[c] for c in columns])

    _emit_output(rows, columns, fmt=fmt, output=output, table=table)


# ── Mail commands ────────────────────────────────────────────────────────


@mail_app.command("list")
def mail_list(
    mailbox: Annotated[
        Optional[str], typer.Option("--mailbox", "-m", help="Mailbox name to filter by.")
    ] = None,
    role: Annotated[
        Optional[str],
        typer.Option("--role", "-r", help="Mailbox role to filter by (e.g. inbox, sent)."),
    ] = None,
    limit: Annotated[
        int, typer.Option("--limit", "-n", help="Max number of emails to show.")
    ] = 10,
    fmt: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Output format: table, json, or csv.")
    ] = OutputFormat.table,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Save output to a file path.")
    ] = None,
) -> None:
    """List recent emails."""
    client = _get_client()

    mailbox_id = None
    if role:
        mailbox_id = client.find_mailbox_id(role=role)
    elif mailbox:
        mailbox_id = client.find_mailbox_id(name=mailbox)

    emails = client.list_emails(mailbox_id=mailbox_id, limit=limit)

    columns = ["Date", "From", "Subject", "ID"]

    table = Table(title="Emails")
    table.add_column("Date", style="dim", no_wrap=True)
    table.add_column("From", style="cyan", max_width=30)
    table.add_column("Subject", style="bold")
    table.add_column("ID", style="dim")

    rows: list[dict[str, Any]] = []
    for email in emails:
        row = {
            "Date": email.get("receivedAt", "")[:19],
            "From": _format_from(email.get("from")),
            "Subject": email.get("subject", "(no subject)"),
            "ID": email.get("id", ""),
        }
        rows.append(row)
        table.add_row(*[row[c] for c in columns])

    _emit_output(rows, columns, fmt=fmt, output=output, table=table)


@mail_app.command("read")
def mail_read(
    email_id: Annotated[str, typer.Argument(help="The ID of the email to read.")],
) -> None:
    """Read a single email by its ID."""
    client = _get_client()
    email = client.read_email(email_id)

    header = (
        f"[bold]Subject:[/] {email.get('subject', '(no subject)')}\n"
        f"[bold]From:[/]    {_format_from(email.get('from'))}\n"
        f"[bold]To:[/]      {_format_from(email.get('to'))}\n"
        f"[bold]Date:[/]    {email.get('receivedAt', 'N/A')}\n"
        f"[bold]ID:[/]      {email.get('id', '')}"
    )
    console.print(Panel(header, title="Email", border_style="blue"))

    # Print body
    body_values = email.get("bodyValues", {})
    text_parts = email.get("textBody", [])
    for part in text_parts:
        part_id = part.get("partId", "")
        if part_id in body_values:
            console.print()
            console.print(body_values[part_id].get("value", ""))
            return

    # Fallback to preview
    preview = email.get("preview", "")
    if preview:
        console.print()
        console.print(f"[dim](preview)[/] {preview}")


@mail_app.command("send")
def mail_send(
    to: Annotated[str, typer.Option("--to", "-t", help="Recipient email address.")],
    subject: Annotated[str, typer.Option("--subject", "-s", help="Email subject.")],
    body: Annotated[
        Optional[str], typer.Option("--body", "-b", help="Email body text. If omitted, reads from stdin.")
    ] = None,
    cc: Annotated[
        Optional[str],
        typer.Option("--cc", help="CC email address (can be repeated)."),
    ] = None,
) -> None:
    """Send an email."""
    client = _get_client()

    if body is None:
        if sys.stdin.isatty():
            console.print("Enter email body (Ctrl+D to finish):", style="dim")
        body = sys.stdin.read()

    to_list = [{"email": addr.strip()} for addr in to.split(",")]
    cc_list = [{"email": addr.strip()} for addr in cc.split(",")] if cc else None

    client.send_email(to=to_list, subject=subject, body=body, cc=cc_list)
    console.print("[bold green]✓[/] Email sent successfully!")


@mail_app.command("delete")
def mail_delete(
    email_id: Annotated[str, typer.Argument(help="The ID of the email to delete.")],
    confirm: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
) -> None:
    """Delete an email by its ID."""
    if not confirm:
        typer.confirm(f"Are you sure you want to delete email {email_id}?", abort=True)

    client = _get_client()
    client.delete_email(email_id)
    console.print(f"[bold green]✓[/] Email {email_id} deleted.")


@mail_app.command("search")
def mail_search(
    query: Annotated[str, typer.Argument(help="Search query text.")],
    limit: Annotated[
        int, typer.Option("--limit", "-n", help="Max number of results.")
    ] = 10,
) -> None:
    """Search emails by text query."""
    client = _get_client()
    emails = client.search_emails(query=query, limit=limit)

    if not emails:
        console.print("[dim]No emails found.[/]")
        return

    table = Table(title=f"Search: '{query}'")
    table.add_column("Date", style="dim", no_wrap=True)
    table.add_column("From", style="cyan", max_width=30)
    table.add_column("Subject", style="bold")
    table.add_column("ID", style="dim")

    for email in emails:
        table.add_row(
            email.get("receivedAt", "")[:19],
            _format_from(email.get("from")),
            email.get("subject", "(no subject)"),
            email.get("id", ""),
        )
    console.print(table)


@mail_app.command("move")
def mail_move(
    email_id: Annotated[str, typer.Argument(help="The ID of the email to move.")],
    mailbox: Annotated[
        Optional[str], typer.Option("--mailbox", "-m", help="Destination mailbox name.")
    ] = None,
    role: Annotated[
        Optional[str],
        typer.Option("--role", "-r", help="Destination mailbox role (e.g. trash, archive)."),
    ] = None,
) -> None:
    """Move an email to a different mailbox."""
    if not mailbox and not role:
        err_console.print("[bold red]Error:[/] Specify --mailbox or --role.")
        raise typer.Exit(code=1)

    client = _get_client()
    if role:
        mailbox_id = client.find_mailbox_id(role=role)
    else:
        mailbox_id = client.find_mailbox_id(name=mailbox)

    client.move_email(email_id, mailbox_id)
    console.print(f"[bold green]✓[/] Email moved to {mailbox or role}.")


# ── Label commands ───────────────────────────────────────────────────────


@label_app.callback()
def label_callback() -> None:
    """Manage labels (keywords) on emails."""


@label_app.command("list")
def label_list(
    email_id: Annotated[str, typer.Argument(help="The ID of the email.")],
) -> None:
    """List all labels (keywords) on an email."""
    client = _get_client()
    keywords = client.get_email_keywords(email_id)

    if not keywords:
        console.print("[dim]No labels on this email.[/]")
        return

    table = Table(title="Labels")
    table.add_column("Keyword", style="bold cyan")
    for kw in sorted(keywords):
        table.add_row(kw)
    console.print(table)


@label_app.command("create")
def label_create(
    email_id: Annotated[str, typer.Argument(help="The ID of the email.")],
    label: Annotated[str, typer.Argument(help="The label (keyword) to add.")],
) -> None:
    """Add a label (keyword) to an email."""
    client = _get_client()
    client.add_email_keyword(email_id, label)
    console.print(f"[bold green]✓[/] Label '{label}' added to email {email_id}.")


@label_app.command("delete")
def label_delete(
    email_id: Annotated[str, typer.Argument(help="The ID of the email.")],
    label: Annotated[str, typer.Argument(help="The label (keyword) to remove.")],
) -> None:
    """Remove a label (keyword) from an email."""
    client = _get_client()
    client.remove_email_keyword(email_id, label)
    console.print(f"[bold green]✓[/] Label '{label}' removed from email {email_id}.")


# ── Masked Email commands ────────────────────────────────────────────────


@masked_app.command("list")
def masked_list(
    fmt: Annotated[
        OutputFormat, typer.Option("--format", "-f", help="Output format: table, json, or csv.")
    ] = OutputFormat.table,
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Save output to a file path.")
    ] = None,
    enabled: Annotated[
        bool, typer.Option("--enabled", help="Show only enabled masked emails.")
    ] = False,
    disabled: Annotated[
        bool, typer.Option("--disabled", help="Show only disabled masked emails.")
    ] = False,
    deleted: Annotated[
        bool, typer.Option("--deleted", help="Show only deleted masked emails.")
    ] = False,
) -> None:
    """List all masked email addresses."""
    state_filters = [
        name
        for name, flag in [("enabled", enabled), ("disabled", disabled), ("deleted", deleted)]
        if flag
    ]
    if len(state_filters) > 1:
        err_console.print(
            "[bold red]Error:[/] Only one of --enabled, --disabled, or --deleted may be specified."
        )
        raise typer.Exit(code=1)

    client = _get_client()
    masked_emails = client.list_masked_emails()

    if state_filters:
        masked_emails = [me for me in masked_emails if me.get("state") == state_filters[0]]

    if not masked_emails:
        console.print("[dim]No masked emails found.[/]")
        return

    columns = ["Email", "State", "For Domain", "Description", "Created By", "Last Message", "ID"]

    table = Table(title="Masked Emails")
    table.add_column("Email", style="bold")
    table.add_column("State", style="cyan")
    table.add_column("For Domain")
    table.add_column("Description")
    table.add_column("Created By", style="dim")
    table.add_column("Last Message", style="dim")
    table.add_column("ID", style="dim")

    rows: list[dict[str, Any]] = []
    for me in masked_emails:
        state = me.get("state", "")
        state_style = {
            "enabled": "green",
            "disabled": "yellow",
            "pending": "blue",
            "deleted": "red",
        }.get(state, "")

        row = {
            "Email": me.get("email", ""),
            "State": state,
            "For Domain": me.get("forDomain", ""),
            "Description": me.get("description", ""),
            "Created By": me.get("createdBy", ""),
            "Last Message": me.get("lastMessageAt") or "",
            "ID": me.get("id", ""),
        }
        rows.append(row)
        table.add_row(
            row["Email"],
            f"[{state_style}]{state}[/{state_style}]" if state_style else state,
            row["For Domain"],
            row["Description"],
            row["Created By"],
            row["Last Message"],
            row["ID"],
        )

    _emit_output(rows, columns, fmt=fmt, output=output, table=table)


@masked_app.command("create")
def masked_create(
    domain: Annotated[
        Optional[str],
        typer.Option("--domain", "-d", help="Domain this masked email is for (e.g. https://example.com)."),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option("--description", help="Short description of the masked email's purpose."),
    ] = None,
    prefix: Annotated[
        Optional[str],
        typer.Option("--prefix", "-p", help="Prefix for the generated email address (a-z, 0-9, _)."),
    ] = None,
    state: Annotated[
        str,
        typer.Option("--state", "-s", help="Initial state: pending or enabled."),
    ] = "enabled",
) -> None:
    """Create a new masked email address."""
    client = _get_client()
    result = client.create_masked_email(
        for_domain=domain,
        description=description,
        prefix=prefix,
        state=state,
    )
    console.print(f"[bold green]✓[/] Created masked email: [bold]{result.get('email', 'N/A')}[/]")
    console.print(f"  ID:    {result.get('id', 'N/A')}")
    console.print(f"  State: {result.get('state', 'N/A')}")


@masked_app.command("update")
def masked_update(
    masked_id: Annotated[str, typer.Argument(help="ID of the masked email to update.")],
    state: Annotated[
        Optional[str],
        typer.Option("--state", "-s", help="New state: enabled, disabled, or deleted."),
    ] = None,
    domain: Annotated[
        Optional[str],
        typer.Option("--domain", "-d", help="Update the forDomain value."),
    ] = None,
    description: Annotated[
        Optional[str],
        typer.Option("--description", help="Update the description."),
    ] = None,
) -> None:
    """Update a masked email address."""
    if not any([state, domain, description]):
        err_console.print("[bold red]Error:[/] Provide at least one field to update.")
        raise typer.Exit(code=1)

    client = _get_client()
    client.update_masked_email(
        masked_email_id=masked_id,
        state=state,
        for_domain=domain,
        description=description,
    )
    console.print(f"[bold green]✓[/] Masked email {masked_id} updated.")


@masked_app.command("delete")
def masked_delete(
    masked_id: Annotated[str, typer.Argument(help="ID of the masked email to delete.")],
    confirm: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
) -> None:
    """Delete a masked email address (sets state to 'deleted')."""
    if not confirm:
        typer.confirm(
            f"Are you sure you want to delete masked email {masked_id}?", abort=True
        )

    client = _get_client()
    client.delete_masked_email(masked_id)
    console.print(f"[bold green]✓[/] Masked email {masked_id} deleted.")


@migrate_app.command("addy")
def migrate_addy(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="File path to save the exported CSV."),
    ] = ...,
    recipients: Annotated[
        Optional[str],
        typer.Option(
            "--recipients",
            "-r",
            help="Comma-separated list of recipient email addresses to populate in every row.",
        ),
    ] = None,
    enabled: Annotated[
        bool, typer.Option("--enabled", help="Export only enabled masked emails.")
    ] = False,
    disabled: Annotated[
        bool, typer.Option("--disabled", help="Export only disabled masked emails.")
    ] = False,
    deleted: Annotated[
        bool, typer.Option("--deleted", help="Export only deleted masked emails.")
    ] = False,
) -> None:
    """Export masked emails in Addy alias import CSV format."""
    state_filters = [
        name
        for name, flag in [("enabled", enabled), ("disabled", disabled), ("deleted", deleted)]
        if flag
    ]
    if len(state_filters) > 1:
        err_console.print(
            "[bold red]Error:[/] Only one of --enabled, --disabled, or --deleted may be specified."
        )
        raise typer.Exit(code=1)

    client = _get_client()
    masked_emails = client.list_masked_emails()

    if state_filters:
        masked_emails = [me for me in masked_emails if me.get("state") == state_filters[0]]

    if not masked_emails:
        console.print("[dim]No masked emails to export.[/]")
        return

    recipients_value = recipients.strip() if recipients else ""

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["alias", "description", "recipients"])
    writer.writeheader()
    for me in masked_emails:
        writer.writerow(
            {
                "alias": me.get("email", ""),
                "description": me.get("description", ""),
                "recipients": recipients_value,
            }
        )

    output.write_text(buf.getvalue())
    console.print(
        f"[bold green]\u2713[/] Exported {len(masked_emails)} masked email(s) "
        f"to [bold]{output}[/] in Addy format."
    )


if __name__ == "__main__":
    app()
