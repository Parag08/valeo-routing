"""Column names, ID formats and fixed vocabularies from docs/DATA.md."""
from __future__ import annotations

VERTICALS = ("nursing", "babysitting", "sample")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# role, staff_id prefix and the vertical each staff role serves (A6).
ROLES = (
    ("home_nurse", "NUR", "nursing"),
    ("babysitter", "BBS", "babysitting"),
    ("collection_nurse", "PHL", "sample"),
)

DATETIME_FMT = "%Y-%m-%dT%H:%M"
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M"
COORD_DECIMALS = 6

COLUMNS = {
    "drivers.csv": ["driver_id", "name", "car_id", "shift_start", "shift_end", "home_area_id"],
    "staff.csv": [
        "staff_id", "name", "role", "home_area_id", "home_lat", "home_lon", "languages", "works_days",
    ],
    "clients.csv": ["client_id", "area_id", "lat", "lon", "building_type", "access_note", "services"],
    "appointments.csv": [
        "appt_id", "service_date", "vertical", "client_id", "staff_id", "start", "end", "service_min",
        "needs_dropoff", "needs_pickup", "test_type", "fasting", "sample_max_min", "lab_id",
        "priority", "booked_at", "channel", "payer", "status", "cancelled_at", "notes",
    ],
    "fleet_events.csv": ["event_id", "date", "car_id", "type", "at", "until"],
}
