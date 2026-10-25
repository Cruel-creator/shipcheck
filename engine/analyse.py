"""One call that turns a Booking into: findings, status, carrier recommendation, confirmation."""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from .carriers import recommend, route_options, collection_day
from .checks import run_checks, status_of, item_value, item_net_weight
from .models import Booking, fmt_date, fmt_num, gbp


def today_ist() -> date:
    return datetime.now(ZoneInfo("Asia/Kolkata")).date()


def analyse(b: Booking, today: date | None = None) -> dict:
    today = today or today_ist()
    rec = recommend(b, today)
    chosen = rec.get("chosen")
    findings = run_checks(b, chosen, today, weight_limits=route_options(b.dest_country) if not chosen else None,
                          preferred=rec.get("ideal"))
    status = status_of(findings)
    return {"booking": b, "findings": findings, "status": status, "rec": rec,
            "confirmation": confirmation(b, findings, status, rec, today)}


STATUS_LABEL = {
    "Red": "On hold: must be fixed before it ships",
    "Amber": "Can be booked, but check the warnings first",
    "Green": "Ready to book",
}


def confirmation(b: Booking, findings, status, rec, today) -> str:
    reds = [f for f in findings if f.severity == "Red"]
    ambers = [f for f in findings if f.severity == "Amber"]
    c = rec.get("chosen")
    lines = []
    route = f"{b.origin_city or '?'} (UK) → {b.dest_city or '?'}, {b.dest_country or '?'} ({(b.dest_type or '?').lower()})"
    lines.append(f"**Booking {b.booking_id or '(new)'}{' for ' + b.seller_name if b.seller_name else ''}**: "
                 f"{fmt_num(b.pallets)} pallet(s), {fmt_num(b.cartons)} cartons, {len(b.items)} product line(s), "
                 f"{route}. Declared value {gbp(b.declared_value)}, gross weight {fmt_num(b.gross_weight)} kg.")
    if c:
        coll = rec.get("collection")
        lines.append(f"**Carrier:** {c['carrier']} · {c['service']}. Price {gbp(c['cost'])} "
                     f"({fmt_num(b.pallets)} × {gbp(c['price_per_pallet'])}/pallet). Collection "
                     f"{fmt_date(coll) or 'TBC'}. Estimated delivery **{fmt_date(c['eta']) or 'TBC'}** "
                     f"({c['transit_days']} working days, {c['on_time']}% on time).")
    elif rec.get("repallet") and rec["repallet"].get("if_repalletised", {}).get("chosen"):
        alt = rec["repallet"]["if_repalletised"]["chosen"]
        n = min(rec["repallet"]["pallets_needed"].values())
        lines.append(f"**Carrier:** none can take pallets this heavy. If you spread the load over **{n} pallets**, "
                     f"we'd book {alt['carrier']} · {alt['service']} for {gbp(alt['cost'])}, with estimated delivery "
                     f"{fmt_date(alt['eta']) or 'TBC'}.")
    lines.append(f"**Status: {STATUS_LABEL[status]}.**")

    nxt = []
    if reds:
        nxt.append(f"Fix the {len(reds)} red issue(s) listed in the checks. We won't send this to the carrier until they are fixed, "
                   f"because each one can get the shipment held at customs or refused at the warehouse.")
    if ambers:
        nxt.append(f"Review the {len(ambers)} amber warning(s) in the checks. You can go ahead, but they are common causes of delays.")
    if c and not reds:
        nxt.append(f"We send the booking to {c['carrier']} and email you a collection confirmation for "
                   f"{fmt_date(rec.get('collection')) or 'your ready date'}.")
    nxt.append("We create the commercial invoice from your item lines (description, HS code, quantity, value, "
               "origin) to go with the goods. Print it and attach a copy to the shipment.")
    if b.dest_type == "Warehouse":
        if b.appointment:
            nxt.append("Your delivery appointment is booked. Label every carton with the booking ID and carton "
                       "number (e.g. 1 of N) so the warehouse can check the count on arrival.")
        else:
            eta = fmt_date(c["eta"]) if c else "the delivery date"
            nxt.append(f"Book a delivery slot at the receiving warehouse for {eta}.")
    nxt.append("You'll get tracking updates at collection, at the UK/EU border (customs clearance) and on delivery.")
    lines.append("**What happens next:**\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(nxt)))
    return "\n\n".join(lines)
