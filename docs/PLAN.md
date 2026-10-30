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

### Rules the engine plans by (step 2)

- **A day starts and ends at the office.** The way home counts towards km, not towards the shift.
- **Arrival** must fall within ±`ARRIVAL_TOLERANCE_MIN` of the requested slot. The pair aims for the
  start of that window, then spends `ACCESS_MIN` before service starts. Planned service time comes from
  the catalog (`PLAN_DURATION_POSITION`).
- **Samples** must reach their lab within `sample_max_min` of the visit ending, inside the lab's opening
  hours and before it closes less the handover. Samples for the same lab are batched into one run. A
  one-visit lookahead sends the pair to the lab early when serving the next visit first would make a
  carried sample late.
- **IV kits.** An IV order not prepared in advance needs the pair to have been at the office at least
  `OFFICE_SUPPLY_STOP_MIN` after the order was published; otherwise the plan adds an office stop.
- **IV orders** go only to IV-certified nurses.
- **Idle gaps** of at least `STANDBY_MIN_GAP_MIN` are spent at the policy's standby spot (the office in
  the Excel era, a hub later) if the detour still arrives on time; otherwise the pair waits in place.
- **Insertion** adds each order where it adds the fewest km across all pairs and positions; ties go to
  the lower pair id. An order that fits nowhere is rejected as `no_certified_nurse`, `lab_unreachable`,
  `outside_shifts` or `no_capacity`.
- **The validator** re-checks every plan without using planner code: continuity in time and place,
  drive km and minutes, arrival windows, durations, shift bounds, certification, lab hours, sample
  deadlines, kits and double-booking.
- **Not yet modelled:** split shifts (one window per pair), late starts and car breakdowns, cancellations
  during the day (the offline plan simply leaves cancelled orders out), and the roster (pairs are
  formed by a placeholder until step 5).

### Acceptance and replay rules (step 3)

- **The competitor's clock.** An order nobody has accepted `competitor_claim_min` minutes after it was
  published is taken by another provider and lost. A decision made exactly at the deadline still counts.
- **Excel era.** Ops see an order when they next sit down (`OFFICE_HOURS`), then take `EXCEL_RESPONSE_MIN_LO`
  to `_HI` minutes to decide. Overnight orders therefore wait for the morning, and most are lost.
- **Logistics Valeo v1.** The tool accepts by itself the moment an order is published when its lead
  time, **not counting `QUIET_HOURS`**, is at least `AUTO_ACCEPT_LEAD_H`: ops would have time to react
  if it got something wrong. Any other order goes to ops with the open slots shown upfront, so they
  decide faster (`MANUAL_RESPONSE_MIN_*`). Both are configurable; the demo default is 12 h.
- **Same planner under both policies.** An accepted order goes where it adds the fewest km. Both
  policies send idle pairs back to the office, so step 3 shows the capture gap; the km gap comes with
  hubs in step 6.
- **What has started cannot change.** A decision at minute `now` may only change what starts after
  `now`; a pair that is waiting can leave early. A cancellation removes the visit only if that rule
  allows it; otherwise it is logged as a late cancellation and the visit still happens.
- **Decision log.** One row per order: published, decided, mode (`auto` / `manual` / `excel`), outcome
  (`accepted` / `declined` / `lost` / `cancelled_before_decision`), pair and the reason, and what finally
  happened to it (`served` / `cancelled` / `late_cancellation` / `not_served`).
- **KPIs.** *Capturable* orders are those not cancelled before anyone decided; *capture rate* is
  accepted over capturable; *visits* are accepted less honoured cancellations; *km per visit* is total
  km (including the way home and late-cancelled visits) over visits; *idle h* is on-shift pair time spent
  neither driving, serving, at the lab nor collecting kits.
- **Assumptions behind the capture gap** (all in `.env`, all to be confirmed): office hours 08:00–20:00,
  quiet hours 22:00–06:00, Excel response 15–90 min, manual response with the tool 5–30 min, auto-accept
  at 12 h. The synthetic competitor claims an order 30–240 min after publishing.
- **Simplifications:** the roster is the day's final one (sick calls are not played out as disruptions
  yet), and v2 swap-out is not built.

### The app (step 4)

- **API** (`valeo-serve`, FastAPI): `/api/meta`, `/api/day?date=&policy=` (pairs and their blocks, jobs,
  decision log, KPIs and the validator's verdict), `/api/compare?date=` (both policies' KPIs) and optional
  overrides for the auto-accept notice, quiet hours and office hours. Read-only. Replays are cached.
  It also serves the built UI at `/`. The server honours `PORT`, which wins over `API_PORT` in `.env`.
- **UI** (`web/`, React + Vite + TypeScript, no chart library): a controls row (day, policy), the stat
  tiles with one hero figure, and two tabs.
  - **Day view:** the timeline is plain SVG. Each visit takes its service category's colour; driving,
    waiting, kit stops and lab drops are neutral. A top row marks orders that were not captured. There is
    a hover crosshair and tooltips, keyboard focus on visits and markers, and a detail card for the
    selected order.
  - **Acceptance engine:** the rules (auto-accept notice, quiet hours, office hours) replay the day on
    change; a stacked outcome bar per policy; and the decision log as a filterable table, which is also
    the table view of the day.
  - Light and dark themes; every status mark pairs an icon with its label.
- **Colour.** Three categorical slots (sample, IV, injection) validated for all-pairs use in both modes.
  Aqua is under 3:1 on the light surface, so visits carry labels where they fit, tooltips and the table.
- **Checked** in the browser pane at 1400 px and 375 px, light and dark; the TypeScript build is the only
  automated check on the UI so far.

### Roster and services (step 5)

- **Demand curve.** For a service day, expected orders per hour come from the *other* days of the month:
  the mean count for that weekday, spread over the hours by when work fell (cancelled orders left out),
  moved `ROSTER_LEAD_MIN` earlier because a pair has to be on the road before the slot. Each order is its
  planned service time plus access time plus `ROSTER_TRAVEL_ALLOWANCE_MIN` of driving; dividing by
  `ROSTER_TARGET_UTILISATION` gives the pairs needed. Any hour with at least `ROSTER_MIN_ORDERS_FOR_COVER`
  expected orders keeps at least `ROSTER_MIN_PAIRS_WHEN_BOOKED` pair on duty.
- **Allocation.** Every available nurse and driver is paired (the smaller group sets the count; the rest
  are reserve). Each pair's shift start, on the `ROSTER_START_*` grid, is chosen greedily to minimise the
  squared shortfall against the needed curve, so peaks are covered first. IV-certified nurses are then
  spread across the starts. Staff marked sick drop out and the reserve steps in where there is one.
- **What the first two attempts taught.** Covering the peaks alone left the early and late hours empty,
  and a pair that has not started cannot serve a 06:00 slot, so the roster lost more orders at the edges
  than it gained at the peaks. The minimum-cover rule and the lead-time shift fix that.
- **Result on the synthetic month** (all 35 days, same people, same planner): the auto roster leaves
  about 2 pair-hours of demand uncovered a day against about 11 for simple pairing, and captures 81.0%
  against 80.0% of orders under Logistics Valeo v1 (66.7% against 65.8% in the Excel era), with fewer
  declines (153 against 167) and less idle time. That is a modest gain of about 14 orders a month, not a
  large one; one day (4 Nov) shows 84% against 76%.
- **Services tab.** Edit on-site minutes (minimum and maximum) and, for lab services, the time allowed to
  reach the lab. Edits travel in the query string (`services=SV-01:30-40,SV-03:10-20:120`) and flow into
  the planned visit lengths, the lab deadlines, the roster's demand estimate and every figure. The kit
  stop, certification and lab requirement are shown but fixed. Edits are not saved: they live in the page.
- **Scenario.** `roster`, `unavailable` (staff marked sick) and `services` join the acceptance-rule
  overrides in one scenario; the page shows a banner when any is active.
- **Not modelled:** split shifts, keeping a nurse and driver together from day to day, `shift_pref`, and
  sick calls played out in real time (marking someone sick changes the whole day's roster).

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
| 2 | **Engine core:** `distance`, `catalog`, `planner`, `validator`, with tests. One day planned end to end from a fixed acceptance. **Done** (`.venv/bin/valeo-plan --date 2026-11-04`). | done |
| 3 | **Acceptance v1 + baseline + replay**, with the decision log. KPIs: capture rate, km per order, idle hours. **Done** (`.venv/bin/valeo-replay --days 7 --log`). | done |
| 4 | **API + Day view + Acceptance tab + policy switch.** This alone is a recordable demo. **Done** (`valeo-serve`, UI in `web/`). Not yet: the replay slider that steps through the day as orders arrive, and the add / cancel / unavailable actions. | done |
| 5 | **Roster auto-allocation + Services tab.** **Done** (Roster and Services tabs; `engine/roster.py`). | done |
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
