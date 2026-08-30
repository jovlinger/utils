# fmt: off
"""Tests for stack_c VM."""

from __future__ import annotations

from imgcomp.stack_c import eval_op, register_base_ops, register_op


def _register_printloop_ops() -> None:
    register_base_ops()
    register_op(
        "loop_body",
        [
            "loop iter {}",
            1,
            "rot",
            "printf",
        ],
    )
    register_op(
        "prog",
        [
            3,
            9,
            2,
            "lit_op",
            "loop_body",
            "int_incr_le",
        ],
    )


def _setup_printloop() -> None:
    from imgcomp.stack_c import reset_vm

    reset_vm()
    _register_printloop_ops()


def test_printloop(capsys) -> None:
    _setup_printloop()
    eval_op("prog")
    assert capsys.readouterr().out == (
        "loop iter 3\n"
        "loop iter 5\n"
        "loop iter 7\n"
        "loop iter 9\n"
    )
