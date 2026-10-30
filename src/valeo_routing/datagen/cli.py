"""`valeo-gen`: generate the synthetic day-zero data and print a short summary."""
from __future__ import annotations

from collections import Counter

from ..settings import load_settings
from .generate import generate, write
from .schema import VERTICALS


def main() -> None:
    settings = load_settings()
    data = generate(settings)
    written = write(data, settings.data_output_dir)

    print("Synthetic data (seed {}) -> {}".format(settings.data_seed, settings.data_output_dir))
    for name, n in written.items():
        print("  {:<18} {:>5} rows".format(name, n))

    per_day = Counter((a.service_date, a.vertical) for a in data.appointments)
    days = sorted({d for d, _ in per_day})
    print("\n  {:<14}".format("date") + "".join("{:>13}".format(v) for v in VERTICALS))
    for d in days:
        print("  {:<14}".format(d.strftime("%a %Y-%m-%d")) + "".join(
            "{:>13}".format(per_day[(d, v)]) for v in VERTICALS
        ))
    statuses = Counter(a.status for a in data.appointments)
    fast = sum(1 for a in data.appointments if a.priority == "fast_track")
    print("\n  status: " + ", ".join("{} {}".format(k, statuses[k]) for k in sorted(statuses)))
    print("  fast-tracks: {}".format(fast))
    print("  declined (no staff free): " + ", ".join("{} {}".format(v, data.declined[v]) for v in VERTICALS))


if __name__ == "__main__":
    main()
