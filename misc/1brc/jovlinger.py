"""
The task is to write a Java program which reads the file, calculates the min, mean, and max temperature value per weather station, and emits the results on stdout like this (i.e. sorted alphabetically by station name, and the result values per station in the format <min>/<mean>/<max>, rounded to one fractional digit):

{Abha=-23.0/18.0/59.2, Abidjan=-16.2/26.0/67.3, Abe'che'=-10.0/29.4/69.0, Accra=-10.1/26.4/66.4, Addis Ababa=-23.7/16.0/67.0, Adelaide=-27.8/17.3/58.5, ...}
"""

import sys
from collections import defaultdict
import multiprocessing as mp 
from operator import add
from os import SEEK_END
from time import time

class SerialPool:
    """Just serial Pool, like multiprocessing.Pool but simpler, also many fewer methods"""
    def imap(self, func, it, chunksize="ignored"):
        for x in it:
            yield(func(x))


def merge_dict(acc: dict, new: dict, fn:"callable"):
    for k, v in new.items():
        if k in acc:
            acc[k] = fn(acc[k], v)
        else:
            acc[k] = v

class State:
    def __init__(self):
        self.mins = defaultdict(lambda : float('inf'))
        self.maxs = defaultdict(lambda : float('-inf'))
        self.tots = defaultdict(lambda : 0.0)
        self.cnts = defaultdict(lambda : 0)

    def out(self, n=-1):
        if n == 0:
            # don't waste time on output for optimizing
            return
        names = sorted(self.cnts.keys())
        for name in names[:n]:
            avg = self.tots[name] / self.cnts[name]
            print(f"{name}={self.mins[name]:.1f}/{avg:.1f}/{self.maxs[name]:.1f}")

    def proc(self, name, temp):
        self.cnts[name] += 1
        self.tots[name] += temp
        self.mins[name] = min(self.mins[name], temp)
        self.maxs[name] = max(self.maxs[name], temp)

    def freeze(self):
        """Default dicts are awkward to pickle, due to the default function. """
        for d in [self.mins, self.maxs, self.tots, self.cnts]:
            if isinstance(d, defaultdict):
                d.default_factory = None

    def merge(self, st):
        merge_dict(self.cnts, st.cnts, add)
        merge_dict(self.tots, st.tots, add)
        merge_dict(self.mins, st.mins, min)
        merge_dict(self.maxs, st.maxs, max)


def file_size(f) -> int:
    x = f.tell()
    ret = f.seek(0, SEEK_END)
    f.seek(x)
    return ret

def seek_next_line(f) -> int:
    """
    find the next line in. Return offset of char following next '\n', or EOF 
    Leave f seeked to that pos. 
    """
    x = f.readline()
    return f.tell()

def gen_chunks(filename: str, chunks: int) -> "Generator[tuple[int,int]]":
    """ 
    yield [lo, hi) positions for each chunk. 
    both lo and hi will point to the beginning of a field
    """
    f = open(filename, 'rb')
    sz = file_size(f)
    chunk_sz = sz // chunks
    print(f"file size: {sz}, chunks {chunks}")
    x = 0
    f.seek(x)
    while x < sz:
        y = x+chunk_sz
        if y >= sz:
            yield (x, sz)
            return
        f.seek(y)
        y = seek_next_line(f)
        yield (x, y)
        x = y

def dochunk(tup) -> State:
    filename, lo, hi = tup 
    f = open(filename)
    f.seek(lo)
    st = State()
    while lo < hi:
        line = f.readline()
        name, tempstr = line.split(';')
        lo += len(line.encode('utf-8'))
        temp = float(tempstr)
        st.proc(name, temp)
    print(f"end lo: {lo} {f.tell()}")
    st.freeze()
    return st


def main(filename, chunk_count):
    print(f"Reading from {filename}. chunks: {chunk_count}")
    start = time()
    # pool = SerialPool()
    pool = mp.Pool()
    acc = State()
    tups = ( (filename, lo, hi) for lo, hi in gen_chunks(filename, chunk_count))
    for i, st in enumerate(pool.imap(dochunk, tups)):
        print(f"RES {i} / {chunk_count} in {time() - start}")
        acc.merge(st)
        
    acc.out(10)

"""
on 1 billion rows split 1000 wants. Try per CPU instead:
Abha=-37.2/18.0/69.9
Abidjan=-24.9/26.0/77.2
Abéché=-18.8/29.4/81.0
Accra=-23.8/26.4/79.8
Addis Ababa=-33.6/16.0/65.1
Adelaide=-31.2/17.3/65.5
Aden=-27.6/29.1/79.9
Ahvaz=-24.1/25.4/80.6
Albuquerque=-34.4/14.0/60.9
Alexandra=-38.9/11.0/61.1

RES 999 / 1000 in 194.36387419700623
( python3 jovlinger.py; )  1258.74s user 37.60s system 666% cpu 3:14.46 total


using 8 cpus (reported by mp.cpu_count()) yields 
RES 7 / 8 in 184.41525411605835  <- BEST
( python3 jovlinger.py; )  1148.30s user 32.67s system 640% cpu 3:04.48 total
"""
    
if __name__ == "__main__":
    from sys import argv
    filename = "measurements.txt"    
    chunk_count = mp.cpu_count() 
    if len(argv) > 1:
        filename = argv[1]
    if len(argv) > 2:
        chunk_count = int(argv[2])
    main(filename, chunk_count)

