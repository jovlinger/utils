"""Round-trip tests for TaskEvent codecs."""

from __future__ import annotations

import unittest

from taskevent import (
    AllInformResult,
    EventEnvelope,
    FormEncodeError,
    LogEmitLine,
    NetPollPlayerstate,
    NetSet,
    SchedStart,
)
from taskevent.constants import TA_EV_LOG, TA_NET_SET_OP_VOLUME
from taskevent.types import EVENT_BY_TYPE_ID


class TaskEventCodecTests(unittest.TestCase):
    def test_log_binary_roundtrip(self) -> None:
        ev = LogEmitLine(severity=3, tag=1, text="boot")
        raw = ev.write_binary()
        got = LogEmitLine.read_binary(raw)
        self.assertEqual(got, ev)

    def test_to_c_struct_is_typedef_not_bytes(self) -> None:
        decl = LogEmitLine.to_c_struct()
        self.assertIsInstance(decl, str)
        self.assertIn("typedef struct", decl)
        self.assertIn("uint8_t severity;", decl)
        self.assertIn("char text[", decl)
        self.assertIn("} ta_log_emit_line_t;", decl)
        # Must not be the old write_binary alias.
        self.assertNotIsInstance(decl, bytes)

    def test_c_literal_is_instance_method(self) -> None:
        lit = LogEmitLine(severity=1, tag=2, text="x").to_c_literal()
        self.assertIn("ta_log_emit_line_t", lit)
        self.assertIn(".severity = 1", lit)
        self.assertIn('.text = "x"', lit)

    def test_log_text_roundtrip(self) -> None:
        ev = LogEmitLine(severity=2, tag=0, text="hi")
        text = ev.write_text()
        self.assertIn("event=LogEmitLine", text)
        self.assertEqual(LogEmitLine.read_text(text), ev)

    def test_log_form_roundtrip(self) -> None:
        ev = LogEmitLine(severity=1, tag=9, text="ok")
        form = ev.to_form()
        self.assertIn("event=LogEmitLine", form)
        self.assertEqual(LogEmitLine.from_form(form), ev)

    def test_all_inform_form_fails(self) -> None:
        ev = AllInformResult(status=0, key="url", n=3, payload=b"abc")
        with self.assertRaises(FormEncodeError):
            ev.to_form()
        raw = ev.write_binary()
        self.assertEqual(AllInformResult.read_binary(raw), ev)

    def test_envelope_binary(self) -> None:
        body = NetPollPlayerstate(reply_to="MPDController")
        env = EventEnvelope(
            src="Draw", session_id=42, enqueue_time_ms=1000, event=body
        )
        raw = env.write_binary()
        got = EventEnvelope.read_binary(raw, EVENT_BY_TYPE_ID)
        self.assertEqual(got.src, "Draw")
        self.assertEqual(got.session_id, 42)
        self.assertEqual(got.event, body)

    def test_net_set_and_sched(self) -> None:
        ns = NetSet(reply_to="", op=TA_NET_SET_OP_VOLUME, volume=40)
        self.assertEqual(NetSet.read_binary(ns.write_binary()), ns)
        st = SchedStart(fire_to="Draw", fire_type=0x201, period_ms=50, flags=0)
        self.assertEqual(SchedStart.read_text(st.write_text()), st)
        self.assertEqual(st.type_id, 0x500)

    def test_type_id_constant(self) -> None:
        self.assertEqual(LogEmitLine.type_id, TA_EV_LOG)


if __name__ == "__main__":
    unittest.main()
