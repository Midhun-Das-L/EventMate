import json
import sys

import pytest
from mcp import Client, StdioServerParameters

from eventmate import store
from eventmate.server import create_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def data(result):
    assert not result.is_error, result.content
    if result.structured_content is not None:
        sc = result.structured_content
        return sc.get("result", sc)
    return result.content[0].text


async def test_full_event_flow():
    async with Client(create_server(store.connect(":memory:"))) as c:
        ev = data(await c.call_tool("create_event", {"name": "PyMeetup", "starts_at": "2030-05-01 18:00",
                                                     "kind": "meetup", "capacity": 3}))
        eid = ev["id"]
        added = data(await c.call_tool("add_attendees", {"event_id": eid, "names": ["Asha", "Ben", "Chen", "Dev"]}))
        assert added["added"] == ["Asha", "Ben", "Chen"] and "Dev (event full)" in added["skipped"]
        assert "Checked in Asha" in data(await c.call_tool("check_in", {"event_id": eid, "name": "asha"}))

        data(await c.call_tool("add_session", {"event_id": eid, "title": "Intro", "starts_at": "2030-05-01 18:00", "minutes": 30}))
        clash = await c.call_tool("add_session", {"event_id": eid, "title": "Talk", "starts_at": "2030-05-01 18:15", "minutes": 30})
        assert clash.is_error

        data(await c.call_tool("add_expense", {"event_id": eid, "description": "Pizza", "amount": 90, "paid_by": "Asha"}))
        s = data(await c.call_tool("settle_expenses", {"event_id": eid}))
        assert s["per_person"] == 30
        assert sorted((p["from"], p["amount"]) for p in s["payments"]) == [("Ben", 30), ("Chen", 30)]

        o = data(await c.call_tool("event_overview", {"event_id": eid}))
        assert o["checked_in"] == 1 and o["seats_left"] == 0 and o["total_spend"] == 90

        tools = {t.name for t in (await c.list_tools()).tools}
        assert {"create_event", "settle_expenses", "get_agenda"} <= tools


async def test_over_stdio(tmp_path):
    params = StdioServerParameters(command=sys.executable, args=["-m", "eventmate.server"],
                                   env={"EVENTMATE_DB": str(tmp_path / "t.db")})
    async with Client(params) as c:
        ev = data(await c.call_tool("create_event", {"name": "Birthday", "starts_at": "2030-01-01"}))
        assert ev["name"] == "Birthday"
