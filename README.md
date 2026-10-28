# linkedin-mcp

A personal MCP server that gives an AI assistant read-only access to your own LinkedIn
data through LinkedIn's
[Member Data Portability (Member) API](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/).
LinkedIn provides this API for members in the EEA and Switzerland under the EU Digital
Markets Act (DMA).

## Terms and disclaimer

- This project is for personal use: each user accesses only their own LinkedIn data,
  with their own credentials.
- There is no warranty or support. The software is provided "as is" under the
  [MIT License](LICENSE). The API can change or stop working at any time.
- This project is not affiliated with, endorsed by, or supported by LinkedIn or
  Microsoft.
- You must accept LinkedIn's
  [API Terms of Use](https://www.linkedin.com/legal/l/api-terms-of-use) and the terms
  of the Member Data Portability API (Member) product. You are responsible for
  complying with them.
- You must create your own personal LinkedIn developer application with the
  **Member Data Portability API (Member)** product (scope
  `r_dma_portability_self_serve`). This repository contains no credentials.
- You must be eligible for that product: LinkedIn only lets members located in the
  European Economic Area (EEA) and Switzerland consent and generate a token.
- The AI assistant you connect this server to receives the data it reads, including
  messages from other people. Check the data handling terms of your AI provider.

## What you can and cannot do

The API is read-only. You cannot send messages, publish posts or change anything.

| Data | Source | Notes |
|---|---|---|
| Messages | `INBOX` snapshot domain | Full history. The newest messages may stop at the time you gave consent; see below. |
| Connections | `CONNECTIONS` snapshot domain | Name, profile URL, company, position, connection date. Email only if the connection allows exporting it. |
| Posts | `MEMBER_SHARE_INFO` snapshot domain | Can be empty for a while after consent: LinkedIn processes some domains later than others. |
| Profile, positions, skills, invitations, endorsements, ... | Other snapshot domains (about 67 in total) | Available through the generic domain tools. |
| Activity after consent (new messages, posts, comments, reactions) | Member Changelog API | Only events from the last 28 days and only after consent. |

LinkedIn does not document whether the snapshot is rebuilt on every request or only
once, at consent time. If it is built once, activity after consent appears only in the
changelog.

## Setup

1. Create a LinkedIn developer app on the
   [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps). Use the
   [Member Data Portability (Member) Default Company](https://www.linkedin.com/company/member-data-portability-member-default-company)
   page as the app's company. Do not create a new company page. Then, on the
   Products tab, request the **Member Data Portability API (Member)** product and
   accept its terms. See
   [LinkedIn's instructions](https://learn.microsoft.com/en-us/linkedin/dma/member-data-portability/member-data-portability-member/).
2. Generate an access token with the
   [OAuth Token Generator](https://www.linkedin.com/developers/tools/oauth/token-generator):
   select your app and the `r_dma_portability_self_serve` scope.
3. Install dependencies and configure the token:

   ```sh
   uv sync
   cp .env.example .env   # then set LINKEDIN_ACCESS_TOKEN
   uv run linkedin-mcp status
   ```

Tokens expire after 60 days and have no refresh token. When a token expires, every
call fails with an error that links to the token generator. Generate a new token and
update `.env`.

### Configuration

The CLI reads settings from environment variables first, then from the `.env` file
(`./.env`, or the path given with `--env-file`).

| Variable | Default | Description |
|---|---|---|
| `LINKEDIN_ACCESS_TOKEN` | (required) | OAuth access token. |
| `LINKEDIN_CACHE_TTL` | `3600` | Seconds to keep snapshot data in memory. `0` disables the cache. |
| `LINKEDIN_TIMEOUT` | `30` | HTTP request timeout in seconds. |

## Using it from an MCP host

The server uses the stdio transport. MCP hosts start it in an arbitrary working
directory, so give the `.env` path explicitly.

Claude Code:

```sh
claude mcp add linkedin -- uv --directory /path/to/linkedin-mcp run linkedin-mcp --env-file /path/to/linkedin-mcp/.env serve
```

Generic JSON configuration (Claude Desktop and others):

```json
{
  "mcpServers": {
    "linkedin": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/linkedin-mcp",
        "run", "linkedin-mcp", "--env-file", "/path/to/linkedin-mcp/.env", "serve"
      ]
    }
  }
}
```

### Tools

| Tool | Description |
|---|---|
| `get_profile` | Basic profile: name, headline, summary, location. |
| `list_conversations` | Conversations, most recently active first. Filters: folder, participant, since. |
| `get_conversation` | One conversation with its messages in chronological order. |
| `search_messages` | Search messages by text, sender, folder and time range. |
| `search_connections` | Search connections by name, company, position, email and connection date. |
| `list_posts` | Your posts, newest first. |
| `get_recent_activity` | Changelog events after consent (last 28 days). |
| `list_data_domains` | All snapshot domains that have data, with row counts. |
| `get_data_domain` | Raw rows from any snapshot domain. |

All list tools support `offset` and `limit` and return the `total` number of matches.
Text matching ignores case and diacritics, so `saric` matches `Šarić`.

### Agent guidance

The server sends a short usage guide to every MCP client in its `instructions`: data
sources, search behaviour and the main caveats.
[`skills/linkedin-mcp/SKILL.md`](skills/linkedin-mcp/SKILL.md) is a longer guide with
steps for messages, contacts, posts, events and changelog data. To use it in Claude Code,
copy it to your skills directory:

```sh
cp -r skills/linkedin-mcp ~/.claude/skills/
```

For other agents, add the file's content to the agent's instructions.

## Command-line debugging

The CLI can call the API directly and print JSON. No MCP host is needed:

```sh
uv run linkedin-mcp status                  # changelog archiving status
uv run linkedin-mcp enable-changelog        # enable archiving (normally automatic)
uv run linkedin-mcp domains                 # domains with data and row counts
uv run linkedin-mcp snapshot SKILLS         # raw data of one domain (omit for all)
uv run linkedin-mcp changelog --since 2026-10-01 --resource messages
```

## Architecture

```
src/linkedin_mcp/
  client.py    LinkedInClient: async HTTP client for the 4 API endpoints, pagination, retries
  models.py    Pydantic models of the raw API responses
  errors.py    Exception hierarchy (AuthenticationError, RateLimitError, ...)
  records.py   Typed records parsed from snapshot rows (Message, Connection, Profile, Post)
  service.py   LinkedInService: in-memory cache, filtering, sorting, pagination
  cache.py     TTL cache
  domains.py   Snapshot domain names and descriptions
  config.py    Settings from the environment and .env
  server.py    MCP server (official `mcp` SDK, MCPServer)
  cli.py       Command-line entry point
```

The API has no server-side filtering, so the service fetches each snapshot domain once
and keeps it in memory for `LINKEDIN_CACHE_TTL` seconds. Changelog data is not cached.

API quirks the client handles:

- Snapshot pagination ends with HTTP 404 "No data found", not with an empty page.
  `paging.total` can undercount, so the client keeps requesting pages until it gets the 404.
- The Snapshot API only accepts `Linkedin-Version: 202312`.
- Domain names are case-sensitive, and some differ from the documentation: events are
  `Events`, and the API also returns the undocumented `WHATSAPP_NUMBERS`.
- The changelog `startTime` is inclusive. The client continues from the latest
  `processedAt` and removes duplicate events by `id`.
- The client retries 5xx responses and connection errors with exponential backoff. It
  does not retry 429, because the rate limits are daily.

## Development

```sh
uv run ruff format .     # format
uv run ruff check .      # lint (includes docstring and annotation rules)
uv run ty check          # type check
uv run pytest            # tests with coverage
```

The unit tests cover the client and service layers and use mocked HTTP (`respx`) and
synthetic data. `server.py` and `cli.py` are thin wrappers and are not included in
coverage.

## License

[MIT](LICENSE)
