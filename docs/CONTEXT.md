# Context: Valeo Health fleet operations

Everything known so far, gathered from Parag on 2026-10-29 and from the Valeo Health case study on
his portfolio (parag08.github.io/work/valeo-health/). Read this before planning or building anything.

## Where this comes from

Over the summer of 2026 Parag worked with the **Valeo Health operations team (UAE)**. He did the
financial diagnosis of the fleet's costs, sat with the people running the routes, specified a
routing application, and built a separate prototype (Valeo Smart Tracker, a medication-adherence
app; not part of this repo).

Results of the real routing work, as published in the case study:

| Result | Value |
|---|---|
| Adoption by the operations team | 100% in the first week |
| Distance saved | 20,000 km per month |
| Cost saved | AED 12,200 per month |

The lesson the case study draws: the cost baseline came first so the problem had a number, and the
product was designed around the people running the routes, because a routing tool nobody uses
removes no kilometres.

**This repo is a demo rebuild, not Valeo's code.** It must use synthetic data only: no real patient,
staff, client or address data from Valeo, and no Valeo branding beyond naming the case.

## The operation

An operations fleet (Parag described it as "a fleet of 10"; read as about 10 cars, to be confirmed)
of drivers carrying nurses and babysitters to clients' homes, across three business verticals.

### 1. Home nursing

- One car starts in the morning, picks up all the nurses (from their homes or a hub), and drops each
  one at their client's location.
- Shape: a morning multi-pickup, multi-drop run with arrival deadlines at each client.
- Unknown: how nurses get home at the end of the shift (does the same car collect them?), shift
  lengths, and whether visits are fixed daily or change.

### 2. Babysitting

- The driver picks up the babysitters and drops them at clients' locations, then later brings them
  from the client's location back to their own location.
- There is **idle time in the middle** for the driver between drop-off and return.
- Shape: paired pickup-and-delivery trips (out in the morning, back later) with a gap the car spends
  idle. The idle gap is the obvious waste and the obvious opportunity.

### 3. Sample collection

- Shifts of **12 hours**. The driver picks up a nurse, then they go from client to client through
  the day: collect samples, drop them at labs, go to the next client.
- **Lots of disruption**: fast-track appointments and other changes arrive during the day and have to
  be fitted in.
- Shape: a dynamic route with time windows, lab drop-offs (samples likely have a time limit before
  they must reach a lab), and re-planning when an urgent job is inserted mid-route.

## Open questions for Parag

1. Fleet: 10 cars in total, or 10 per vertical? Are cars dedicated to a vertical or shared?
2. Home nursing: who brings nurses home, and when? Fixed visits or daily changes?
3. Babysitting: typical length of a booking, and so of the driver's idle gap?
4. Sample collection: how long can a sample wait before reaching a lab? How many labs? How often do
   fast-track appointments arrive, and how much notice do they give?
5. Geography: which emirates or areas (Dubai only, or Dubai + Sharjah + Abu Dhabi)?
6. How were routes planned before (by hand, by a dispatcher, on WhatsApp)? This is the baseline the
   demo compares against.
7. Cost inputs: fuel cost per km, driver cost per hour, any per-trip charges, so the demo can report
   AED like the case study did.
8. What did the real product's frontline workflow look like (dispatcher screen, driver phone view)?

## Parag's standing preferences that apply here

- **Config in `.env`, never hardcoded.** Every parameter (costs, speeds, shift lengths, solver time
  limits, API keys, map keys) comes from `.env` through a settings layer that fails fast on a missing
  key. No silent in-code defaults. Ship a `.env.example` documenting every key. Reference and seed
  data live in data files, not code literals.
- **Minimal, modern design.** The UI should be clean and quiet, not decorated.
- **Honesty in claims.** The portfolio states what is real and what is a demo; numbers the demo
  produces must be labelled as coming from synthetic data.
- **Portfolio tie-in.** The finished demo should become a card on parag08.github.io/projects.html,
  which currently shows JobSearch, MicroDuck and the pluggable support agent, each with a recorded
  clip and a vermilion hanko seal (道, 歩, 助). A natural seal here would be 路 ("route"). The existing
  "Valeo routing application" case study on the site would link to it.
