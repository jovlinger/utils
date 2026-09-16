"""Qualified cross-reference targets: the ``relto`` grammar.

A ``relto`` element points at something with a namespace-qualified ``target``
string -- the same spelling an id takes in prose, so ONE grammar serves the
value stored in the record, the token ``doctor`` scans prose for, and what a
human types::

    objid:0034              an object in THIS record
    todo:dea7               a whole todo
    todo:c03d/objid:0045    an object in another todo's record

Every hex component takes 4+ characters, the floor ``todo_url.MIN_PREFIX``
imposes: an ``objid:`` target is matched against every object in a record, and
a ``todo:`` prefix against every record in the store. Work-item addressing is
the other regime -- there ``objid:3`` is padded to ``0003`` and matched against
one short list (``todo.py`` ``_workitem_index_by_objid``).

Targets are stored AS WRITTEN and resolved at use time, like every other
selector the tool takes; a prefix that goes ambiguous later is a doctor
finding.

``mention`` is the one DERIVED relation type: ``doctor`` reconciles a node's
``mention`` entries against the targets its own prose contains, and touches no
entry of any other type. ``relates`` is the manual default.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, NamedTuple, Union

import todo_url

# The relation type doctor owns; every other type is manual and doctor leaves
# it untouched, which is what makes a derived field safe to hand-edit.
TYPE_MENTION: str = "mention"

# What relto-add writes when no type is given.
TYPE_RELATES: str = "relates"

RELATION_TYPES: frozenset = frozenset({TYPE_MENTION, TYPE_RELATES})

# Namespace prefixes. Both are part of the stored value, not decoration.
TODO_SCHEME: str = "todo:"
OBJID_SCHEME: str = "objid:"

# One hex component of a target.
_HEX: str = f"[0-9a-f]{{{todo_url.MIN_PREFIX},}}"

# A whole target, anchored. The cross-todo group is greedy, so the two-segment
# spelling wins over the ``todo:`` prefix it begins with.
_TARGET_RE = re.compile(
    rf"^(?:{TODO_SCHEME}(?P<todo>{_HEX})(?:/{OBJID_SCHEME}(?P<remote>{_HEX}))?"
    rf"|{OBJID_SCHEME}(?P<local>{_HEX}))$"
)

# Any lowercase-hex run, for telling "wrong case" apart from "too short".
_LOWER_HEX_RE = re.compile(r"^[0-9a-f]+$")

# The same grammar loose in prose. The lookarounds keep a token whole: ``/``
# and ``:`` on the left, so an unqualified ``c03d/objid:0045`` never reads as a
# local target; a word character on the right, so ``objid:0034x`` is not a
# target trailed by an ``x``; and ``/objid:`` on the right, so a malformed
# cross-todo spelling yields nothing rather than its own first half.
_SCAN_RE = re.compile(
    rf"(?<![0-9A-Za-z_/:])"
    rf"(?:{TODO_SCHEME}{_HEX}(?:/{OBJID_SCHEME}{_HEX})?|{OBJID_SCHEME}{_HEX})"
    rf"(?![0-9A-Za-z_])(?!/{OBJID_SCHEME})"
)

JsonDict = Dict[str, Any]


class TodoRefError(Exception):
    """A target that does not parse, or does not resolve where it was asked."""


class Target(NamedTuple):
    """A parsed target: the prefixes it carries, and the spelling it came in.

    ``todo_prefix`` is empty for a target local to the record holding it;
    ``objid_prefix`` is empty for one naming a whole todo. Both are prefixes,
    never resolved ids, because ``raw`` is what the record stores.
    """

    raw: str
    todo_prefix: str
    objid_prefix: str

    @property
    def is_local(self) -> bool:
        """True when the target names an object in the record holding it."""
        return not self.todo_prefix and bool(self.objid_prefix)

    @property
    def is_whole_todo(self) -> bool:
        """True when the target names a todo rather than an object in one."""
        return bool(self.todo_prefix) and not self.objid_prefix

    @property
    def is_remote(self) -> bool:
        """True when the target names an object in ANOTHER todo's record."""
        return bool(self.todo_prefix) and bool(self.objid_prefix)


def _fault(value: str) -> str:
    """The most specific complaint that applies to an unparseable *value*."""
    segments = value.split("/")
    if len(segments) > 2:
        return f"target {value!r} has too many segments; at most todo:<hex>/objid:<hex>"
    if len(segments) == 2 and not (
        segments[0].startswith(TODO_SCHEME) and segments[1].startswith(OBJID_SCHEME)
    ):
        return f"target {value!r} spells a cross-todo reference todo:<hex>/objid:<hex>"
    for segment in segments:
        scheme, sep, hexpart = segment.partition(":")
        if not sep:
            return (
                f"target {value!r} is not qualified: objid:<hex> names an object in this "
                "record, todo:<hex> a todo, todo:<hex>/objid:<hex> an object in another todo"
            )
        if f"{scheme}:" not in (TODO_SCHEME, OBJID_SCHEME):
            return f"'{scheme}:' is not a target namespace; use 'todo:' or 'objid:'"
        if not _LOWER_HEX_RE.match(hexpart):
            return f"{segment!r} must end in lowercase hex"
        if len(hexpart) < todo_url.MIN_PREFIX:
            return (
                f"{segment!r} is shorter than {todo_url.MIN_PREFIX} characters, and a "
                "target prefix is matched record-wide"
            )
    return f"target {value!r} does not parse"


def parse_target(value: Any) -> Target:
    """Parse *value* as a target, or raise ``TodoRefError`` naming the fault."""
    if not isinstance(value, str) or not value:
        raise TodoRefError("a target is a non-empty string, e.g. objid:0034")
    match = _TARGET_RE.match(value)
    if match is None:
        raise TodoRefError(_fault(value))
    return Target(
        raw=value,
        todo_prefix=match.group("todo") or "",
        objid_prefix=match.group("remote") or match.group("local") or "",
    )


def is_target(value: Any) -> bool:
    """True when *value* is a well-formed target."""
    return isinstance(value, str) and _TARGET_RE.match(value) is not None


def scan_targets(text: Any) -> List[str]:
    """Every target token in *text*, in first-occurrence order, de-duplicated.

    De-duplicated because a caller reconciling a node's ``mention`` entries
    wants the SET its prose names: citing one object twice in a paragraph is
    one relation, not two.
    """
    if not isinstance(text, str) or not text:
        return []
    found: Dict[str, None] = {}
    for match in _SCAN_RE.finditer(text):
        found.setdefault(match.group(0), None)
    return list(found)


def resolve_local(todo: JsonDict, target: Union[str, Target]) -> str:
    """Return the json dot-path of the object a LOCAL *target* names in *todo*.

    Delegates to the permalink resolver, so ``objid:0034`` in a relto and
    ``/<todoid>/objid/0034`` in a link find the same object under the same
    ambiguity and length rules. A target naming a whole todo, or an object in
    another record, is a caller error rather than a miss: neither is resolvable
    against *todo* at all.
    """
    parsed = target if isinstance(target, Target) else parse_target(target)
    if parsed.is_whole_todo:
        raise TodoRefError(f"target {parsed.raw!r} names a whole todo, not an object in one")
    if parsed.is_remote:
        raise TodoRefError(
            f"target {parsed.raw!r} names another todo's record; resolve it against that record"
        )
    try:
        return todo_url.to_json_path(todo, ["objid", parsed.objid_prefix])
    except todo_url.TodoUrlError as exc:
        raise TodoRefError(f"target {parsed.raw!r}: {exc}") from exc
