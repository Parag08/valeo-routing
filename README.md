# Valeo fleet routing demo

A demo rebuild of the routing problem Parag worked on with **Valeo Health's** operations team
(UAE, summer 2026). A small fleet carries nurses and babysitters to clients' homes across three
verticals: home nursing, babysitting, and sample collection with lab drop-offs and fast-track
disruptions. The demo plans a synthetic day the old way and the optimised way, then shows the
difference in kilometres, idle time, lateness and AED.

The real project reached 100% adoption in its first week and saved 20,000 km and AED 12,200 a
month. This repo uses **synthetic data only**. It is not Valeo's code or data.

Status: **planning.** No code yet.

- [docs/CONTEXT.md](docs/CONTEXT.md): the business, the three verticals, open questions, standing preferences
- [docs/PLAN.md](docs/PLAN.md): what the demo shows, how each vertical is modelled, proposed stack, build order
- [CLAUDE.md](CLAUDE.md): rules for anyone (or any agent) building here
