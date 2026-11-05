"""Phase 8 preparation: the transport-agnostic event stream core.

These tests pin the parts of the realtime channel that do **not** need a
running app, so phase 8 only has to add the endpoint and the generator loop.
The wire format asserted here is the one written down in TODO §8.2.
"""

from __future__ import annotations

import json

import pytest

from faultevolve.webapi.event_stream import (
    HEARTBEAT_INTERVAL_SECONDS,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    _data_lines,
    coerce_last_event_id,
    heartbeat_frame,
    select_after,
    serialize_payload,
    sse_frame,
    split_page,
)


class TestSseFrame:
    def test_matches_the_todo_8_2_wire_format(self) -> None:
        frame = sse_frame(
            event_id=124, event_type="iteration_complete", data={"node_id": "n1"}
        )
        assert frame == (
            "id: 124\n"
            "event: iteration_complete\n"
            'data: {"node_id":"n1"}\n'
            "\n"
        )

    def test_frame_ends_with_a_blank_line(self) -> None:
        """The blank line is what dispatches the event; without it nothing fires."""
        assert sse_frame(event_id=1, event_type="run_finished", data={}).endswith("\n\n")

    def test_id_is_omitted_when_the_engine_gave_none(self) -> None:
        """No id means "cannot be resumed from here", not "resume from 0"."""
        frame = sse_frame(event_id=None, event_type="run_finished", data={})
        assert "id:" not in frame
        assert frame.startswith("event: run_finished\n")

    def test_payload_newlines_never_break_the_frame(self) -> None:
        frame = sse_frame(
            event_id=7, event_type="iteration_complete", data={"message": "a\nb\r\nc"}
        )
        body = frame.rstrip("\n")
        assert len(body.split("\n")) == 3  # id, event, data -- exactly one data line
        assert "\r" not in body
        # The value survives, escaped: nothing is silently dropped.
        assert json.loads(body.split("\n")[2][len("data: ") :]) == {
            "message": "a\nb\r\nc"
        }

    def test_event_name_cannot_forge_a_frame_boundary(self) -> None:
        """A name is the one field a caller could inject text through."""
        frame = sse_frame(event_id=1, event_type="evil\nevent: injected", data={})
        body = frame.rstrip("\n")
        event_lines = [ln for ln in body.split("\n") if ln.startswith("event:")]
        assert len(event_lines) == 1  # no extra field line was created
        name = event_lines[0][len("event: ") :]
        assert all(c.isalnum() or c in "_.-" for c in name)

    def test_empty_event_name_falls_back(self) -> None:
        assert "event: unknown" in sse_frame(event_id=1, event_type="\n\r", data={})

    def test_chinese_payload_stays_readable(self) -> None:
        frame = sse_frame(event_id=1, event_type="iteration_complete", data={"原因": "超时"})
        assert "超时" in frame  # ensure_ascii=False
        assert "\\u" not in frame

    def test_unserializable_field_does_not_kill_the_stream(self) -> None:
        frame = sse_frame(event_id=1, event_type="x", data={"obj": object()})
        assert "data: " in frame
        assert "<object object at" in frame

    def test_payload_is_compact(self) -> None:
        assert serialize_payload({"a": 1, "b": 2}) == '{"a":1,"b":2}'


class TestDataLines:
    def test_single_line_payload_produces_one_data_line(self) -> None:
        assert _data_lines('{"a":1}') == ['data: {"a":1}']

    def test_multi_line_payload_becomes_repeated_data_lines(self) -> None:
        """The SSE spec's multi-line form, for a payload that arrived verbatim."""
        assert _data_lines("line1\nline2") == ["data: line1", "data: line2"]

    def test_carriage_returns_are_stripped(self) -> None:
        assert _data_lines("a\r\nb") == ["data: a", "data: b"]

    def test_empty_payload_still_emits_one_data_line(self) -> None:
        assert _data_lines("") == ["data: "]


class TestHeartbeat:
    def test_heartbeat_is_a_comment_not_an_event(self) -> None:
        frame = heartbeat_frame()
        assert frame == ": keep-alive\n\n"
        assert "event:" not in frame  # must never fire onmessage

    def test_heartbeat_interval_is_positive(self) -> None:
        assert HEARTBEAT_INTERVAL_SECONDS > 0


class TestHeaders:
    def test_media_type_is_event_stream(self) -> None:
        assert SSE_MEDIA_TYPE == "text/event-stream"

    def test_headers_disable_buffering_and_caching(self) -> None:
        """Buffering would make a live stream look dead until the run finished."""
        assert SSE_HEADERS["Cache-Control"] == "no-store"
        assert SSE_HEADERS["X-Accel-Buffering"] == "no"


class TestCoerceLastEventId:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("124", 124),
            (124, 124),
            (" 7 ", 7),
            ("0", 0),
            (0, 0),
            (None, None),
            ("", None),
            ("   ", None),
            ("abc", None),
            ("-1", None),
            ("1.5", None),
            ("0x10", None),
            (True, None),  # bool is an int subclass; not a cursor
        ],
    )
    def test_parsing(self, raw: object, expected: int | None) -> None:
        assert coerce_last_event_id(raw) == expected  # type: ignore[arg-type]

    def test_garbage_never_becomes_zero(self) -> None:
        """A bogus cursor must fall back to "replay everything", not to a
        partial timeline the client would mistake for complete."""
        assert coerce_last_event_id("not-a-number") is None


class TestSelectAfter:
    EVENTS = [
        {"id": 1, "type": "a"},
        {"id": 2, "type": "b"},
        {"id": 3, "type": "c"},
        {"type": "no-id"},  # engine never gave one
        {"id": "4", "type": "string-id"},  # not an int
    ]

    def test_none_returns_the_whole_timeline(self) -> None:
        assert [e["id"] for e in select_after(self.EVENTS, None)] == [1, 2, 3]

    def test_cursor_is_exclusive(self) -> None:
        """Strictly after: replaying id 2 would duplicate it client-side."""
        assert [e["id"] for e in select_after(self.EVENTS, 2)] == [3]

    def test_unknown_ids_are_dropped_not_fabricated(self) -> None:
        assert all(isinstance(e.get("id"), int) for e in select_after(self.EVENTS, None))

    def test_order_is_preserved(self) -> None:
        assert select_after(self.EVENTS, None) == select_after(self.EVENTS, None)

    def test_cursor_past_the_end_yields_nothing(self) -> None:
        assert select_after(self.EVENTS, 999) == []


class TestSplitPage:
    def test_no_limit_returns_everything_and_no_more(self) -> None:
        page, has_more = split_page([1, 2, 3], None)
        assert (page, has_more) == ([1, 2, 3], False)

    def test_partial_page_reports_more(self) -> None:
        page, has_more = split_page([1, 2, 3], 2)
        assert (page, has_more) == ([1, 2], True)

    def test_exactly_full_page_reports_no_more(self) -> None:
        """Three of three is complete, even though the page is full."""
        page, has_more = split_page([1, 2, 3], 3)
        assert (page, has_more) == ([1, 2, 3], False)

    def test_empty_input(self) -> None:
        assert split_page([], 5) == ([], False)
