"""Typed records parsed from snapshot data rows.

Snapshot rows are flat dictionaries with human-readable keys (the same columns as
LinkedIn's "Download your data" CSV export). Each domain uses its own date format.
Missing keys are treated as empty strings, so a changed export layout degrades to
empty fields instead of failing.
"""

import unicodedata
from datetime import UTC, date, datetime

from pydantic import BaseModel, JsonValue

from linkedin_mcp.models import SnapshotRecord

INBOX_DATE_FORMAT = "%Y-%m-%d %H:%M:%S UTC"
CONNECTION_DATE_FORMAT = "%d %b %Y"
POST_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d")

_EXTRA_FOLDINGS = str.maketrans({"đ": "d", "ł": "l", "ø": "o", "æ": "ae", "œ": "oe"})


def field_text(record: SnapshotRecord, key: str) -> str:
    """Return a record field as a stripped string.

    Args:
        record: Snapshot data row.
        key: Column name.

    Returns:
        The value as a string, or "" if the key is missing or the value is null.
    """
    value = record.get(key)
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def split_list(value: str) -> list[str]:
    """Split a comma-separated field into its non-empty parts.

    Args:
        value: Field value such as "Ana Anić,Ivo Ivić".

    Returns:
        The stripped, non-empty parts.
    """
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_datetime(value: str, *formats: str) -> datetime | None:
    """Parse a timestamp in the first matching format, as UTC.

    Args:
        value: Timestamp string.
        *formats: `strptime` formats to try in order.

    Returns:
        A timezone-aware UTC datetime, or None if no format matches.
    """
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def parse_date(value: str, fmt: str) -> date | None:
    """Parse a date string.

    Args:
        value: Date string.
        fmt: `strptime` format.

    Returns:
        The date, or None if the value does not match the format.
    """
    try:
        return datetime.strptime(value, fmt).date()
    except ValueError:
        return None


def normalize_text(value: str) -> str:
    """Normalize text for case- and accent-insensitive matching.

    Args:
        value: Text to normalize.

    Returns:
        Case-folded text without diacritics ("Đurđa Šarić" becomes "durda saric").
    """
    decomposed = unicodedata.normalize("NFKD", value.casefold().translate(_EXTRA_FOLDINGS))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def matches(query: str, *fields: str) -> bool:
    """Check whether any field contains the query (case- and accent-insensitive).

    Args:
        query: Search text.
        *fields: Text fields to search.

    Returns:
        True if the normalized query is a substring of any normalized field.
    """
    needle = normalize_text(query)
    return any(needle in normalize_text(field) for field in fields)


class Message(BaseModel):
    """A message from the INBOX snapshot domain.

    Attributes:
        conversation_id: Identifier of the conversation the message belongs to.
        conversation_title: Conversation title (usually empty).
        sender: Display name of the sender.
        sender_profile_url: LinkedIn profile URL of the sender.
        recipients: Display names of the recipients.
        recipient_profile_urls: LinkedIn profile URLs of the recipients.
        sent_at: Send time in UTC, or None if it could not be parsed.
        subject: Message subject (usually empty).
        content: Message body.
        folder: Mailbox folder, for example "INBOX", "ARCHIVE" or "SPAM".
        attachments: Attachment URLs.
    """

    conversation_id: str
    conversation_title: str
    sender: str
    sender_profile_url: str
    recipients: list[str]
    recipient_profile_urls: list[str]
    sent_at: datetime | None
    subject: str
    content: str
    folder: str
    attachments: list[str]

    @classmethod
    def from_record(cls, record: SnapshotRecord) -> Message:
        """Build a message from an INBOX snapshot row.

        Args:
            record: INBOX snapshot data row.

        Returns:
            The parsed message.
        """
        return cls(
            conversation_id=field_text(record, "CONVERSATION ID"),
            conversation_title=field_text(record, "CONVERSATION TITLE"),
            sender=field_text(record, "FROM"),
            sender_profile_url=field_text(record, "SENDER PROFILE URL"),
            recipients=split_list(field_text(record, "TO")),
            recipient_profile_urls=split_list(field_text(record, "RECIPIENT PROFILE URLS")),
            sent_at=parse_datetime(field_text(record, "DATE"), INBOX_DATE_FORMAT),
            subject=field_text(record, "SUBJECT"),
            content=field_text(record, "CONTENT"),
            folder=field_text(record, "FOLDER"),
            attachments=split_list(field_text(record, "ATTACHMENTS")),
        )


class ConversationSummary(BaseModel):
    """Overview of a conversation, without its messages.

    Attributes:
        conversation_id: Identifier of the conversation.
        title: Conversation title (usually empty).
        participants: Display names of everyone who sent or received a message.
        message_count: Number of messages in the conversation.
        folder: Folder of the latest message.
        first_message_at: Time of the first message.
        last_message_at: Time of the latest message.
        last_message_sender: Sender of the latest message.
        last_message_preview: Start of the latest message body.
    """

    conversation_id: str
    title: str
    participants: list[str]
    message_count: int
    folder: str
    first_message_at: datetime | None
    last_message_at: datetime | None
    last_message_sender: str
    last_message_preview: str


class Conversation(ConversationSummary):
    """A conversation with its messages.

    Attributes:
        messages: Messages in chronological order (possibly only the most recent ones).
    """

    messages: list[Message]


class Connection(BaseModel):
    """A first-degree connection from the CONNECTIONS snapshot domain.

    Attributes:
        first_name: First name.
        last_name: Last name.
        profile_url: LinkedIn profile URL.
        email: Email address, only present if the connection allows exporting it.
        company: Current company.
        position: Current position.
        connected_on: Date the connection was made.
    """

    first_name: str
    last_name: str
    profile_url: str
    email: str | None
    company: str
    position: str
    connected_on: date | None

    @property
    def full_name(self) -> str:
        """First and last name separated by a space."""
        return f"{self.first_name} {self.last_name}".strip()

    @classmethod
    def from_record(cls, record: SnapshotRecord) -> Connection:
        """Build a connection from a CONNECTIONS snapshot row.

        Args:
            record: CONNECTIONS snapshot data row.

        Returns:
            The parsed connection.
        """
        return cls(
            first_name=field_text(record, "First Name"),
            last_name=field_text(record, "Last Name"),
            profile_url=field_text(record, "URL"),
            email=field_text(record, "Email Address") or None,
            company=field_text(record, "Company"),
            position=field_text(record, "Position"),
            connected_on=parse_date(field_text(record, "Connected On"), CONNECTION_DATE_FORMAT),
        )


class Profile(BaseModel):
    """Basic profile information from the PROFILE snapshot domain.

    Attributes:
        first_name: First name.
        last_name: Last name.
        maiden_name: Maiden name.
        headline: Profile headline.
        summary: Profile "About" text.
        industry: Industry.
        location: Geographic location.
        address: Postal address.
        zip_code: Postal code.
        birth_date: Birth date as shown in the export.
        websites: Websites as shown in the export.
        twitter_handles: Twitter handles as shown in the export.
        instant_messengers: Instant messenger accounts as shown in the export.
    """

    first_name: str
    last_name: str
    maiden_name: str
    headline: str
    summary: str
    industry: str
    location: str
    address: str
    zip_code: str
    birth_date: str
    websites: str
    twitter_handles: str
    instant_messengers: str

    @classmethod
    def from_record(cls, record: SnapshotRecord) -> Profile:
        """Build a profile from a PROFILE snapshot row.

        Args:
            record: PROFILE snapshot data row.

        Returns:
            The parsed profile.
        """
        return cls(
            first_name=field_text(record, "First Name"),
            last_name=field_text(record, "Last Name"),
            maiden_name=field_text(record, "Maiden Name"),
            headline=field_text(record, "Headline"),
            summary=field_text(record, "Summary"),
            industry=field_text(record, "Industry"),
            location=field_text(record, "Geo Location"),
            address=field_text(record, "Address"),
            zip_code=field_text(record, "Zip Code"),
            birth_date=field_text(record, "Birth Date"),
            websites=field_text(record, "Websites"),
            twitter_handles=field_text(record, "Twitter Handles"),
            instant_messengers=field_text(record, "Instant Messengers"),
        )


class Post(BaseModel):
    """A post (share) from the MEMBER_SHARE_INFO snapshot domain.

    The column names follow LinkedIn's "Shares.csv" export layout. They are not yet
    verified against the API, so the original row is kept in `raw`.

    Attributes:
        posted_at: Post time in UTC, or None if it could not be parsed.
        share_link: URL of the post on LinkedIn.
        commentary: Post text.
        shared_url: URL of shared external content.
        media_url: URL of attached media.
        visibility: Post visibility, for example "MEMBER_NETWORK".
        raw: The original snapshot row.
    """

    posted_at: datetime | None
    share_link: str
    commentary: str
    shared_url: str
    media_url: str
    visibility: str
    raw: dict[str, JsonValue]

    @classmethod
    def from_record(cls, record: SnapshotRecord) -> Post:
        """Build a post from a MEMBER_SHARE_INFO snapshot row.

        Args:
            record: MEMBER_SHARE_INFO snapshot data row.

        Returns:
            The parsed post.
        """
        return cls(
            posted_at=parse_datetime(field_text(record, "Date"), *POST_DATE_FORMATS),
            share_link=field_text(record, "ShareLink"),
            commentary=field_text(record, "ShareCommentary"),
            shared_url=field_text(record, "SharedUrl"),
            media_url=field_text(record, "MediaUrl"),
            visibility=field_text(record, "Visibility"),
            raw=record,
        )
