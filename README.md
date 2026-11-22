# EventMate 🎟️ — an MCP server for organising events with Claude

EventMate gives Claude a small, persistent "event desk". You can use it for any gathering:
**meetups, workshops, hackathons, college fests, birthday parties, weddings, team offsites and trips.**
Ask Claude in plain language ("add these 20 people", "who hasn't arrived yet?",
"who owes whom for the trip?"). Claude calls EventMate's tools, and the data stays in a local SQLite file.

## Tools

| Area | Tools | What it does |
|---|---|---|
| Events | `create_event`, `list_events`, `event_overview`, `delete_event` | Countdown, headcount, seats left, open tasks, total spend |
| Attendees | `add_attendees`, `check_in`, `list_attendees` | Bulk registration that enforces capacity, skips duplicates, and supports door check-in |
| Agenda | `add_session`, `get_agenda` | Refuses overlapping slots so the schedule never clashes |
| Tasks | `add_task`, `complete_task`, `list_tasks` | Organiser to-dos with owners, due dates and overdue flags |
| Money | `add_expense`, `settle_expenses` | Equal split, then the fewest payments needed to settle up |

It also has a **resource** `eventmate://events/{id}/summary` (a Markdown brief) and a **prompt**
`plan_event(kind, guests, date)` that has Claude set up a full plan for a new event.

## Install

```bash
git clone -b ccr-3b5e7e94-wmx1q8 https://github.com/Midhun-Das-L/EventMate.git && cd EventMate
uv venv && uv pip install -e ".[dev]"     # or: pip install -e ".[dev]"
```

Data is stored at `~/.eventmate/eventmate.db`. To use a different file, set `EVENTMATE_DB`.

## Connect to Claude

**Claude Code:** this repo ships a `.mcp.json`, so run `claude` in the repo folder and approve the
`eventmate` server. To add it globally instead:

```bash
claude mcp add eventmate -- uv run --project /path/to/EventMate eventmate-mcp
```

**Claude Desktop:** add this to `claude_desktop_config.json` (Settings → Developer → Edit Config), then restart Claude Desktop:

```json
{
  "mcpServers": {
    "eventmate": {
      "command": "uv",
      "args": ["run", "--project", "/absolute/path/to/EventMate", "eventmate-mcp"]
    }
  }
}
```

## Try it

> Create a hackathon "Hack Night" on 2030-03-14 18:00 with 50 seats, add Asha, Ben and Chen,
> check in Ben, add a 30-min Kickoff at 18:00, Asha paid 120 for pizza. Show the overview and who owes whom.

Claude's reply: *3 attendees, 1 checked in, 47 seats left; Ben pays Asha 40, Chen pays Asha 40.*

To inspect the server interactively: `uv run mcp dev src/eventmate/server.py`, or use the
[MCP Inspector](https://github.com/modelcontextprotocol/inspector).

## Tests

```bash
.venv/bin/python -m pytest -q
```

The tests drive the server in-process and over real stdio, which is the same transport Claude uses.
