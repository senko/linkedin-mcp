from datetime import UTC, datetime, timedelta, timezone

from linkedin_mcp.models import (
    ChangelogEvent,
    Paging,
    SnapshotPage,
    datetime_to_ms,
    ms_to_datetime,
)
from tests.factories import changelog_event_json


def test_ms_to_datetime() -> None:
    assert ms_to_datetime(1574449632116) == datetime(2019, 11, 22, 19, 7, 12, 116000, tzinfo=UTC)


def test_datetime_to_ms_treats_naive_as_utc() -> None:
    assert datetime_to_ms(datetime(2019, 11, 22, 19, 7, 12, 116000)) == 1574449632116


def test_datetime_to_ms_respects_timezone() -> None:
    cet = timezone(timedelta(hours=1))

    assert datetime_to_ms(datetime(2019, 11, 22, 20, 7, 12, 116000, tzinfo=cet)) == 1574449632116


def test_paging_has_next() -> None:
    assert Paging.model_validate({"links": [{"rel": "next", "href": "/x"}]}).has_next
    assert not Paging.model_validate({"links": [{"rel": "prev", "href": "/x"}]}).has_next
    assert not Paging().has_next


def test_snapshot_page_keeps_unknown_fields() -> None:
    page = SnapshotPage.model_validate({"elements": [], "newField": 1})

    assert page.model_extra == {"newField": 1}


def test_changelog_event_parses_camel_case_and_defaults() -> None:
    body = changelog_event_json(5, processed_at=1574449662997, captured_at=1574449632331)
    del body["activity"]
    body["methodName"] = "markRead"

    event = ChangelogEvent.model_validate(body)

    assert event.captured_at == 1574449632331
    assert event.captured_datetime == ms_to_datetime(1574449632331)
    assert event.method_name == "markRead"
    assert event.activity == {}
    assert event.sibling_activities == []


def test_changelog_event_accepts_unprocessed_field_markers() -> None:
    # LinkedIn replaces fields it cannot process with marker strings and messages.
    body = changelog_event_json(6, processed_at=1)
    body["resourceId"] = "Unable_to_process_this_field."
    body["processedActivity"] = {"message": "Unable to process this event."}

    event = ChangelogEvent.model_validate(body)

    assert event.resource_id == "Unable_to_process_this_field."
    assert event.processed_activity == {"message": "Unable to process this event."}
