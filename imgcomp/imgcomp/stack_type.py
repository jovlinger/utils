"""Stack layout contracts for the stack VM (Chuck Moore-style slot lists).

Each slot is a string name. For now every name matches any stack value; height
must match ``len(pre)`` / ``len(post)``. ``PrePost`` wraps authoring lists:
debug off strips the wrapper with zero runtime cost; debug on inserts Python
stack checks before and after the inner program.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

from imgcomp import _stack_c as _cy

# Wildcard slot: matches any value until we add typed matchers.
ANY: str = "name"

StackSlot = str
CheckKind = Literal["pre", "post"]

_DEBUG = os.environ.get("IMGCOMP_STACK_TYPE_DEBUG", "").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

_CHECK_BINDINGS: dict[str, tuple[CheckKind, tuple[str, ...], str]] = {}
_CHECK_OP_NAMES: dict[tuple[CheckKind, tuple[str, ...], str], str] = {}


@dataclass(frozen=True)
class StackType:
    """Stack effect ``( pre -- post )`` using named slots (bottom to top)."""

    pre: tuple[str, ...] = ()
    post: tuple[str, ...] = ()

    def effect_str(self) -> str:
        pre_txt = " ".join(self.pre) if self.pre else ""
        post_txt = " ".join(self.post) if self.post else ""
        return f"( {pre_txt} -- {post_txt} )"

    def check_pre(self, sp: int, *, site: str) -> None:
        expected = len(self.pre)
        if sp != expected:
            raise RuntimeError(
                f"{site}: stack pre-check {self.effect_str()}: "
                f"expected height {expected}, got {sp}"
            )

    def check_post(self, sp: int, *, site: str) -> None:
        expected = len(self.post)
        if sp != expected:
            raise RuntimeError(
                f"{site}: stack post-check {self.effect_str()}: "
                f"expected height {expected}, got {sp}"
            )


class PrePost:
    """Authoring wrapper: body plus ``( pre -- post )`` stack effect."""

    __slots__ = ("body", "stack_type", "label")

    def __init__(
        self,
        body: list[Any],
        *,
        pre: list[str] | tuple[str, ...] = (),
        post: list[str] | tuple[str, ...] = (),
        label: str = "",
    ) -> None:
        self.body = body
        self.stack_type = StackType(pre=tuple(pre), post=tuple(post))
        self.label = label

    def __repr__(self) -> str:
        suffix = f" {self.label!r}" if self.label else ""
        return f"PrePost{self.stack_type.effect_str()}{suffix}"


def stack_type_debug_enabled() -> bool:
    return _DEBUG


def set_stack_type_debug(on: bool) -> None:
    global _DEBUG
    _DEBUG = on
    _cy.set_stack_type_debug(_DEBUG)


def reset_check_state() -> None:
    _CHECK_BINDINGS.clear()
    _CHECK_OP_NAMES.clear()


def run_stack_check(op_id: int, sp: int) -> None:
    """Python callback from the VM when a debug check op runs."""
    name = _cy.op_name(op_id)
    kind, slots, label = _CHECK_BINDINGS[name]
    site = label or name
    stack_type = StackType(
        pre=slots if kind == "pre" else (),
        post=slots if kind == "post" else (),
    )
    if kind == "pre":
        stack_type.check_pre(sp, site=site)
    else:
        stack_type.check_post(sp, site=site)


def flatten_authoring(tokens: list[Any]) -> list[Any]:
    """Expand ``PrePost`` wrappers for the current debug mode."""
    out: list[Any] = []
    for token in tokens:
        if isinstance(token, PrePost):
            if stack_type_debug_enabled():
                out.extend(_emit_prepost(token))
            else:
                out.extend(flatten_authoring(token.body))
        else:
            out.append(token)
    return out


def _check_op(kind: CheckKind, slots: tuple[str, ...], label: str) -> Any:
    from imgcomp import stack_c as sc

    key = (kind, slots, label)
    name = _CHECK_OP_NAMES.get(key)
    if name is None:
        suffix = label or str(len(_CHECK_BINDINGS))
        name = f"__stack_{kind}_{suffix}"
        sc.register_op(name, _cy.py_stack_check)
        _CHECK_BINDINGS[name] = (kind, slots, label)
        _CHECK_OP_NAMES[key] = name
    return sc.get_op(name)


def _emit_prepost(prepost: PrePost) -> list[Any]:
    st = prepost.stack_type
    label = prepost.label
    out: list[Any] = []
    if st.pre:
        out.append(_check_op("pre", st.pre, label))
    out.extend(flatten_authoring(prepost.body))
    if st.post:
        out.append(_check_op("post", st.post, label))
    return out


_cy.set_stack_type_debug(_DEBUG)
