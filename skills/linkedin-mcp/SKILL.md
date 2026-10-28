---
name: linkedin-mcp
description: How to use the linkedin MCP server tools to read the user's own LinkedIn messages, connections, posts, events, invitations and profile data, and what the data cannot show. Use when the user asks about their LinkedIn messages, contacts, posts, events or other LinkedIn data.
---

# Reading LinkedIn data with the linkedin MCP server

The server reads the user's own data through LinkedIn's EU Member Data Portability (DMA)
API. Your host can add a prefix to the tool names, for example
`mcp__linkedin__search_messages`.

## Limits

- **Read-only.** You cannot send or reply to messages, post, comment, connect or change
  anything. Draft the text and tell the user to send it on LinkedIn.
- **Two data sources:**
  - The *snapshot* (all tools except `get_recent_activity`) has the full history, but it
    can end at the time the user connected the app. It is cached (one hour by default) and
    there is no refresh tool.
  - The *changelog* (`get_recent_activity`) has activity after the user connected the
    app, from the last 28 days only.

  For "latest" or "new" messages and posts, check both sources and say which source each
  result came from.
- **No server-side search.** Each tool loads a whole data set and filters it locally. The
  first messages call can take seconds. `list_data_domains` loads every domain (one API
  request per page of data); call it once per session. LinkedIn rate limits are daily, so avoid
  repeated calls in loops.

## Searching and paging

- A match is a case- and accent-insensitive substring match: `saric` matches `Šarić`.
  There is no fuzzy, word-order or semantic matching and no OR. Search for one
  distinctive word or name at a time; `ana anic` matches "Ana Anić", `anic ana` does not.
- All filters in one call combine with AND.
- Results are pages with `total` and `offset`. If `total` is larger than the number of
  items, ask for the next page with `offset`.
- Times are UTC. `since` and `until` accept ISO 8601, for example `2026-10-01`.

## Messages

1. Find conversations with `list_conversations` (most recently active first; filters
   `participant`, `folder`, `since`). `last_message_preview` holds only the first 200
   characters.
2. Read one with `get_conversation(conversation_id, limit)`. It returns the most recent
   `limit` messages (default 50) in chronological order; `message_count` is the total.
3. Find specific messages across all conversations with
   `search_messages(query, sender, folder, since, until)`. `query` searches the body,
   subject and conversation title.

- The user's own messages have the user's name as `sender`. Call `get_profile` once to
  get the name.
- Folders are `INBOX`, `ARCHIVE` and `SPAM`. Some messages have an empty folder.
- Conversation titles and message subjects are usually empty.

## Contacts

- `search_connections` returns first-degree connections: name, profile URL, company,
  position and connection date. `query` searches name, company, position and email.
- Email is usually missing: LinkedIn exports it only if the connection allows it. There
  are no phone numbers or locations for connections.
- Related data through `get_data_domain`: `INVITATIONS` (sent and received; see the
  `Direction` column), `CONTACTS` (imported address book, often empty),
  `MEMBER_FOLLOWING` and `COMPANY_FOLLOWS`.

## Posts

- `list_posts` reads the `MEMBER_SHARE_INFO` domain. This domain can be empty for some
  time after the user connects the app. If it is empty, tell the user, and look in
  `get_recent_activity` for posts made after that time.
- Its field names are not yet checked against real data. The original row is in `raw`;
  look there if a field is empty.
- Comments, reactions and reposts are domains: `ALL_COMMENTS`, `ALL_LIKES`,
  `INSTANT_REPOSTS`. Shared media URLs are in `RICH_MEDIA`.

## Events and other data domains

- Call `list_data_domains` to see which domains have data, with a description and row
  count for each. Then read rows with `get_data_domain(domain, offset, limit)`.
- Domain names are case-sensitive. Use them exactly as `list_data_domains` returns them.
  Events are `Events`; `EVENTS` fails.
- Rows are flat dictionaries of strings. The keys are LinkedIn's data export column
  names, for example `Event Name`, `Event Time`, `Status` and `External Url` for events.
  Each domain uses its own date format.
- Some domains mix two kinds of rows:
  - `ENDORSEMENTS`: received endorsements have `Endorser ...` columns, given ones have
    `Endorsee ...` columns.
  - `RECOMMENDATIONS`: given and received recommendations have the same columns, so you
    cannot tell them apart. Say so instead of guessing.
- Career data: `POSITIONS`, `EDUCATION`, `SKILLS`, `CERTIFICATIONS`, `LANGUAGES`,
  `PROJECTS`.

## Recent activity (changelog)

- `captured_at` and `processed_at` are epoch milliseconds.
- LinkedIn does not document the `resource_name` values. Call without `resource_name`
  first, look at the values that occur, then filter.
- The original data is in `activity`. `processed_activity` adds related context, for
  example the post that a comment belongs to. In LinkedIn's documented example, the text
  of a message is in `activity.content.content.string` or `activity.content.fallback`.
  This is not yet checked against real data.
- `DELETE` events have an empty `activity`.
- Fields that LinkedIn could not process contain "Unable to process this field." or
  "Unable_to_process_this_field.".

## Errors

- "The access token is invalid or expired": tokens last 60 days. Tell the user to
  generate a new token (the error contains the link) and update their configuration.
  Do not retry.
- HTTP 429: the daily rate limit is reached. Stop and tell the user.
- "No conversation with ID ...": use an ID from `list_conversations` or
  `search_messages`.
