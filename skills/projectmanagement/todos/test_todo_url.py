#!/usr/bin/env python3
"""Unit tests for the permalink path grammar (url path -> json dot-path)."""

from __future__ import annotations

import unittest

import todo_url

# A record with one of everything the grammar has to walk: a plain object, a
# list whose name takes the drop-the-s alias, a list whose name does not, both
# Tag and legacy Tags (so exact match must beat the alias), and an Oxen field
# standing in for a future list nobody taught the parser about.
TODO = {
    "Id": "557ab9d3" + "0" * 56,
    "Branch": "557ab9d3-routing",
    "State": {"working": {"owner": "agent"}},
    "Summary": {"raw": "routing and agent choice", "objid": "0000"},
    "Scope": {"branch": "557ab9d3-routing", "objid": "0001"},
    "WorkItems": [
        {"summary": "first", "sha": "883368de28aa", "objid": "0002"},
        {"summary": "second", "sha": "b138145541dd", "objid": "0003"},
        {
            "summary": "third",
            "sha": "b138999999ff",
            "objid": "0004",
            "execution": {"mode": "parallel", "objid": "0005"},
        },
    ],
    "Subtodos": [
        {"Id": "13e57db1aaaa", "subtodo_id": "13e57db1aaaa", "objid": "0006"},
        {"Id": "1ae90d40bbbb", "subtodo_id": "1ae90d40bbbb", "objid": "0007"},
    ],
    "Tag": [{"raw": "alpha", "objid": "0008"}],
    "Tags": [{"raw": "legacy", "objid": "0009"}],
    "Oxen": [{"name": "bessie", "objid": "000a"}],
    # A widened id (this todo once held more than 65536 objects), which is the
    # only way two objids can share a 4-character prefix -- so it is what makes
    # an ambiguous objid prefix testable at all.
    "Agent": {"type": "cli", "objid": "00025"},
    "_nextobjid": 38,
}


class SplitUrlPathTest(unittest.TestCase):
    """A permalink splits into a todo selector plus segments."""

    def test_full_url(self) -> None:
        self.assertEqual(
            ("557a", ["workitem", "5", "summary"]),
            todo_url.split_url_path("http://localhost:8765/557a/workitem/5/summary"),
        )

    def test_bare_path(self) -> None:
        self.assertEqual(
            ("557a", ["workitem", "5"]),
            todo_url.split_url_path("/557a/workitem/5"),
        )

    def test_trailing_slash_and_query_and_fragment(self) -> None:
        self.assertEqual(
            ("557a", ["summary"]),
            todo_url.split_url_path("http://h/557a/summary/?x=1#frag"),
        )

    def test_percent_decoding(self) -> None:
        self.assertEqual(("557a", ["a b"]), todo_url.split_url_path("/557a/a%20b"))

    def test_todoid_only(self) -> None:
        self.assertEqual(("557a", []), todo_url.split_url_path("/557a"))

    def test_empty_path_errors(self) -> None:
        with self.assertRaises(todo_url.TodoUrlError):
            todo_url.split_url_path("http://localhost:8765/")


class ToJsonPathTest(unittest.TestCase):
    """Segments translate to the internal dot-path get-json-path takes."""

    def path(self, *segments: str) -> str:
        return todo_url.to_json_path(TODO, list(segments))

    def test_no_segments_is_the_record(self) -> None:
        self.assertEqual("", self.path())

    def test_field_is_case_insensitive(self) -> None:
        self.assertEqual("Summary.raw", self.path("summary", "raw"))
        self.assertEqual("Summary.raw", self.path("SUMMARY", "RAW"))
        self.assertEqual("Summary.raw", self.path("Summary", "raw"))

    def test_bare_index_is_zero_based(self) -> None:
        self.assertEqual("WorkItems.0.summary", self.path("workitem", "0", "summary"))
        self.assertEqual("WorkItems.1.summary", self.path("workitem", "1", "summary"))

    def test_explicit_idx(self) -> None:
        self.assertEqual("WorkItems.1.summary", self.path("workitem", "idx", "1", "summary"))

    def test_plural_field_name_also_works(self) -> None:
        self.assertEqual("WorkItems.1", self.path("workitems", "1"))

    def test_drop_the_s_is_not_singularization(self) -> None:
        self.assertEqual("Oxen.0.name", self.path("oxen", "0", "name"))
        with self.assertRaises(todo_url.TodoUrlError):
            self.path("ox", "0")

    def test_exact_match_beats_drop_the_s_alias(self) -> None:
        # `tag` is the real Tag field, never the alias of legacy Tags.
        self.assertEqual("Tag.0.raw", self.path("tag", "0", "raw"))
        self.assertEqual("Tags.0.raw", self.path("tags", "0", "raw"))

    def test_non_list_field_has_no_alias(self) -> None:
        with self.assertRaises(todo_url.TodoUrlError):
            self.path("scop")

    def test_sha_prefix(self) -> None:
        self.assertEqual("WorkItems.0.summary", self.path("workitem", "sha", "883368", "summary"))

    def test_subtodo_id_prefix(self) -> None:
        self.assertEqual("Subtodos.1", self.path("subtodo", "subtodo_id", "1ae90d40"))

    def test_objid_prefix_within_a_list(self) -> None:
        self.assertEqual("WorkItems.2", self.path("workitem", "objid", "0004"))

    def test_objid_at_top_level_needs_no_collection(self) -> None:
        self.assertEqual("WorkItems.2.execution", self.path("objid", "0005"))
        self.assertEqual("Subtodos.0", self.path("objid", "0006"))

    def test_objid_at_top_level_can_be_walked_further(self) -> None:
        self.assertEqual("WorkItems.1.summary", self.path("objid", "0003", "summary"))

    def test_objid_is_a_field_below_the_root(self) -> None:
        self.assertEqual("Summary.objid", self.path("summary", "objid"))

    def test_out_of_bounds_index(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "out of bounds"):
            self.path("workitem", "883368", "summary")

    def test_bare_non_numeric_segment_is_not_an_index(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "always an index"):
            self.path("workitem", "883368de", "summary")

    def test_ambiguous_sha_prefix(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "ambiguous"):
            self.path("workitem", "sha", "b138")

    def test_ambiguous_objid_prefix(self) -> None:
        # 0002 is WorkItems.0's whole id and also a prefix of Agent's 00025.
        with self.assertRaisesRegex(todo_url.TodoUrlError, "ambiguous"):
            self.path("objid", "0002")

    def test_widened_objid_resolves_exactly(self) -> None:
        self.assertEqual("Agent", self.path("objid", "00025"))

    def test_short_prefix_rejected(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "shorter than 4"):
            self.path("workitem", "sha", "883")

    def test_unmatched_prefix(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "no element here"):
            self.path("workitem", "sha", "deadbeef")

    def test_unknown_objid(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "no object in this todo"):
            self.path("objid", "ffff")

    def test_unknown_field_lists_what_is_there(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "unknown field 'nope'"):
            self.path("nope")

    def test_where_key_without_a_value(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "needs a value"):
            self.path("workitem", "sha")

    def test_top_level_objid_without_a_value(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "needs a value"):
            self.path("objid")

    def test_cannot_descend_into_a_scalar(self) -> None:
        with self.assertRaisesRegex(todo_url.TodoUrlError, "cannot descend"):
            self.path("summary", "raw", "more")

    def test_state_is_reachable_without_an_objid(self) -> None:
        self.assertEqual("State.working.owner", self.path("state", "working", "owner"))


class ValueAtTest(unittest.TestCase):
    """value_at returns what the translated path addresses."""

    def test_scalar(self) -> None:
        self.assertEqual("first", todo_url.value_at(TODO, "WorkItems.0.summary"))

    def test_object(self) -> None:
        self.assertEqual({"mode": "parallel", "objid": "0005"},
                         todo_url.value_at(TODO, "WorkItems.2.execution"))

    def test_empty_path_is_the_record(self) -> None:
        self.assertIs(TODO, todo_url.value_at(TODO, ""))


if __name__ == "__main__":
    unittest.main()
