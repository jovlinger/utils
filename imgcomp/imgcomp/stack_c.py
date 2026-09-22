"""Stack VM sketch (Python registers names; Cython runs).

Surface body programs use Python values: literals and registered ``OpHandler``
tokens (``op_id`` written at ``register_op``)::

    loop_body = register_op("loop_body", [
        "loop iter {}",
        1,
        rot,
        printf,
    ])

    register_op("prog", [
        3, 9, 2,
        lit_op, loop_body,
        int_incr_le,
    ])

Compile expands literals into internal PC-loaded ``lit_*`` instructions.
"""

from __future__ import annotations

from typing import Any

from imgcomp import _stack_c as _cy

OpHandler = _cy.OpHandler

# Populated by register_base_ops().
lit_op: OpHandler
dup: OpHandler
drop: OpHandler
swap: OpHandler
over: OpHandler
rot: OpHandler
i_add: OpHandler
i_sub: OpHandler
i_eq: OpHandler
i_gt: OpHandler
i_add_at: OpHandler
i_to_f: OpHandler
f_add: OpHandler
f_sub: OpHandler
f_mul: OpHandler
f_gt: OpHandler
f_add_at: OpHandler
if_nzero_run: OpHandler
call_op: OpHandler
printf: OpHandler
int_incr_le: OpHandler
float_incr_le: OpHandler
while_loop: OpHandler


def register_op(name: str, handler: OpHandler | list[Any]) -> OpHandler:
    """Register a cdef handler or a body opcode (token list)."""
    return _cy.register_op(name, handler)


def reset_vm() -> None:
    _cy.reset_vm()


def register_base_ops() -> None:
    global lit_op, dup, drop, swap, over, rot
    global i_add, i_sub, i_eq, i_gt, i_add_at, i_to_f
    global f_add, f_sub, f_mul, f_gt, f_add_at
    global if_nzero_run, call_op, printf, int_incr_le, float_incr_le, while_loop
    lit_op = register_op("lit_op", _cy.lit_op)
    dup = register_op("dup", _cy.dup)
    drop = register_op("drop", _cy.drop)
    swap = register_op("swap", _cy.swap)
    over = register_op("over", _cy.over)
    rot = register_op("rot", _cy.rot)
    i_add = register_op("i_add", _cy.i_add)
    i_sub = register_op("i_sub", _cy.i_sub)
    i_eq = register_op("i_eq", _cy.i_eq)
    i_gt = register_op("i_gt", _cy.i_gt)
    i_add_at = register_op("i_add_at", _cy.i_add_at)
    i_to_f = register_op("i_to_f", _cy.i_to_f)
    f_add = register_op("f_add", _cy.f_add)
    f_sub = register_op("f_sub", _cy.f_sub)
    f_mul = register_op("f_mul", _cy.f_mul)
    f_gt = register_op("f_gt", _cy.f_gt)
    f_add_at = register_op("f_add_at", _cy.f_add_at)
    if_nzero_run = register_op("if_nzero_run", _cy.if_nzero_run)
    call_op = register_op("call_op", _cy.call_op)
    printf = register_op("printf", _cy.printf)
    int_incr_le = register_op("int_incr_le", _cy.int_incr_le)
    float_incr_le = register_op("float_incr_le", _cy.float_incr_le)
    while_loop = register_op("while", _cy.while_loop)


def eval_op(name: str) -> None:
    _cy.run_op(name)
