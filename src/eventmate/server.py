"""EventMate - an MCP server that turns Claude into an event co-organiser.

Works for any gathering: meetups, workshops, hackathons, college fests,
birthday parties, weddings, team offsites, trips. Claude can create events,
register and check in attendees, build a clash-free agenda, track to-dos and
split shared costs fairly.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from . import store

INSTRUCTIONS = """EventMate stores events and everything about them.
Start with list_events or create_event to get an event_id, then use the other
tools with that id. Dates are 'YYYY-MM-DD HH:MM' in the organiser's local time.
Use event_overview for a quick status report and settle_expenses to work out
who owes whom."""


def create_server(conn: sqlite3.Connection | None = None) -> MCPServer:
    db = conn or store.connect()
    mcp = MCPServer("EventMate", instructions=INSTRUCTIONS, version="0.1.0")

    # ---------- helpers ----------
    def get_event(event_id: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            raise ValueError(f"No event with id {event_id}. Call list_events to see ids.")
        return row

    def rows(sql: str, *args: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in db.execute(sql, args).fetchall()]

    def countdown(starts_at: str) -> str:
        delta = store.parse_dt(starts_at) - datetime.now()
        if delta.total_seconds() < 0:
            return "started / past"
        days, rem = divmod(int(delta.total_seconds()), 86400)
        return f"{days}d {rem // 3600}h to go"

    # ---------- events ----------
    @mcp.tool()
    def create_event(
        name: str,
        starts_at: str,
        kind: str = "general",
        venue: str = "",
        capacity: int | None = None,
    ) -> dict[str, Any]:
        """Create a new event. kind is free text, e.g. meetup, workshop, hackathon,
        birthday, wedding, offsite, trip. capacity limits the attendee count."""
        store.parse_dt(starts_at)
        cur = db.execute(
            "INSERT INTO events (name, kind, starts_at, venue, capacity, created_at) VALUES (?,?,?,?,?,?)",
            (name, kind, starts_at, venue, capacity, store.now_iso()),
        )
        db.commit()
        return dict(get_event(cur.lastrowid))

    @mcp.tool()
    def list_events() -> list[dict[str, Any]]:
        """List all events (soonest first) with attendee counts."""
        return rows(
            """SELECT e.id, e.name, e.kind, e.starts_at, e.venue, e.capacity,
                      COUNT(a.id) AS attendees
               FROM events e LEFT JOIN attendees a ON a.event_id = e.id
               GROUP BY e.id ORDER BY e.starts_at"""
        )

    @mcp.tool()
    def delete_event(event_id: int) -> str:
        """Permanently delete an event and all its attendees, agenda, tasks and expenses."""
        ev = get_event(event_id)
        db.execute("DELETE FROM events WHERE id = ?", (event_id,))
        db.commit()
        return f"Deleted event {ev['name']!r}."

    @mcp.tool()
    def event_overview(event_id: int) -> dict[str, Any]:
        """One-glance status: countdown, headcount and check-ins, agenda size,
        open tasks and total spend."""
        return _overview(event_id)

    def _overview(event_id: int) -> dict[str, Any]:
        ev = dict(get_event(event_id))
        a = db.execute(
            "SELECT COUNT(*) total, COUNT(checked_in_at) checked_in FROM attendees WHERE event_id=?",
            (event_id,),
        ).fetchone()
        t = db.execute(
            "SELECT COUNT(*) total, COALESCE(SUM(done),0) done FROM tasks WHERE event_id=?", (event_id,)
        ).fetchone()
        spend = db.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE event_id=?", (event_id,)
        ).fetchone()[0]
        sessions = db.execute("SELECT COUNT(*) FROM sessions WHERE event_id=?", (event_id,)).fetchone()[0]
        return {
            **ev,
            "countdown": countdown(ev["starts_at"]),
            "attendees": a["total"],
            "checked_in": a["checked_in"],
            "seats_left": None if ev["capacity"] is None else ev["capacity"] - a["total"],
            "agenda_sessions": sessions,
            "tasks_open": t["total"] - t["done"],
            "tasks_done": t["done"],
            "total_spend": round(spend, 2),
        }

    # ---------- attendees ----------
    @mcp.tool()
    def add_attendees(event_id: int, names: list[str], role: str = "guest", email: str = "") -> dict[str, Any]:
        """Register one or more people. role e.g. guest, speaker, volunteer, organiser.
        Duplicates are skipped; capacity is enforced."""
        ev = get_event(event_id)
        added, skipped = [], []
        for raw in names:
            name = raw.strip()
            if not name:
                continue
            count = db.execute("SELECT COUNT(*) FROM attendees WHERE event_id=?", (event_id,)).fetchone()[0]
            if ev["capacity"] is not None and count >= ev["capacity"]:
                skipped.append(f"{name} (event full)")
                continue
            try:
                db.execute(
                    "INSERT INTO attendees (event_id, name, email, role) VALUES (?,?,?,?)",
                    (event_id, name, email if len(names) == 1 else "", role),
                )
                added.append(name)
            except sqlite3.IntegrityError:
                skipped.append(f"{name} (already registered)")
        db.commit()
        return {"added": added, "skipped": skipped}

    @mcp.tool()
    def check_in(event_id: int, name: str) -> str:
        """Mark an attendee as arrived (case-insensitive name match)."""
        get_event(event_id)
        row = db.execute(
            "SELECT id, name, checked_in_at FROM attendees WHERE event_id=? AND lower(name)=lower(?)",
            (event_id, name.strip()),
        ).fetchone()
        if row is None:
            raise ValueError(f"{name!r} is not registered for this event.")
        if row["checked_in_at"]:
            return f"{row['name']} was already checked in at {row['checked_in_at']}."
        db.execute("UPDATE attendees SET checked_in_at=? WHERE id=?", (store.now_iso(), row["id"]))
        db.commit()
        return f"Checked in {row['name']}."

    @mcp.tool()
    def list_attendees(
        event_id: int, status: Literal["all", "checked_in", "not_arrived"] = "all"
    ) -> list[dict[str, Any]]:
        """List attendees, optionally only those checked in or not yet arrived."""
        get_event(event_id)
        cond = {"all": "", "checked_in": "AND checked_in_at IS NOT NULL", "not_arrived": "AND checked_in_at IS NULL"}
        return rows(
            f"SELECT name, role, email, checked_in_at FROM attendees WHERE event_id=? {cond[status]} ORDER BY name",
            event_id,
        )

    # ---------- agenda ----------
    @mcp.tool()
    def add_session(event_id: int, title: str, starts_at: str, minutes: int, host: str = "") -> dict[str, Any]:
        """Add an agenda item (talk, game, meal, ceremony...). Refuses if it overlaps
        an existing session so the schedule stays clash-free."""
        get_event(event_id)
        if minutes <= 0:
            raise ValueError("minutes must be positive.")
        start = store.parse_dt(starts_at)
        end = start + timedelta(minutes=minutes)
        for s in rows("SELECT * FROM sessions WHERE event_id=?", event_id):
            s_start = store.parse_dt(s["starts_at"])
            s_end = s_start + timedelta(minutes=s["minutes"])
            if start < s_end and s_start < end:
                raise ValueError(
                    f"Clashes with {s['title']!r} ({s_start:%H:%M}-{s_end:%H:%M}). Pick another time."
                )
        cur = db.execute(
            "INSERT INTO sessions (event_id, title, starts_at, minutes, host) VALUES (?,?,?,?,?)",
            (event_id, title, start.isoformat(timespec="minutes"), minutes, host),
        )
        db.commit()
        return {"id": cur.lastrowid, "title": title, "start": f"{start:%Y-%m-%d %H:%M}", "end": f"{end:%H:%M}"}

    @mcp.tool()
    def get_agenda(event_id: int) -> list[dict[str, Any]]:
        """The event schedule in time order."""
        get_event(event_id)
        out = []
        for s in rows("SELECT * FROM sessions WHERE event_id=? ORDER BY starts_at", event_id):
            start = store.parse_dt(s["starts_at"])
            out.append({
                "id": s["id"],
                "time": f"{start:%Y-%m-%d %H:%M}-{start + timedelta(minutes=s['minutes']):%H:%M}",
                "title": s["title"],
                "host": s["host"],
            })
        return out

    # ---------- tasks ----------
    @mcp.tool()
    def add_task(event_id: int, title: str, owner: str = "", due: str = "") -> dict[str, Any]:
        """Add a to-do for the organising team (book venue, order cake, print badges...)."""
        get_event(event_id)
        if due:
            store.parse_dt(due)
        cur = db.execute(
            "INSERT INTO tasks (event_id, title, owner, due) VALUES (?,?,?,?)", (event_id, title, owner, due)
        )
        db.commit()
        return {"id": cur.lastrowid, "title": title, "owner": owner, "due": due}

    @mcp.tool()
    def complete_task(task_id: int) -> str:
        """Mark a task as done."""
        n = db.execute("UPDATE tasks SET done=1 WHERE id=?", (task_id,)).rowcount
        db.commit()
        if not n:
            raise ValueError(f"No task with id {task_id}.")
        return f"Task {task_id} done."

    @mcp.tool()
    def list_tasks(event_id: int, include_done: bool = False) -> list[dict[str, Any]]:
        """Open tasks (or all, with include_done), earliest due first; overdue ones are flagged."""
        get_event(event_id)
        sql = "SELECT id, title, owner, due, done FROM tasks WHERE event_id=?"
        if not include_done:
            sql += " AND done=0"
        result = rows(sql + " ORDER BY due = '', due", event_id)
        now = datetime.now()
        for r in result:
            r["done"] = bool(r["done"])
            r["overdue"] = bool(r["due"]) and not r["done"] and store.parse_dt(r["due"]) < now
        return result

    # ---------- expenses ----------
    @mcp.tool()
    def add_expense(event_id: int, description: str, amount: float, paid_by: str) -> dict[str, Any]:
        """Record money someone spent for the event."""
        get_event(event_id)
        if amount <= 0:
            raise ValueError("amount must be positive.")
        cur = db.execute(
            "INSERT INTO expenses (event_id, description, amount, paid_by) VALUES (?,?,?,?)",
            (event_id, description, amount, paid_by.strip()),
        )
        db.commit()
        return {"id": cur.lastrowid, "description": description, "amount": amount, "paid_by": paid_by}

    @mcp.tool()
    def settle_expenses(event_id: int, split_between: list[str] | None = None) -> dict[str, Any]:
        """Split all expenses equally and return the fewest payments that settle up.
        split_between defaults to everyone who paid plus all registered attendees."""
        get_event(event_id)
        expenses = rows("SELECT amount, paid_by FROM expenses WHERE event_id=?", event_id)
        if not expenses:
            return {"total": 0, "per_person": 0, "payments": []}
        people = split_between or sorted(
            {e["paid_by"] for e in expenses}
            | {a["name"] for a in rows("SELECT name FROM attendees WHERE event_id=?", event_id)}
        )
        total = sum(e["amount"] for e in expenses)
        share = total / len(people)
        balance = {p: -share for p in people}
        for e in expenses:
            balance[e["paid_by"]] = balance.get(e["paid_by"], 0) + e["amount"]
        debtors = sorted(([p, -b] for p, b in balance.items() if b < -0.005), key=lambda x: -x[1])
        creditors = sorted(([p, b] for p, b in balance.items() if b > 0.005), key=lambda x: -x[1])
        payments, i, j = [], 0, 0
        while i < len(debtors) and j < len(creditors):
            pay = min(debtors[i][1], creditors[j][1])
            payments.append({"from": debtors[i][0], "to": creditors[j][0], "amount": round(pay, 2)})
            debtors[i][1] -= pay
            creditors[j][1] -= pay
            if debtors[i][1] < 0.005:
                i += 1
            if creditors[j][1] < 0.005:
                j += 1
        return {"total": round(total, 2), "per_person": round(share, 2), "people": people, "payments": payments}

    # ---------- resource & prompt ----------
    @mcp.resource("eventmate://events/{event_id}/summary")
    def event_summary(event_id: int) -> str:
        """Markdown summary of an event, handy to attach as context."""
        o = _overview(int(event_id))
        agenda = get_agenda(int(event_id))
        lines = [
            f"# {o['name']} ({o['kind']})",
            f"When: {o['starts_at']} ({o['countdown']})  Where: {o['venue'] or 'TBD'}",
            f"Attendees: {o['attendees']} (checked in {o['checked_in']})",
            f"Tasks: {o['tasks_open']} open / {o['tasks_done']} done  Spend: {o['total_spend']}",
            "## Agenda",
            *(f"- {s['time']} {s['title']}" + (f" ({s['host']})" if s["host"] else "") for s in agenda),
        ]
        return "\n".join(lines)

    @mcp.prompt()
    def plan_event(kind: str, guests: int, date: str) -> str:
        """Kick-off prompt: have Claude set up a complete plan for a new event."""
        return (
            f"I'm organising a {kind} for about {guests} people on {date}. Using the EventMate tools: "
            "create the event, draft a realistic agenda with add_session, add a checklist of the "
            "key preparation tasks with sensible due dates, then show me event_overview."
        )

    return mcp


def main() -> None:
    create_server().run()  # stdio transport, which is what Claude Desktop / Claude Code use


if __name__ == "__main__":
    main()
