from datetime import UTC, date, datetime

import pytest

from linkedin_mcp.models import SnapshotRecord
from linkedin_mcp.records import (
    CONNECTION_DATE_FORMAT,
    INBOX_DATE_FORMAT,
    Connection,
    Message,
    Post,
    Profile,
    field_text,
    matches,
    normalize_text,
    parse_date,
    parse_datetime,
    split_list,
)
from tests.factories import connection_record, inbox_record, post_record

# Helpers


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        ({"Name": "  Python  "}, "Python"),
        ({"Name": None}, ""),
        ({}, ""),
        ({"Name": 42}, "42"),
    ],
)
def test_field_text(record: SnapshotRecord, expected: str) -> None:
    assert field_text(record, "Name") == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", []),
        ("Ana Anić", ["Ana Anić"]),
        ("Ana Anić,Ivo Ivić", ["Ana Anić", "Ivo Ivić"]),
        (" a , ,b ", ["a", "b"]),
    ],
)
def test_split_list(value: str, expected: list[str]) -> None:
    assert split_list(value) == expected


def test_parse_datetime_returns_utc() -> None:
    assert parse_datetime("2021-07-14 09:30:15 UTC", INBOX_DATE_FORMAT) == datetime(
        2021, 7, 14, 9, 30, 15, tzinfo=UTC
    )


def test_parse_datetime_tries_formats_in_order() -> None:
    parsed = parse_datetime("2024-05-01", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")

    assert parsed == datetime(2024, 5, 1, tzinfo=UTC)


@pytest.mark.parametrize("value", ["", "yesterday", "14/07/2021"])
def test_parse_datetime_returns_none_for_unknown_format(value: str) -> None:
    assert parse_datetime(value, INBOX_DATE_FORMAT) is None


def test_parse_date() -> None:
    assert parse_date("15 Aug 2025", CONNECTION_DATE_FORMAT) == date(2025, 8, 15)
    assert parse_date("", CONNECTION_DATE_FORMAT) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Đurđa Šarić", "durda saric"),
        ("ŽELJKO Čolić", "zeljko colic"),
        ("Łukasz Møller", "lukasz moller"),
        ("Straße", "strasse"),
    ],
)
def test_normalize_text(value: str, expected: str) -> None:
    assert normalize_text(value) == expected


def test_matches_ignores_case_and_accents() -> None:
    assert matches("saric", "Đurđa Šarić")
    assert matches("ŠARIĆ", "durda saric")
    assert matches("acme", "Nothing", "ACME Corp")
    assert not matches("globex", "ACME Corp")


# Message


def test_message_from_record() -> None:
    record = inbox_record(
        "2-abc",
        "2022-03-10 14:05:00 UTC",
        sender="Ana Anić",
        to="Ivo Ivić,Eva Ević",
        content="Pozdrav",
        subject="Hi",
        title="Project",
        folder="ARCHIVE",
        attachments="https://example.com/a,https://example.com/b",
    )
    record["RECIPIENT PROFILE URLS"] = "https://example.com/in/ivo,https://example.com/in/eva"

    message = Message.from_record(record)

    assert message == Message(
        conversation_id="2-abc",
        conversation_title="Project",
        sender="Ana Anić",
        sender_profile_url="https://example.com/in/sender",
        recipients=["Ivo Ivić", "Eva Ević"],
        recipient_profile_urls=["https://example.com/in/ivo", "https://example.com/in/eva"],
        sent_at=datetime(2022, 3, 10, 14, 5, 0, tzinfo=UTC),
        subject="Hi",
        content="Pozdrav",
        folder="ARCHIVE",
        attachments=["https://example.com/a", "https://example.com/b"],
    )


def test_message_from_record_with_missing_fields() -> None:
    message = Message.from_record({"CONTENT": "only content"})

    assert message.content == "only content"
    assert message.conversation_id == ""
    assert message.recipients == []
    assert message.sent_at is None


# Connection


def test_connection_from_record() -> None:
    record = connection_record(
        "Ana",
        "Anić",
        company="Acme",
        position="CTO",
        connected_on="05 Mar 2024",
        email="ana@example.com",
    )

    connection = Connection.from_record(record)

    assert connection.first_name == "Ana"
    assert connection.last_name == "Anić"
    assert connection.full_name == "Ana Anić"
    assert connection.profile_url == "https://example.com/in/ana"
    assert connection.email == "ana@example.com"
    assert connection.company == "Acme"
    assert connection.position == "CTO"
    assert connection.connected_on == date(2024, 3, 5)


def test_connection_without_email_or_name() -> None:
    connection = Connection.from_record(connection_record("", "", email="", connected_on="bad"))

    assert connection.email is None
    assert connection.full_name == ""
    assert connection.connected_on is None


# Profile


def test_profile_from_record() -> None:
    record: SnapshotRecord = {
        "First Name": "Ana",
        "Last Name": "Anić",
        "Maiden Name": "",
        "Headline": "Engineer at Acme",
        "Summary": "About me",
        "Industry": "Software Development",
        "Geo Location": "Example City",
        "Address": "",
        "Zip Code": "12345",
        "Birth Date": "",
        "Websites": "[PERSONAL:https://example.com]",
        "Twitter Handles": "[ana]",
        "Instant Messengers": "",
    }

    profile = Profile.from_record(record)

    assert profile.first_name == "Ana"
    assert profile.headline == "Engineer at Acme"
    assert profile.summary == "About me"
    assert profile.industry == "Software Development"
    assert profile.location == "Example City"
    assert profile.zip_code == "12345"
    assert profile.websites == "[PERSONAL:https://example.com]"
    assert profile.twitter_handles == "[ana]"
    assert profile.maiden_name == ""


# Post


def test_post_from_record_keeps_raw_row() -> None:
    record = post_record("2024-05-10 10:12:44", "My first post")
    record["Extra Column"] = "kept"

    post = Post.from_record(record)

    assert post.posted_at == datetime(2024, 5, 10, 10, 12, 44, tzinfo=UTC)
    assert post.commentary == "My first post"
    assert post.share_link == "https://example.com/feed/update/urn:li:share:1"
    assert post.visibility == "MEMBER_NETWORK"
    assert post.raw["Extra Column"] == "kept"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2024-05-10 10:12:44 UTC", datetime(2024, 5, 10, 10, 12, 44, tzinfo=UTC)),
        ("2024-05-10", datetime(2024, 5, 10, tzinfo=UTC)),
        ("May 10, 2024", None),
    ],
)
def test_post_date_formats(value: str, expected: datetime | None) -> None:
    assert Post.from_record(post_record(value, "text")).posted_at == expected
