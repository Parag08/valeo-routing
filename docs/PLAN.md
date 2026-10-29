# Plan: Valeo fleet routing demo

## Goal

A working web demo that recreates the problem Valeo Health's operations team had and shows
how routing software fixes it:

1. Generate a realistic synthetic day for all three verticals.
2. Plan it the way it was planned before (the baseline).
3. Plan it with an optimiser.
4. Show the difference in kilometres, idle time, lateness and AED on one screen.
5. Throw in disruptions, such as a fast-track sample collection, and re-plan live.

The demo should read in 30 seconds to someone from operations: "this is my day, this is the same day
planned better, and this is what happens when a fast-track comes in at 11:40."

## What the screen shows

- **Map:** each car's route for the day in its own colour, with stops numbered. The vertical is shown
  by stop shape: nursing, babysitting, sample collection, lab.
- **Timeline:** one row per car across the day, with blocks for driving, waiting at a client, idle
  and lab drop-offs. The babysitting idle gaps should be impossible to miss.
- **Before and after:** baseline plan against optimised plan. KPIs are km, driver hours, idle
  minutes, late arrivals, samples that missed their lab window, and AED per day and per month.
- **Disruption controls:** add a fast-track appointment, cancel a visit, make a car unavailable, or
  delay a lab. The plan repairs itself, and the screen shows what changed.
- **Driver view (stretch goal):** the run sheet for one car, as a phone-sized list, because adoption
  came from fitting the frontline workflow.

## How each vertical is modelled

| Vertical | Problem type | Key constraints |
|---|---|---|
| Home nursing | Multi-pickup, multi-drop routing with time windows | Arrive at each client by the visit start; car capacity (seats); morning-only run, plus an evening return if confirmed |
| Babysitting | Paired pickup and delivery, out and back | Drop-off by booking start, pick-up at booking end; the gap between them is free car time |
| Sample collection | Dynamic routing with time windows and lab deliveries | 12-hour shift; driver and nurse stay together; each sample must reach a lab within its time limit; fast-track jobs are inserted mid-day |

**Cross-vertical pooling** is where the large saving likely sits: babysitting idle gaps and
nursing cars that sit after the morning run could absorb sample-collection legs or other drops. The
demo should be able to show "verticals planned separately" against "one shared fleet".

**Baseline.** Model how routes were planned before (to be confirmed with Parag, question 6 in
CONTEXT.md). Default assumption: each vertical has its own cars, and stops are visited in booking
order with no optimisation.

## Proposed stack

Everything below is a proposal to confirm before building.

- **Backend:** Python 3.12 + FastAPI. Use **Google OR-Tools** for the routing solver: it supports
  vehicle routing with time windows, pickup-and-delivery pairs, capacities and time limits. Use
  pydantic-settings for config, which fails fast on a missing `.env` key.
- **Distances:** behind a small port with two adapters. The first is straight-line distance × a road
  factor, which needs no external service and is good enough for day one. The second is a real road
  router (self-hosted OSRM, or a hosted API with a key in `.env`). This is the same ports-and-adapters
  idea as the support agent.
- **Synthetic data:** a seeded generator. It places clients, staff homes, labs and a depot in real
  Dubai neighbourhoods (by area centroids, never real addresses), and produces bookings per vertical
  with realistic time windows. The seed and volumes come from `.env`.
- **Frontend:** React + Vite + MapLibre GL with free OpenStreetMap-based tiles (provider and key in
  `.env`), plus a simple timeline component. The design is minimal and modern.
- **Tests:** pytest for the generator, constraints and solver outputs. Every plan is checked against
  hard constraints (no late lab drops, capacity, shift length) by an independent validator, not by
  the solver itself.
- **Deploy:** decide later. A static frontend on Vercel or GitHub Pages, and the API on a small free
  host, or a precomputed "demo day" if no backend is hosted.

## Build order (from tomorrow)

1. **Skeleton.** Repo layout, settings layer, `.env.example`, pytest, an empty FastAPI app and a
   Vite app. Data model for depot, car, staff, client, lab and the booking per vertical.
2. **Synthetic day.** The seeded generator, plus a JSON fixture for one demo day. Draw it on the map
   with no routing yet.
3. **Home nursing first.** It's the simplest: baseline against OR-Tools, and a KPI panel. This proves
   the pipeline from data to solver to validator to UI.
4. **Babysitting.** Pickup-and-delivery pairs, idle gaps visible on the timeline.
5. **Sample collection.** Lab deliveries with sample time limits and the 12-hour shift.
6. **Disruptions.** Insert a fast-track or cancel a visit, and re-solve from the current time with the
   cars where they are now. Show the change set.
7. **Shared fleet.** All three verticals in one solve against separate solves, with the saving shown in km
   and AED.
8. **Polish and record.** Driver run-sheet view, a recorded clip, a card on the portfolio projects
   page, and a link from the Valeo case study.

Steps 1–3 are a realistic first day. Steps 4–5 are the second, and 6–8 after that.

## Done looks like

- One command to run the demo locally, documented in the README.
- The same seed always produces the same day and the same plans.
- The validator passes on every optimised plan, with tests to prove it.
- The KPI panel shows a clear before/after for a synthetic day, labelled as synthetic.
- A 20–30 second clip of the demo for the portfolio.

## Risks

- **Road distances:** straight-line distance understates UAE road distances, because of motorways
  and U-turns. Use the road factor at first, and swap in a real router before quoting km.
- **Solver time:** OR-Tools with time windows can be slow on large days. Cap it with a time limit
  from `.env`, and keep the demo day to a realistic size (about 10 cars and 60–120 stops).
- **Over-claiming:** the demo's savings come from synthetic data. Only the case-study figures
  (20,000 km and AED 12,200 a month) describe the real work, and the UI should say so.
