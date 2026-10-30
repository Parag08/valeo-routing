"""What has already happened, and must not change when the plan is revised later in the day.

At time `now` a pair's day is split in two: blocks that started before `now` are committed; the rest can
be re-planned (a pair leaving exactly at `now` is still free to). A pair waiting somewhere (standby) may leave earlier than planned, so a wait that is still
under way counts as committed only up to its start, place and reason. A pair that has finished its
visits sits idle at the office until the end of its shift, so that idle stretch is part of the plan too.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

from .model import STANDBY, Block, Loc, Pair


def with_idle_tail(pair: Pair, blocks: Sequence[Block], office: Loc) -> List[Block]:
    """The pair's blocks plus the idle wait at the office that follows its last block."""
    tail_start = blocks[-1].end if blocks else pair.shift_start_min
    tail = Block(STANDBY, tail_start, max(tail_start, pair.shift_end_min), office, note="office")
    return list(blocks) + [tail]


def _committed_key(b: Block, now: int) -> Tuple:
    if b.kind == STANDBY and b.start < now <= b.end:
        return (b.kind, b.start, b.loc, b.note)  # still waiting: free to leave early
    return (b,)


def prefix_matches(old: Sequence[Block], new: Sequence[Block], now: int) -> bool:
    """True if `new` keeps everything in `old` that started before `now`, and adds nothing that did."""
    return [_committed_key(b, now) for b in old if b.start < now] == \
        [_committed_key(b, now) for b in new if b.start < now]
