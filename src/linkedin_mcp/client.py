"""Low-level async client for the LinkedIn Member Data Portability (Member) API.

The API has four endpoints:

- `GET /rest/memberSnapshotData`: the member's data, grouped into snapshot domains.
- `GET /rest/memberChangeLogs`: activity events from the last 28 days.
- `GET /rest/memberAuthorizations`: whether changelog archiving is active.
- `POST /rest/memberAuthorizations`: enable changelog archiving.

See https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/
"""

import asyncio
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Self

import httpx

from linkedin_mcp.errors import LinkedInConnectionError, api_error_for_status
from linkedin_mcp.models import (
    ChangelogEvent,
    ChangelogPage,
    MemberAuthorization,
    MemberAuthorizationPage,
    SnapshotPage,
    SnapshotSection,
)

BASE_URL = "https://api.linkedin.com/rest"
API_VERSION = "202312"
"""The Snapshot API rejects every other version with 426 NONEXISTENT_VERSION."""

DEFAULT_CHANGELOG_COUNT = 10
MAX_CHANGELOG_COUNT = 50
DEFAULT_MAX_PAGES = 1000
"""Safety limit for paginated loops that only stop on a "no data" response."""

RETRY_STATUSES = frozenset({500, 502, 503, 504})
_NO_DATA_MESSAGE_PREFIX = "No data found"


class LinkedInClient:
    """Async client for the LinkedIn Member Data Portability (Member) API.

    Use as an async context manager, or call `aclose()` when done:

        async with LinkedInClient(token) as client:
            sections = await client.get_snapshot("CONNECTIONS")
    """

    def __init__(
        self,
        access_token: str,
        *,
        base_url: str = BASE_URL,
        timeout: float = 30.0,
        max_retries: int = 2,
        retry_backoff: float = 1.0,
    ) -> None:
        """Create a client.

        Args:
            access_token: OAuth 2.0 access token for the member.
            base_url: Base URL of the LinkedIn REST API.
            timeout: Request timeout in seconds.
            max_retries: How many times to retry on 5xx responses and connection errors.
            retry_backoff: Initial delay between retries in seconds; doubles on each retry.
        """
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Linkedin-Version": API_VERSION,
            },
        )

    async def __aenter__(self) -> Self:
        """Enter the async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the async context manager and close the HTTP connection pool."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP connection pool."""
        await self._http.aclose()

    async def get_snapshot_page(
        self, domain: str | None = None, start: int = 0
    ) -> SnapshotPage | None:
        """Fetch one page of member snapshot data.

        Args:
            domain: Snapshot domain (case-sensitive, for example "INBOX"), or None for all
                domains. Without a domain, each page holds one domain.
            start: Zero-based page index.

        Returns:
            The page, or None if LinkedIn reports that there is no (more) data.

        Raises:
            LinkedInAPIError: On an error response, for example `BadRequestError` for an
                unsupported domain.
            LinkedInConnectionError: If the API cannot be reached.
        """
        params: dict[str, str | int] = {"q": "criteria", "start": start}
        if domain is not None:
            params["domain"] = domain
        response = await self._request("GET", "/memberSnapshotData", params=params)
        if response.status_code == 404 and _is_no_data_response(response):
            return None
        _raise_for_status(response)
        return SnapshotPage.model_validate(response.json())

    async def iter_snapshot_pages(
        self, domain: str | None = None, *, max_pages: int = DEFAULT_MAX_PAGES
    ) -> AsyncIterator[SnapshotPage]:
        """Iterate over all pages of member snapshot data.

        Follows the documented approach: request increasing `start` values until the
        API responds with "No data found". The `paging.total` value is not used because
        LinkedIn documents that it can undercount.

        Args:
            domain: Snapshot domain, or None for all domains.
            max_pages: Maximum number of pages to fetch.

        Yields:
            Snapshot pages in order.
        """
        for start in range(max_pages):
            page = await self.get_snapshot_page(domain, start)
            if page is None:
                return
            yield page

    async def get_snapshot(self, domain: str | None = None) -> list[SnapshotSection]:
        """Fetch all snapshot sections for a domain (or for all domains).

        Args:
            domain: Snapshot domain, or None for all domains.

        Returns:
            All sections from all pages, in page order. Empty if there is no data.
        """
        return [
            section async for page in self.iter_snapshot_pages(domain) for section in page.elements
        ]

    async def get_changelog_page(
        self, *, start_time: int | None = None, count: int = DEFAULT_CHANGELOG_COUNT
    ) -> ChangelogPage:
        """Fetch one page of changelog events.

        Args:
            start_time: Inclusive lower bound on event time, in epoch milliseconds. Times
                older than 28 days are clamped by LinkedIn.
            count: Number of events to return, 1 to 50.

        Returns:
            The page of events.

        Raises:
            ValueError: If `count` is out of range.
            LinkedInAPIError: On an error response.
            LinkedInConnectionError: If the API cannot be reached.
        """
        if not 1 <= count <= MAX_CHANGELOG_COUNT:
            raise ValueError(f"count must be between 1 and {MAX_CHANGELOG_COUNT}, got {count}")
        params: dict[str, str | int] = {"q": "memberAndApplication", "count": count}
        if start_time is not None:
            params["startTime"] = start_time
        response = await self._request("GET", "/memberChangeLogs", params=params)
        _raise_for_status(response)
        return ChangelogPage.model_validate(response.json())

    async def iter_changelog(
        self,
        *,
        start_time: int | None = None,
        count: int = DEFAULT_CHANGELOG_COUNT,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> AsyncIterator[ChangelogEvent]:
        """Iterate over all changelog events since `start_time`.

        Follows the documented approach: the next request uses the latest `processedAt`
        of the previous page as `startTime`. Because `startTime` is inclusive, events
        repeat across pages; they are de-duplicated by `id`. Iteration stops when a page
        contains no new events.

        Args:
            start_time: Inclusive lower bound on event time, in epoch milliseconds.
            count: Page size, 1 to 50.
            max_pages: Maximum number of pages to fetch.

        Yields:
            Each event once, in the order the API returns them.
        """
        seen_ids: set[int] = set()
        cursor = start_time
        for _ in range(max_pages):
            page = await self.get_changelog_page(start_time=cursor, count=count)
            new_events = [event for event in page.elements if event.id not in seen_ids]
            if not new_events:
                return
            for event in new_events:
                seen_ids.add(event.id)
                yield event
            cursor = max(event.processed_at for event in page.elements)

    async def get_member_authorizations(self) -> list[MemberAuthorization]:
        """Fetch the changelog archiving status for the member.

        Returns:
            The member's authorizations. Empty if changelog archiving is not enabled.

        Raises:
            LinkedInAPIError: On an error response.
            LinkedInConnectionError: If the API cannot be reached.
        """
        response = await self._request(
            "GET", "/memberAuthorizations", params={"q": "memberAndApplication"}
        )
        _raise_for_status(response)
        return MemberAuthorizationPage.model_validate(response.json()).elements

    async def enable_changelog(self) -> None:
        """Enable changelog archiving for the member.

        LinkedIn normally enables archiving within seconds of consent. This call is only
        needed if `get_member_authorizations()` returns no authorization.

        Raises:
            LinkedInAPIError: On an error response.
            LinkedInConnectionError: If the API cannot be reached.
        """
        response = await self._request("POST", "/memberAuthorizations", json={})
        _raise_for_status(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        json: dict[str, object] | None = None,
    ) -> httpx.Response:
        """Send a request, retrying on 5xx responses and connection errors.

        Args:
            method: HTTP method.
            path: Path relative to the base URL.
            params: Query parameters.
            json: JSON request body.

        Returns:
            The final response, which may be an error response.

        Raises:
            LinkedInConnectionError: If the request fails at the transport level after
                all retries.
        """
        for attempt in range(self._max_retries + 1):
            is_last_attempt = attempt == self._max_retries
            try:
                response = await self._http.request(method, path, params=params, json=json)
            except httpx.TransportError as exc:
                if is_last_attempt:
                    raise LinkedInConnectionError(f"Cannot reach LinkedIn API: {exc}") from exc
            else:
                if is_last_attempt or response.status_code not in RETRY_STATUSES:
                    return response
            await asyncio.sleep(self._retry_backoff * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover


def _is_no_data_response(response: httpx.Response) -> bool:
    """Check whether a 404 response is LinkedIn's "No data found" end-of-data marker.

    Args:
        response: The HTTP response.

    Returns:
        True if the response body carries the "No data found" message.
    """
    return _error_message(response).startswith(_NO_DATA_MESSAGE_PREFIX)


def _error_message(response: httpx.Response) -> str:
    """Extract the error message from a LinkedIn error response.

    Args:
        response: The HTTP response.

    Returns:
        The `message` field of the JSON body, or the raw body text.
    """
    try:
        body = response.json()
    except ValueError:
        return response.text
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return body["message"]
    return response.text


def _raise_for_status(response: httpx.Response) -> None:
    """Raise the matching `LinkedInAPIError` if the response is an error.

    Args:
        response: The HTTP response.

    Raises:
        LinkedInAPIError: If the response status is not 2xx.
    """
    if response.is_success:
        return
    service_error_code: int | None = None
    code: str | None = None
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        if isinstance(body.get("serviceErrorCode"), int):
            service_error_code = body["serviceErrorCode"]
        if isinstance(body.get("code"), str) and body["code"]:
            code = body["code"]
    raise api_error_for_status(
        response.status_code,
        _error_message(response),
        service_error_code=service_error_code,
        code=code,
    )
