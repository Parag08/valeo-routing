# Plan: rebuild Logistics Valeo as a public showcase

## Goal

A working web app that rebuilds the dispatch tool Parag shipped at Valeo Health, running on
synthetic data, so anyone can click through it. It should read in 30 seconds to three audiences:

| Audience | What they should see |
|---|---|
| **Forward deployed engineer** (the primary target) | A real operations tool: an engine that accepts orders, sequences each pair's day and replays it live, built against the messy constraints ops actually had |
| **Product manager** | The decisions behind it: what was built and what wasn't, how ops pushback changed it, v1 → v2, how the result was measured |
| **Program manager** | The rollout: launch, 14 days of daily catch-ups, and a measurement plan agreed before the result |

The app's own numbers are always labelled **synthetic**. The real results (CONTEXT.md, "Verified
results") appear only on the case-study page and the About panel, labelled as real.

## The 30-second story

> "This is a day of field visits. **Excel era:** orders claimed by hand, pairs waiting at the
> office. **Logistics Valeo:** the acceptance engine claims what the fleet can serve, and pairs wait
> at hubs. Same demand: more orders captured, fewer km per order. And here's what happens when a
> nurse calls in sick tomorrow."

The **policy switch** (Excel era ↔ Logistics Valeo, plus v2 as "next") sits in the header and
re-renders every tab on the same synthetic day.

## Screens: the seven tabs

### Tier 1: the core

1. **Day view** (the hero screen):
   - a 06:00–22:00 timeline with one row per pair
   - blocks for visits (coloured by service), travel legs labelled with km, time on site, lab
     drops, office stops for IV supplies, and standby at a hub or the office
   - idle time impossible to miss
   - a scrubbable "now" line and replay: orders appear as they are published, and the plan updates
   - actions at the top: add appointment, cancel, mark a pair unavailable
2. **Roster:**
   - tomorrow's staff, with available/sick toggles
   - **auto-allocate** builds pairs and shift start times to cover the hourly demand curve (peaks
     at 07:00–10:00 and 16:00–18:00)
   - shows the demand curve against the capacity on duty
3. **Services:** a catalog of service types with on-site duration ranges, lab requirements and
   whether supplies need an office stop. Editable; changes flow into the day view.
4. **Acceptance engine:**
   - a decision log, one row per order: published at, decision, why (fits pair X / no capacity /
     inside the manual window / quiet hours), and time to decide
   - configuration: auto-accept lead time, manual window, quiet hours, claim window
   - KPIs: orders captured, lost and why
   - a **v2 toggle** for swap-out, labelled "designed, not shipped"

### Tier 2: depth

5. **Hub siting:**
   - a map of the last 30 days of synthetic orders
   - K-median siting for 1–4 hubs, with km per order against the number of hubs
   - "apply" sends the hubs to the day view
6. **Capacity:** pairs needed for each day's demand at p50, p75 and p90 service levels, from a
   concurrency floor and a simulation of the day.
7. **Metrics:**
   - predicted against "actual" km and time, per pair and per day
   - km per order computed from totals, with bad days excluded and the reason shown
   - the saving at the marginal against the all-in cost per km, so the measurement method is
     visible

Plus an **About / case study** panel: the real story, the verified numbers, what was real and what
is synthetic, and what was left unbuilt.

## The engine

All of it is pure functions over plain data, with no web framework inside.

| Module | Does | Notes |
|---|---|---|
| `distance` | Travel km and minutes between two points | Port with two adapters: straight-line × road factor (default), and a road router later. Speed by hour of day. |
| `catalog` | Service duration and requirements | Draws the actual on-site time from the service's range |
| `planner` | Builds and repairs each pair's day: inserts an order at the cheapest feasible position, decides where to wait between jobs (office or nearest hub with a free bay), adds lab drops before each sample's deadline and office stops for IV supplies | Cheapest-insertion plus local improvement. OR-Tools only if insertion proves too weak. |
| `acceptance` | v1: accept if `planner` finds a feasible insertion and the order is outside the manual window and quiet hours; otherwise queue it for ops or decline. v2: if nothing fits, try swapping out one accepted order, scored on km gained and each order's cancellation probability. Writes the decision log. | Rules and thresholds from `.env` |
| `baseline` | Excel era: ops act only in office hours, with a decision delay, so orders can be lost to the claim window; first come, first served; standby at the office | Same planner, different policy |
| `roster` | Auto-allocate: from available staff, form pairs and choose shift starts to cover the hourly demand curve; respects shift length and rest days | Greedy cover of the demand curve |
| `hubs` | K-median on 30 days of order locations (greedy plus local swap) | Hubs are chosen from synthetic demand, never from real sites |
| `capacity` | Pairs needed: a concurrency floor, then simulation at service levels | |
| `metrics` | Predicted against actual; km per order from totals; exclusion rules; saving at a configurable rate | |
| `validator` | Independent of the planner. Checks every plan for time windows (±tolerance), shift length, lab deadlines, no double-booked pair, the office stop before IV | Runs in tests and on every API response in dev |
| `replay` | Steps through a day minute by minute: publishes orders, runs acceptance, applies cancellations and disruptions | Drives the day view's "now" line |

## Stack

- **Backend:** Python 3.9-compatible (the local machine's Python), FastAPI and pydantic-settings.
  Every parameter comes from `.env`, with no in-code defaults. pytest.
- **Frontend:** React and Vite. The timeline is custom SVG; the hub map is MapLibre GL with OSM
  tiles (provider and key in `.env`). The design is quiet and minimal, and the timeline carries the
  page.
- **Data:** the seeded generator writes CSVs; the API loads them at startup. There is no database
  until one is needed.
- **Deploy:** decide later. Either a static frontend plus a small API host, or the API precomputed
  into JSON for a static-only site.

## Build order

| Step | Work | Size |
|---|---|---|
| 0 | **Docs** (this rewrite) and README claim fixes | done |
| 1 | **Rework the generator for the field-visit model** (DATA.md): services, staff, availability, 35 days of orders with publish times and cancellations, events. Reuses the settings layer and the land-only point placement. **Done.** "Actual" km is derived later by the replay (step 3), not stored. | done |
| 2 | **Engine core:** `distance`, `catalog`, `planner`, `validator`, with tests. One day planned end to end from a fixed acceptance. | 1–2 days |
| 3 | **Acceptance v1 + baseline + replay**, with the decision log. KPIs: capture rate, km per order, idle hours. | 1 day |
| 4 | **API + Day view + Acceptance tab + policy switch.** This alone is a recordable demo. | 2 days |
| 5 | **Roster auto-allocation + Services tab.** | 1 day |
| 6 | **Tier 2:** hub siting, capacity, metrics. | 2–3 days |
| 7 | **v2 swap-out** behind its toggle. | 1 day |
| 8 | **Polish:** About panel, recorded clip (20–30 s), portfolio card with the 路 seal, rewritten case study. | 1 day |

Steps 1–4 are the minimum showcase, about a week. Steps 5–8 bring it to the full tool.

## Done looks like

- One command runs it locally, documented in the README.
- The same seed gives the same days, the same plans and the same KPIs.
- The validator passes on every plan, under every policy, in tests.
- The policy switch shows a clear gap on the same synthetic day. The synthetic numbers aren't tuned
  to match the real ones; they only need to move in the same direction for the same reasons.
- Every real figure carries its source and status. Every synthetic figure says "synthetic".
- A 20–30 s clip and a case-study page that work for both FDE and PM readers.

## Risks

- **Confidentiality.** The private internship folder must never feed this repo, beyond the
  aggregate shapes written into DATA.md. Hubs come from synthetic demand, and names come from a
  synthetic pool.
- **Over-claiming.** The demo's gap between policies is synthetic. Only CONTEXT.md's verified
  results describe the real work, with the volume caveat.
- **Scope.** Seven tabs is a lot. Tier 1 ships first and stands on its own.
- **Python 3.9.** The machine has only system Python 3.9. Keep the code 3.9-compatible, or install
  a newer Python before step 2.
