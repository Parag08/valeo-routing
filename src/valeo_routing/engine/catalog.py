"""Service durations: what the plan allows for a visit, and what a visit actually takes."""
from __future__ import annotations

import math
import random

from valeo_routing.datagen.reference import Service


class Catalog:
    def __init__(self, plan_duration_position: float):
        self.position = plan_duration_position

    def planned_minutes(self, service: Service) -> int:
        """On-site minutes the plan reserves: the service's minimum plus a fraction of its range, rounded up."""
        span = service.duration_min_hi - service.duration_min_lo
        return int(math.ceil(service.duration_min_lo + self.position * span - 1e-9))

    @staticmethod
    def actual_minutes(rng: random.Random, service: Service) -> int:
        """What a visit really takes, drawn uniformly from the service's range (used by the replay)."""
        return rng.randint(service.duration_min_lo, service.duration_min_hi)
