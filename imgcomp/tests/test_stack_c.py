# fmt: off
"""Tests for stack_c VM."""

from __future__ import annotations

from imgcomp import stack_c as sc


def _register_printloop_ops() -> None:
    sc.register_base_ops()
    loop_body = sc.register_op(
        "loop_body",
        [
            "loop iter {}",
            1,
            sc.rot,
            sc.printf,
        ],
    )
    sc.register_op(
        "prog",
        [
            3,
            9,
            2,
            sc.lit_op,
            loop_body,
            sc.int_incr_le,
        ],
    )


def _setup_printloop() -> None:
    sc.reset_vm()
    _register_printloop_ops()


def test_printloop(capsys) -> None:
    _setup_printloop()
    sc.eval_op("prog")
    assert capsys.readouterr().out == (
        "loop iter 3\n"
        "loop iter 5\n"
        "loop iter 7\n"
        "loop iter 9\n"
    )


def _register_while_countdown_ops() -> None:
    sc.register_base_ops()
    whilefn = sc.register_op("whilefn", [sc.dup, 0, sc.i_gt])
    step = sc.register_op("step", [1, sc.i_sub])
    sc.register_op("countdown", [3, whilefn, step, sc.while_loop])


def test_while_loop() -> None:
    sc.reset_vm()
    _register_while_countdown_ops()
    sc.eval_op("countdown")
    from imgcomp import _stack_c as _cy

    assert _cy.pop_int() == 0
