"""Translate a permalink path into an internal json dot-path.

A permalink is all path segments, no query string::

    http://localhost:8765/557a/workitem/5/summary
    http://localhost:8765/557a/workitem/sha/883368/summary
    http://localhost:8765/557a/objid/0a3f

The first segment selects the todo (any 4+ hex Id prefix, the same selector
every other command takes); the rest walk into that todo's record. Translation
to a json path is the FIRST step of resolving a link -- everything downstream
(the CLI's ``resolveurl``, the web viewer's deep links) works from the path, so
there is one grammar and one place it is interpreted.

Walking a **dict**, a segment names a field, matched case-insensitively. One
usability aid: a LIST-valued field whose name ends in ``s`` also answers to the
name without it -- that is naming the element type, not singularizing, so
``WorkItems`` (a list of WorkItem) answers to ``workitem`` while ``Oxen``
answers only to ``oxen``. An exact case-insensitive match always wins over a
drop-the-s alias, so ``tag`` means ``Tag`` even when legacy ``Tags`` is present.

Walking a **list**, a segment is a where-clause. The default key is ``idx``, so
a bare segment is ALWAYS an index -- ``/workitem/883368/summary`` is perfectly
well defined and simply out of bounds. Indexes are 0-based, identical to the
json path, ``jq``, and doctor's finding labels, so a link built from what those
print can never be off by one. An index is exact; the other three keys --
``sha``, ``subtodo_id``, ``objid`` -- match on a 4+ character prefix.

``/<todoid>/objid/<prefix>`` is the canonical form: it finds an object anywhere
in the record without naming the collection that holds it, which is what makes
a permalink survive edits to the work plan.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple
from urllib.parse import unquote, urlsplit

import todo_objid

JsonDict = Dict[str, Any]

# Where-clause keys accepted in front of a list. `idx` is the default (a bare
# segment), and is the only one that is not a prefix match.
IDX_KEY: str = "idx"
PREFIX_KEYS: Tuple[str, ...] = ("sha", "subtodo_id", "objid")
WHERE_KEYS: Tuple[str, ...] = (IDX_KEY,) + PREFIX_KEYS

# Shortest prefix accepted for a prefix-matched where-clause, matching the 4+
# hex rule Id selectors use.
MIN_PREFIX: int = 4


class TodoUrlError(Exception):
    """A permalink path that does not address anything in this todo."""


def split_url_path(url: str) -> Tuple[str, List[str]]:
    """Split a permalink into ``(todo_selector, segments)``.

    Accepts a full URL or a bare path; any scheme, host, query, or fragment is
    discarded, so a link pasted from a browser works as-is. Segments are
    percent-decoded. Purely syntactic -- nothing here touches a record.
    """
    parts = urlsplit(url)
    raw = parts.path if parts.scheme or parts.netloc else url.split("?")[0].split("#")[0]
    segments = [unquote(segment) for segment in raw.split("/") if segment]
    if not segments:
        raise TodoUrlError("empty path: expected /<todoid>/<path...>")
    return segments[0], segments[1:]


def _resolve_field(node: JsonDict, segment: str) -> str:
    """Return the field of *node* that *segment* names, or raise."""
    wanted = segment.lower()
    exact = [key for key in node if key.lower() == wanted]
    if len(exact) > 1:
        raise TodoUrlError(f"{segment!r} matches several fields: {', '.join(sorted(exact))}")
    if exact:
        return exact[0]
    aliased = [
        key
        for key, value in node.items()
        if isinstance(value, list) and key.lower().endswith("s") and key.lower()[:-1] == wanted
    ]
    if len(aliased) > 1:
        raise TodoUrlError(f"{segment!r} matches several fields: {', '.join(sorted(aliased))}")
    if aliased:
        return aliased[0]
    known = ", ".join(sorted(node)) or "nothing"
    raise TodoUrlError(f"unknown field {segment!r}; this object has {known}")


def _resolve_index(node: List[Any], value: str) -> int:
    """Return the list index *value* names, or raise."""
    if not value.isdigit():
        raise TodoUrlError(f"index {value!r} is not a number (a bare segment is always an index)")
    index = int(value)
    if index >= len(node):
        raise TodoUrlError(f"index {index} is out of bounds ({len(node)} items)")
    return index


def _resolve_prefix(node: List[Any], key: str, value: str) -> int:
    """Return the index of the one element whose *key* starts with *value*."""
    if len(value) < MIN_PREFIX:
        raise TodoUrlError(f"{key} {value!r} is shorter than {MIN_PREFIX} characters")
    hits = [
        index
        for index, element in enumerate(node)
        if isinstance(element, dict)
        and isinstance(element.get(key), str)
        and element[key].startswith(value)
    ]
    if not hits:
        raise TodoUrlError(f"no element here has {key} starting with {value!r}")
    if len(hits) > 1:
        raise TodoUrlError(
            f"{key} {value!r} is ambiguous: matches indexes {', '.join(str(i) for i in hits)}"
        )
    return hits[0]


def _find_by_objid(todo: JsonDict, value: str) -> str:
    """Return the json path of the one object in *todo* whose objid matches."""
    if len(value) < MIN_PREFIX:
        raise TodoUrlError(f"objid {value!r} is shorter than {MIN_PREFIX} characters")
    hits = [
        path
        for path, obj in todo_objid.iter_objects(todo)
        if isinstance(obj.get(todo_objid.OBJID_KEY), str)
        and obj[todo_objid.OBJID_KEY].startswith(value)
    ]
    if not hits:
        raise TodoUrlError(f"no object in this todo has objid starting with {value!r}")
    if len(hits) > 1:
        raise TodoUrlError(f"objid {value!r} is ambiguous: matches {', '.join(sorted(hits))}")
    return hits[0]


def to_json_path(todo: JsonDict, segments: Sequence[str]) -> str:
    """Translate permalink *segments* into an internal json dot-path.

    Returns the empty string for no segments (the record itself). Raises
    ``TodoUrlError`` with a message naming what failed -- an unknown field, an
    out-of-bounds index, an ambiguous or too-short prefix.
    """
    node: Any = todo
    parts: List[str] = []
    pending = list(segments)
    while pending:
        segment = pending.pop(0)
        if isinstance(node, dict):
            # At the root, `objid` cannot be a field (the root is never stamped),
            # so it is the collection-free canonical lookup instead.
            if not parts and segment.lower() == "objid":
                if not pending:
                    raise TodoUrlError("objid needs a value: /<todoid>/objid/<prefix>")
                path = _find_by_objid(todo, pending.pop(0))
                parts = path.split(".")
                node = _dig(todo, parts)
                continue
            field = _resolve_field(node, segment)
            parts.append(field)
            node = node[field]
            continue
        if isinstance(node, list):
            key, value = IDX_KEY, segment
            if segment.lower() in WHERE_KEYS:
                if not pending:
                    raise TodoUrlError(f"{segment} needs a value")
                key, value = segment.lower(), pending.pop(0)
            if key == IDX_KEY:
                index = _resolve_index(node, value)
            else:
                index = _resolve_prefix(node, key, value)
            parts.append(str(index))
            node = node[index]
            continue
        raise TodoUrlError(f"cannot descend into {'.'.join(parts) or 'the record'} at {segment!r}")
    return ".".join(parts)


def _dig(todo: JsonDict, parts: Sequence[str]) -> Any:
    """Return the value at the already-resolved dot-path *parts*."""
    node: Any = todo
    for part in parts:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def value_at(todo: JsonDict, json_path: str) -> Any:
    """Return the value the translated *json_path* addresses in *todo*."""
    if not json_path:
        return todo
    return _dig(todo, json_path.split("."))
