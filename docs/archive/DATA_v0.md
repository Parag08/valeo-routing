# Day-zero data: what the business has before any routing tool

This is the data contract for the synthetic generator. It describes what Valeo-style operations would
already hold on **day zero**, before any routing software exists: master data (fleet, people, places)
kept in spreadsheets, plus the booking export for each day. Everything is **synthetic and mocked**.
Each assumption is numbered (A1, A2, ...) so Parag can fact-check it against the real data and
correct it.

## Layout

```
data/
  reference/            hand-maintained master data (committed, edited by hand)
    areas.csv           public Dubai neighbourhood centroids + demand weights
    labs.csv            partner labs
    depot.csv           where cars park overnight
    fleet.csv           cars
    names.csv           synthetic first names + last initials for people
    demand_profile.json shape of demand per vertical (durations, windows, mixes)
  sample/               generator output for the configured seed (committed for review)
    drivers.csv
    staff.csv
    clients.csv
    appointments.csv
    fleet_events.csv
```

Volumes, the seed, the start date, the number of days and all paths come from `.env` (see
`.env.example`). Shapes of demand (durations, time windows, mixes) live in `demand_profile.json`.
Costs (fuel price, driver cost per hour) are `.env` keys used by the planner later, not data.

All times are local Dubai time (UTC+4), ISO 8601 without offset: `2026-11-02T07:30`.
Coordinates are WGS84 decimal degrees, 6 decimals. Client and staff points are jittered around an
area centroid (A3) and never point at a real address.

## Reference tables (hand-maintained)

### areas.csv

| column | type | meaning |
|---|---|---|
| area_id | str | `AR-01` ... |
| area_name | str | public neighbourhood name, e.g. `Dubai Marina` |
| emirate | str | `Dubai` (A1) |
| lat, lon | float | approximate public centroid |
| jitter_m | int | radius for scattering points around the centroid |
| w_nursing | float | relative weight of home-nursing clients living here |
| w_babysitting | float | relative weight of babysitting clients |
| w_sample | float | relative weight of sample-collection clients |
| w_staff_home | float | relative weight of nurses/babysitters living here |

### depot.csv

| column | type | meaning |
|---|---|---|
| depot_id | str | `DEP-01` |
| name | str | e.g. `Ops base (Al Quoz)` |
| area_id | str | FK areas |
| lat, lon | float | |

### labs.csv

| column | type | meaning |
|---|---|---|
| lab_id | str | `LAB-01` ... |
| name | str | synthetic, e.g. `Central Lab (Healthcare City)` |
| area_id | str | FK areas |
| lat, lon | float | |
| opens, closes | HH:MM | receiving hours |
| handover_min | int | minutes to hand over a cool box |

### fleet.csv

| column | type | meaning |
|---|---|---|
| car_id | str | `CAR-01` ... |
| plate | str | synthetic, e.g. `K 48213` |
| make_model | str | e.g. `Toyota Innova` |
| passenger_seats | int | seats excluding the driver |
| fuel_l_per_100km | float | |
| has_cool_box | bool | can carry samples |
| home_vertical | str | `nursing` / `babysitting` / `sample`; how cars are assigned today (A4) |
| depot_id | str | FK depot |
| status | str | `active` / `maintenance` |

### names.csv

| column | type | meaning |
|---|---|---|
| first_name | str | common first name, synthetic pool |
| last_initial | str | single letter |

### demand_profile.json

Per vertical: booking-length options and weights, start-time distribution (hour → weight), service
time on site, booking channels and payer mix, lead-time distribution, cancellation and no-show rates.
Sample collection adds: test types with sample time limits, fasting share, fast-track share and notice.
The exact keys are documented at the top of the file.

## Generated tables (per seed)

### drivers.csv

| column | type | meaning |
|---|---|---|
| driver_id | str | `DRV-01` ... |
| name | str | synthetic `First L.` |
| car_id | str | usual car (A5) |
| shift_start, shift_end | HH:MM | contracted shift |
| home_area_id | str | FK areas |

### staff.csv (nurses and babysitters)

| column | type | meaning |
|---|---|---|
| staff_id | str | `NUR-001`, `BBS-001`, `PHL-001` |
| name | str | synthetic |
| role | str | `home_nurse` / `babysitter` / `collection_nurse` (A6) |
| home_area_id | str | FK areas |
| home_lat, home_lon | float | jittered |
| languages | str | `;`-separated, e.g. `English;Tagalog` |
| works_days | str | `;`-separated weekdays, e.g. `Mon;Tue;Wed;Thu;Fri;Sat` |

### clients.csv

| column | type | meaning |
|---|---|---|
| client_id | str | `CL-0001` ... |
| area_id | str | FK areas |
| lat, lon | float | jittered |
| building_type | str | `villa` / `apartment` |
| access_note | str | e.g. `gate code at security`, `parking in basement B1`, empty |
| services | str | `;`-separated verticals the client uses |

### appointments.csv (the booking export, one row per booking per day)

| column | type | meaning |
|---|---|---|
| appt_id | str | `AP-20261102-0001` |
| service_date | date | |
| vertical | str | `nursing` / `babysitting` / `sample` |
| client_id | str | FK clients |
| staff_id | str | assigned nurse or babysitter, FK staff |
| start | datetime | visit/booking start; for `sample` the start of the slot |
| end | datetime | visit end; for `sample` the end of the slot (A9) |
| service_min | int | minutes on site (sample: collection time; others: end − start) |
| needs_dropoff | bool | staff must be driven to the client by `start` (A7) |
| needs_pickup | bool | staff must be collected from the client at `end` (A7) |
| test_type | str | sample only, e.g. `CBC`, `lipid_fasting`, `PCR` |
| fasting | bool | sample only |
| sample_max_min | int | sample only: minutes allowed from collection to lab (A10) |
| lab_id | str | sample only: lab the sample must go to |
| priority | str | `routine` / `fast_track` (A11) |
| booked_at | datetime | when the booking was made; same-day for fast-tracks |
| channel | str | `app` / `call_centre` / `whatsapp` / `b2b` |
| payer | str | `self_pay` / `insurance` / `corporate` |
| status | str | `confirmed` / `cancelled` / `no_show` |
| cancelled_at | datetime | when cancelled, empty otherwise |
| notes | str | free text an ops person would see |

### fleet_events.csv (things that happen to cars on a day)

| column | type | meaning |
|---|---|---|
| event_id | str | `FE-0001` |
| date | date | |
| car_id | str | FK fleet |
| type | str | `breakdown` / `late_start` / `driver_absent` |
| at | datetime | when ops learns about it |
| until | datetime | when the car is back, empty if out for the day |

## Assumptions to fact-check

| # | Assumption | Mocked as |
|---|---|---|
| A1 | Operation is Dubai only | all areas in Dubai |
| A2 | One depot where cars park overnight | `DEP-01` in Al Quoz |
| A3 | Locations at neighbourhood level are enough | points scattered within `jitter_m` of a public centroid |
| A4 | 10 cars in total, dedicated to a vertical today | 3 nursing, 3 babysitting, 4 sample collection |
| A5 | One driver per car, fixed pairing | 10 drivers |
| A6 | Separate staff pools per vertical; sample collection uses nurses who ride with the driver all shift | three roles |
| A7 | Nursing and babysitting staff are driven both ways (drop at start, pick up at end) | `needs_dropoff` and `needs_pickup` true for most; some nurses travel home on their own |
| A8 | Home nursing is mostly 8 or 12 h day shifts starting 07:00–09:00, plus ~10% 12 h night shifts from 19:00 and ~10% 24 h live-in (dropped off, not collected) | see `demand_profile.json` |
| A9 | Routine sample collections are booked in 1-hour slots between 07:00 and 19:00, heavier early (fasting tests) | |
| A10 | Time from collection to lab depends on the test: glucose and urine 2 h, lipids 4 h, CBC and PT/INR 8 h (PT/INR must not be chilled), PCR 24 h (business limit) | per test type |
| A11 | Fast-tracks are booked the same day with 30–120 min notice, about 10–15% of collections, and can fall 06:00–22:00 | |
| A12 | Babysitting bookings are 4–10 h (4 h agency minimum), starting 08:00–20:00 | |
| A13 | Daily volume: about 12 nursing visits, 10 babysitting bookings, 40 sample collections | `.env` volumes |
| A14 | Demand runs 7 days, lighter at the weekend (Sat ~0.8, Sun ~0.7 of a weekday) | weekday multipliers in the profile |

Public benchmarks behind A8–A12 and A14 (provider pages, lab stability charts) were checked on
2026-10-30. They support plausible demo values, not Valeo's actual numbers. Cost inputs from the
same check: fuel about AED 4.3/L (Special 95, Oct 2026, reset monthly) and drivers about
AED 3,500/month base, about AED 4,500 fully loaded.
| A15 | 3 partner labs | Healthcare City, Al Barsha, Al Qusais |
