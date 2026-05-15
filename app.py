"""Flask app: search Google Flights and build trip plans."""

from __future__ import annotations

import json
import os
from datetime import date, timedelta

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
app.secret_key = os.environ.get("FLIGHTS_SECRET", "dev-secret-change-me")

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
    adults = max(int(form.get("adults") or 1), 1)
    children = max(int(form.get("children") or 0), 0)
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


@app.route("/plans/<int:plan_id>/legs", methods=["POST"])
def add_leg(plan_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        abort(404)

    raw_payload = request.form.get("payload")
    if not raw_payload:
        flash("Missing flight payload.", "error")
        return redirect(url_for("view_plan", plan_id=plan_id))
    try:
        offer = json.loads(raw_payload)
    except json.JSONDecodeError:
        flash("Could not parse flight payload.", "error")
        return redirect(url_for("view_plan", plan_id=plan_id))

    origin = (request.form.get("origin") or "").strip().upper()
    destination = (request.form.get("destination") or "").strip().upper()
    depart_date = (request.form.get("depart_date") or "").strip()
    seat = (request.form.get("seat") or "economy").strip()

    db.add_leg(
        plan_id,
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        airline=offer.get("airline", "Unknown"),
        departure=offer.get("departure", ""),
        arrival=offer.get("arrival", ""),
        duration=offer.get("duration", ""),
        stops=int(offer.get("stops") or 0),
        price=offer.get("price", ""),
        seat=seat,
        source=offer.get("source", "unknown"),
        raw=offer,
    )
    flash(
        f"Added {offer.get('airline', 'flight')} ({origin}→{destination}) to '{plan['name']}'.",
        "success",
    )
    next_url = request.form.get("next") or url_for("view_plan", plan_id=plan_id)
    return redirect(next_url)


@app.route("/plans/<int:plan_id>/legs/<int:leg_id>/delete", methods=["POST"])
def delete_leg(plan_id: int, leg_id: int):
    plan = db.get_plan(plan_id)
    if not plan:
        abort(404)
    db.delete_leg(leg_id)
    flash("Removed leg.", "success")
    return redirect(url_for("view_plan", plan_id=plan_id))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=True)
