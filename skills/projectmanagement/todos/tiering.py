"""Test tier classification for the todos suite, shared by conftest and its guard.

Every test lands in exactly one tier, decided by the harness it uses rather than
by what it means to cover:

``e2e``
    Drives ``todo.py`` as a subprocess against a store and git repo built from
    scratch for that one test, i.e. the class subclasses ``test_todo.TodoCase``.
    Happy paths and complex multi-command behaviour; each feature wants at least
    one positive and one negative case here.
``integration``
    A real store or filesystem, but not the whole CLI from scratch. Declared
    with ``pytestmark = pytest.mark.integration``. Multiple arguments and edge
    cases live here.
``unit``
    No store and no filesystem: argument parsing, error handling, pure
    transforms. The default, so a new test is unit until its harness says
    otherwise.

``e2e`` is derived and cannot be overridden, so a test cannot claim a cheaper
tier than the harness it actually runs on. ``integration`` is declared, because
"opens a real store" is not visible from the base class.
"""

from __future__ import annotations

TIERS: tuple[str, ...] = ("e2e", "integration", "unit")
DEFAULT_TIER = "unit"

# Names that mean a test reaches a real store, a real database, or the
# filesystem. A class whose body mentions one of these cannot be `unit`.
HEAVY_NAMES: tuple[str, ...] = (
    "subprocess",
    "tempfile",
    "mkdtemp",
    "TemporaryDirectory",
    "NamedTemporary",
    "sqlite3",
)


def e2e_base() -> type:
    """The base class that means "fresh CLI plus fresh store, per test"."""
    from test_todo import TodoCase

    return TodoCase


def is_e2e(cls: type | None) -> bool:
    """True when *cls* inherits the fresh-CLI-plus-fresh-store harness."""
    return cls is not None and issubclass(cls, e2e_base())


def tier_for(cls: type | None, declared: set[str]) -> str:
    """Resolve the tier of a test class from its base and its own markers.

    Raises ``ValueError`` when a class on the e2e harness declares a cheaper
    tier, or when it declares more than one.
    """
    declared = declared & set(TIERS)
    if len(declared) > 1:
        raise ValueError(f"{cls!r} declares more than one tier: {sorted(declared)}")
    if is_e2e(cls):
        if declared - {"e2e"}:
            raise ValueError(
                f"{cls!r} runs on the e2e harness but declares {sorted(declared)}"
            )
        return "e2e"
    return declared.pop() if declared else DEFAULT_TIER
