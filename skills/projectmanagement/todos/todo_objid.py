"""Stable per-object ids (``objid``) inside one todo record.

Every JSON object nested in a todo carries an immutable ``objid``: a short
lowercase-hex string, unique within that todo, which names the object for the
life of the record. Permalinks are built on it -- ``/<todoid>/objid/<prefix>``
addresses one object without depending on a list index that shifts whenever the
work plan is edited. A subtodo is a separate record and therefore a separate
id scope; the same ``objid`` in two todos means nothing.

Allocation is a creation-order counter, not a PRNG: ids come from the top-level
``_nextobjid`` cursor and render as ``%04x``, widening past four characters only
if one todo ever holds more than 65536 objects. The cursor is an allocation
bookmark ONLY -- it is deliberately not an optimistic-locking token, since it
does not change on every write (``update_dt`` is the field that would serve
that role).

Two objects are exempt:

* the **root** record, which the todo ``Id`` already names;
* the whole **State** subtree, because ``doctor`` requires ``State`` to hold
  exactly one key and each state's value object has its own metadata
  allow-list (see ``_STATE_METADATA`` in ``todo.py``). ``State`` stays
  addressable by path, it just carries no ``objid``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterator, List, Tuple

JsonDict = Dict[str, Any]

OBJID_KEY: str = "objid"
NEXT_OBJID_KEY: str = "_nextobjid"

# A well-formed objid: lowercase hex, at least the 4 characters `%04x` renders.
# Uppercase is deliberately rejected so there is exactly one spelling of an id
# and a prefix match never has to case-fold.
OBJID_RE = re.compile(r"^[0-9a-f]{4,}$")

# Top-level field whose subtree is never stamped (see module docstring).
_EXEMPT_TOP_FIELD: str = "State"


def format_objid(value: int) -> str:
    """Render an allocation counter as an objid."""
    return format(value, "04x")


def is_objid(value: Any) -> bool:
    """True when *value* is a well-formed objid."""
    return isinstance(value, str) and bool(OBJID_RE.match(value))


def iter_objects(todo: JsonDict) -> Iterator[Tuple[str, JsonDict]]:
    """Yield ``(json_path, object)`` for every stampable object in *todo*.

    Walk order is depth-first in record order, each object before its children,
    so ids read as creation order and a parent always sorts below its own
    contents. Paths are the internal dot-path syntax ``get-json-path`` uses
    (``WorkItems.0.execution``), so a caller can hand one straight to the
    existing path machinery. The root and the ``State`` subtree are skipped.
    """

    def walk(node: Any, path: str) -> Iterator[Tuple[str, JsonDict]]:
        if isinstance(node, dict):
            if path:
                yield path, node
            for key, value in node.items():
                if not path and key == _EXEMPT_TOP_FIELD:
                    continue
                if isinstance(value, (dict, list)):
                    yield from walk(value, f"{path}.{key}" if path else str(key))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if isinstance(value, (dict, list)):
                    yield from walk(value, f"{path}.{index}")

    yield from walk(todo, "")


def stamp_objids(todo: JsonDict) -> bool:
    """Give every stampable object in *todo* an objid; return True if it changed.

    Idempotent and non-destructive: an existing well-formed id is never
    rewritten, so a stamped record re-stamps to itself. An object gets a fresh
    id only when its own id is missing, malformed, or a DUPLICATE of one seen
    earlier in the walk -- duplicates arise when code copies a subobject inside
    a record, and breaking the tie in favour of the earlier occurrence keeps
    the id attached to the object that has been carrying it.

    ``_nextobjid`` is advanced past every id in the record, including ids that
    were already higher than the stored cursor (a hand-edited or
    partially-migrated record), so it always names an unused value.
    """
    objects: List[Tuple[str, JsonDict]] = list(iter_objects(todo))
    if not objects:
        return False

    highest = -1
    for _, obj in objects:
        existing = obj.get(OBJID_KEY)
        if is_objid(existing):
            highest = max(highest, int(existing, 16))

    cursor = todo.get(NEXT_OBJID_KEY)
    if not isinstance(cursor, int) or isinstance(cursor, bool) or cursor < 0:
        cursor = 0
    cursor = max(cursor, highest + 1)

    changed = False
    taken: set = set()
    for _, obj in objects:
        existing = obj.get(OBJID_KEY)
        if is_objid(existing) and existing not in taken:
            taken.add(existing)
            continue
        while format_objid(cursor) in taken:
            cursor += 1
        fresh = format_objid(cursor)
        cursor += 1
        obj[OBJID_KEY] = fresh
        taken.add(fresh)
        changed = True

    if todo.get(NEXT_OBJID_KEY) != cursor:
        todo[NEXT_OBJID_KEY] = cursor
        changed = True
    return changed
