"""High-level, cached read access to the member's LinkedIn data.

The service fetches whole snapshot domains (the API has no server-side filtering),
caches them in memory, and filters, sorts and paginates them locally.
"""

import time
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Protocol

from pydantic import BaseModel

from linkedin_mcp.cache import TTLCache
from linkedin_mcp.config import DEFAULT_CACHE_TTL
from linkedin_mcp.domains import CONNECTIONS, INBOX, MEMBER_SHARE_INFO, PROFILE, describe_domain
from linkedin_mcp.models import (
    ChangelogEvent,
    MemberAuthorization,
    SnapshotRecord,
    SnapshotSection,
    datetime_to_ms,
)
from linkedin_mcp.records import (
    Connection,
    Conversation,
    ConversationSummary,
    Message,
    Post,
    Profile,
    matches,
    normalize_text,
)

PREVIEW_LENGTH = 200
_OLDEST = datetime.min.replace(tzinfo=UTC)


class PortabilityAPI(Protocol):
    """The subset of `LinkedInClient` that the service uses."""

    async def get_snapshot(self, domain: str | None = None) -> list[SnapshotSection]:
        """Fetch all snapshot sections for a domain, or for all domains if None."""
        ...

    def iter_changelog(self, *, start_time: int | None = None) -> AsyncIterator[ChangelogEvent]:
        """Iterate over changelog events since `start_time` (epoch milliseconds)."""
        ...

    async def get_member_authorizations(self) -> list[MemberAuthorization]:
        """Fetch the changelog archiving status."""
        ...

    async def enable_changelog(self) -> None:
        """Enable changelog archiving."""
        ...


class Page[T](BaseModel):
    """A slice of a longer result list.

    Attributes:
        total: Number of items matching the request, before pagination.
        offset: Index of the first returned item.
        items: The returned items.
    """

    total: int
    offset: int
    items: list[T]


class DomainSummary(BaseModel):
    """A snapshot domain that has data for the member.

    Attributes:
        domain: Domain name, for use with `get_domain_records`.
        description: Documented description of the domain.
        record_count: Number of data rows in the domain.
    """

    domain: str
    description: str
    record_count: int


class LinkedInService:
    """Cached, filtered access to the member's LinkedIn data."""

    def __init__(
        self,
        api: PortabilityAPI,
        *,
        cache_ttl: float = DEFAULT_CACHE_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a service.

        Args:
            api: LinkedIn API client.
            cache_ttl: Seconds to keep fetched snapshot data in memory; 0 disables caching.
            clock: Function that returns the current time in seconds (for tests).
        """
        self._api = api
        self._cache: TTLCache[str | None, list[SnapshotSection]] = TTLCache(cache_ttl, clock)

    def clear_cache(self) -> None:
        """Discard all cached snapshot data."""
        self._cache.clear()

    async def get_sections(
        self, domain: str | None = None, *, refresh: bool = False
    ) -> list[SnapshotSection]:
        """Return all snapshot sections for a domain, using the cache.

        Args:
            domain: Snapshot domain, or None for all domains.
            refresh: Fetch fresh data even if cached data is available.

        Returns:
            The snapshot sections. Empty if the domain has no data.
        """
        return await self._cache.get_or_load(
            domain, lambda: self._api.get_snapshot(domain), refresh=refresh
        )

    async def get_records(self, domain: str, *, refresh: bool = False) -> list[SnapshotRecord]:
        """Return all data rows of a domain, across all sections.

        Args:
            domain: Snapshot domain (case-sensitive).
            refresh: Fetch fresh data even if cached data is available.

        Returns:
            The data rows. Empty if the domain has no data.
        """
        sections = await self.get_sections(domain, refresh=refresh)
        return [record for section in sections for record in section.snapshot_data]

    async def list_domains(self, *, refresh: bool = False) -> list[DomainSummary]:
        """List the snapshot domains that have data, with row counts.

        This fetches the data of all domains, so the first call is slow.

        Args:
            refresh: Fetch fresh data even if cached data is available.

        Returns:
            Domains sorted by name.
        """
        counts: dict[str, int] = {}
        for section in await self.get_sections(None, refresh=refresh):
            domain = section.snapshot_domain
            counts[domain] = counts.get(domain, 0) + len(section.snapshot_data)
        return [
            DomainSummary(domain=domain, description=describe_domain(domain), record_count=count)
            for domain, count in sorted(counts.items())
        ]

    async def get_domain_records(
        self, domain: str, *, offset: int = 0, limit: int = 50, refresh: bool = False
    ) -> Page[SnapshotRecord]:
        """Return a page of raw data rows from any snapshot domain.

        Args:
            domain: Snapshot domain (case-sensitive).
            offset: Number of rows to skip.
            limit: Maximum number of rows to return.
            refresh: Fetch fresh data even if cached data is available.

        Returns:
            A page of rows in API order.
        """
        return paginate(await self.get_records(domain, refresh=refresh), offset, limit)

    async def get_profile(self, *, refresh: bool = False) -> Profile | None:
        """Return the member's basic profile.

        Args:
            refresh: Fetch fresh data even if cached data is available.

        Returns:
            The profile, or None if the PROFILE domain has no data.
        """
        records = await self.get_records(PROFILE, refresh=refresh)
        return Profile.from_record(records[0]) if records else None

    async def get_messages(self, *, refresh: bool = False) -> list[Message]:
        """Return all messages, newest first.

        Args:
            refresh: Fetch fresh data even if cached data is available.

        Returns:
            All messages from the INBOX domain. Messages without a parseable date are last.
        """
        messages = [
            Message.from_record(record) for record in await self.get_records(INBOX, refresh=refresh)
        ]
        return sorted(messages, key=_message_time, reverse=True)

    async def list_conversations(
        self,
        *,
        folder: str | None = None,
        participant: str | None = None,
        since: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Page[ConversationSummary]:
        """List conversations, most recently active first.

        Args:
            folder: Only conversations whose latest message is in this folder
                (case-insensitive), for example "INBOX", "ARCHIVE" or "SPAM".
            participant: Only conversations with a participant whose name contains this text.
            since: Only conversations with a message at or after this time (naive = UTC).
            offset: Number of conversations to skip.
            limit: Maximum number of conversations to return.

        Returns:
            A page of conversation summaries.
        """
        summaries = [
            summarize_conversation(conversation_id, messages)
            for conversation_id, messages in group_by_conversation(
                await self.get_messages()
            ).items()
        ]
        if folder is not None:
            summaries = [s for s in summaries if s.folder.casefold() == folder.casefold()]
        if participant is not None:
            summaries = [s for s in summaries if matches(participant, *s.participants)]
        if since is not None:
            threshold = as_utc(since)
            summaries = [
                s for s in summaries if s.last_message_at and s.last_message_at >= threshold
            ]
        summaries.sort(key=lambda s: s.last_message_at or _OLDEST, reverse=True)
        return paginate(summaries, offset, limit)

    async def get_conversation(
        self, conversation_id: str, *, limit: int | None = None
    ) -> Conversation | None:
        """Return one conversation with its messages in chronological order.

        Args:
            conversation_id: Conversation identifier, as returned by `list_conversations`.
            limit: Return only the most recent `limit` messages. None returns all.

        Returns:
            The conversation, or None if no message has this conversation identifier.
        """
        messages = group_by_conversation(await self.get_messages()).get(conversation_id)
        if not messages:
            return None
        summary = summarize_conversation(conversation_id, messages)
        shown = messages if limit is None else messages[-limit:] if limit > 0 else []
        return Conversation(**summary.model_dump(), messages=shown)

    async def search_messages(
        self,
        query: str | None = None,
        *,
        sender: str | None = None,
        folder: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Page[Message]:
        """Search messages, newest first.

        All given filters must match.

        Args:
            query: Text to find in the message body, subject or conversation title
                (case- and accent-insensitive).
            sender: Text to find in the sender's name.
            folder: Exact folder name (case-insensitive).
            since: Only messages sent at or after this time (naive = UTC).
            until: Only messages sent before this time (naive = UTC).
            offset: Number of messages to skip.
            limit: Maximum number of messages to return.

        Returns:
            A page of matching messages.
        """
        results: Iterable[Message] = await self.get_messages()
        if query is not None:
            results = (
                m for m in results if matches(query, m.content, m.subject, m.conversation_title)
            )
        if sender is not None:
            results = (m for m in results if matches(sender, m.sender))
        if folder is not None:
            results = (m for m in results if m.folder.casefold() == folder.casefold())
        if since is not None:
            start = as_utc(since)
            results = (m for m in results if m.sent_at is not None and m.sent_at >= start)
        if until is not None:
            end = as_utc(until)
            results = (m for m in results if m.sent_at is not None and m.sent_at < end)
        return paginate(list(results), offset, limit)

    async def search_connections(
        self,
        query: str | None = None,
        *,
        company: str | None = None,
        connected_since: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Page[Connection]:
        """Search first-degree connections, most recently connected first.

        All given filters must match.

        Args:
            query: Text to find in the name, company, position or email
                (case- and accent-insensitive).
            company: Text to find in the company name.
            connected_since: Only connections made on or after this date.
            offset: Number of connections to skip.
            limit: Maximum number of connections to return.

        Returns:
            A page of matching connections.
        """
        results: Iterable[Connection] = [
            Connection.from_record(record) for record in await self.get_records(CONNECTIONS)
        ]
        if query is not None:
            results = (
                c
                for c in results
                if matches(query, c.full_name, c.company, c.position, c.email or "")
            )
        if company is not None:
            results = (c for c in results if matches(company, c.company))
        if connected_since is not None:
            results = (c for c in results if c.connected_on and c.connected_on >= connected_since)
        ordered = sorted(results, key=lambda c: c.connected_on or date.min, reverse=True)
        return paginate(ordered, offset, limit)

    async def list_posts(
        self,
        query: str | None = None,
        *,
        since: datetime | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Page[Post]:
        """List the member's posts, newest first.

        Args:
            query: Text to find in the post text (case- and accent-insensitive).
            since: Only posts made at or after this time (naive = UTC).
            offset: Number of posts to skip.
            limit: Maximum number of posts to return.

        Returns:
            A page of posts. Empty if the MEMBER_SHARE_INFO domain has no data.
        """
        results: Iterable[Post] = [
            Post.from_record(record) for record in await self.get_records(MEMBER_SHARE_INFO)
        ]
        if query is not None:
            results = (p for p in results if matches(query, p.commentary))
        if since is not None:
            start = as_utc(since)
            results = (p for p in results if p.posted_at is not None and p.posted_at >= start)
        ordered = sorted(results, key=lambda p: p.posted_at or _OLDEST, reverse=True)
        return paginate(ordered, offset, limit)

    async def get_recent_activity(
        self,
        *,
        since: datetime | None = None,
        resource_name: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Page[ChangelogEvent]:
        """Return changelog events (activity since consent, last 28 days), newest first.

        Changelog data is not cached.

        Args:
            since: Only events captured at or after this time (naive = UTC).
            resource_name: Only events for this resource type (case-insensitive), for
                example "messages".
            offset: Number of events to skip.
            limit: Maximum number of events to return.

        Returns:
            A page of events.
        """
        start_time = datetime_to_ms(since) if since is not None else None
        events = [event async for event in self._api.iter_changelog(start_time=start_time)]
        if resource_name is not None:
            wanted = normalize_text(resource_name)
            events = [e for e in events if normalize_text(e.resource_name) == wanted]
        events.sort(key=lambda e: e.captured_at, reverse=True)
        return paginate(events, offset, limit)

    async def get_authorizations(self) -> list[MemberAuthorization]:
        """Return the changelog archiving status.

        Returns:
            The member's authorizations. Empty if changelog archiving is not enabled.
        """
        return await self._api.get_member_authorizations()

    async def enable_changelog(self) -> None:
        """Enable changelog archiving for the member."""
        await self._api.enable_changelog()


def paginate[T](items: Sequence[T], offset: int, limit: int) -> Page[T]:
    """Slice a list into a page.

    Args:
        items: All items.
        offset: Number of items to skip; must not be negative.
        limit: Maximum number of items to return; must not be negative.

    Returns:
        The page.

    Raises:
        ValueError: If `offset` or `limit` is negative.
    """
    if offset < 0 or limit < 0:
        raise ValueError(f"offset and limit must not be negative, got {offset} and {limit}")
    return Page[T](total=len(items), offset=offset, items=list(items[offset : offset + limit]))


def as_utc(value: datetime) -> datetime:
    """Return a timezone-aware datetime, treating naive values as UTC.

    Args:
        value: A naive or aware datetime.

    Returns:
        An aware datetime.
    """
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def group_by_conversation(messages: Iterable[Message]) -> dict[str, list[Message]]:
    """Group messages by conversation, each group in chronological order.

    Args:
        messages: Messages in any order.

    Returns:
        A mapping from conversation identifier to its messages, oldest first.
    """
    groups: dict[str, list[Message]] = {}
    for message in messages:
        groups.setdefault(message.conversation_id, []).append(message)
    for group in groups.values():
        group.sort(key=_message_time)
    return groups


def summarize_conversation(
    conversation_id: str, messages: Sequence[Message]
) -> ConversationSummary:
    """Build a conversation summary.

    Args:
        conversation_id: Conversation identifier.
        messages: The conversation's messages in chronological order; must not be empty.

    Returns:
        The summary.
    """
    participants: dict[str, None] = {}
    for message in messages:
        for name in (message.sender, *message.recipients):
            if name:
                participants.setdefault(name)
    first, last = messages[0], messages[-1]
    title = next((m.conversation_title for m in reversed(messages) if m.conversation_title), "")
    return ConversationSummary(
        conversation_id=conversation_id,
        title=title,
        participants=list(participants),
        message_count=len(messages),
        folder=last.folder,
        first_message_at=first.sent_at,
        last_message_at=last.sent_at,
        last_message_sender=last.sender,
        last_message_preview=last.content[:PREVIEW_LENGTH],
    )


def _message_time(message: Message) -> datetime:
    """Sort key for messages: send time, with unparseable dates treated as oldest.

    Args:
        message: The message.

    Returns:
        The send time, or the minimum datetime.
    """
    return message.sent_at or _OLDEST
