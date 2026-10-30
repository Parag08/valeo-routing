# Logistics Valeo, rebuilt

A public rebuild of the dispatch tool Parag designed and shipped for **Valeo Health**'s field-visit
operation (UAE, summer 2026). Nurse–driver pairs drive to patients' homes for sample collection, IV
and injections. Orders arrive from a partner booking platform and have to be claimed, scheduled
around lab deadlines, and served from where the pairs wait between visits.

The tool has seven tabs:

1. **Day view**: one timeline row per pair, 06:00–22:00
2. **Roster**: auto-allocated around the demand peaks
3. **Services**: on-site duration per appointment type
4. **Acceptance engine**: auto-claims what the fleet can serve, with a decision log
5. **Metrics**: predicted against actual km
6. **Hub siting**: where pairs should wait between visits
7. **Capacity**: how many pairs the demand needs

**Real results, from the original tool:**

- Live on 1 August 2026; ops were fully on it within a week.
- Order capture rose from 60–70% to 80–90%.
- Distance per field visit fell 25% (60 → 45 km) in the first month, about 23,000 km and AED 12,400
  a month.

See [docs/CONTEXT.md](docs/CONTEXT.md) for the measurement and its caveats.

**This repo is synthetic.** It is not Valeo's code or data. Every number the app produces comes from
seeded synthetic data and is labelled as such.

Status: **data generator reworked** (PLAN step 1 done): a month of synthetic field-visit orders,
staff, availability and events across Dubai and the northern emirates. The engine and the app are next.

- [docs/CONTEXT.md](docs/CONTEXT.md): the real project, the seven tabs, rollout, verified results, open questions
- [docs/PLAN.md](docs/PLAN.md): screens, engine, stack, build order
- [docs/DATA.md](docs/DATA.md): the synthetic data contract and its assumptions
- [CLAUDE.md](CLAUDE.md): rules for anyone (or any agent) building here

## Run the generator

```bash
python3 -m venv .venv && .venv/bin/pip install -e . pytest
cp .env.example .env
.venv/bin/valeo-gen
.venv/bin/pytest -q
```
