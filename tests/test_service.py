from collections.abc import AsyncIterator, Sequence
from datetime import UTC, date, datetime
from typing import Any

import pytest

from linkedin_mcp.models import (
    ChangelogEvent,
    MemberAuthorization,
    MemberAuthorizationKey,
    SnapshotSection,
)
from linkedin_mcp.service import (
    PREVIEW_LENGTH,
    LinkedInService,
    as_utc,
    paginate,
)
from tests.factories import (
    changelog_event,
    connection_record,
    inbox_record,
    post_record,
    section,
)


class FakeClock:
    """A manually advanced clock."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FakeAPI:
    """In-memory stand-in for `LinkedInClient` that records calls."""

    def __init__(
        self,
        snapshots: dict[str | None, list[SnapshotSection]] | None = None,
        events: Sequence[ChangelogEvent] = (),
        authorizations: Sequence[MemberAuthorization] = (),
    ) -> None:
        self.snapshots = snapshots or {}
        self.events = list(events)
        self.authorizations = list(authorizations)
        self.snapshot_calls: list[str | None] = []
        self.changelog_calls: list[int | None] = []
        self.changelog_enabled = False

    async def get_snapshot(self, domain: str | None = None) -> list[SnapshotSection]:
        self.snapshot_calls.append(domain)
        return self.snapshots.get(domain, [])

    async def iter_changelog(
        self, *, start_time: int | None = None
    ) -> AsyncIterator[ChangelogEvent]:
        self.changelog_calls.append(start_time)
        for event in self.events:
            yield event

    async def get_member_authorizations(self) -> list[MemberAuthorization]:
        return self.authorizations

    async def enable_changelog(self) -> None:
        self.changelog_enabled = True


def make_service(api: FakeAPI, clock: FakeClock | None = None) -> LinkedInService:
    return LinkedInService(api, cache_ttl=60, clock=clock or FakeClock())


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# Three conversations: "c1" (2 messages, newest activity), "c2" (archived), "c3" (spam).
INBOX_SECTIONS = [
    section(
        "INBOX",
        [
            inbox_record(
                "c1", "2024-01-01 10:00:00 UTC", sender="Ana Anić", to="Me", content="Bok"
            ),
            inbox_record(
                "c2",
                "2023-06-01 09:00:00 UTC",
                sender="Đuro Đurić",
                to="Me",
                content="Ponuda za posao",
                folder="ARCHIVE",
            ),
        ],
    ),
    section(
        "INBOX",
        [
            inbox_record(
                "c1",
                "2024-03-01 12:00:00 UTC",
                sender="Me",
                to="Ana Anić",
                content="x" * 500,
                title="Lunch",
            ),
            inbox_record(
                "c3",
                "2022-01-01 08:00:00 UTC",
                sender="Spammer",
                to="Me",
                content="Buy now",
                folder="SPAM",
                subject="Offer",
            ),
            inbox_record(
                "c3", "not a date", sender="Spammer", to="Me", content="Undated", folder="SPAM"
            ),
        ],
    ),
]


@pytest.fixture
def inbox_service() -> LinkedInService:
    return make_service(FakeAPI({"INBOX": INBOX_SECTIONS}))


# Caching


async def test_get_sections_caches_per_domain() -> None:
    api = FakeAPI({"SKILLS": [section("SKILLS", [{"Name": "Python"}])]})
    service = make_service(api)

    first = await service.get_sections("SKILLS")
    second = await service.get_sections("SKILLS")
    await service.get_sections(None)

    assert first == second
    assert api.snapshot_calls == ["SKILLS", None]


async def test_get_sections_refetches_after_ttl() -> None:
    api = FakeAPI()
    clock = FakeClock()
    service = make_service(api, clock)

    await service.get_sections("SKILLS")
    clock.now = 61
    await service.get_sections("SKILLS")

    assert api.snapshot_calls == ["SKILLS", "SKILLS"]


async def test_refresh_and_clear_cache_refetch() -> None:
    api = FakeAPI()
    service = make_service(api)

    await service.get_sections("SKILLS")
    await service.get_sections("SKILLS", refresh=True)
    service.clear_cache()
    await service.get_sections("SKILLS")

    assert api.snapshot_calls == ["SKILLS", "SKILLS", "SKILLS"]


# Generic domains


async def test_get_records_flattens_sections() -> None:
    api = FakeAPI(
        {
            "ENDORSEMENTS": [
                section("ENDORSEMENTS", [{"Endorser First Name": "Ana"}]),
                section("ENDORSEMENTS", [{"Endorsee First Name": "Ivo"}]),
            ]
        }
    )

    records = await make_service(api).get_records("ENDORSEMENTS")

    assert records == [{"Endorser First Name": "Ana"}, {"Endorsee First Name": "Ivo"}]


async def test_list_domains_aggregates_counts_and_adds_descriptions() -> None:
    api = FakeAPI(
        {
            None: [
                section("SKILLS", [{"Name": "a"}, {"Name": "b"}]),
                section("INBOX", [{"CONTENT": "1"}]),
                section("INBOX", [{"CONTENT": "2"}, {"CONTENT": "3"}]),
                section("NEW_DOMAIN", []),
            ]
        }
    )

    domains = await make_service(api).list_domains()

    assert [(d.domain, d.record_count) for d in domains] == [
        ("INBOX", 3),
        ("NEW_DOMAIN", 0),
        ("SKILLS", 2),
    ]
    assert domains[0].description == "Messages sent and received."
    assert domains[1].description == ""


async def test_get_domain_records_paginates() -> None:
    api = FakeAPI({"SKILLS": [section("SKILLS", [{"Name": str(i)} for i in range(5)])]})

    page = await make_service(api).get_domain_records("SKILLS", offset=1, limit=2)

    assert page.total == 5
    assert page.offset == 1
    assert page.items == [{"Name": "1"}, {"Name": "2"}]


# Profile


async def test_get_profile() -> None:
    api = FakeAPI({"PROFILE": [section("PROFILE", [{"First Name": "Ana", "Headline": "CTO"}])]})

    profile = await make_service(api).get_profile()

    assert profile is not None
    assert profile.first_name == "Ana"
    assert profile.headline == "CTO"


async def test_get_profile_returns_none_without_data() -> None:
    assert await make_service(FakeAPI()).get_profile() is None


# Messages and conversations


async def test_get_messages_sorts_newest_first_with_undated_last(
    inbox_service: LinkedInService,
) -> None:
    messages = await inbox_service.get_messages()

    assert [m.content[:7] for m in messages] == [
        "xxxxxxx",
        "Bok",
        "Ponuda ",
        "Buy now",
        "Undated",
    ]


async def test_list_conversations_summarizes_and_sorts(inbox_service: LinkedInService) -> None:
    page = await inbox_service.list_conversations()

    assert page.total == 3
    assert [c.conversation_id for c in page.items] == ["c1", "c2", "c3"]
    c1 = page.items[0]
    assert c1.title == "Lunch"
    assert c1.participants == ["Ana Anić", "Me"]
    assert c1.message_count == 2
    assert c1.folder == "INBOX"
    assert c1.first_message_at == utc(2024, 1, 1, 10)
    assert c1.last_message_at == utc(2024, 3, 1, 12)
    assert c1.last_message_sender == "Me"
    assert c1.last_message_preview == "x" * PREVIEW_LENGTH


async def test_list_conversations_puts_undated_messages_first_in_conversation(
    inbox_service: LinkedInService,
) -> None:
    page = await inbox_service.list_conversations(folder="SPAM")

    c3 = page.items[0]
    assert c3.first_message_at is None
    assert c3.last_message_at == utc(2022, 1, 1, 8)
    assert c3.last_message_preview == "Buy now"


@pytest.mark.parametrize(
    ("kwargs", "expected_ids"),
    [
        ({"folder": "archive"}, ["c2"]),
        ({"participant": "djuro"}, []),
        ({"participant": "duro duric"}, ["c2"]),
        ({"participant": "ANA"}, ["c1"]),
        ({"since": datetime(2023, 6, 1, 9)}, ["c1", "c2"]),
        ({"since": utc(2024, 1, 2)}, ["c1"]),
        ({"folder": "INBOX", "participant": "Đuro"}, []),
    ],
)
async def test_list_conversations_filters(
    inbox_service: LinkedInService, kwargs: dict[str, Any], expected_ids: list[str]
) -> None:
    page = await inbox_service.list_conversations(**kwargs)

    assert [c.conversation_id for c in page.items] == expected_ids


async def test_list_conversations_paginates(inbox_service: LinkedInService) -> None:
    page = await inbox_service.list_conversations(offset=1, limit=1)

    assert page.total == 3
    assert page.offset == 1
    assert [c.conversation_id for c in page.items] == ["c2"]


async def test_get_conversation_returns_messages_in_order(inbox_service: LinkedInService) -> None:
    conversation = await inbox_service.get_conversation("c1")

    assert conversation is not None
    assert conversation.message_count == 2
    assert [m.sent_at for m in conversation.messages] == [utc(2024, 1, 1, 10), utc(2024, 3, 1, 12)]


async def test_get_conversation_limit_returns_most_recent(inbox_service: LinkedInService) -> None:
    conversation = await inbox_service.get_conversation("c1", limit=1)

    assert conversation is not None
    assert conversation.message_count == 2
    assert [m.sender for m in conversation.messages] == ["Me"]


async def test_get_conversation_zero_limit_returns_no_messages(
    inbox_service: LinkedInService,
) -> None:
    conversation = await inbox_service.get_conversation("c1", limit=0)

    assert conversation is not None
    assert conversation.messages == []


async def test_get_conversation_unknown_id(inbox_service: LinkedInService) -> None:
    assert await inbox_service.get_conversation("missing") is None


@pytest.mark.parametrize(
    ("query", "kwargs", "expected"),
    [
        ("ponuda", {}, ["Ponuda za posao"]),
        ("offer", {}, ["Buy now"]),
        ("lunch", {}, ["x" * 500]),
        (None, {"sender": "spammer"}, ["Buy now", "Undated"]),
        (None, {"folder": "spam"}, ["Buy now", "Undated"]),
        (None, {"since": utc(2024, 1, 1, 10)}, ["x" * 500, "Bok"]),
        (None, {"until": utc(2024, 1, 1, 10)}, ["Ponuda za posao", "Buy now"]),
        (
            None,
            {"since": datetime(2023, 1, 1), "until": datetime(2024, 2, 1)},
            ["Bok", "Ponuda za posao"],
        ),
        ("bok", {"sender": "Ana"}, ["Bok"]),
        ("bok", {"sender": "Me"}, []),
    ],
)
async def test_search_messages_filters(
    inbox_service: LinkedInService,
    query: str | None,
    kwargs: dict[str, Any],
    expected: list[str],
) -> None:
    page = await inbox_service.search_messages(query, **kwargs)

    assert [m.content for m in page.items] == expected
    assert page.total == len(expected)


async def test_search_messages_paginates(inbox_service: LinkedInService) -> None:
    page = await inbox_service.search_messages(offset=4, limit=10)

    assert page.total == 5
    assert [m.content for m in page.items] == ["Undated"]


# Connections


CONNECTION_SECTIONS = [
    section(
        "CONNECTIONS",
        [
            connection_record(
                "Ana",
                "Anić",
                company="Acme",
                position="CTO",
                connected_on="05 Mar 2024",
                email="ana@example.com",
            ),
            connection_record(
                "Ivo", "Ivić", company="Globex", position="Designer", connected_on="10 Jan 2020"
            ),
            connection_record(
                "Šime", "Šimić", company="Acme Labs", position="Engineer", connected_on="?"
            ),
            connection_record(
                "Eva", "Ević", company="Initech", position="Sales", connected_on="15 Aug 2025"
            ),
        ],
    )
]


@pytest.fixture
def connections_service() -> LinkedInService:
    return make_service(FakeAPI({"CONNECTIONS": CONNECTION_SECTIONS}))


async def test_search_connections_sorts_newest_first(
    connections_service: LinkedInService,
) -> None:
    page = await connections_service.search_connections()

    assert page.total == 4
    assert [c.first_name for c in page.items] == ["Eva", "Ana", "Ivo", "Šime"]


@pytest.mark.parametrize(
    ("query", "kwargs", "expected"),
    [
        ("sime", {}, ["Šime"]),
        ("designer", {}, ["Ivo"]),
        ("acme", {}, ["Ana", "Šime"]),
        ("ana@example", {}, ["Ana"]),
        ("ana anic", {}, ["Ana"]),
        (None, {"company": "acme"}, ["Ana", "Šime"]),
        ("engineer", {"company": "acme"}, ["Šime"]),
        (None, {"connected_since": date(2024, 3, 5)}, ["Eva", "Ana"]),
    ],
)
async def test_search_connections_filters(
    connections_service: LinkedInService,
    query: str | None,
    kwargs: dict[str, Any],
    expected: list[str],
) -> None:
    page = await connections_service.search_connections(query, **kwargs)

    assert [c.first_name for c in page.items] == expected


async def test_search_connections_paginates(connections_service: LinkedInService) -> None:
    page = await connections_service.search_connections(offset=1, limit=2)

    assert page.total == 4
    assert [c.first_name for c in page.items] == ["Ana", "Ivo"]


# Posts


POST_SECTIONS = [
    section(
        "MEMBER_SHARE_INFO",
        [
            post_record("2023-01-01 10:00:00", "Hiring engineers"),
            post_record("2024-06-01 10:00:00", "Conference talk"),
            post_record("unknown", "Undated post"),
        ],
    )
]


async def test_list_posts_sorts_newest_first() -> None:
    service = make_service(FakeAPI({"MEMBER_SHARE_INFO": POST_SECTIONS}))

    page = await service.list_posts()

    assert [p.commentary for p in page.items] == [
        "Conference talk",
        "Hiring engineers",
        "Undated post",
    ]


async def test_list_posts_filters() -> None:
    service = make_service(FakeAPI({"MEMBER_SHARE_INFO": POST_SECTIONS}))

    by_query = await service.list_posts("HIRING")
    by_date = await service.list_posts(since=datetime(2024, 1, 1))

    assert [p.commentary for p in by_query.items] == ["Hiring engineers"]
    assert [p.commentary for p in by_date.items] == ["Conference talk"]


async def test_list_posts_without_data() -> None:
    page = await make_service(FakeAPI()).list_posts()

    assert page.total == 0
    assert page.items == []


# Changelog


async def test_get_recent_activity_sorts_newest_first_and_passes_start_time() -> None:
    api = FakeAPI(
        events=[
            changelog_event(1, captured_at=1000),
            changelog_event(2, captured_at=3000, resource_name="ugcPosts"),
            changelog_event(3, captured_at=2000),
        ]
    )
    service = make_service(api)

    page = await service.get_recent_activity(since=datetime(2019, 11, 22, 19, 7, 12, 116000))

    assert [e.id for e in page.items] == [2, 3, 1]
    assert api.changelog_calls == [1574449632116]


async def test_get_recent_activity_filters_by_resource_name() -> None:
    api = FakeAPI(
        events=[
            changelog_event(1, captured_at=1000),
            changelog_event(2, captured_at=3000, resource_name="ugcPosts"),
        ]
    )

    page = await make_service(api).get_recent_activity(resource_name="MESSAGES")

    assert [e.id for e in page.items] == [1]
    assert api.changelog_calls == [None]


async def test_get_recent_activity_is_not_cached() -> None:
    api = FakeAPI(events=[changelog_event(1, captured_at=1000)])
    service = make_service(api)

    await service.get_recent_activity()
    await service.get_recent_activity()

    assert len(api.changelog_calls) == 2


async def test_get_recent_activity_paginates() -> None:
    api = FakeAPI(events=[changelog_event(i, captured_at=i * 1000) for i in range(1, 6)])

    page = await make_service(api).get_recent_activity(offset=1, limit=2)

    assert page.total == 5
    assert [e.id for e in page.items] == [4, 3]


# Authorizations


async def test_authorizations_and_enable_changelog_delegate_to_api() -> None:
    authorization = MemberAuthorization(
        member_compliance_authorization_key=MemberAuthorizationKey(
            developer_application="urn:li:developerApplication:1", member="urn:li:person:a"
        ),
        regulated_at=1,
        member_compliance_scopes=["DMA"],
    )
    api = FakeAPI(authorizations=[authorization])
    service = make_service(api)

    assert await service.get_authorizations() == [authorization]
    await service.enable_changelog()
    assert api.changelog_enabled


# Helpers


def test_paginate() -> None:
    page = paginate([1, 2, 3], 2, 5)

    assert page.total == 3
    assert page.offset == 2
    assert page.items == [3]


def test_paginate_past_end() -> None:
    assert paginate([1, 2, 3], 10, 5).items == []


@pytest.mark.parametrize(("offset", "limit"), [(-1, 5), (0, -1)])
def test_paginate_rejects_negative_values(offset: int, limit: int) -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        paginate([1], offset, limit)


def test_as_utc() -> None:
    aware = utc(2024, 1, 1)

    assert as_utc(datetime(2024, 1, 1)) == aware
    assert as_utc(aware) is aware


async def test_conversation_participants_skip_empty_names() -> None:
    api = FakeAPI(
        {
            "INBOX": [
                section(
                    "INBOX", [inbox_record("c1", "2024-01-01 10:00:00 UTC", sender="", to="Me")]
                )
            ]
        }
    )

    page = await make_service(api).list_conversations()

    assert page.items[0].participants == ["Me"]
