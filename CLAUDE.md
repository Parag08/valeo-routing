# Valeo fleet routing demo: working rules

Read docs/CONTEXT.md and docs/PLAN.md before starting any session.

- **Synthetic data only.** Never add real Valeo patient, staff, client or address data. Locations are
  area centroids in public neighbourhoods, generated from a seed.
- **Config in `.env`, never hardcoded.** Costs, speeds, shift lengths, solver limits, map and router
  keys, the data seed and volumes all come from `.env` through one settings module that fails fast on
  a missing key. There are no in-code defaults. Keep `.env.example` documenting every key, and never
  commit `.env`.
- **Plans are checked independently.** Every optimised plan goes through a validator separate from
  the solver: time windows, capacity, shift length and sample-to-lab time limits. Tests cover it.
- **Honest numbers.** The UI labels demo KPIs as synthetic. Only the case-study figures describe the
  real project.
- **Minimal, modern UI.** Quiet and clean; the map and timeline carry the page.
- **Keep the open questions current.** When Parag answers one in docs/CONTEXT.md, update the
  model and the docs together.
