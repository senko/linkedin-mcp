"""Pydantic models for the raw LinkedIn Member Data Portability API responses."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, JsonValue
from pydantic.alias_generators import to_camel

type SnapshotRecord = dict[str, JsonValue]
"""One snapshot data row. Keys are human-readable column names such as "First Name"."""

type JsonObject = dict[str, JsonValue]
"""An arbitrary JSON object."""


def ms_to_datetime(timestamp_ms: int) -> datetime:
    """Convert an epoch timestamp in milliseconds to a timezone-aware UTC datetime.

    Args:
        timestamp_ms: Milliseconds since the Unix epoch.

    Returns:
        The corresponding UTC datetime.
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)


def datetime_to_ms(value: datetime) -> int:
    """Convert a datetime to an epoch timestamp in milliseconds.

    Naive datetimes are interpreted as UTC.

    Args:
        value: The datetime to convert.

    Returns:
        Milliseconds since the Unix epoch.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


class APIModel(BaseModel):
    """Base model that maps LinkedIn's camelCase JSON keys to snake_case attributes.

    Unknown fields are kept, so new API fields are not lost.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        extra="allow",
    )


class PagingLink(APIModel):
    """A link to an adjacent page of results.

    Attributes:
        rel: Link relation, "next" or "prev".
        href: Relative URL of the linked page.
        type: Media type of the linked page.
    """

    rel: str
    href: str
    type: str | None = None


class Paging(APIModel):
    """Pagination metadata of a collection response.

    Attributes:
        start: Index of this page (snapshot API) or offset of the first element.
        count: Requested page size.
        total: Total number of pages or elements. For snapshots this may undercount.
        links: Links to the previous and next pages.
    """

    start: int = 0
    count: int = 0
    total: int | None = None
    links: list[PagingLink] = []

    @property
    def has_next(self) -> bool:
        """Whether the response includes a link to a next page."""
        return any(link.rel == "next" for link in self.links)


class SnapshotSection(APIModel):
    """Data for one snapshot domain, as returned in one snapshot page.

    A domain can span several pages, and a single domain can return sections with
    different record layouts (for example, given and received recommendations).

    Attributes:
        snapshot_domain: Domain name, for example "INBOX" or "CONNECTIONS".
        snapshot_data: Data rows for the domain.
    """

    snapshot_domain: str
    snapshot_data: list[SnapshotRecord] = []


class SnapshotPage(APIModel):
    """One page of the Member Snapshot API response.

    Attributes:
        paging: Pagination metadata.
        elements: Snapshot sections on this page (in practice exactly one).
    """

    paging: Paging = Paging()
    elements: list[SnapshotSection] = []


class ChangelogEvent(APIModel):
    """One activity event from the Member Changelog API.

    Attributes:
        id: Unique identifier of the event record.
        captured_at: Time the event was captured, in epoch milliseconds.
        processed_at: Time the event was processed, in epoch milliseconds.
        resource_name: Name of the affected resource type, for example "messages".
        method: Resource method: CREATE, UPDATE, PARTIAL_UPDATE, DELETE or ACTION.
        config_version: Processing configuration version (for debugging).
        owner: URN of the member who owns the record.
        actor: URN of the member who performed the action.
        resource_id: Identifier of the affected resource.
        resource_uri: URI of the affected resource.
        method_name: Method name, only present for ACTION methods.
        activity: The original activity data.
        processed_activity: The activity decorated with related context.
        sibling_activities: Up to 10 previous activities on the same resource level.
        parent_sibling_activities: Up to 10 previous activities on the parent resource level.
        activity_id: Identifier shared by all records of the same captured activity.
        activity_status: SUCCESS, FAILURE or SUCCESSFUL_REPLAY.
    """

    id: int
    captured_at: int
    processed_at: int
    resource_name: str
    method: str
    config_version: int | None = None
    owner: str | None = None
    actor: str | None = None
    resource_id: str | None = None
    resource_uri: str | None = None
    method_name: str | None = None
    activity: JsonObject = {}
    processed_activity: JsonObject = {}
    sibling_activities: list[JsonValue] = []
    parent_sibling_activities: list[JsonValue] = []
    activity_id: str | None = None
    activity_status: str | None = None

    @property
    def captured_datetime(self) -> datetime:
        """The capture time as a UTC datetime."""
        return ms_to_datetime(self.captured_at)


class ChangelogPage(APIModel):
    """One page of the Member Changelog API response.

    Attributes:
        paging: Pagination metadata.
        elements: Changelog events on this page.
    """

    paging: Paging = Paging()
    elements: list[ChangelogEvent] = []


class MemberAuthorizationKey(APIModel):
    """Identifies the member and the application of a compliance authorization.

    Attributes:
        developer_application: URN of the developer application the member consented to.
        member: URN of the member whose events are archived.
    """

    developer_application: str
    member: str


class MemberAuthorization(APIModel):
    """Status of changelog archiving for the member.

    Attributes:
        member_compliance_authorization_key: The member and application this applies to.
        regulated_at: Epoch milliseconds since which activity is archived.
        member_compliance_scopes: Compliance products the member consented to ("DMA").
    """

    member_compliance_authorization_key: MemberAuthorizationKey
    regulated_at: int | None = None
    member_compliance_scopes: list[str] = []


class MemberAuthorizationPage(APIModel):
    """Response of the Member Authorizations finder.

    Attributes:
        paging: Pagination metadata.
        elements: Authorizations for the member and application.
    """

    paging: Paging = Paging()
    elements: list[MemberAuthorization] = []
