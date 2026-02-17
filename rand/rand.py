#! /usr/bin/python

import sys, random, argparse


class Inputs:
    "Inputs opens a number of files (or stdin, if no files provided), and reads lines from the round-robin"

    def __init__(self, inputFiles):
        self.n = 0
        if not inputFiles:
            self.files = [sys.stdin]
            return
        self.files = [open(inputFile, "r") for inputFile in inputFiles]

    def line(self):
        "returns None if all inputs are exhausted, else read round-robin from input files"
        while self.files:
            self.n = (self.n + 1) % len(self.files)
            line = self.files[
                self.n
            ].readline()  # '' is EOF, '/n' terminates all read lines
            if line:
                return line
            del self.files[self.n]
        return None


class RandBuffer:
    "RandBuffer stores a number if items, providing them in random order"

    def __init__(self, cap):
        if cap < 0:
            raise ValueError("Requirement failed: cap non-negative")
        self.buf = []
        self.cap = cap

    def empty(self):
        return len(self.buf) == 0

    def full(self):
        return len(self.buf) >= self.cap

    def add(self, item):
        if self.full():
            raise IndexError("RandBuffer Full")
        self.buf.append(item)

    def some(self):
        "Removes and returns a randomly chosen item."
        if self.empty():
            raise IndexError("RandBuffer Empty")
        i = random.randrange(len(self.buf))
        item = self.buf[i]
        self.buf[i] = self.buf[-1]
        del self.buf[-1]
        return item


def randomize(inputs, outfile, cap):
    buf = RandBuffer(cap)
    n = 0
    while True:
        line = inputs.line()
        if line:
            n += 1
            if not buf.full():
                buf.add(line)
                continue
            if random.random() <= (1.0 / n) or buf.cap == 0:
                outfile.write(line)
                continue
        if buf.empty():
            break
        if not buf.empty():
            outfile.write(buf.some())
        if line:
            buf.add(line)


if __name__ == "__main__":
    ap = argparse.ArgumentParser("Randomize lines from files, or stdin.")
    ap.add_argument(
        "-b",
        "--buffer",
        help="buffer capacity, defaults to 1000",
        type=int,
        default=1000,
    )
    ap.add_argument(
        "files", help="file to randomize lines from", metavar="FILE", nargs="*"
    )
    args = ap.parse_args()

    randomize(Inputs(args.files), sys.stdout, args.buffer)
