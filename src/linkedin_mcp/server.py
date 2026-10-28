"""MCP server that exposes the member's LinkedIn data as read-only tools."""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import date, datetime
from typing import Annotated, Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from linkedin_mcp.client import LinkedInClient
from linkedin_mcp.config import Settings
from linkedin_mcp.errors import LinkedInError
from linkedin_mcp.models import ChangelogEvent, SnapshotRecord
from linkedin_mcp.records import (
    Connection,
    Conversation,
    ConversationSummary,
    Message,
    Post,
    Profile,
)
from linkedin_mcp.service import DomainSummary, LinkedInService, Page

INSTRUCTIONS = """\
Read-only access to the user's own LinkedIn data through LinkedIn's EU Member Data Portability API.

Data sources:
- Snapshot (all tools except get_recent_activity): the user's full history. It can end at the time the user connected this app, and it is cached (one hour by default).
- get_recent_activity: activity after the user connected the app (new messages, posts, comments, reactions), only from the last 28 days. For the latest messages or posts, check both sources.

Usage notes:
- Search is a case- and accent-insensitive substring match, not fuzzy or semantic. Search for one name or word at a time. Filters combine with AND.
- The user's own messages have the user's name as `sender`; get_profile returns it.
- Connection emails are usually missing: LinkedIn exports them only if the connection allows it.
- For other data (events, invitations, positions, skills, comments, likes), call list_data_domains once (it is slow), then get_data_domain. Domain names are case-sensitive; events are "Events".
- The posts data can be empty for some time after the user connects the app.
"""  # noqa: E501 (unwrapped lines save tokens)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

# Plain assignments, not `type` statements: the SDK detects the context parameter with
# `inspect.isclass`, which a `TypeAliasType` does not satisfy.
Offset = Annotated[int, Field(ge=0, description="Number of results to skip.")]
Limit = Annotated[int, Field(ge=1, le=100, description="Maximum number of results.")]
ServiceContext = Context[LinkedInService, Any]


def create_server(settings: Settings) -> MCPServer[LinkedInService]:
    """Create the MCP server.

    The LinkedIn client is created when the server starts and closed when it stops.

    Args:
        settings: Access token and runtime settings.

    Returns:
        The configured server, ready to `run()`.
    """

    @asynccontextmanager
    async def lifespan(_server: MCPServer[LinkedInService]) -> AsyncGenerator[LinkedInService]:
        """Open the LinkedIn client for the lifetime of the server."""
        async with LinkedInClient(settings.access_token, timeout=settings.timeout) as client:
            yield LinkedInService(client, cache_ttl=settings.cache_ttl)

    mcp = MCPServer("linkedin", instructions=INSTRUCTIONS, lifespan=lifespan)

    @mcp.tool(annotations=READ_ONLY)
    async def get_profile(ctx: ServiceContext) -> Profile:
        """Get the user's basic LinkedIn profile: name, headline, summary, location."""
        with _tool_errors():
            profile = await _service(ctx).get_profile()
        if profile is None:
            raise ToolError("No profile data available.")
        return profile

    @mcp.tool(annotations=READ_ONLY)
    async def list_conversations(
        ctx: ServiceContext,
        folder: Annotated[
            str | None,
            Field(description='Folder of the latest message: "INBOX", "ARCHIVE", "SPAM".'),
        ] = None,
        participant: Annotated[
            str | None, Field(description="Text to find in a participant's name.")
        ] = None,
        since: Annotated[
            datetime | None, Field(description="Only conversations active at or after this time.")
        ] = None,
        offset: Offset = 0,
        limit: Limit = 20,
    ) -> Page[ConversationSummary]:
        """List LinkedIn message conversations, most recently active first."""
        with _tool_errors():
            return await _service(ctx).list_conversations(
                folder=folder, participant=participant, since=since, offset=offset, limit=limit
            )

    @mcp.tool(annotations=READ_ONLY)
    async def get_conversation(
        ctx: ServiceContext,
        conversation_id: Annotated[
            str, Field(description="From list_conversations or search_messages.")
        ],
        limit: Annotated[
            int, Field(ge=1, le=500, description="Return only the most recent messages.")
        ] = 50,
    ) -> Conversation:
        """Get one LinkedIn conversation with its messages in chronological order."""
        with _tool_errors():
            conversation = await _service(ctx).get_conversation(conversation_id, limit=limit)
        if conversation is None:
            raise ToolError(f"No conversation with ID {conversation_id!r}.")
        return conversation

    @mcp.tool(annotations=READ_ONLY)
    async def search_messages(
        ctx: ServiceContext,
        query: Annotated[
            str | None, Field(description="Text to find in the message body or subject.")
        ] = None,
        sender: Annotated[
            str | None, Field(description="Text to find in the sender's name.")
        ] = None,
        folder: Annotated[
            str | None, Field(description='Message folder: "INBOX", "ARCHIVE", "SPAM".')
        ] = None,
        since: Annotated[
            datetime | None, Field(description="Only messages sent at or after this time.")
        ] = None,
        until: Annotated[
            datetime | None, Field(description="Only messages sent before this time.")
        ] = None,
        offset: Offset = 0,
        limit: Limit = 20,
    ) -> Page[Message]:
        """Search LinkedIn messages, newest first. Matching ignores case and accents."""
        with _tool_errors():
            return await _service(ctx).search_messages(
                query,
                sender=sender,
                folder=folder,
                since=since,
                until=until,
                offset=offset,
                limit=limit,
            )

    @mcp.tool(annotations=READ_ONLY)
    async def search_connections(
        ctx: ServiceContext,
        query: Annotated[
            str | None, Field(description="Text to find in the name, company, position or email.")
        ] = None,
        company: Annotated[
            str | None, Field(description="Text to find in the company name.")
        ] = None,
        connected_since: Annotated[
            date | None, Field(description="Only connections made on or after this date.")
        ] = None,
        offset: Offset = 0,
        limit: Limit = 50,
    ) -> Page[Connection]:
        """Search the user's first-degree LinkedIn connections, most recent first.

        Email addresses are only present for connections who allow exporting them.
        """
        with _tool_errors():
            return await _service(ctx).search_connections(
                query, company=company, connected_since=connected_since, offset=offset, limit=limit
            )

    @mcp.tool(annotations=READ_ONLY)
    async def list_posts(
        ctx: ServiceContext,
        query: Annotated[str | None, Field(description="Text to find in the post text.")] = None,
        since: Annotated[
            datetime | None, Field(description="Only posts made at or after this time.")
        ] = None,
        offset: Offset = 0,
        limit: Limit = 20,
    ) -> Page[Post]:
        """List the user's LinkedIn posts, newest first.

        Posts made after the user's consent may only appear in get_recent_activity.
        """
        with _tool_errors():
            return await _service(ctx).list_posts(query, since=since, offset=offset, limit=limit)

    @mcp.tool(annotations=READ_ONLY)
    async def get_recent_activity(
        ctx: ServiceContext,
        since: Annotated[
            datetime | None, Field(description="Only events at or after this time.")
        ] = None,
        resource_name: Annotated[
            str | None,
            Field(
                description="Only events for this resource type. The values are not "
                "documented: call without this filter first to see which values occur."
            ),
        ] = None,
        offset: Offset = 0,
        limit: Limit = 10,
    ) -> Page[ChangelogEvent]:
        """Get the user's LinkedIn activity since consent (last 28 days), newest first.

        Covers new messages, posts, comments and reactions. Times are epoch milliseconds.
        """
        with _tool_errors():
            return await _service(ctx).get_recent_activity(
                since=since, resource_name=resource_name, offset=offset, limit=limit
            )

    @mcp.tool(annotations=READ_ONLY)
    async def list_data_domains(ctx: ServiceContext) -> list[DomainSummary]:
        """List all LinkedIn data domains that have data for the user, with row counts.

        The first call fetches all data and takes several seconds.
        """
        with _tool_errors():
            return await _service(ctx).list_domains()

    @mcp.tool(annotations=READ_ONLY)
    async def get_data_domain(
        ctx: ServiceContext,
        domain: Annotated[
            str,
            Field(description='Case-sensitive name from list_data_domains, e.g. "Events".'),
        ],
        offset: Offset = 0,
        limit: Limit = 50,
    ) -> Page[SnapshotRecord]:
        """Get raw data rows from any LinkedIn data domain, for example POSITIONS or SKILLS."""
        with _tool_errors():
            return await _service(ctx).get_domain_records(domain, offset=offset, limit=limit)

    return mcp


def _service(ctx: ServiceContext) -> LinkedInService:
    """Return the service created by the server lifespan.

    Args:
        ctx: The request context.

    Returns:
        The LinkedIn service.
    """
    return ctx.request_context.lifespan_context


@contextmanager
def _tool_errors() -> Generator[None]:
    """Report LinkedIn and validation errors to the model as tool errors.

    The SDK hides the message of unexpected exceptions from the model, so errors the
    model can act on (expired token, unknown domain) are converted to `ToolError`.

    Yields:
        Nothing.
    """
    try:
        yield
    except (LinkedInError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
