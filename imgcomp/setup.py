"""Build the optional Cython leaf-math extension."""

from __future__ import annotations

from setuptools import Extension, setup

try:
    from Cython.Build import cythonize
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Cython is required to build imgcomp._math") from exc

setup(
    name="imgcomp",
    ext_modules=cythonize(
        [
            Extension(
                "imgcomp._math",
                ["imgcomp/_math.pyx"],
            )
        ],
        compiler_directives={"language_level": "3"},
    ),
)
