"""Stack VM sketch (Python registers names; Cython runs).

Surface body programs use self-evaluating literals and opcode names::

    register_op("loop_body", [
        "loop iter {}",
        1,
        "rot",
        "printf",
    ])

    register_op("prog", [
        3, 9, 2,
        "lit_op", "loop_body",
        "int_incr_le",
    ])

Compile expands literals into internal PC-loaded ``lit_*`` instructions in
``WordBuf`` streams. ``lit_int`` / ``lit_float`` / ``lit_str`` are compile-
time only, not registered surface opcodes.
"""

from __future__ import annotations

from typing import Any

from imgcomp import _stack_c as _cy


def register_op(name: str, handler: _cy.OpHandler | list[Any]) -> int:
    """Register a cdef handler or a body opcode (token list)."""
    return _cy.register_op(name, handler)


def reset_vm() -> None:
    _cy.reset_vm()


def register_base_ops() -> None:
    register_op("lit_op", _cy.lit_op)
    register_op("dup", _cy.dup)
    register_op("drop", _cy.drop)
    register_op("swap", _cy.swap)
    register_op("over", _cy.over)
    register_op("rot", _cy.rot)
    register_op("i_add", _cy.i_add)
    register_op("i_sub", _cy.i_sub)
    register_op("i_eq", _cy.i_eq)
    register_op("i_add_at", _cy.i_add_at)
    register_op("i_to_f", _cy.i_to_f)
    register_op("f_add", _cy.f_add)
    register_op("f_sub", _cy.f_sub)
    register_op("f_mul", _cy.f_mul)
    register_op("f_gt", _cy.f_gt)
    register_op("f_add_at", _cy.f_add_at)
    register_op("if_nzero_run", _cy.if_nzero_run)
    register_op("call_op", _cy.call_op)
    register_op("printf", _cy.printf)
    register_op("int_incr_le", _cy.int_incr_le)
    register_op("float_incr_le", _cy.float_incr_le)


def eval_op(name: str) -> None:
    _cy.run_op(name)
