from setuptools import Extension, setup

from Cython.Build import cythonize

setup(
    ext_modules=cythonize(
        [
            Extension(
                "imgcomp._stack_c",
                ["imgcomp/_stack_c.pyx"],
            ),
            Extension(
                "tests._stack_bench_c",
                ["tests/_stack_bench_c.pyx"],
            ),
        ],
        compiler_directives={"language_level": "3"},
    ),
)
