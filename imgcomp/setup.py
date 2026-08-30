from setuptools import Extension, setup

from Cython.Build import cythonize

CYTHON_COMPILER_DIRECTIVES = {
    "language_level": "3",
    "boundscheck": False,
    "wraparound": False,
    "initializedcheck": False,
    "nonecheck": False,
    "cdivision": True,
    "embedsignature": False,
}

C_COMPILE_ARGS = ["-O3"]

setup(
    ext_modules=cythonize(
        [
            Extension(
                "imgcomp._math",
                ["imgcomp/_math.pyx", "imgcomp/affine_simd.c"],
                include_dirs=["imgcomp"],
                extra_compile_args=C_COMPILE_ARGS,
            ),
            Extension(
                "imgcomp._stack_c",
                ["imgcomp/_stack_c.pyx"],
                extra_compile_args=C_COMPILE_ARGS,
            ),
            Extension(
                "tests._stack_bench_c",
                ["tests/_stack_bench_c.pyx"],
                extra_compile_args=C_COMPILE_ARGS,
            ),
            Extension(
                "tests._math_bench_c",
                ["tests/_math_bench_c.pyx", "imgcomp/affine_simd.c"],
                include_dirs=["imgcomp"],
                extra_compile_args=C_COMPILE_ARGS,
            ),
        ],
        compiler_directives=CYTHON_COMPILER_DIRECTIVES,
    ),
)
