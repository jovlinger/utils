"""Build optional Cython extensions: leaf math and specialized paint kernel."""

from __future__ import annotations

from setuptools import Extension, setup

try:
    from Cython.Build import cythonize
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Cython is required to build imgcomp extensions") from exc

extensions = [
    Extension("imgcomp._math", ["imgcomp/_math.pyx"]),
    Extension("imgcomp._paint", ["imgcomp/_paint.pyx"]),
]

setup(
    name="imgcomp",
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
)
