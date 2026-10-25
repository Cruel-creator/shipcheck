"""Carrier recommendation: filter by route + pallet weight, then rank by seller priority."""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional

from .models import Booking, gbp
from .reference import CARRIER_OPTIONS, BALANCED_WEIGHTS


def add_working_days(start: date, days: int) -> date:
    """Collection on the ready date (or next weekday), then N working days in transit."""
    d = start
    while d.weekday() >= 5:
        d += timedelta(days=1)
    added = 0
    while added < days:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


def collection_day(start: date) -> date:
    d = start
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def route_options(dest_country: Optional[str]) -> list[dict]:
    return [c for c in CARRIER_OPTIONS
            if c["origin_country"] == "United Kingdom" and c["dest_country"] == dest_country]


def _rank(options: list[dict], priority: str) -> list[dict]:
    """Return options sorted best-first for the priority, each annotated with a score + reason."""
    if not options:
        return []
    if priority == "Fastest":
        key = lambda o: (o["transit_days"], o["cost"], -o["on_time"])
    elif priority == "Most reliable":
        key = lambda o: (-o["on_time"], o["cost"], o["transit_days"])
    elif priority == "Balanced":
        costs = [o["cost"] for o in options]
        days = [o["transit_days"] for o in options]
        ots = [o["on_time"] for o in options]

        def norm(v, lo, hi, higher_better):
            if hi == lo:
                return 1.0
            x = (v - lo) / (hi - lo)
            return x if higher_better else 1 - x

        for o in options:
            o["score"] = round(
                BALANCED_WEIGHTS["cost"] * norm(o["cost"], min(costs), max(costs), False)
                + BALANCED_WEIGHTS["speed"] * norm(o["transit_days"], min(days), max(days), False)
                + BALANCED_WEIGHTS["reliability"] * norm(o["on_time"], min(ots), max(ots), True), 3)
        key = lambda o: (-o["score"], o["cost"])
    else:  # Cheapest (default)
        key = lambda o: (o["cost"], -o["on_time"], o["transit_days"])
    return sorted(options, key=key)


def recommend(b: Booking, today: Optional[date] = None) -> dict:
    """Returns a dict describing the recommendation, all options, exclusions and reasoning."""
    out = {"ok": False, "options": [], "excluded": [], "chosen": None, "reason": "",
           "alternative": None, "repallet": None, "weight_per_pallet": None}
    opts = route_options(b.dest_country)
    if not opts:
        out["reason"] = "Destination country is missing or not served, so no carrier can be matched yet."
        return out
    priority = b.priority or "Balanced"
    pallets = b.pallets or 0
    wpp = (b.gross_weight / pallets) if (b.gross_weight and pallets) else None
    out["weight_per_pallet"] = wpp

    start = b.ready_date
    if start and today and start < today:
        start = today  # a past ready date can't be collected in the past; plan from today
    out["collection"] = collection_day(start) if start else None
    enriched = []
    for c in opts:
        o = dict(c)
        o["cost"] = round(c["price_per_pallet"] * pallets, 2) if pallets else None
        o["eta"] = add_working_days(start, c["transit_days"]) if start else None
        o["fits_weight"] = (wpp is None) or (wpp <= c["max_kg_per_pallet"] + 1e-9)
        enriched.append(o)
    out["options"] = enriched

    if not pallets:
        out["reason"] = "Number of pallets is missing, so cost can't be calculated yet."
        return out

    eligible = [o for o in enriched if o["fits_weight"]]
    out["excluded"] = [o for o in enriched if not o["fits_weight"]]
    ideal = _rank([dict(o) for o in enriched], priority)[0]
    out["ideal"] = ideal

    if not eligible:
        # No carrier accepts pallets this heavy -> propose re-palletising.
        need = {o["carrier"]: math.ceil(b.gross_weight / o["max_kg_per_pallet"]) for o in enriched}
        alt = Booking(**{**b.__dict__, "pallets": float(min(need.values()))})
        alt_rec = recommend(alt, today) if alt.pallets != b.pallets else None
        out["repallet"] = {"pallets_needed": need, "if_repalletised": alt_rec}
        out["reason"] = (f"At {wpp:,.0f} kg per pallet, every carrier on this route is over its pallet "
                         f"weight limit. The shipment needs to be split over more pallets first.")
        return out

    ranked = _rank([dict(o) for o in eligible], priority)
    chosen = ranked[0]
    out.update(ok=True, chosen=chosen, ranked=ranked,
               alternative=ranked[1] if len(ranked) > 1 else None)

    why = {
        "Cheapest": f"it is the lowest-cost option ({gbp(chosen['cost'])} for {pallets:g} pallet(s))",
        "Fastest": f"it has the shortest transit time ({chosen['transit_days']} working days)",
        "Most reliable": f"it has the highest on-time rate ({chosen['on_time']}%)",
        "Balanced": (f"it has the best combined score ({chosen.get('score')}) when cost, speed and "
                     f"reliability are weighted 40/30/30"),
    }[priority]
    reason = f"Your priority is **{priority}**, and {chosen['carrier']} · {chosen['service']} fits best because {why}."
    if ideal["carrier"] != chosen["carrier"]:
        need = math.ceil(b.gross_weight / ideal["max_kg_per_pallet"])
        reason += (f" {ideal['carrier']} would otherwise have been the pick, but its limit is "
                   f"{ideal['max_kg_per_pallet']} kg per pallet and yours weigh {wpp:,.0f} kg. "
                   f"Spreading the load over {need} pallets would make it eligible.")
    alt = out["alternative"]
    if alt:
        dc = (alt["cost"] or 0) - (chosen["cost"] or 0)
        dd = alt["transit_days"] - chosen["transit_days"]
        bits = []
        if dc:
            bits.append(f"{'+' if dc > 0 else '−'}{gbp(abs(dc))}")
        if dd:
            bits.append(f"{'+' if dd > 0 else '−'}{abs(dd)} day(s)")
        if alt["on_time"] != chosen["on_time"]:
            bits.append(f"{alt['on_time']}% on-time")
        reason += f" Runner-up: {alt['carrier']} · {alt['service']} ({', '.join(bits) or 'similar'})."
    out["reason"] = reason
    return out
