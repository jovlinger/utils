"""Guard the tier classification in `tiering`: no test may under-declare its harness."""

from __future__ import annotations

import importlib
import inspect
import unittest
from pathlib import Path

import tiering

HERE = Path(__file__).resolve().parent
SELF = Path(__file__).name


def _test_classes():
    """Yield (module name, class) for every TestCase defined in a test module."""
    for path in sorted(HERE.glob("test_*.py")):
        if path.name == SELF:
            continue
        module = importlib.import_module(path.stem)
        for _, obj in vars(module).items():
            if not (inspect.isclass(obj) and issubclass(obj, unittest.TestCase)):
                continue
            if obj.__module__ != path.stem:
                continue
            if not any(name.startswith("test") for name in dir(obj)):
                continue
            yield path.name, obj


def _declared(cls: type) -> set[str]:
    mark = getattr(cls, "pytestmark", None)
    if mark is None:
        return set()
    marks = mark if isinstance(mark, list) else [mark]
    return {m.name for m in marks}


class TierClassificationTest(unittest.TestCase):
    """Every test class resolves to one tier, and `unit` really means no I/O."""

    def test_every_test_class_resolves_to_a_known_tier(self) -> None:
        seen = 0
        for where, cls in _test_classes():
            with self.subTest(cls=f"{where}::{cls.__name__}"):
                tier = tiering.tier_for(cls, _declared(cls))
                self.assertIn(tier, tiering.TIERS)
                seen += 1
        self.assertGreater(seen, 50, "test discovery found almost nothing")

    def test_unit_classes_touch_no_store_or_filesystem(self) -> None:
        """A class naming subprocess/tempfile/sqlite3 must declare a heavier tier.

        This is what stops the `unit` default from quietly absorbing a test that
        builds a store, which would put slow I/O back into the fast suite.
        """
        for where, cls in _test_classes():
            tier = tiering.tier_for(cls, _declared(cls))
            if tier != "unit":
                continue
            try:
                src = inspect.getsource(cls)
            except OSError:  # pragma: no cover - source always available here
                continue
            found = sorted(n for n in tiering.HEAVY_NAMES if n in src)
            with self.subTest(cls=f"{where}::{cls.__name__}"):
                self.assertEqual(
                    [], found,
                    f"{cls.__name__} is unit but names {found}; mark it integration",
                )

    def test_e2e_harness_cannot_declare_a_cheaper_tier(self) -> None:
        base = tiering.e2e_base()
        with self.assertRaises(ValueError):
            tiering.tier_for(base, {"unit"})
        with self.assertRaises(ValueError):
            tiering.tier_for(base, {"integration"})

    def test_two_declared_tiers_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            tiering.tier_for(None, {"unit", "integration"})


if __name__ == "__main__":
    unittest.main()
