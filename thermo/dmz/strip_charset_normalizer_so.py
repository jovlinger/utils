"""Strip charset_normalizer native modules after pip install (linux/arm/v6 + musl SIGSEGV in cd.*.so).

Run only in the Docker *builder* stage after ``pip install -r requirements.txt``; the same
tree is copied into the runtime image. Do not run on the developer host venv unless you mean to.
"""

from __future__ import annotations

import pathlib

import charset_normalizer


def main() -> None:
    root = pathlib.Path(charset_normalizer.__file__).parent
    shared = list(root.rglob("*.so"))
    for path in shared:
        path.unlink()
    print("charset_normalizer: removed", len(shared), "shared objects under", root)
    from charset_normalizer import from_bytes

    from_bytes(b"abc")
    from authlib.integrations.flask_client import OAuth  # noqa: F401 — validates Flask OAuth import chain

    print("strip_charset_normalizer_so: import smoke ok")


if __name__ == "__main__":
    main()
