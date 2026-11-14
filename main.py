"""Electricity Consumption and Bill Calculator - FastAPI backend.

Same logic as the original C program (slab tariff + fixed charge), now exposed
as a REST API with a SQLite database replacing bill.txt.
Run:  uvicorn main:app --reload
"""
import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

if getattr(sys, "frozen", False):  # running as a packaged .exe
    BASE_DIR = Path(sys._MEIPASS)            # bundled files (static/)
    DB_PATH = Path(sys.executable).parent / "bills.db"  # database next to the .exe
else:
    BASE_DIR = Path(__file__).parent
    DB_PATH = BASE_DIR / "bills.db"

DAYS_IN_MONTH = 30
FIXED_CHARGE = 50.0
# (from, to, rate per unit, label) - editable tariff, same as the C code
SLABS = [
    (0, 100, 3.00, "1-100"),
    (100, 200, 4.50, "101-200"),
    (200, 500, 6.00, "201-500"),
    (500, None, 8.00, "Above 500"),
]

app = FastAPI(title="Electricity Consumption and Bill Calculator")


# ---------- models (replace the scanf validation in C) ----------
class Appliance(BaseModel):
    name: str = Field(default="Appliance", max_length=60)
    watts: float = Field(gt=0, description="Power rating in watts")
    quantity: int = Field(gt=0)
    hours: float = Field(ge=0, le=24, description="Usage hours per day")


class BillRequest(BaseModel):
    appliances: List[Appliance] = Field(min_length=1)


# ---------- Module 1: units ----------
def appliance_units(a: Appliance) -> dict:
    daily = a.watts * a.quantity * a.hours / 1000.0
    return {
        "name": a.name or "Appliance",
        "daily_units": round(daily, 4),
        "monthly_units": round(daily * DAYS_IN_MONTH, 4),
    }


# ---------- Module 2: bill ----------
def slab_breakdown(units: float):
    parts, energy = [], 0.0
    for low, high, rate, label in SLABS:
        top = units if high is None else min(units, high)
        used = max(0.0, top - low)
        charge = used * rate
        energy += charge
        parts.append({"slab": label, "units": round(used, 2), "rate": rate, "charge": round(charge, 2)})
    return parts, energy


def calculate(req: BillRequest) -> dict:
    items = [appliance_units(a) for a in req.appliances]
    total_units = sum(i["monthly_units"] for i in items)
    for i in items:
        i["share_percent"] = round(i["monthly_units"] / total_units * 100, 1) if total_units else 0.0
    slabs, energy = slab_breakdown(total_units)
    return {
        "appliances": items,
        "total_units": round(total_units, 2),
        "slabs": slabs,
        "energy_charge": round(energy, 2),
        "fixed_charge": FIXED_CHARGE,
        "total_bill": round(energy + FIXED_CHARGE, 2),
    }


# ---------- database (replaces fopen/fprintf/fclose) ----------
# Local use: SQLite file (bills.db).  Online: set DATABASE_URL to a PostgreSQL
# connection string (e.g. a free Neon database) so bills are never lost.
DATABASE_URL = os.getenv("DATABASE_URL", "")
PG = DATABASE_URL.startswith("postgres")
if PG:
    import psycopg2
    import psycopg2.extras

# Online (PostgreSQL / MULTI_USER=1): each visitor only sees their own bills.
MULTI_USER = PG or os.getenv("MULTI_USER") == "1"


@contextmanager
def db():
    if PG:
        conn = psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def run(conn, sql, params=()):
    if PG:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur
    return conn.execute(sql, params)


with db() as c:
    run(
        c,
        f"""CREATE TABLE IF NOT EXISTS bills (
            id {"SERIAL" if PG else "INTEGER"} PRIMARY KEY {"" if PG else "AUTOINCREMENT"},
            saved_at TEXT NOT NULL,
            total_units DOUBLE PRECISION NOT NULL,
            energy_charge DOUBLE PRECISION NOT NULL,
            fixed_charge DOUBLE PRECISION NOT NULL,
            total_bill DOUBLE PRECISION NOT NULL,
            appliances TEXT NOT NULL,
            owner TEXT NOT NULL DEFAULT 'local'
        )""",
    )
    if not PG:  # upgrade an older local bills.db that has no owner column
        try:
            run(c, "ALTER TABLE bills ADD COLUMN owner TEXT NOT NULL DEFAULT 'local'")
        except sqlite3.OperationalError:
            pass


def row_to_dict(r) -> dict:
    d = dict(r)
    d.pop("owner", None)
    d["appliances"] = json.loads(d["appliances"])
    return d


def get_owner(request: Request, response: Response) -> str:
    """Local app: one shared owner. Online: a private id stored in a cookie."""
    if not MULTI_USER:
        return "local"
    cid = request.cookies.get("cid")
    if not cid:
        cid = uuid.uuid4().hex
        response.set_cookie("cid", cid, max_age=60 * 60 * 24 * 365, httponly=True, samesite="lax")
    return cid


# ---------- API ----------
@app.post("/api/calculate")
def api_calculate(req: BillRequest):
    """Calculate units and bill without saving."""
    return calculate(req)


@app.post("/api/bills", status_code=201)
def api_save(req: BillRequest, request: Request, response: Response):
    """Calculate on the server and save the bill."""
    owner = get_owner(request, response)
    result = calculate(req)
    with db() as c:
        row = run(
            c,
            "INSERT INTO bills (saved_at,total_units,energy_charge,fixed_charge,total_bill,appliances,owner) "
            "VALUES (?,?,?,?,?,?,?) RETURNING *",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                result["total_units"],
                result["energy_charge"],
                result["fixed_charge"],
                result["total_bill"],
                json.dumps([a.model_dump() for a in req.appliances]),
                owner,
            ),
        ).fetchone()
    return row_to_dict(row)


@app.get("/api/bills")
def api_list(request: Request, response: Response):
    owner = get_owner(request, response)
    with db() as c:
        rows = run(c, "SELECT * FROM bills WHERE owner=? ORDER BY id DESC", (owner,)).fetchall()
    return [row_to_dict(r) for r in rows]


@app.get("/api/bills/export", response_class=PlainTextResponse)
def api_export(request: Request, response: Response):
    """All bills in the same line format the C program wrote to bill.txt."""
    owner = get_owner(request, response)
    with db() as c:
        rows = run(c, "SELECT * FROM bills WHERE owner=? ORDER BY id", (owner,)).fetchall()
    text = "".join(
        f"Units: {r['total_units']:.2f} | Energy: Rs. {r['energy_charge']:.2f} | "
        f"Fixed: Rs. {r['fixed_charge']:.2f} | Total: Rs. {r['total_bill']:.2f}\n"
        for r in rows
    )
    return PlainTextResponse(text, headers={"Content-Disposition": 'attachment; filename="bill.txt"'})


@app.delete("/api/bills/{bill_id}", status_code=204)
def api_delete(bill_id: int, request: Request, response: Response):
    owner = get_owner(request, response)
    with db() as c:
        cur = run(c, "DELETE FROM bills WHERE id=? AND owner=?", (bill_id, owner))
        if cur.rowcount == 0:
            raise HTTPException(404, "Bill not found")


@app.delete("/api/bills", status_code=204)
def api_clear(request: Request, response: Response):
    owner = get_owner(request, response)
    with db() as c:
        run(c, "DELETE FROM bills WHERE owner=?", (owner,))


@app.get("/api/tariff")
def api_tariff():
    return {
        "days_in_month": DAYS_IN_MONTH,
        "fixed_charge": FIXED_CHARGE,
        "slabs": [{"from": s[0], "to": s[1], "rate": s[2], "label": s[3]} for s in SLABS],
    }


# ---------- frontend ----------
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")
