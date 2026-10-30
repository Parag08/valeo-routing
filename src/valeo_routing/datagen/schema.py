"""Column names, ID formats and fixed vocabularies from docs/DATA.md."""
from __future__ import annotations

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

DATETIME_FMT = "%Y-%m-%dT%H:%M"
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M"
COORD_DECIMALS = 6

COLUMNS = {
    "staff.csv": [
        "staff_id", "name", "role", "iv_certified", "home_area_id", "home_lat", "home_lon",
        "rest_day", "shift_pref", "usual_car_id",
    ],
    "availability.csv": ["date", "staff_id", "status", "known_at"],
    "orders.csv": [
        "order_id", "published_at", "slot_start", "service_id", "area_id", "lat", "lon", "patient_ref",
        "lab_id", "supplies_ready", "competitor_claim_min", "cancelled_at",
    ],
    "events.csv": ["event_id", "date", "type", "staff_id", "car_id", "at", "until"],
}
