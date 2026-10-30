# Data contract: the field-visit model (v1)

This is the synthetic data behind the Logistics Valeo rebuild (PLAN.md). It describes what the
operation holds: master data (office, labs, services, staff, cars) and the partner order feed, over
30+ days so hub siting and capacity have history to learn from.

**Everything is synthetic.** The shapes (volumes, peaks, durations, lead times) follow the real
operation's aggregates as ranges. No real row, location, name or volume figure enters this repo.

> The generator in `src/valeo_routing/datagen/` still implements the earlier three-vertical contract
> (`docs/archive/DATA_v0.md`). PLAN step 1 reworks it to this one.

## Layout

```
data/
  reference/              hand-maintained (committed)
    areas.csv             public Dubai neighbourhood centroids + weights
    office.csv            the ops office: supplies, default standby
    labs.csv              partner labs (synthetic names)
    services.csv          the service catalog (Services tab)
    fleet.csv             cars
    names.csv             synthetic name pool
    demand_profile.json   demand shapes: hourly curve, lead times, mixes, rates
  sample/                 generator output for the configured seed (committed for review)
    staff.csv
    availability.csv
    orders.csv
    events.csv
```

The seed, start date, number of days, volumes, staff counts and paths come from `.env`. So do all
engine and policy parameters (road factor, speeds, tolerance, acceptance rules, claim window,
cost-per-km rates). Distribution shapes live in `demand_profile.json`. Hubs are **not** data: the
Hub siting tab computes them from the orders.

All times are Dubai local time, ISO 8601 without offset. Coordinates are WGS84 with 6 decimals.
Patient and staff points are jittered around a public area centroid and never point at a real
address.

## Reference tables

### areas.csv

| column | type | meaning |
|---|---|---|
| area_id | str | `AR-01` … |
| area_name | str | public neighbourhood name |
| emirate | str | `Dubai` (S1) |
| lat, lon | float | approximate public centroid |
| jitter_m | int | radius for scattering points |
| w_orders | float | relative weight of field-visit orders from this area |
| w_staff_home | float | relative weight of staff living here |

### office.csv

| column | type | meaning |
|---|---|---|
| office_id | str | `OF-01` |
| name | str | synthetic, e.g. `Ops office (Al Quoz)` |
| area_id | str | FK areas |
| lat, lon | float | |

### labs.csv

| column | type | meaning |
|---|---|---|
| lab_id | str | `LAB-01` … |
| name | str | synthetic |
| area_id | str | FK areas |
| lat, lon | float | |
| opens, closes | HH:MM | receiving hours |
| handover_min | int | minutes to hand over samples |

### services.csv

| column | type | meaning |
|---|---|---|
| service_id | str | `SV-01` … |
| name | str | e.g. `Blood draw – routine panel`, `IV – hydration`, `IV – extended infusion` |
| category | str | `sample` / `iv` / `injection` |
| duration_min_lo, duration_min_hi | int | range of time on site (S6) |
| needs_lab | bool | samples must reach a lab |
| sample_max_min | int | minutes allowed from collection to lab; empty if no lab |
| keep_cold | bool | sample handling flag |
| needs_office_supplies | bool | IV kits are collected at the office unless prepared the day before (S12) |
| iv_certified_only | bool | only IV-certified nurses may serve it |
| mix_weight | float | share of demand (S5) |

### fleet.csv

| column | type | meaning |
|---|---|---|
| car_id | str | `CAR-01` … |
| plate | str | synthetic |
| make_model | str | |
| fuel_l_per_100km | float | |
| has_cool_box | bool | |
| status | str | `active` / `maintenance` |

### names.csv

Unchanged from v0: `first_name`, `last_initial`.

## Generated tables

### staff.csv

| column | type | meaning |
|---|---|---|
| staff_id | str | `NUR-001` …, `DRV-001` … |
| name | str | synthetic `First L.` |
| role | str | `nurse` / `driver` |
| iv_certified | bool | nurses only |
| home_area_id | str | FK areas |
| home_lat, home_lon | float | jittered |
| rest_day | str | fixed weekly rest day, e.g. `Fri` (S3) |
| shift_pref | str | `day` / `split` / `any` |
| usual_car_id | str | drivers only; FK fleet |

### availability.csv

The roster's input: one row per staff member per day.

| column | type | meaning |
|---|---|---|
| date | date | |
| staff_id | str | FK staff |
| status | str | `available` / `rest` / `sick` / `leave` |
| known_at | datetime | when ops learns of it; sick calls can arrive the same morning |

### orders.csv

The partner feed: one row per order the platform publishes.

| column | type | meaning |
|---|---|---|
| order_id | str | `OR-20261102-0001` |
| published_at | datetime | when the order appears on the platform (S8) |
| slot_start | datetime | requested arrival time; arrival allowed within ± tolerance (S9) |
| service_id | str | FK services |
| area_id | str | FK areas |
| lat, lon | float | jittered patient point |
| patient_ref | str | synthetic, `PT-00042`; repeat patients exist |
| lab_id | str | nearest lab for samples; empty otherwise |
| supplies_ready | bool | IV booked before the prep cut-off the day before, so no office stop is needed |
| competitor_claim_min | int | minutes after publishing until another provider takes the order if it isn't accepted (S13) |
| cancelled_at | datetime | when the patient cancels; empty if they don't (S10) |

### events.csv

| column | type | meaning |
|---|---|---|
| event_id | str | `EV-0001` |
| date | date | |
| type | str | `sick_call` / `car_breakdown` / `late_start` |
| staff_id | str | for staff events |
| car_id | str | for car events |
| at | datetime | when ops learns of it |
| until | datetime | when it ends; empty if it lasts all day |

## Ground truth for the Metrics tab

"Actual" km and minutes aren't stored as data. The replay derives them from the plan with seeded
noise: a per-day traffic factor, per-leg noise, and a share of unplanned detours. All their
parameters are `.env` keys (S14). This keeps the plan honest: the planner only ever sees predicted
distances.

## Assumptions (shaped by real aggregates; Parag to confirm)

| # | Assumption | Mocked as |
|---|---|---|
| S1 | The demo covers Dubai only (the real fleet also served other emirates) | Dubai areas |
| S2 | One ops office: supplies pick-up and the default standby spot | `OF-01` |
| S3 | 9–12 nurse–driver pairs on duty a day; 12 h shifts inside 06:00–22:00, some split 6+6; fixed weekly rest day | staff counts in `.env`, shift shapes in the profile |
| S4 | About 35–55 orders published a day | mean in `.env`, weekday multipliers in the profile |
| S5 | Mix of about 60% sample collection, 30% IV, 10% injection | `services.mix_weight` |
| S6 | On site: blood draw 10–20 min, other samples up to 30, injection 20–30, IV 30–120 by type | duration ranges per service |
| S7 | Demand peaks 07:00–10:00 and 16:00–18:00 | hourly weights in the profile |
| S8 | Orders are published 2–48 h ahead, some same-day | lead-time distribution in the profile |
| S9 | Arrival tolerance ±15 min | `.env` |
| S10 | About 5% of orders cancelled | rate in the profile |
| S11 | Samples must reach a lab within their time limit: 2 h for glucose and urine, 4 h for lipids, 8 h for CBC and coagulation | `services.sample_max_min` |
| S12 | IV kits come from the office unless booked before 18:00 the day before | `supplies_ready` |
| S13 | An order not accepted is taken by another provider after 30–240 min | `competitor_claim_min` (open question 3) |
| S14 | Predicted km = straight line × road factor (1.4–1.5); actual adds traffic noise and unplanned detours | `.env` |
| S15 | Excel-era ops decide only in office hours (about 08:00–20:00), 15–90 min after an order is published | `.env`, baseline policy |
