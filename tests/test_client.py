from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import respx

from linkedin_mcp.client import API_VERSION, BASE_URL, LinkedInClient
from linkedin_mcp.errors import (
    AuthenticationError,
    BadRequestError,
    LinkedInAPIError,
    LinkedInConnectionError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServerError,
)
from tests.factories import (
    changelog_event_json,
    changelog_page_json,
    no_data_response,
    snapshot_page_json,
)

TOKEN = "test-token"


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def client() -> AsyncIterator[LinkedInClient]:
    async with LinkedInClient(TOKEN, retry_backoff=0) as linkedin:
        yield linkedin


# Headers and context manager


async def test_requests_send_auth_and_version_headers(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberSnapshotData").mock(
        return_value=httpx.Response(200, json=snapshot_page_json("PROFILE", []))
    )

    await client.get_snapshot_page("PROFILE")

    headers = route.calls.last.request.headers
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Linkedin-Version"] == API_VERSION


async def test_context_manager_closes_http_client(api: respx.MockRouter) -> None:
    async with LinkedInClient(TOKEN) as linkedin:
        pass

    with pytest.raises(RuntimeError):
        await linkedin.get_snapshot_page()


# Snapshot API


async def test_get_snapshot_page_parses_response(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    body = snapshot_page_json(
        "SKILLS", [{"Name": "Python"}, {"Name": "Go"}], start=1, links=["prev"]
    )
    route = api.get("/memberSnapshotData").mock(return_value=httpx.Response(200, json=body))

    page = await client.get_snapshot_page("SKILLS", start=1)

    assert page is not None
    assert dict(route.calls.last.request.url.params) == {
        "q": "criteria",
        "start": "1",
        "domain": "SKILLS",
    }
    assert page.paging.start == 1
    assert not page.paging.has_next
    assert len(page.elements) == 1
    assert page.elements[0].snapshot_domain == "SKILLS"
    assert page.elements[0].snapshot_data == [{"Name": "Python"}, {"Name": "Go"}]


async def test_get_snapshot_page_without_domain_omits_domain_param(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberSnapshotData").mock(
        return_value=httpx.Response(200, json=snapshot_page_json("SKILLS", []))
    )

    await client.get_snapshot_page()

    assert dict(route.calls.last.request.url.params) == {"q": "criteria", "start": "0"}


@pytest.mark.parametrize(
    "message",
    ["No data found for this domain and memberId.", "No data found for this memberId."],
)
async def test_get_snapshot_page_returns_none_when_no_data(
    api: respx.MockRouter, client: LinkedInClient, message: str
) -> None:
    api.get("/memberSnapshotData").mock(return_value=no_data_response(message))

    assert await client.get_snapshot_page("INBOX", start=2) is None


async def test_get_snapshot_page_raises_for_other_404(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberSnapshotData").mock(
        return_value=httpx.Response(404, json={"message": "Resource not found", "status": 404})
    )

    with pytest.raises(NotFoundError):
        await client.get_snapshot_page("INBOX")


async def test_get_snapshot_page_raises_for_unsupported_domain(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberSnapshotData").mock(
        return_value=httpx.Response(
            400,
            json={
                "code": "",
                "message": "The following domain is not supported: EVENTS",
                "status": 400,
            },
        )
    )

    with pytest.raises(BadRequestError, match="not supported: EVENTS"):
        await client.get_snapshot_page("EVENTS")


async def test_iter_snapshot_pages_continues_until_no_data(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    # The last data page has no "next" link, but LinkedIn documents that paging can
    # undercount, so the client keeps going until it gets "No data found".
    route = api.get("/memberSnapshotData").mock(
        side_effect=[
            httpx.Response(
                200, json=snapshot_page_json("INBOX", [{"CONTENT": "a"}], links=["next"])
            ),
            httpx.Response(200, json=snapshot_page_json("INBOX", [{"CONTENT": "b"}], start=1)),
            httpx.Response(200, json=snapshot_page_json("INBOX", [{"CONTENT": "c"}], start=2)),
            no_data_response(),
        ]
    )

    pages = [page async for page in client.iter_snapshot_pages("INBOX")]

    assert len(pages) == 3
    assert [call.request.url.params["start"] for call in route.calls] == ["0", "1", "2", "3"]


async def test_iter_snapshot_pages_stops_at_max_pages(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberSnapshotData").mock(
        return_value=httpx.Response(200, json=snapshot_page_json("INBOX", []))
    )

    pages = [page async for page in client.iter_snapshot_pages("INBOX", max_pages=2)]

    assert len(pages) == 2
    assert route.call_count == 2


async def test_get_snapshot_flattens_sections_from_all_pages(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberSnapshotData").mock(
        side_effect=[
            httpx.Response(200, json=snapshot_page_json("SKILLS", [{"Name": "Python"}])),
            httpx.Response(200, json=snapshot_page_json("PROFILE", [{"First Name": "Ana"}])),
            no_data_response(),
        ]
    )

    sections = await client.get_snapshot()

    assert [s.snapshot_domain for s in sections] == ["SKILLS", "PROFILE"]


async def test_get_snapshot_returns_empty_list_without_data(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberSnapshotData").mock(return_value=no_data_response())

    assert await client.get_snapshot("ARTICLES") == []


# Error mapping


@pytest.mark.parametrize(
    ("status", "error_class"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (426, LinkedInAPIError),
        (429, RateLimitError),
        (500, ServerError),
        (504, ServerError),
    ],
)
async def test_error_status_maps_to_error_class(
    api: respx.MockRouter,
    client: LinkedInClient,
    status: int,
    error_class: type[LinkedInAPIError],
) -> None:
    api.get("/memberAuthorizations").mock(
        return_value=httpx.Response(status, json={"message": "Failure", "status": status})
    )

    with pytest.raises(error_class) as exc_info:
        await client.get_member_authorizations()

    assert type(exc_info.value) is error_class
    assert exc_info.value.status == status
    assert exc_info.value.message == "Failure"


async def test_error_keeps_service_error_code_and_code(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberAuthorizations").mock(
        return_value=httpx.Response(
            401,
            json={"message": "Expired access token", "serviceErrorCode": 65601, "code": "EXPIRED"},
        )
    )

    with pytest.raises(AuthenticationError) as exc_info:
        await client.get_member_authorizations()

    assert exc_info.value.service_error_code == 65601
    assert exc_info.value.code == "EXPIRED"


async def test_authentication_error_explains_how_to_get_a_new_token(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberAuthorizations").mock(
        return_value=httpx.Response(401, json={"message": "Expired access token", "status": 401})
    )

    with pytest.raises(AuthenticationError) as exc_info:
        await client.get_member_authorizations()

    message = str(exc_info.value)
    assert "Expired access token" in message
    assert "token-generator" in message
    assert "LINKEDIN_ACCESS_TOKEN" in message


async def test_error_with_non_json_body_uses_body_text(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberAuthorizations").mock(return_value=httpx.Response(403, text="Forbidden"))

    with pytest.raises(PermissionDeniedError) as exc_info:
        await client.get_member_authorizations()

    assert exc_info.value.message == "Forbidden"
    assert exc_info.value.service_error_code is None
    assert exc_info.value.code is None


# Retries


async def test_retries_server_errors_then_succeeds(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberAuthorizations").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(504),
            httpx.Response(200, json={"elements": []}),
        ]
    )

    assert await client.get_member_authorizations() == []
    assert route.call_count == 3


async def test_gives_up_after_max_retries(api: respx.MockRouter) -> None:
    route = api.get("/memberAuthorizations").mock(return_value=httpx.Response(500))

    async with LinkedInClient(TOKEN, max_retries=1, retry_backoff=0) as linkedin:
        with pytest.raises(ServerError):
            await linkedin.get_member_authorizations()

    assert route.call_count == 2


@pytest.mark.parametrize("status", [400, 401, 429])
async def test_does_not_retry_client_errors(
    api: respx.MockRouter, client: LinkedInClient, status: int
) -> None:
    route = api.get("/memberAuthorizations").mock(return_value=httpx.Response(status))

    with pytest.raises(LinkedInAPIError):
        await client.get_member_authorizations()

    assert route.call_count == 1


async def test_retries_transport_errors_then_raises_connection_error(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberAuthorizations").mock(side_effect=httpx.ConnectError("refused"))

    with pytest.raises(LinkedInConnectionError, match="refused"):
        await client.get_member_authorizations()

    assert route.call_count == 3


async def test_recovers_from_transport_error(api: respx.MockRouter, client: LinkedInClient) -> None:
    api.get("/memberAuthorizations").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"elements": []})]
    )

    assert await client.get_member_authorizations() == []


async def test_retry_delay_doubles(api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr("linkedin_mcp.client.asyncio.sleep", fake_sleep)
    api.get("/memberAuthorizations").mock(return_value=httpx.Response(502))

    async with LinkedInClient(TOKEN, max_retries=3, retry_backoff=0.5) as linkedin:
        with pytest.raises(ServerError):
            await linkedin.get_member_authorizations()

    assert delays == [0.5, 1.0, 2.0]


# Changelog API


async def test_get_changelog_page_sends_params_and_parses_events(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberChangeLogs").mock(
        return_value=httpx.Response(
            200, json=changelog_page_json([changelog_event_json(7, processed_at=2000)])
        )
    )

    page = await client.get_changelog_page(start_time=1000, count=25)

    assert dict(route.calls.last.request.url.params) == {
        "q": "memberAndApplication",
        "count": "25",
        "startTime": "1000",
    }
    event = page.elements[0]
    assert event.id == 7
    assert event.processed_at == 2000
    assert event.resource_name == "messages"
    assert event.activity_status == "SUCCESS"


async def test_get_changelog_page_omits_start_time_by_default(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberChangeLogs").mock(
        return_value=httpx.Response(200, json=changelog_page_json([]))
    )

    await client.get_changelog_page()

    assert "startTime" not in route.calls.last.request.url.params
    assert route.calls.last.request.url.params["count"] == "10"


@pytest.mark.parametrize("count", [0, 51])
async def test_get_changelog_page_rejects_invalid_count(
    api: respx.MockRouter, client: LinkedInClient, count: int
) -> None:
    route = api.get("/memberChangeLogs")

    with pytest.raises(ValueError, match="count must be between 1 and 50"):
        await client.get_changelog_page(count=count)

    assert route.call_count == 0


async def test_iter_changelog_follows_latest_processed_at_and_deduplicates(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberChangeLogs").mock(
        side_effect=[
            httpx.Response(
                200,
                json=changelog_page_json(
                    [
                        changelog_event_json(1, processed_at=100),
                        changelog_event_json(2, processed_at=200),
                    ]
                ),
            ),
            # startTime is inclusive, so event 2 is returned again.
            httpx.Response(
                200,
                json=changelog_page_json(
                    [
                        changelog_event_json(2, processed_at=200),
                        changelog_event_json(3, processed_at=300),
                    ]
                ),
            ),
            httpx.Response(
                200, json=changelog_page_json([changelog_event_json(3, processed_at=300)])
            ),
        ]
    )

    events = [event async for event in client.iter_changelog(start_time=50)]

    assert [event.id for event in events] == [1, 2, 3]
    assert [call.request.url.params["startTime"] for call in route.calls] == ["50", "200", "300"]


async def test_iter_changelog_stops_on_empty_page(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberChangeLogs").mock(
        return_value=httpx.Response(200, json=changelog_page_json([]))
    )

    assert [event async for event in client.iter_changelog()] == []
    assert route.call_count == 1


async def test_iter_changelog_stops_at_max_pages(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    pages = [
        httpx.Response(200, json=changelog_page_json([changelog_event_json(i, processed_at=i)]))
        for i in range(1, 5)
    ]
    route = api.get("/memberChangeLogs").mock(side_effect=pages)

    events = [event async for event in client.iter_changelog(max_pages=2)]

    assert [event.id for event in events] == [1, 2]
    assert route.call_count == 2


# Member authorizations API


async def test_get_member_authorizations_parses_response(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.get("/memberAuthorizations").mock(
        return_value=httpx.Response(
            200,
            json={
                "paging": {"start": 0, "count": 10, "links": []},
                "elements": [
                    {
                        "regulatedAt": 1698382869085,
                        "memberComplianceScopes": ["DMA"],
                        "memberComplianceAuthorizationKey": {
                            "developerApplication": "urn:li:developerApplication:1",
                            "member": "urn:li:person:abc",
                        },
                    }
                ],
            },
        )
    )

    authorizations = await client.get_member_authorizations()

    assert dict(route.calls.last.request.url.params) == {"q": "memberAndApplication"}
    assert len(authorizations) == 1
    authorization = authorizations[0]
    assert authorization.regulated_at == 1698382869085
    assert authorization.member_compliance_scopes == ["DMA"]
    assert authorization.member_compliance_authorization_key.member == "urn:li:person:abc"


async def test_enable_changelog_posts_empty_object(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    route = api.post("/memberAuthorizations").mock(return_value=httpx.Response(201))

    await client.enable_changelog()

    request = route.calls.last.request
    assert request.content == b"{}"
    assert request.headers["Content-Type"] == "application/json"


async def test_enable_changelog_raises_on_error(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.post("/memberAuthorizations").mock(
        return_value=httpx.Response(403, json={"message": "Not allowed", "status": 403})
    )

    with pytest.raises(PermissionDeniedError):
        await client.enable_changelog()


async def test_error_with_json_body_without_message_uses_body_text(
    api: respx.MockRouter, client: LinkedInClient
) -> None:
    api.get("/memberAuthorizations").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    with pytest.raises(ServerError) as exc_info:
        await client.get_member_authorizations()

    assert exc_info.value.message == '{"error":"internal"}'
