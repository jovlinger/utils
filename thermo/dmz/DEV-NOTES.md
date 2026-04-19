# DMZ dev notes

- **Tests:** `make test-local` / `./test/run.sh` (host **pytest** under `test/`); `make test-docker` (in-image pytest + **`smoketest/`** Docker + host pytest); `make test` (both). Umbrella: **`make test`** from **`thermo/`** runs **dmz** (including **smoketest**), **onboard**, **test/**. See `test/README.md` and `smoketest/README.md`.
- **Entry:** `start.sh` runs as **root** only for mounts; the app always runs as **`dmz`** via `su-exec`.
- **Pydantic:** Stay on **v1** (`pydantic<2` in `requirements.txt`) for musl / ARM wheel consistency; Dockerfile forces pydantic-core build from source when needed.


# future directions

- rewrite
  - ribbit: very minimal scheme R4RS. very compact on disk/mem 1% of cpython, cpython-ish speed
  - gambit: larger scheme, more libraries, more performance, 10% size of cpython, 15-40x speedup vs cpython
  - gforth: 3% memory of python, 5-10x speedup of python


| Feature | Gforth | Gambit (Gambit-C) | Ribbit |
|:--- |:--- |:--- |:--- |
| **Execution Type** | Indirect Threaded (Interpreter) | Native (Compiles via C) | Minimal VM (AOT Compiled) |
| **Slowdown vs. C** | ~5x | **~1.1x – 2x** | ~10x – 20x |
| **Idle RAM** | ~1 MB | ~3 – 5 MB | **< 100 KB** |
| **Binary Size** | ~1 – 2 MB | ~2 – 4 MB (Stand-alone) | **< 10 KB (Core)** |
| **ARMv6 Support** | Yes (Excellent) | Yes (via C backend) | Yes (via C or JS backends) |
| **Flask-like Library** | No (Manual socket/HTTP) | **Spock** or **Spheres** | No (Minimalist/Raw) |
| **Primary Focus** | Bare-metal efficiency | High-performance Scheme | Extreme compactness |
| **Download/Repo** | [GNU Gforth](https://gnu.org) | [Gambit Scheme](http://gambitscheme.org) | [Ribbit Repo](https://github.com) |

Gforth: You'll likely use the built-in unix/socket.fs. It's very low-level; you'll be manipulating file descriptors directly, similar to C.
Gambit: Check out Spock or the networking modules in Gerbil Scheme (which runs on Gambit) if you want a more modern web-handling feel.
Ribbit: This is so minimal that "libraries" essentially don't exist in the traditional sense. You would likely write a tiny R4RS script and compile it using the Ribbit AOT compiler targeting the C backend for your ARMv6 device.