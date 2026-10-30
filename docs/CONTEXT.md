# Context: what this demo recreates

Read this before planning or building anything. Sources: Parag's own account (2026-10-30) and his
internship deliverables, checked claim by claim against them. Those deliverables stay private; see
"What must never come into this repo".

## The project

In summer 2026 Parag was a management intern at **Valeo Health**, a UAE home-healthcare provider,
working on fleet and scheduling cost. Nurse–driver pairs drive to patients' homes for short field
visits: **sample collection (SC), IV therapy and injections** (SC/IV for short). Orders come from a
partner booking platform, where they are broadcast and claimed by the provider. The company also
runs home nursing and babysitting, which are long shifts with commute-only driving. Those lines were
analysed but deliberately not tooled (see "Judgement calls").

He started from no baseline at all. He rebuilt the fleet's cost base from invoices, trackers, card
statements and payroll; designed hub siting and roster planning; and built **Logistics Valeo**, the
dispatch tool ops ran the field-visit line on. It was built on Lovable, the low-code platform ops
already used.

## How it worked before

- Ops kept acceptance and scheduling in **Excel**, claiming orders from the platform by hand. They
  captured about **60–70%** of the orders offered.
- Idle pairs waited at the **office** between visits, so every gap became a round trip.
- Field visits averaged **60 km per order**, the agreed baseline from four months of closed
  accounts.
- A km saved is worth the **marginal** cost per km (fuel, tolls, parking), which is less than half
  the all-in average. Salary and rental don't fall when cars drive less.

## What Logistics Valeo did: seven tabs

The demo rebuilds these with synthetic data.

1. **Day view.** A timeline from 06:00 to 22:00 with one row per nurse–driver pair. It shows each
   appointment, the travel legs with km to the next stop, and time on site. "Add appointment" and
   the other actions sit at the top. This is the screen ops lived in.
2. **Roster.** Who is on duty tomorrow, and removing anyone who is sick. It **auto-allocates** the
   roster from the staff who are present, planning around the demand peaks of 07:00–10:00 and about
   16:00–18:00.
3. **Services.** On-site duration per appointment type. A blood draw takes about 15 minutes; IV
   takes from about 30 minutes to 2 hours depending on the type. This sets every appointment's
   length.
4. **Acceptance engine.** It automatically accepts an order if the fleet has the capacity to serve
   it. It keeps a log of the decision on every order, and its parameters are configurable.
   - **Lead-time rule.** Orders far enough ahead are accepted automatically. Orders inside the
     manual window go to ops to accept, with the open slots shown upfront.
   - **Changes after ops pushback.** The auto-accept lead time moved from 3 h to 24 h and became
     configurable. Night hours are ignored. Without these changes, orders booked overnight were
     accepted for early-morning slots after the ops shift had ended, leaving nobody to react if the
     tool got it wrong.
   - **Demo rule.** The demo accepts by itself when the lead time, not counting quiet hours
     (22:00–06:00), is at least a configurable number of hours (default 12). Which numbers shipped, and
     how night hours were excluded, is open question 6.
   - **v2, designed but not shipped.** When an order doesn't fit, check whether swapping out an
     accepted order makes the fleet better off. Score each swap on distance and on each order's
     probability of being cancelled.
5. **Metrics.** Predicted km against actual km from ground data, and the same comparison for time.
   Predictions came from straight-line distance × a road multiplier.
6. **Hub siting.** Where standby hubs should sit, from the last 30 days of orders.
7. **Capacity.** How many nurses and drivers the incoming demand needs, for example 11 or 12.

## Rollout and adoption

- Live on **1 August 2026**: partly at first, with ops fully on the tool **within a week**.
- The first day had many issues. Parag held **daily catch-ups with ops for 14 days** to collect
  problems and improvements.
- What won ops over: the tool worked out the routing itself and showed the whole day live.
- **Hub resistance.** Nurses wanted to stay at the office and said the hubs didn't seem optimal.
  Carrot and stick moved them: Wi-Fi and an air-conditioned place to sit at each hub, and staff
  seen at the office were sent back to their hub. The km data settled the argument.

## Verified results (real; the only real numbers this repo may show)

| Result | Value | Status |
|---|---|---|
| Orders captured from the platform | 60–70% → 80–90% | Measured, validated by the ops lead |
| SC/IV distance per order | 60 → 45.3 km (−24.6%) over 16 Aug–16 Sep; 42.6 km in September | Measured on 29 clean days |
| Distance saved | ~23,000 km a month | Measured, at that month's order volume |
| Cost saved | ~AED 12,400 a month, at the marginal cost per km | Measured; accepted by the company |

- **Caveat (Parag's own).** Daily order volume rose over the same period, and denser days cost less
  per order. The share of the km drop due to hubs versus volume was not separated. Say "km per order
  fell 25% after launch", not "hubs cut km by 25%".
- **Do not claim:**
  - "100% adoption": say "ops fully moved onto the tool within a week".
  - Any absolute fleet spend.
  - The modelled ~21% programme saving, unless it is clearly labelled "modelled".

## Judgement calls worth telling

- **Home nursing and babysitting got no routing tool.** Ops already paired 86% of shift changeovers
  and 93% of movements repeat day to day, so routing had little left to gain. The lever there is a
  trip record and an incentive, not an optimiser.
- **The baseline was withdrawn when the data disproved it.** Every money figure in CEO reporting was
  tagged by confidence: invoiced, measured, modelled, bounded or do-not-bank.
- **The saving was counted carefully:**
  - from totals (sum of km ÷ sum of orders), not by averaging daily ratios
  - excluding corrupt or incomplete days
  - at the marginal rate per km

## What must never come into this repo

- Any file, row, screenshot or code from the private internship folder. It contains patient and
  staff names, addresses, home coordinates, a partner API host and keys.
- Real hub or office locations, staff or patient names, vendor names, salaries, absolute costs, or
  order volumes beyond the ranges used to shape synthetic data.
- The demo's code is written fresh. The algorithms are generic, but the original code touched real
  data and belongs to the employer.

## Open questions for Parag

1. **Roster auto-allocation** (your description cut off at "who all are present that…"). What rules
   did it use: shift shapes (12 h, split 6+6), fixed driver–nurse pairs, rest days, how peaks set
   start times?
2. **Acceptance v1 capacity check.** Was "has capacity" a full feasibility check (a pair can reach
   it on time given its existing jobs, lab deadline and shift end) or a simpler slot count?
3. **The claim race.** How quickly did an unclaimed order disappear to another provider? This sets
   how much capture the Excel era lost.
4. **Cancellation probability for v2.** Which signals did you have in mind: lead time, service
   type, area, patient history?
5. **Metrics.** Where did "actual" km come from: vehicle trackers, odometers or the portal?
6. **The auto-accept rule as shipped.** You described a 12 h lead time and, after ops pushed back, a
   change from 3 h to 24 h with night hours ignored. What exactly was the final rule, and what did the
   tool do with an order published at night for the next morning?
7. **How fast did ops decide?** The demo assumes 15–90 min in the Excel era (office hours only) and
   5–30 min with the tool. Roughly right?
