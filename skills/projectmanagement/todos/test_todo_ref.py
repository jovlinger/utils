#!/usr/bin/env python3
"""Unit tests for the relto target grammar, prose scanner, and resolver."""

from __future__ import annotations

import unittest

import todo_objid
import todo_ref


def _record() -> dict:
    """A stamped todo-shaped record with a note and two work items."""
    todo: dict = {
        "Id": "aa62d424" + "0" * 56,
        "Branch": "aa62d424-notes",
        "State": {"working": {"owner": "agent"}},
        "Summary": {"raw": "a summary"},
        "Body": {"raw": "strategy"},
        "Notes": [{"raw": "a fact"}],
        "WorkItems": [
            {"kind": "task", "summary": "first", "done": False},
            {"kind": "task", "summary": "second", "done": False},
        ],
    }
    todo_objid.stamp_objids(todo)
    return todo


class TargetSpellingTest(unittest.TestCase):
    """The three qualified spellings, and what each one carries."""

    def test_a_local_target_names_an_object_in_this_record(self) -> None:
        parsed = todo_ref.parse_target("objid:0034")
        self.assertEqual(parsed.objid_prefix, "0034")
        self.assertEqual(parsed.todo_prefix, "")
        self.assertTrue(parsed.is_local)
        self.assertFalse(parsed.is_whole_todo)
        self.assertFalse(parsed.is_remote)

    def test_a_todo_target_names_a_whole_todo(self) -> None:
        parsed = todo_ref.parse_target("todo:dea7")
        self.assertEqual(parsed.todo_prefix, "dea7")
        self.assertEqual(parsed.objid_prefix, "")
        self.assertTrue(parsed.is_whole_todo)
        self.assertFalse(parsed.is_local)

    def test_a_cross_todo_target_carries_both_prefixes(self) -> None:
        parsed = todo_ref.parse_target("todo:c03d/objid:0045")
        self.assertEqual(parsed.todo_prefix, "c03d")
        self.assertEqual(parsed.objid_prefix, "0045")
        self.assertTrue(parsed.is_remote)
        self.assertFalse(parsed.is_local)

    def test_raw_keeps_the_spelling_it_came_in(self) -> None:
        # Targets are stored as written and resolved at use time, so a full
        # 64-hex todo id and a 4-hex prefix are both kept verbatim.
        full = "todo:" + "c" * 64 + "/objid:0045"
        self.assertEqual(todo_ref.parse_target(full).raw, full)
        self.assertEqual(todo_ref.parse_target("objid:0034").raw, "objid:0034")

    def test_a_longer_prefix_is_still_one_target(self) -> None:
        parsed = todo_ref.parse_target("objid:0034abcdef")
        self.assertEqual(parsed.objid_prefix, "0034abcdef")

    def test_is_target_agrees_with_parse(self) -> None:
        for value in ("objid:0034", "todo:dea7", "todo:c03d/objid:0045"):
            with self.subTest(value=value):
                self.assertTrue(todo_ref.is_target(value))
        for value in ("0034", "objid:34", "objid:00FF", None, "", 4):
            with self.subTest(value=value):
                self.assertFalse(todo_ref.is_target(value))


class TargetRejectionTest(unittest.TestCase):
    """What a target is NOT, and whether the message says which fault it hit."""

    def _fault(self, value: object) -> str:
        with self.assertRaises(todo_ref.TodoRefError) as caught:
            todo_ref.parse_target(value)
        return str(caught.exception)

    def test_a_bare_hex_string_is_not_qualified(self) -> None:
        self.assertIn("not qualified", self._fault("0034"))

    def test_a_short_prefix_names_the_length_floor(self) -> None:
        self.assertIn("shorter than 4", self._fault("objid:34"))
        self.assertIn("shorter than 4", self._fault("todo:c0"))

    def test_uppercase_hex_is_reported_as_case_not_length(self) -> None:
        self.assertIn("lowercase hex", self._fault("objid:00FF"))

    def test_a_cross_todo_form_missing_its_todo_scheme(self) -> None:
        self.assertIn("cross-todo", self._fault("c03d/objid:0045"))

    def test_three_segments_is_too_many(self) -> None:
        self.assertIn("too many segments", self._fault("todo:c03d/objid:0045/objid:0046"))

    def test_an_unknown_namespace_is_named(self) -> None:
        self.assertIn("not a target namespace", self._fault("sha:0034"))

    def test_an_empty_or_non_string_target(self) -> None:
        for value in ("", None, 4, [], {"target": "objid:0034"}):
            with self.subTest(value=value):
                self.assertIn("non-empty string", self._fault(value))

    def test_trailing_junk_does_not_parse(self) -> None:
        for value in ("objid:0034x", "objid:0034.", "todo:dea7/", " objid:0034"):
            with self.subTest(value=value):
                self.assertRaises(todo_ref.TodoRefError, todo_ref.parse_target, value)


class ScanProseTest(unittest.TestCase):
    """What the doctor-side scanner finds in text a human wrote."""

    def test_a_target_in_backticks(self) -> None:
        self.assertEqual(todo_ref.scan_targets("see `objid:0034` for the count"), ["objid:0034"])

    def test_a_target_at_end_of_sentence(self) -> None:
        self.assertEqual(todo_ref.scan_targets("the count lives in objid:0034."), ["objid:0034"])

    def test_a_target_inside_a_markdown_link(self) -> None:
        text = "[objid:0034](http://localhost:8765/aa62/objid/0034) has it"
        self.assertEqual(todo_ref.scan_targets(text), ["objid:0034"])

    def test_a_permalink_is_not_a_target(self) -> None:
        # Slash-and-no-colon is the permalink grammar; only the colon spelling
        # is a target.
        self.assertEqual(todo_ref.scan_targets("http://localhost:8765/aa62/objid/0034"), [])

    def test_a_cross_todo_target_is_found_whole(self) -> None:
        self.assertEqual(
            todo_ref.scan_targets("ratified in todo:c03d/objid:0045, do not relitigate"),
            ["todo:c03d/objid:0045"],
        )

    def test_a_malformed_cross_todo_target_yields_nothing(self) -> None:
        # Not even its own first half: the text names no well-formed target.
        self.assertEqual(todo_ref.scan_targets("see todo:c03d/objid:45 please"), [])

    def test_an_unqualified_cross_todo_form_is_not_a_local_target(self) -> None:
        self.assertEqual(todo_ref.scan_targets("see c03d/objid:0045 please"), [])

    def test_a_word_character_on_either_side_disqualifies(self) -> None:
        for text in ("objid:0034x", "noobjid:0034", "xtodo:dea7"):
            with self.subTest(text=text):
                self.assertEqual(todo_ref.scan_targets(text), [])

    def test_several_targets_come_back_in_first_occurrence_order(self) -> None:
        text = "todo:dea7 then objid:0034, then objid:0034 again, then todo:c03d/objid:0045"
        self.assertEqual(
            todo_ref.scan_targets(text),
            ["todo:dea7", "objid:0034", "todo:c03d/objid:0045"],
        )

    def test_prose_with_no_target(self) -> None:
        for text in ("", None, "no ids here at all", "0034 and 45"):
            with self.subTest(text=text):
                self.assertEqual(todo_ref.scan_targets(text), [])


class ResolveLocalTest(unittest.TestCase):
    """A local target against a real record: hit, miss, ambiguity, wrong kind."""

    def test_a_local_target_resolves_to_a_json_path(self) -> None:
        todo = _record()
        note_objid = todo["Notes"][0]["objid"]
        self.assertEqual(todo_ref.resolve_local(todo, f"objid:{note_objid}"), "Notes.0")

    def test_any_object_is_a_legal_target_not_only_a_note(self) -> None:
        todo = _record()
        item_objid = todo["WorkItems"][1]["objid"]
        self.assertEqual(todo_ref.resolve_local(todo, f"objid:{item_objid}"), "WorkItems.1")
        body_objid = todo["Body"]["objid"]
        self.assertEqual(todo_ref.resolve_local(todo, f"objid:{body_objid}"), "Body")

    def test_a_parsed_target_is_accepted_as_well_as_a_string(self) -> None:
        todo = _record()
        parsed = todo_ref.parse_target(f"objid:{todo['Notes'][0]['objid']}")
        self.assertEqual(todo_ref.resolve_local(todo, parsed), "Notes.0")

    def test_an_objid_no_object_carries_is_a_miss(self) -> None:
        with self.assertRaises(todo_ref.TodoRefError) as caught:
            todo_ref.resolve_local(_record(), "objid:ffff")
        self.assertIn("ffff", str(caught.exception))

    def test_an_ambiguous_prefix_is_an_error_not_a_guess(self) -> None:
        todo = _record()
        todo["Notes"].append({"objid": "0abc", "raw": "one"})
        todo["Notes"].append({"objid": "0abd", "raw": "two"})
        with self.assertRaises(todo_ref.TodoRefError) as caught:
            todo_ref.resolve_local(todo, "objid:0ab")
        self.assertIn("shorter than 4", str(caught.exception))
        with self.assertRaises(todo_ref.TodoRefError) as caught:
            todo_ref.resolve_local(todo, "objid:0abc0")
        self.assertIn("0abc0", str(caught.exception))

    def test_a_four_character_prefix_matching_two_objects_is_ambiguous(self) -> None:
        todo = _record()
        todo["Notes"].append({"objid": "0abc1", "raw": "one"})
        todo["Notes"].append({"objid": "0abc2", "raw": "two"})
        with self.assertRaises(todo_ref.TodoRefError) as caught:
            todo_ref.resolve_local(todo, "objid:0abc")
        self.assertIn("ambiguous", str(caught.exception))

    def test_a_whole_todo_target_does_not_resolve_against_a_record(self) -> None:
        with self.assertRaises(todo_ref.TodoRefError) as caught:
            todo_ref.resolve_local(_record(), "todo:dea7")
        self.assertIn("whole todo", str(caught.exception))

    def test_a_cross_todo_target_must_be_resolved_against_that_record(self) -> None:
        with self.assertRaises(todo_ref.TodoRefError) as caught:
            todo_ref.resolve_local(_record(), "todo:c03d/objid:0045")
        self.assertIn("another todo", str(caught.exception))


class RelationTypeTest(unittest.TestCase):
    """The seeded relation vocabulary."""

    def test_mention_is_the_derived_type_and_relates_the_manual_default(self) -> None:
        self.assertEqual(todo_ref.TYPE_MENTION, "mention")
        self.assertEqual(todo_ref.TYPE_RELATES, "relates")

    def test_the_allow_list_holds_exactly_the_seeded_types(self) -> None:
        self.assertEqual(todo_ref.RELATION_TYPES, frozenset({"mention", "relates"}))


if __name__ == "__main__":
    unittest.main()
