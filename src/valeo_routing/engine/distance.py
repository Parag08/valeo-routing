"""Travel distance and time between two points.

`DistanceModel` is the port; `StraightLineRoad` is the adapter used until a road router is wired in:
straight-line distance times a road factor, at an average speed that drops in the peak windows.
"""
from __future__ import annotations

import math
from typing import List, Protocol, Tuple

from valeo_routing.datagen.geo import haversine_m
from valeo_routing.settings import EngineSettings

from .model import Loc


class DistanceModel(Protocol):
    def km(self, a: Loc, b: Loc) -> float: ...

    def minutes(self, a: Loc, b: Loc, depart_min: int) -> int: ...


class StraightLineRoad:
    def __init__(self, road_factor: float, speed_off_peak: float, speed_peak: float,
                 peak_windows: List[Tuple[int, int]]):
        self.road_factor = road_factor
        self.speed_off_peak = speed_off_peak
        self.speed_peak = speed_peak
        self.peak_windows = peak_windows

    @classmethod
    def from_settings(cls, s: EngineSettings) -> "StraightLineRoad":
        return cls(s.road_factor, s.speed_kmh_off_peak, s.speed_kmh_peak, s.peak_window_minutes)

    def km(self, a: Loc, b: Loc) -> float:
        if a == b:
            return 0.0
        return haversine_m(a[0], a[1], b[0], b[1]) / 1000.0 * self.road_factor

    def speed_kmh(self, depart_min: int) -> float:
        in_peak = any(start <= depart_min % (24 * 60) < end for start, end in self.peak_windows)
        return self.speed_peak if in_peak else self.speed_off_peak

    def minutes(self, a: Loc, b: Loc, depart_min: int) -> int:
        """Whole minutes, rounded up, using the speed in force when the drive starts."""
        if a == b:
            return 0
        return int(math.ceil(self.km(a, b) / self.speed_kmh(depart_min) * 60.0 - 1e-9))
