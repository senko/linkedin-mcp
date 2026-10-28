"""Builders for synthetic API payloads and snapshot rows used in tests."""

from collections.abc import Sequence

import httpx
from pydantic import JsonValue

from linkedin_mcp.models import ChangelogEvent, SnapshotRecord, SnapshotSection

NO_DATA_MESSAGE = "No data found for this domain and memberId."


def snapshot_page_json(
    domain: str,
    records: Sequence[SnapshotRecord],
    *,
    start: int = 0,
    links: Sequence[str] = (),
) -> dict[str, JsonValue]:
    """Build a Member Snapshot API page body."""
    return {
        "paging": {
            "start": start,
            "count": 10,
            "total": 2,
            "links": [
                {
                    "type": "application/json",
                    "rel": rel,
                    "href": f"/rest/memberSnapshotData?start={start}",
                }
                for rel in links
            ],
        },
        "elements": [{"snapshotDomain": domain, "snapshotData": list(records)}],
    }


def no_data_response(message: str = NO_DATA_MESSAGE) -> httpx.Response:
    """Build the 404 response LinkedIn uses to mark the end of snapshot data."""
    return httpx.Response(404, json={"code": "", "message": message, "status": 404})


def changelog_event_json(
    event_id: int,
    *,
    processed_at: int,
    captured_at: int | None = None,
    resource_name: str = "messages",
    method: str = "CREATE",
) -> dict[str, JsonValue]:
    """Build a Member Changelog API event body."""
    return {
        "id": event_id,
        "capturedAt": captured_at if captured_at is not None else processed_at - 100,
        "processedAt": processed_at,
        "configVersion": 1,
        "owner": "urn:li:person:owner",
        "actor": "urn:li:person:actor",
        "resourceName": resource_name,
        "resourceId": f"resource-{event_id}",
        "resourceUri": f"/{resource_name}/resource-{event_id}",
        "method": method,
        "activity": {"id": f"resource-{event_id}"},
        "processedActivity": {"id": f"resource-{event_id}"},
        "activityId": f"activity-{event_id}",
        "activityStatus": "SUCCESS",
    }


def changelog_page_json(events: Sequence[dict[str, JsonValue]]) -> dict[str, JsonValue]:
    """Build a Member Changelog API page body."""
    return {"paging": {"start": 0, "count": 10, "links": []}, "elements": list(events)}


def changelog_event(
    event_id: int,
    *,
    captured_at: int,
    resource_name: str = "messages",
) -> ChangelogEvent:
    """Build a parsed changelog event."""
    return ChangelogEvent.model_validate(
        changelog_event_json(
            event_id,
            processed_at=captured_at + 100,
            captured_at=captured_at,
            resource_name=resource_name,
        )
    )


def section(domain: str, records: Sequence[SnapshotRecord]) -> SnapshotSection:
    """Build a parsed snapshot section."""
    return SnapshotSection(snapshot_domain=domain, snapshot_data=list(records))


def inbox_record(
    conversation_id: str,
    date: str,
    *,
    sender: str = "Ana Anić",
    to: str = "Ivo Ivić",
    content: str = "Hello",
    subject: str = "",
    title: str = "",
    folder: str = "INBOX",
    attachments: str = "",
) -> SnapshotRecord:
    """Build an INBOX snapshot row."""
    return {
        "CONVERSATION ID": conversation_id,
        "CONVERSATION TITLE": title,
        "FROM": sender,
        "SENDER PROFILE URL": "https://example.com/in/sender",
        "TO": to,
        "RECIPIENT PROFILE URLS": "https://example.com/in/recipient",
        "DATE": date,
        "SUBJECT": subject,
        "CONTENT": content,
        "FOLDER": folder,
        "ATTACHMENTS": attachments,
    }


def connection_record(
    first_name: str,
    last_name: str,
    *,
    company: str = "Acme",
    position: str = "Engineer",
    connected_on: str = "05 Mar 2024",
    email: str = "",
) -> SnapshotRecord:
    """Build a CONNECTIONS snapshot row."""
    return {
        "First Name": first_name,
        "Last Name": last_name,
        "URL": f"https://example.com/in/{first_name.lower()}",
        "Email Address": email,
        "Company": company,
        "Position": position,
        "Connected On": connected_on,
    }


def post_record(
    date: str, commentary: str, *, visibility: str = "MEMBER_NETWORK"
) -> SnapshotRecord:
    """Build a MEMBER_SHARE_INFO snapshot row."""
    return {
        "Date": date,
        "ShareLink": "https://example.com/feed/update/urn:li:share:1",
        "ShareCommentary": commentary,
        "SharedUrl": "",
        "MediaUrl": "",
        "Visibility": visibility,
    }
