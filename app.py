"""Flask app: search Google Flights and build trip plans."""

from __future__ import annotations

import json
import os
import secrets
from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

import db
import flights


app = Flask(__name__)


def _resolve_secret_key() -> str:
    env_secret = os.environ.get("FLIGHTS_SECRET")
    if env_secret:
        return env_secret
    if os.environ.get("FLIGHTS_ENV", "development") != "development":
        raise RuntimeError(
            "FLIGHTS_SECRET must be set when FLIGHTS_ENV is not 'development'."
        )
    # Random per-process secret for dev. Sessions don't survive restarts,
    # which is the right default for local work.
    return secrets.token_hex(32)


app.secret_key = _resolve_secret_key()

db.init_db()


SEAT_CHOICES = [
    ("economy", "Economy"),
    ("premium-economy", "Premium economy"),
    ("business", "Business"),
    ("first", "First"),
]


@app.template_filter("from_json")
def from_json_filter(value):
    if not value:
        return {}
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


@app.route("/")
def index():
    today = date.today()
    defaults = {
        "origin": request.args.get("origin", ""),
        "destination": request.args.get("destination", ""),
        "depart_date": request.args.get("depart_date", (today + timedelta(days=30)).isoformat()),
        "return_date": request.args.get("return_date", (today + timedelta(days=37)).isoformat()),
        "adults": request.args.get("adults", "1"),
        "children": request.args.get("children", "0"),
        "seat": request.args.get("seat", "economy"),
        "trip": request.args.get("trip", "one-way"),
        "max_stops": request.args.get("max_stops", ""),
    }
    plans = db.list_plans()
    return render_template(
        "index.html",
        defaults=defaults,
        seat_choices=SEAT_CHOICES,
        plans=plans,
    )


@app.route("/search", methods=["GET", "POST"])
def search():
    form = request.values
    origin = (form.get("origin") or "").strip().upper()
    destination = (form.get("destination") or "").strip().upper()
    depart_date = (form.get("depart_date") or "").strip()
    return_date = (form.get("return_date") or "").strip() or None
    trip = form.get("trip") or "one-way"
    seat = form.get("seat") or "economy"
    try:
        adults = max(int(form.get("adults") or 1), 1)
        children = max(int(form.get("children") or 0), 0)
    except (TypeError, ValueError):
        flash("Passenger counts must be whole numbers.", "error")
        return redirect(url_for("index"))
    max_stops_raw = (form.get("max_stops") or "").strip()
    max_stops = int(max_stops_raw) if max_stops_raw.isdigit() else None

    if not origin or not destination or not depart_date:
        flash("Origin, destination, and departure date are required.", "error")
        return redirect(url_for("index"))

    if len(origin) != 3 or len(destination) != 3:
        flash("Use 3-letter IATA airport codes (e.g. SFO, JFK).", "error")
        return redirect(url_for("index"))

    if trip not in ("one-way", "round-trip"):
        trip = "one-way"
    if seat not in dict(SEAT_CHOICES):
        seat = "economy"

    result = flights.search(
        origin,
        destination,
        depart_date,
        return_date=return_date if trip == "round-trip" else None,
        adults=adults,
        children=children,
        seat=seat,
        trip=trip,
        max_stops=max_stops,
    )

    plans = db.list_plans()
    return render_template(
        "results.html",
        result=result,
        query={
            "origin": origin,
            "destination": destination,
            "depart_date": depart_date,
            "return_date": return_date,
            "trip": trip,
            "seat": seat,
            "adults": adults,
            "children": children,
            "max_stops": max_stops_raw,
        },
        plans=plans,
        seat_choices=SEAT_CHOICES,
    )


@app.route("/plans", methods=["GET"])
def plans():
    return render_template("plans.html", plans=db.list_plans())


@app.route("/plans/new", methods=["POST"])
def create_plan():
    name = (request.form.get("name") or "").strip()
    traveler = (request.form.get("traveler") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    if not name:
        flash("Plan needs a name.", "error")
        return redirect(request.referrer or url_for("plans"))
    plan_id = db.create_plan(name, traveler, notes)
    flash(f"Created plan '{name}'.", "success")
    return redirect(url_for("view_plan", plan_id=plan_id))


@app.route("/plans/<int:plan_id>")
def view_plan(plan_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        abort(404)
    legs = db.list_legs(plan_id)
    totals = db.plan_totals(plan_id)
    return render_template("plan.html", plan=plan, legs=legs, totals=totals)


@app.route("/plans/<int:plan_id>/edit", methods=["POST"])
def edit_plan(plan_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        abort(404)
    name = (request.form.get("name") or "").strip()
    traveler = (request.form.get("traveler") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    if not name:
        flash("Plan needs a name.", "error")
        return redirect(url_for("view_plan", plan_id=plan_id))
    db.update_plan(plan_id, name, traveler, notes)
    flash("Plan updated.", "success")
    return redirect(url_for("view_plan", plan_id=plan_id))


@app.route("/plans/<int:plan_id>/delete", methods=["POST"])
def delete_plan_route(plan_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        abort(404)
    db.delete_plan(plan_id)
    flash(f"Deleted plan '{plan['name']}'.", "success")
    return redirect(url_for("plans"))


MAX_LEG_FIELD_LEN = 200
ALLOWED_LEG_SOURCES = {"google", "mock", "unknown"}
ALLOWED_SEATS = {key for key, _ in SEAT_CHOICES}


def _validated_offer(raw_payload: str) -> Optional[dict]:
    """Parse and shape-check the hidden flight payload.

    The payload is round-tripped through the client, so we don't trust its
    contents — we just keep them in known fields with bounded sizes so a
    tampered submission can't smuggle in unexpected types.
    """
    try:
        data = json.loads(raw_payload)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    def _str(value, default: str = "") -> str:
        if value is None:
            return default
        return str(value)[:MAX_LEG_FIELD_LEN]

    try:
        stops = int(data.get("stops") or 0)
    except (TypeError, ValueError):
        stops = 0
    stops = max(0, min(stops, 10))

    source = _str(data.get("source"), "unknown")
    if source not in ALLOWED_LEG_SOURCES:
        source = "unknown"

    return {
        "airline": _str(data.get("airline"), "Unknown"),
        "departure": _str(data.get("departure")),
        "arrival": _str(data.get("arrival")),
        "duration": _str(data.get("duration")),
        "stops": stops,
        "price": _str(data.get("price")),
        "source": source,
    }


def _safe_next_url(value: Optional[str], fallback: str) -> str:
    """Allow only same-origin relative URLs to avoid open redirects."""
    if not value:
        return fallback
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    if not value.startswith("/"):
        return fallback
    return value


@app.route("/plans/<int:plan_id>/legs", methods=["POST"])
def add_leg(plan_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        abort(404)

    raw_payload = request.form.get("payload")
    if not raw_payload:
        flash("Missing flight payload.", "error")
        return redirect(url_for("view_plan", plan_id=plan_id))

    offer = _validated_offer(raw_payload)
    if offer is None:
        flash("Could not parse flight payload.", "error")
        return redirect(url_for("view_plan", plan_id=plan_id))

    origin = (request.form.get("origin") or "").strip().upper()
    destination = (request.form.get("destination") or "").strip().upper()
    depart_date = (request.form.get("depart_date") or "").strip()
    seat = (request.form.get("seat") or "economy").strip()

    if len(origin) != 3 or not origin.isalpha() or len(destination) != 3 or not destination.isalpha():
        flash("Leg must use 3-letter IATA codes.", "error")
        return redirect(url_for("view_plan", plan_id=plan_id))
    try:
        datetime.strptime(depart_date, "%Y-%m-%d")
    except ValueError:
        flash("Leg depart date is not a valid date.", "error")
        return redirect(url_for("view_plan", plan_id=plan_id))
    if seat not in ALLOWED_SEATS:
        seat = "economy"

    db.add_leg(
        plan_id,
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        airline=offer["airline"],
        departure=offer["departure"],
        arrival=offer["arrival"],
        duration=offer["duration"],
        stops=offer["stops"],
        price=offer["price"],
        seat=seat,
        source=offer["source"],
        raw=offer,
    )
    flash(
        f"Added {offer['airline']} ({origin}→{destination}) to '{plan['name']}'.",
        "success",
    )
    return redirect(
        _safe_next_url(request.form.get("next"), url_for("view_plan", plan_id=plan_id))
    )


@app.route("/plans/<int:plan_id>/legs/<int:leg_id>/delete", methods=["POST"])
def delete_leg(plan_id: int, leg_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        abort(404)
    db.delete_leg(leg_id)
    flash("Removed leg.", "success")
    return redirect(url_for("view_plan", plan_id=plan_id))


if __name__ == "__main__":
    debug = os.environ.get("FLIGHTS_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=debug)
