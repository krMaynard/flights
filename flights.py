"""Flight search wrapper.

Uses the fast-flights library (which talks to Google Flights' protobuf
endpoint) when the network allows. Falls back to a deterministic mock
generator so the app stays fully functional offline / behind firewalls.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional

from fast_flights import FlightData, Passengers, get_flights


TripType = Literal["one-way", "round-trip"]
SeatClass = Literal["economy", "premium-economy", "business", "first"]


@dataclass
class FlightOffer:
    airline: str
    departure: str
    arrival: str
    duration: str
    stops: int
    price: str
    is_best: bool
    arrival_time_ahead: str
    delay: Optional[str]
    source: str  # "google" or "mock"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchResult:
    current_price: str
    flights: list[FlightOffer]
    source: str
    notice: Optional[str] = None


def search(
    origin: str,
    destination: str,
    depart_date: str,
    *,
    return_date: Optional[str] = None,
    adults: int = 1,
    children: int = 0,
    infants_in_seat: int = 0,
    infants_on_lap: int = 0,
    seat: SeatClass = "economy",
    trip: TripType = "one-way",
    max_stops: Optional[int] = None,
) -> SearchResult:
    """Run a flight search, returning live data when possible."""
    origin = origin.strip().upper()
    destination = destination.strip().upper()

    flight_data = [FlightData(date=depart_date, from_airport=origin, to_airport=destination)]
    if trip == "round-trip" and return_date:
        flight_data.append(
            FlightData(date=return_date, from_airport=destination, to_airport=origin)
        )

    try:
        result = get_flights(
            flight_data=flight_data,
            trip=trip,
            seat=seat,
            passengers=Passengers(
                adults=adults,
                children=children,
                infants_in_seat=infants_in_seat,
                infants_on_lap=infants_on_lap,
            ),
            fetch_mode="common",
            max_stops=max_stops,
        )
    except Exception as exc:
        return _mock_search(
            origin,
            destination,
            depart_date,
            return_date=return_date,
            seat=seat,
            trip=trip,
            max_stops=max_stops,
            reason=str(exc),
        )

    offers = [
        FlightOffer(
            airline=f.name or "Unknown",
            departure=f.departure or "",
            arrival=f.arrival or "",
            duration=f.duration or "",
            stops=int(f.stops or 0),
            price=f.price or "",
            is_best=bool(f.is_best),
            arrival_time_ahead=f.arrival_time_ahead or "",
            delay=f.delay,
            source="google",
        )
        for f in result.flights
    ]
    return SearchResult(
        current_price=result.current_price or "",
        flights=offers,
        source="google",
    )


# -------- mock fallback --------

_AIRLINES = [
    ("Delta", "DL"),
    ("United", "UA"),
    ("American", "AA"),
    ("JetBlue", "B6"),
    ("Alaska", "AS"),
    ("Southwest", "WN"),
    ("Spirit", "NK"),
    ("Frontier", "F9"),
    ("Lufthansa", "LH"),
    ("British Airways", "BA"),
    ("Air France", "AF"),
    ("KLM", "KL"),
    ("Emirates", "EK"),
    ("ANA", "NH"),
]


def _seeded_rng(*parts: str) -> random.Random:
    h = hashlib.sha256("|".join(parts).encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def _format_time(dt: datetime) -> str:
    return dt.strftime("%I:%M %p on %a, %b %-d").lstrip("0")


def _mock_offers_for_leg(
    origin: str,
    destination: str,
    depart_date: str,
    seat: SeatClass,
    max_stops: Optional[int],
) -> list[FlightOffer]:
    rng = _seeded_rng(origin, destination, depart_date, seat)
    try:
        base_date = datetime.strptime(depart_date, "%Y-%m-%d")
    except ValueError:
        base_date = datetime.utcnow()

    base_hours = 2 + (sum(ord(c) for c in origin + destination) % 10)
    base_price = 120 + (sum(ord(c) for c in origin + destination) % 350)
    if seat == "premium-economy":
        base_price = int(base_price * 1.6)
    elif seat == "business":
        base_price = int(base_price * 3.2)
    elif seat == "first":
        base_price = int(base_price * 4.8)

    offers: list[FlightOffer] = []
    for i in range(8):
        airline, code = rng.choice(_AIRLINES)
        depart_hour = rng.randint(5, 22)
        depart_min = rng.choice([0, 5, 15, 25, 35, 45, 55])
        depart_dt = base_date.replace(hour=depart_hour, minute=depart_min)
        flight_hours = base_hours + rng.randint(-1, 3)
        flight_minutes = rng.randint(0, 59)
        duration = timedelta(hours=flight_hours, minutes=flight_minutes)
        arrive_dt = depart_dt + duration

        stops = rng.choices([0, 1, 2], weights=[5, 4, 1])[0]
        if max_stops is not None:
            stops = min(stops, max_stops)
        if stops > 0:
            duration += timedelta(hours=rng.randint(1, 3))
            arrive_dt = depart_dt + duration

        price = base_price + rng.randint(-60, 200) + stops * -30
        price = max(price, 49)

        ahead = ""
        if arrive_dt.date() > depart_dt.date():
            ahead = f"+{(arrive_dt.date() - depart_dt.date()).days}"

        offers.append(
            FlightOffer(
                airline=f"{airline} {code}{rng.randint(100, 9999)}",
                departure=_format_time(depart_dt),
                arrival=_format_time(arrive_dt),
                duration=f"{int(duration.total_seconds() // 3600)} hr {int((duration.total_seconds() % 3600) // 60)} min",
                stops=stops,
                price=f"${price}",
                is_best=False,
                arrival_time_ahead=ahead,
                delay=None,
                source="mock",
            )
        )

    offers.sort(key=lambda o: int(o.price.lstrip("$").replace(",", "")))
    offers[0].is_best = True
    return offers


def _mock_search(
    origin: str,
    destination: str,
    depart_date: str,
    *,
    return_date: Optional[str],
    seat: SeatClass,
    trip: TripType,
    max_stops: Optional[int],
    reason: str,
) -> SearchResult:
    offers = _mock_offers_for_leg(origin, destination, depart_date, seat, max_stops)
    if trip == "round-trip" and return_date:
        # For UI simplicity we show outbound options; the saved plan can include
        # a separate return leg via a second search.
        pass

    cheapest = offers[0].price if offers else ""
    notice = (
        "Showing sample data — live Google Flights is unreachable from this "
        "environment. Run locally with network access for real prices."
    )
    return SearchResult(
        current_price=f"typical {cheapest}" if cheapest else "",
        flights=offers,
        source="mock",
        notice=notice,
    )
