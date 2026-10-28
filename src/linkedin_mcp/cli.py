"""Command-line interface: run the MCP server or query the API directly."""

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from linkedin_mcp.client import LinkedInClient
from linkedin_mcp.config import DEFAULT_ENV_FILE, Settings, load_settings
from linkedin_mcp.errors import LinkedInError
from linkedin_mcp.server import create_server
from linkedin_mcp.service import LinkedInService

type Command = Callable[[LinkedInService, argparse.Namespace], Awaitable[object]]


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser with all subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="linkedin-mcp",
        description="LinkedIn Member Data Portability MCP server and debugging CLI.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Path to a .env file with LINKEDIN_ACCESS_TOKEN (default: ./.env).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("serve", help="Run the MCP server on stdio.")
    commands.add_parser("status", help="Show whether changelog archiving is active.")
    commands.add_parser("enable-changelog", help="Enable changelog archiving.")
    commands.add_parser("domains", help="List snapshot domains that have data.")

    snapshot = commands.add_parser("snapshot", help="Print raw snapshot data as JSON.")
    snapshot.add_argument("domain", nargs="?", help="Domain name (case-sensitive); omit for all.")

    changelog = commands.add_parser("changelog", help="Print recent changelog events as JSON.")
    changelog.add_argument(
        "--since", type=datetime.fromisoformat, help="ISO 8601 start time (naive = UTC)."
    )
    changelog.add_argument("--resource", help='Only this resource type, e.g. "messages".')
    changelog.add_argument("--limit", type=int, default=20, help="Maximum number of events.")
    return parser


async def _status(service: LinkedInService, _args: argparse.Namespace) -> object:
    """Return the changelog archiving status."""
    return await service.get_authorizations()


async def _enable_changelog(service: LinkedInService, _args: argparse.Namespace) -> object:
    """Enable changelog archiving and return the new status."""
    await service.enable_changelog()
    return await service.get_authorizations()


async def _domains(service: LinkedInService, _args: argparse.Namespace) -> object:
    """Return the domains that have data."""
    return await service.list_domains()


async def _snapshot(service: LinkedInService, args: argparse.Namespace) -> object:
    """Return the raw snapshot sections for a domain."""
    return await service.get_sections(args.domain)


async def _changelog(service: LinkedInService, args: argparse.Namespace) -> object:
    """Return recent changelog events."""
    return await service.get_recent_activity(
        since=args.since, resource_name=args.resource, limit=args.limit
    )


COMMANDS: dict[str, Command] = {
    "status": _status,
    "enable-changelog": _enable_changelog,
    "domains": _domains,
    "snapshot": _snapshot,
    "changelog": _changelog,
}


async def run_command(command: Command, settings: Settings, args: argparse.Namespace) -> None:
    """Run a debugging command against the live API and print its result as JSON.

    Args:
        command: The command implementation.
        settings: Access token and runtime settings.
        args: Parsed command-line arguments.
    """
    async with LinkedInClient(settings.access_token, timeout=settings.timeout) as client:
        result = await command(LinkedInService(client, cache_ttl=0), args)
    print(to_json(result))


def to_json(value: object) -> str:
    """Serialize a command result (models, lists of models, dicts) as indented JSON.

    Args:
        value: The value to serialize.

    Returns:
        The JSON text.
    """
    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json")
    else:
        data = TypeAdapter(object).dump_python(value, mode="json")
    return json.dumps(data, indent=2, ensure_ascii=False)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface.

    Args:
        argv: Command-line arguments without the program name; defaults to `sys.argv`.

    Returns:
        The process exit code.
    """
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings(args.env_file)
        if args.command == "serve":
            create_server(settings).run("stdio")
        else:
            asyncio.run(run_command(COMMANDS[args.command], settings, args))
    except LinkedInError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def entry_point() -> None:
    """Console script entry point: run `main()` and exit with its status code."""
    sys.exit(main())
