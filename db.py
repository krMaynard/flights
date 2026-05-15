"""SQLite-backed storage for trip plans."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path(__file__).parent / "flights.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    traveler TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS leg (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plan(id) ON DELETE CASCADE,
    order_idx INTEGER NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    depart_date TEXT NOT NULL,
    airline TEXT NOT NULL,
    departure TEXT NOT NULL,
    arrival TEXT NOT NULL,
    duration TEXT,
    stops INTEGER NOT NULL DEFAULT 0,
    price TEXT,
    seat TEXT,
    source TEXT,
    raw_json TEXT
);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def list_plans() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(
            conn.execute(
                """
                SELECT plan.*,
                       (SELECT COUNT(*) FROM leg WHERE leg.plan_id = plan.id) AS leg_count,
                       (SELECT MIN(depart_date) FROM leg WHERE leg.plan_id = plan.id) AS first_date
                FROM plan
                ORDER BY datetime(plan.created_at) DESC
                """
            )
        )


def create_plan(name: str, traveler: Optional[str], notes: Optional[str]) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO plan (name, traveler, notes, created_at) VALUES (?, ?, ?, ?)",
            (name, traveler or None, notes or None, datetime.utcnow().isoformat(timespec="seconds")),
        )
        return int(cur.lastrowid)


def get_plan(plan_id: int) -> Optional[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM plan WHERE id = ?", (plan_id,)).fetchone()


def delete_plan(plan_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM plan WHERE id = ?", (plan_id,))


def update_plan(plan_id: int, name: str, traveler: Optional[str], notes: Optional[str]) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE plan SET name = ?, traveler = ?, notes = ? WHERE id = ?",
            (name, traveler or None, notes or None, plan_id),
        )


def list_legs(plan_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return list(
            conn.execute(
                "SELECT * FROM leg WHERE plan_id = ? ORDER BY order_idx ASC, id ASC",
                (plan_id,),
            )
        )


def add_leg(plan_id: int, *, origin: str, destination: str, depart_date: str,
            airline: str, departure: str, arrival: str, duration: str,
            stops: int, price: str, seat: str, source: str, raw: dict) -> int:
    with get_conn() as conn:
        next_idx = conn.execute(
            "SELECT COALESCE(MAX(order_idx), -1) + 1 FROM leg WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """
            INSERT INTO leg (
                plan_id, order_idx, origin, destination, depart_date,
                airline, departure, arrival, duration, stops, price,
                seat, source, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id, next_idx, origin, destination, depart_date,
                airline, departure, arrival, duration, stops, price,
                seat, source, json.dumps(raw),
            ),
        )
        return int(cur.lastrowid)


def delete_leg(leg_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM leg WHERE id = ?", (leg_id,))


def plan_totals(plan_id: int) -> dict:
    legs = list_legs(plan_id)
    total_cents = 0
    has_price = False
    for leg in legs:
        price = (leg["price"] or "").strip()
        digits = "".join(ch for ch in price if ch.isdigit() or ch == ".")
        if digits:
            try:
                total_cents += int(round(float(digits) * 100))
                has_price = True
            except ValueError:
                pass
    return {
        "leg_count": len(legs),
        "total_price": f"${total_cents / 100:,.2f}" if has_price else None,
    }
