from pydantic import BaseModel

from datetime import datetime
from typing import Iterator, List, Optional

"""
Run the doctests: (skip the -v maybe)
> python -m doctest -v models.py
"""


"""
def enum_pairwise(it: Iterator, sentinel=None) -> Iterator[tuple]:
    """Iterate over `it` == `[a,b,c,d..z]` as  `(a, b)`, `(b,c)` .. `(z,sentinel)` """
    emit = False
    prev = None
    for x in it:
        if emit:
            yield(prev, x)
        emit = True
        prev = x
"""


class Entry(BaseModel):
    # All fields are required. We might allow empty min/max in representation, but we will fill in on reading. 
    key: str         # c.f. config_file_name.key_namev
    min_t: datetime  # valid from
    max_t: datetime  # valid to
    ins_t: datetime  # created on 
    val: str       # c.f. mail.example.com         

    def __less__(self, other) -> bool:
        if not isinstance(other, Entry):
            return False
        if self.ins_t == other.ins_t:
            return self.min_t < other.min_t
        return self.ins_t < other.ins_t

    def active(self, d: datetime) -> bool:
        """Is this record active at time `d`?"""
        if d < self.min_t:
            # not active yet. Note the `<` here. Active is inclusive start time
            return False
        if self.max_t <= d:
            # expired. Note the `<=` here. Active is exclusive end time. 
            return False
        return True

    def pick(self, other: "Entry", d: datetime) -> Optional["Entry"]:
        """Which is more applicable? Same `key` assumed. Only active @ d will be considered.
 
        >>> a = datetime(2023,10,1)
        >>> b = datetime(2023,10,2)
        >>> c = datetime(2023,10,3)
        >>> d = datetime(2023,10,4)
        >>> e = datetime(2023,10,5)
        >>> e1 = Entry(key="k", min_t=b, max_t=d, ins_t=a, val="e1")
        >>> e2 = Entry(key="k", min_t=b, max_t=e, ins_t=b, val="e2")
        >>> e1.pick(e2, c) == e1
        True
        >>> e2.pick(e1, c) == e1
        True
        >>> e1.pick(e1, c) == e1
        True
        >>> e1.pick(e2, a) is None
        True
        >>> e1.pick(e2, d) == e2
        True
        >>> e1.pick(e2, e) is None
        True
        """
        if self.active(d) and not other.active(d):
            return self
        if not self.active(d) and other.active(d):
            return other
        if not self.active(d) and not other.active(d):
            return None


        # 1. earliest insertion
        if self.ins_t < other.ins_t:
            return self
        if other.ins_t < self.ins_t:
            return other
        # 2. else the active closest to `d`
        s_t = d - self.min_t
        o_t = d - other.min_t
        if s_t <= o_t:
            return self
        return other

class Entries:
    entries: List[Entry] # sorted
    key: str

    def __init__(self, entries: List[Entry]):
        self.entries = sorted(entries)
        if len(entries) == 0:
            self.key = None
            return
        keys = { e.key for e in entries }
        assert len(keys) == 1
        self.key = keys.pop()

        
    def active_entry(d: datetime) -> Optional[Entry]:
        """Which entry in `self` is active at time `d`?
        ASSUMES: `entries` is sorted, have same `key`
        """
        found = None
        for entry in entries:
            if not entry.active(d):
                if found: break         # we are past our search area.
                else: continue          # not yet at search area.
            if not found:               # first match found
                found = entry
                continue
            # the interesting case. We have two contenders. which is better? 
            found = found.pick(entry, d)
        return found
    
    
    @staticmethod
    def simplify(entries: Iterator["Entry"]) -> List[Entry]:
        es = sorted(entries)
        ds_set = { e.min_t for e in es } | { e.max_t for e in es } | { e.ins_t for e in es }
        ds = sorted(ds_set)

        res = []
        cur = None

        # the approach is very simplistic. Go through all the start/end times, and see what value is current then. Create a simple, non-overlapping, val@min...max list. 
        for d in ds:
            if cur is not None:
                # trim cur to end at d
                cur.max_t = d
            act = Entry._get_active_at_time(d, es)
            if not act:
                # uncommon case. No value defined for this time.
                cur = None
                continue
            # there is a value at time `d`. common case
            if cur is None or act.val != cur.val:
                # if value has changed, insert it as the new `cur` value
                cur = act.copy()
                cur.min_t = d
                res.append(cur)
        return res
            

       
