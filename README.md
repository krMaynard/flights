# Flight Planner

A small Flask app that searches Google Flights and lets you build multi-leg
trip plans you can save and revisit.

## What it does

- Search by origin, destination, dates, passengers, cabin class, max stops.
- Live Google Flights data via the [`fast-flights`](https://pypi.org/project/fast-flights/)
  library (which talks to Google Flights' protobuf endpoint). When the host
  can't reach Google (firewalled CI, sandboxed environments), the app
  transparently falls back to a deterministic mock dataset so it stays usable
  for development.
- Save any result as a leg on a named trip plan; legs are persisted in SQLite
  (`flights.db`).
- View plans with all legs, estimated total cost, and a one-click jump to
  search the next leg starting from where the previous one landed.

## Run

```bash
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000>.

## Stack

- Flask + Jinja templates
- SQLite (stdlib)
- [`fast-flights`](https://pypi.org/project/fast-flights/) for live Google Flights queries
- Plain CSS — no JS framework

## Layout

```
app.py          Flask routes
flights.py      Search wrapper (live + mock fallback)
db.py           SQLite storage for plans and legs
templates/      Jinja templates
static/         CSS
```

## Notes

- Airport inputs accept 3-letter IATA codes (`SFO`, `JFK`, `LHR`, ...).
- The `FLIGHTS_SECRET` env var sets the Flask session secret in production.
- The mock fallback is seeded by the search parameters, so the same query
  produces the same options — useful for screenshots and demos.
