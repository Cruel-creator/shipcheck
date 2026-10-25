"""Booking / Item data model plus tolerant value normalisers."""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from typing import Optional

from .reference import DEST_CITIES, DEST_TYPES, PRIORITIES, ORIGIN_CITIES, ITEM_ORIGINS


@dataclass
class Item:
    booking_id: str = ""
    sku: str = ""
    description: str = ""
    hs_code: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    units_per_carton: Optional[float] = None
    cartons: Optional[float] = None
    unit_weight: Optional[float] = None
    origin_country: Optional[str] = None


@dataclass
class Booking:
    booking_id: str = ""
    seller_name: Optional[str] = None
    origin_city: Optional[str] = None
    origin_country: Optional[str] = "United Kingdom"
    dest_city: Optional[str] = None
    dest_country: Optional[str] = None
    dest_type: Optional[str] = None
    ready_date: Optional[date] = None
    priority: Optional[str] = None
    pallets: Optional[float] = None
    cartons: Optional[float] = None
    declared_value: Optional[float] = None
    currency: str = "GBP"
    gross_weight: Optional[float] = None
    appointment: Optional[bool] = None
    items: list[Item] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ready_date"] = fmt_date(self.ready_date)
        return d


# ---------------------------------------------------------------- normalisers
def is_blank(v) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    return isinstance(v, str) and v.strip() == ""


def to_num(v) -> Optional[float]:
    """'£5,400.00' -> 5400.0 ; blanks -> None ; junk -> None"""
    if is_blank(v):
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.\-]", "", str(v).replace(",", ""))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def to_text(v) -> Optional[str]:
    if is_blank(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def to_hs(v) -> Optional[str]:
    """Keep only digits. 691200.0 -> '691200'; '6912.00' -> '691200'; blank -> None."""
    if is_blank(v):
        return None
    if isinstance(v, float):
        v = str(int(v)) if v.is_integer() else str(v)
    digits = re.sub(r"\D", "", str(v))
    return digits or None


def to_date(v) -> Optional[date]:
    """Day-first parsing. Accepts datetime, Excel serials and DD-MM-YYYY style text."""
    if is_blank(v):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:  # Excel serial
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).date()
    s = str(v).strip().split(" ")[0]
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", s)  # ISO: year first
    if m:
        y, mo, d = map(int, m.groups())
        return _safe_date(y, mo, d)
    m = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$", s)  # DD-MM-YYYY
    if m:
        d, mo, y = map(int, m.groups())
        if y < 100:
            y += 2000
        return _safe_date(y, mo, d)
    return None


def _safe_date(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None


def to_bool(v) -> Optional[bool]:
    if is_blank(v):
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("yes", "y", "true", "1", "booked"):
        return True
    if s in ("no", "n", "false", "0", "not booked"):
        return False
    return None


def _match(v, options) -> Optional[str]:
    t = to_text(v)
    if t is None:
        return None
    for o in options:
        if t.lower() == o.lower():
            return o
    return t  # keep what the seller wrote; validation will surface it


def norm_dest_type(v):
    t = to_text(v)
    if t and "ware" in t.lower():
        return "Warehouse"
    if t and ("business" in t.lower() or "address" in t.lower()):
        return "Business address"
    return _match(v, DEST_TYPES)


def norm_priority(v):
    t = (to_text(v) or "").lower()
    if not t:
        return None
    if "cheap" in t or "cost" in t:
        return "Cheapest"
    if "fast" in t or "quick" in t or "speed" in t:
        return "Fastest"
    if "reliab" in t or "on-time" in t or "on time" in t:
        return "Most reliable"
    if "balanc" in t:
        return "Balanced"
    return _match(v, PRIORITIES)


def norm_city(v, options):
    return _match(v, options)


def norm_country(v, options=ITEM_ORIGINS):
    t = to_text(v)
    if t and t.lower() in ("uk", "u.k.", "great britain", "gb", "england", "britain"):
        return "United Kingdom"
    return _match(v, options)


def dest_country_for(city: Optional[str]) -> Optional[str]:
    return DEST_CITIES.get(city or "")


def fmt_date(d: Optional[date]) -> Optional[str]:
    return d.strftime("%d-%m-%Y") if d else None


def fmt_num(x, dp=2) -> str:
    if x is None:
        return "—"
    if float(x).is_integer():
        return f"{int(x):,}"
    return f"{x:,.{dp}f}"


def gbp(x) -> str:
    return "—" if x is None else f"£{x:,.2f}"
