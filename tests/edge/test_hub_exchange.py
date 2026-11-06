"""Per-candidate tablet exchange: snapshot upload, alarm downlink and ack, across threads."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from faultevolve.edge.hub import EdgeHub


def test_candidate_exchange_round_trip() -> None:
    hub = EdgeHub()
    seen: list[dict[str, Any]] = []

    async def tablet() -> None:
        outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        hub.bind(asyncio.get_running_loop(), outbox, "10.0.0.2")
        assert hub.tablet_linked
        result: dict[str, bool] = {}
        worker = threading.Thread(target=lambda: result.update(
            snap=hub.exchange("c1", {"type": "eval_request", "candidate": "c1"}, "snapshot", 5.0),
            ack=hub.exchange("c1", {"type": "candidate_alarms", "candidate": "c1", "alarms": ["A"]}, "ack", 5.0),
        ))
        worker.start()

        request = await asyncio.wait_for(outbox.get(), 5)
        seen.append(request)
        await hub.process({"type": "snapshot_begin", "candidate": "c1", "columns": ["smart_5_raw"],
                           "history_days": 2, "horizon_days": 1, "start_date": "2026-11-01",
                           "disks": [{"sn": "A", "model": "m", "cap": 1, "rack": 0, "slot": 0},
                                     {"sn": "B", "model": "m", "cap": 1, "rack": 0, "slot": 1}]}, 100)
        for day in (1, 2):
            await hub.process({"type": "snapshot", "candidate": "c1", "day": day,
                               "rows": [["A", [float(day)]], ["B", [0.0]]]}, 50)
        await hub.process({"type": "snapshot_end", "candidate": "c1", "failures": {"A": 3}}, 20)

        alarms = await asyncio.wait_for(outbox.get(), 5)
        seen.append(alarms)
        await hub.process({"type": "candidate_ack", "candidate": "c1", "shown": 1}, 10)
        await asyncio.to_thread(worker.join, 5)
        hub.unbind(outbox)
        assert result == {"snap": True, "ack": True}

    asyncio.run(tablet())

    assert [m["type"] for m in seen] == ["eval_request", "candidate_alarms"]
    assert hub.phase == "done" and len(hub.rows) == 4 and hub.failures == {"A": 3}
    assert hub.exchanges["c1"]["rows"] == 4 and hub.exchanges["c1"]["frames"] == 4
    assert "acked_at" in hub.exchanges["c1"]
    assert not hub.tablet_linked


def test_exchange_without_tablet_returns_immediately() -> None:
    hub = EdgeHub()
    assert hub.exchange("c1", {"type": "eval_request"}, "snapshot", 5.0) is False
