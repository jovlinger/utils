#!/usr/bin/env python3
"""

this is a generic mock command. The idea is you arrange make a
directory of mock commands, full of syminks (like "docker") symlinked
to this executable.  Then arrange for this directory to be first in your path.

Now this executable is ready to parrot back responses and exit codes that match the invocations.
Because this is a toy implementation, we don't have support for wildcard matches or 
file-contained responses or invoking helpers.  (but all that could be wired in). 

"""


import sys
import os
import json
import argparse


MOCK_FILE = os.environ.get("MOCK_FILE", "/tmp/mock_config.json")


def dbg(msg):  # pylint: disable=unused-argument
    # print(msg)
    pass


def load_mocks():
    if os.path.exists(MOCK_FILE):
        with open(MOCK_FILE, "r") as f:
            return json.load(f)
    return {}


def save_mocks(mocks):
    with open(MOCK_FILE, "w") as f:
        json.dump(mocks, f)


def reset_mocks():
    save_mocks({})


def set_mock(cmd, args, exit_code, stdout, stderr):
    mocks = load_mocks()
    key = f"{cmd} {' '.join(args)}"
    mocks[key] = {"exit_code": exit_code, "stdout": stdout, "stderr": stderr}
    save_mocks(mocks)
    dbg(f"Mock set for: {cmd} {' '.join(args)}")


def get_mock(cmd, args):
    mocks = load_mocks()
    key = f"{cmd} {' '.join(args)}"
    return mocks.get(key)


def main():
    if len(sys.argv) < 2:
        dbg("Usage: mock_cmd.py [--reset|--mock_exit N --mock_stdout TEXT --mock_stderr TEXT --mock_match CMD ARGS...]")
        sys.exit(1)

    if sys.argv[1] == "--reset":
        reset_mocks()
        dbg("Mock configuration reset")
        return

    if sys.argv[1] == "--mock_exit":
        parser = argparse.ArgumentParser()
        parser.add_argument("--mock_exit", type=int, required=True)
        parser.add_argument("--mock_stdout", default="")
        parser.add_argument("--mock_stderr", default="")
        parser.add_argument("--mock_match", nargs="+", required=True)

        args = parser.parse_args()
        cmd = args.mock_match[0]
        cmd_args = args.mock_match[1:]

        set_mock(cmd, cmd_args, args.mock_exit, args.mock_stdout, args.mock_stderr)
        return

    # Called as symlink - look up mock
    cmd_name = os.path.basename(sys.argv[0])
    args = sys.argv[1:]

    mock = get_mock(cmd_name, args)
    if mock:
        print(mock["stdout"])
        print(mock["stderr"], file=sys.stderr)
        sys.exit(mock["exit_code"])
    else:
        print(f"ERROR: No mock configured for: {cmd_name} {' '.join(args)}", file=sys.stderr)
        print(f"Available mocks:", file=sys.stderr)
        mocks = load_mocks()
        for key in mocks.keys():
            print(f"  {key}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
