"""`valeo-gen`: generate the synthetic field-visit data and print a summary of the month."""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean

from ..settings import load_settings
from .generate import Dataset, generate, write
from .schema import WEEKDAYS


def _share(counter: Counter, total: int) -> str:
    return ", ".join("{} {:.0%}".format(k, v / total) for k, v in counter.most_common())


def summarise(data: Dataset) -> str:
    ref = data.reference
    service = {s.service_id: s for s in ref.services}
    area = {a.area_id: a for a in ref.areas}
    role = {s.staff_id: s.role for s in data.staff}
    n = len(data.orders)
    lines = []

    per_day = Counter(o.slot_start.date() for o in data.orders)
    avail = defaultdict(Counter)
    for a in data.availability:
        if a.status == "available":
            avail[a.date][role[a.staff_id]] += 1
    days = sorted(per_day)
    pairs = [min(avail[d]["nurse"], avail[d]["driver"]) for d in days]
    lines.append("Orders by service day (pairs = min of nurses and drivers available):")
    for d in days:
        lines.append("  {} {}  orders {:>3}  nurses {:>2}  drivers {:>2}  pairs {:>2}".format(
            WEEKDAYS[d.weekday()], d, per_day[d], avail[d]["nurse"], avail[d]["driver"],
            min(avail[d]["nurse"], avail[d]["driver"])))
    counts = [per_day[d] for d in days]
    lines.append("  orders/day: mean {:.1f}, min {}, max {};  pairs on duty: mean {:.1f}, min {}, max {}".format(
        mean(counts), min(counts), max(counts), mean(pairs), min(pairs), max(pairs)))

    lines.append("\nMix:")
    lines.append("  category: " + _share(Counter(service[o.service_id].category for o in data.orders), n))
    lines.append("  emirate:  " + _share(Counter(area[o.area_id].emirate for o in data.orders), n))
    lines.append("  slot hour: " + " ".join(
        "{:02d}h:{}".format(h, c) for h, c in sorted(Counter(o.slot_start.hour for o in data.orders).items())))

    lead_h = [(o.slot_start - o.published_at).total_seconds() / 3600 for o in data.orders]
    night = sum(1 for o in data.orders if o.published_at.hour >= 21 or o.published_at.hour < 6)
    lines.append("\nTiming:")
    lines.append("  lead time (h): min {:.1f}, median {:.1f}, max {:.1f};  inside 12 h: {:.0%};  published 21:00-06:00: {:.0%}".format(
        min(lead_h), sorted(lead_h)[n // 2], max(lead_h), sum(1 for h in lead_h if h < 12) / n, night / n))
    claims = [o.competitor_claim_min for o in data.orders]
    lines.append("  competitor claim after (min): min {}, median {}, max {}".format(
        min(claims), sorted(claims)[n // 2], max(claims)))
    cancelled = sum(1 for o in data.orders if o.cancelled_at)
    lines.append("  cancelled: {:.1%}".format(cancelled / n))
    lines.append("  samples with a lab: {};  IV/vaccine orders with supplies ready: {:.0%}".format(
        sum(1 for o in data.orders if o.lab_id),
        sum(1 for o in data.orders if service[o.service_id].needs_office_supplies and o.supplies_ready)
        / max(1, sum(1 for o in data.orders if service[o.service_id].needs_office_supplies))))
    repeat = n - len({o.patient_ref for o in data.orders})
    lines.append("  patients: {} (repeat orders {:.0%})".format(len({o.patient_ref for o in data.orders}), repeat / n))

    status = Counter(a.status for a in data.availability)
    lines.append("\nStaff-days: " + ", ".join("{} {}".format(k, status[k]) for k in sorted(status)))
    lines.append("Events: " + ", ".join("{} {}".format(k, v) for k, v in sorted(Counter(e.type for e in data.events).items())))
    return "\n".join(lines)


def main() -> None:
    settings = load_settings()
    data = generate(settings)
    written = write(data, settings.data_output_dir)

    print("Synthetic data (seed {}) -> {}".format(settings.data_seed, settings.data_output_dir))
    for name, n in written.items():
        print("  {:<18} {:>5} rows".format(name, n))
    print()
    print(summarise(data))


if __name__ == "__main__":
    main()
