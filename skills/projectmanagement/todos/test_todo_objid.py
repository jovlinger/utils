#!/usr/bin/env python3
"""Unit tests for the objid allocator and stamper."""

from __future__ import annotations

import json
import unittest

import todo_objid


def _record(**extra: object) -> dict:
    """A minimal todo-shaped record; *extra* adds or overrides top-level fields."""
    todo: dict = {
        "Id": "71fabcb7" + "0" * 56,
        "Branch": "71fabcb7-objid",
        "State": {"working": {"owner": "agent"}},
        "Summary": {"raw": "a summary"},
    }
    todo.update(extra)
    return todo


def _bare(**extra: object) -> dict:
    """A record holding NO stampable object of its own -- State is exempt.

    Counter arithmetic is asserted against this so the expected ids are the
    ones *extra* produces, with nothing allocated ahead of them.
    """
    todo: dict = {"Id": "71fabcb7" + "0" * 56, "State": {"groom": {}}}
    todo.update(extra)
    return todo


def _objids(node: object) -> list:
    """Every objid in *node*, in depth-first walk order."""
    found: list = []
    if isinstance(node, dict):
        if isinstance(node.get("objid"), str):
            found.append(node["objid"])
        for value in node.values():
            found.extend(_objids(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_objids(value))
    return found


class StampObjidsTest(unittest.TestCase):
    """stamp_objids assigns, preserves, and de-duplicates object ids."""

    def test_stamps_every_nested_object(self) -> None:
        todo = _record(
            Scope={"branch": "b"},
            Summary={"raw": "s"},
            Body={"raw": "b"},
            WorkItems=[{"summary": "one", "done": False}],
            Subtodos=[{"Id": "abc", "State": "merged"}],
        )
        todo_objid.stamp_objids(todo)
        self.assertIn("objid", todo["Scope"])
        self.assertIn("objid", todo["Summary"])
        self.assertIn("objid", todo["Body"])
        self.assertIn("objid", todo["WorkItems"][0])
        self.assertIn("objid", todo["Subtodos"][0])

    def test_root_is_exempt(self) -> None:
        todo = _record()
        todo_objid.stamp_objids(todo)
        self.assertNotIn("objid", todo)

    def test_state_subtree_is_exempt(self) -> None:
        todo = _record(State={"working": {"owner": "agent"}})
        todo_objid.stamp_objids(todo)
        self.assertNotIn("objid", todo["State"])
        self.assertNotIn("objid", todo["State"]["working"])
        self.assertEqual({"working": {"owner": "agent"}}, todo["State"])

    def test_allocates_from_zero_in_walk_order(self) -> None:
        todo = _record(
            Summary={"raw": "s"},
            WorkItems=[{"summary": "one"}, {"summary": "two"}],
        )
        todo_objid.stamp_objids(todo)
        self.assertEqual("0000", todo["Summary"]["objid"])
        self.assertEqual("0001", todo["WorkItems"][0]["objid"])
        self.assertEqual("0002", todo["WorkItems"][1]["objid"])
        self.assertEqual(3, todo["_nextobjid"])

    def test_parent_is_stamped_before_its_children(self) -> None:
        todo = _record(WorkItems=[{"summary": "one", "execution": {"mode": "parallel"}}])
        todo_objid.stamp_objids(todo)
        item = todo["WorkItems"][0]
        self.assertLess(int(item["objid"], 16), int(item["execution"]["objid"], 16))

    def test_existing_objids_are_preserved(self) -> None:
        todo = _record(
            Summary={"raw": "s", "objid": "00ff"},
            WorkItems=[{"summary": "one", "objid": "0a3f"}],
        )
        todo_objid.stamp_objids(todo)
        self.assertEqual("00ff", todo["Summary"]["objid"])
        self.assertEqual("0a3f", todo["WorkItems"][0]["objid"])

    def test_restamp_is_a_no_op(self) -> None:
        todo = _record(
            Scope={"branch": "b"},
            WorkItems=[{"summary": "one"}, {"summary": "two"}],
        )
        self.assertTrue(todo_objid.stamp_objids(todo))
        snapshot = json.dumps(todo, sort_keys=True)
        self.assertFalse(todo_objid.stamp_objids(todo))
        self.assertEqual(snapshot, json.dumps(todo, sort_keys=True))

    def test_new_object_gets_the_next_id_leaving_others_alone(self) -> None:
        todo = _bare(WorkItems=[{"summary": "one"}])
        todo_objid.stamp_objids(todo)
        first = todo["WorkItems"][0]["objid"]
        todo["WorkItems"].append({"summary": "two"})
        self.assertTrue(todo_objid.stamp_objids(todo))
        self.assertEqual(first, todo["WorkItems"][0]["objid"])
        self.assertEqual("0001", todo["WorkItems"][1]["objid"])

    def test_duplicate_reassigns_the_later_occurrence(self) -> None:
        todo = _bare(
            WorkItems=[
                {"summary": "one", "objid": "0007"},
                {"summary": "copy", "objid": "0007"},
            ]
        )
        todo_objid.stamp_objids(todo)
        self.assertEqual("0007", todo["WorkItems"][0]["objid"])
        self.assertNotEqual("0007", todo["WorkItems"][1]["objid"])
        self.assertEqual(2, len(set(_objids(todo))))

    def test_malformed_objids_are_replaced(self) -> None:
        todo = _record(
            Summary={"raw": "s", "objid": "zzzz"},
            Body={"raw": "b", "objid": 17},
            Scope={"branch": "b", "objid": "0a3"},
        )
        todo_objid.stamp_objids(todo)
        for field in ("Summary", "Body", "Scope"):
            with self.subTest(field=field):
                self.assertRegex(todo[field]["objid"], r"^[0-9a-f]{4,}$")
        self.assertEqual(3, len(set(_objids(todo))))

    def test_uppercase_hex_is_malformed(self) -> None:
        todo = _record(Summary={"raw": "s", "objid": "00FF"})
        todo_objid.stamp_objids(todo)
        self.assertEqual("0000", todo["Summary"]["objid"])

    def test_cursor_comes_from_nextobjid(self) -> None:
        todo = _bare(WorkItems=[{"summary": "one"}], _nextobjid=41)
        todo_objid.stamp_objids(todo)
        self.assertEqual("0029", todo["WorkItems"][0]["objid"])
        self.assertEqual(42, todo["_nextobjid"])

    def test_never_reuses_an_id_the_cursor_already_passed(self) -> None:
        todo = _record(
            Summary={"raw": "s", "objid": "0005"},
            WorkItems=[{"summary": "one"}],
            _nextobjid=5,
        )
        todo_objid.stamp_objids(todo)
        self.assertEqual("0005", todo["Summary"]["objid"])
        self.assertEqual("0006", todo["WorkItems"][0]["objid"])
        self.assertEqual(7, todo["_nextobjid"])

    def test_nextobjid_catches_up_to_existing_ids(self) -> None:
        todo = _record(Summary={"raw": "s", "objid": "00ff"})
        todo_objid.stamp_objids(todo)
        self.assertEqual(0x100, todo["_nextobjid"])

    def test_broken_nextobjid_is_recovered(self) -> None:
        todo = _bare(WorkItems=[{"summary": "one"}], _nextobjid="nonsense")
        todo_objid.stamp_objids(todo)
        self.assertEqual("0000", todo["WorkItems"][0]["objid"])
        self.assertEqual(1, todo["_nextobjid"])

    def test_ids_widen_past_four_hex(self) -> None:
        todo = _bare(WorkItems=[{"summary": "one"}], _nextobjid=0xFFFF)
        todo_objid.stamp_objids(todo)
        self.assertEqual("ffff", todo["WorkItems"][0]["objid"])
        todo["WorkItems"].append({"summary": "two"})
        todo_objid.stamp_objids(todo)
        self.assertEqual("10000", todo["WorkItems"][1]["objid"])

    def test_non_dict_list_members_are_untouched(self) -> None:
        todo = _record(Summary={"raw": "s", "vec": [[0.1, 0.2], [0.3]]})
        todo_objid.stamp_objids(todo)
        self.assertEqual([[0.1, 0.2], [0.3]], todo["Summary"]["vec"])

    def test_empty_record_allocates_nothing(self) -> None:
        todo = {"Id": "x", "State": {"groom": {}}}
        self.assertFalse(todo_objid.stamp_objids(todo))
        self.assertNotIn("_nextobjid", todo)


class IterObjectsTest(unittest.TestCase):
    """iter_objects yields the stampable objects with their json paths."""

    def test_yields_path_and_object(self) -> None:
        todo = _record(WorkItems=[{"summary": "one", "execution": {"mode": "parallel"}}])
        paths = [path for path, _ in todo_objid.iter_objects(todo)]
        self.assertEqual(
            ["Summary", "WorkItems.0", "WorkItems.0.execution"],
            paths,
        )

    def test_skips_root_and_state(self) -> None:
        todo = _record()
        paths = [path for path, _ in todo_objid.iter_objects(todo)]
        self.assertEqual(["Summary"], paths)


if __name__ == "__main__":
    unittest.main()
