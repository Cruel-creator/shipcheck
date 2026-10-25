"""Conversational booking.

Each user turn:
  1) LLM -> JSON patch of what the seller just said (never decides pass/fail)
  2) code applies patch, fills in derivable values, computes what is still missing
  3) code re-runs every rule + carrier ranking (same engine as file upload)
  4) LLM writes the reply from those facts (deterministic fallback if the call fails)
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict
from datetime import date

from . import llm
from .analyse import analyse
from .models import (Booking, Item, to_num, to_text, to_hs, to_date, to_bool, norm_dest_type, norm_priority,
                     norm_city, norm_country, dest_country_for, fmt_date, fmt_num, gbp)
from .reference import ORIGIN_CITIES, DEST_CITIES, DEST_TYPES, PRIORITIES, ITEM_ORIGINS

BOOKING_FIELDS = {
    "seller_name": "seller / business name",
    "origin_city": "collection city",
    "dest_city": "destination city",
    "dest_type": "destination type (warehouse or business address)",
    "ready_date": "date the goods are ready for collection",
    "priority": "what matters most (cheapest, fastest, most reliable or balanced)",
    "pallets": "number of pallets",
    "gross_weight": "total gross weight incl. packaging and pallets (kg)",
    "appointment": "whether a delivery slot is booked at the warehouse",
    "cartons": "total cartons",
    "declared_value": "total declared value (GBP)",
}
ITEM_FIELDS = {
    "description": "product description",
    "quantity": "number of units",
    "unit_price": "price per unit (GBP)",
    "units_per_carton": "units per carton",
    "cartons": "number of cartons",
    "unit_weight": "weight of one unit (kg)",
    "origin_country": "country where it was made",
    "hs_code": "HS code (6+ digits)",
}


def new_state() -> dict:
    return {"booking": Booking(booking_id=f"CHAT-{random.randint(1000, 9999)}"),
            "declined": [],          # fields the seller said they don't know -> stop asking, rules will flag
            "derived": [],           # fields we calculated
            "changelog": [],         # [(turn, text)]
            "messages": [],          # chat transcript
            "turn": 0}


# ------------------------------------------------------------- extraction
EXTRACT_SYSTEM = """You turn a UK seller's chat messages into structured shipment-booking updates.
Today is {today} (DD-MM-YYYY). All shipments go from the United Kingdom to Germany, France or the Netherlands.

Allowed values:
- origin_city: {origins}
- dest_city: {dests}
- dest_type: Warehouse | Business address  (Amazon FC / fulfilment / distribution centre = Warehouse; shop/office/store = Business address)
- priority: Cheapest | Fastest | Most reliable | Balanced
- item origin_country: {item_origins}
- appointment: true/false (delivery time slot booked at the receiving warehouse)
- money is GBP; weights in kg (convert g/tonnes/lb to kg); dates as DD-MM-YYYY (resolve "next Friday" etc. from today)

CURRENT BOOKING STATE (items have a "ref" you must reuse to edit them):
{state}

The assistant's last message was: {last_q}

Return ONLY a JSON object:
{{
 "booking": {{ <only booking fields the user stated or changed in THIS message> }},
 "items": [ {{"ref": "<existing ref or null for a new product>", "action": "upsert" | "remove", <only item fields stated>}} ],
 "declined": [ "<field names the user says they don't know / can't provide, e.g. hs_code>" ],
 "unclear": "<short note if something was ambiguous, else empty>"
}}
Booking field names: seller_name, origin_city, dest_city, dest_type, ready_date, priority, pallets, cartons,
declared_value, gross_weight, appointment.
Item field names: sku, description, hs_code, quantity, unit_price, units_per_carton, cartons, unit_weight, origin_country.

Rules:
- Record numbers exactly as the seller states them. Do NOT fix or recompute the seller's numbers; the app checks them.
- Relative edits use the current state: "add a pallet" with pallets=3 -> pallets 4; "two more cartons of mugs" -> that item's cartons + 2.
- If the seller states a per-item carton count, put it on the item; a shipment-wide total goes in booking.cartons.
- Short answers ("yes", "Leeds", "500") answer the assistant's last question.
- If a value is not in an allowed list, map it to the closest allowed one only if it is clearly the same (e.g. "Amazon warehouse" -> Warehouse). Otherwise pass it through as written.
- Never invent values that were not stated."""


def _state_json(st):
    b: Booking = st["booking"]
    d = b.to_dict()
    d.pop("items")
    d["items"] = [{"ref": f"ITEM-{i + 1}", **{k: v for k, v in asdict(it).items() if k != "booking_id"}}
                  for i, it in enumerate(b.items)]
    return json.dumps(d, default=str)


def extract(st, user_msg: str, today: date) -> dict:
    last_q = next((m["content"] for m in reversed(st["messages"]) if m["role"] == "assistant"), "(none)")
    system = EXTRACT_SYSTEM.format(today=fmt_date(today), origins=", ".join(ORIGIN_CITIES),
                                   dests=", ".join(f"{c} ({k})" for c, k in DEST_CITIES.items()),
                                   item_origins=", ".join(ITEM_ORIGINS), state=_state_json(st),
                                   last_q=last_q[:800])
    return llm.complete_json(system, [{"role": "user", "content": user_msg}])


# ------------------------------------------------------------- apply patch
_BOOKING_NORM = {
    "seller_name": to_text, "origin_city": lambda v: norm_city(v, ORIGIN_CITIES),
    "dest_city": lambda v: norm_city(v, list(DEST_CITIES)), "dest_type": norm_dest_type,
    "ready_date": to_date, "priority": norm_priority, "pallets": to_num, "cartons": to_num,
    "declared_value": to_num, "gross_weight": to_num, "appointment": to_bool,
}
_ITEM_NORM = {
    "sku": to_text, "description": to_text, "hs_code": to_hs, "quantity": to_num, "unit_price": to_num,
    "units_per_carton": to_num, "cartons": to_num, "unit_weight": to_num, "origin_country": norm_country,
}


def _show(v):
    if isinstance(v, date):
        return fmt_date(v)
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        return fmt_num(v)
    return "—" if v in (None, "") else str(v)


def apply_patch(st, patch: dict) -> list[str]:
    b: Booking = st["booking"]
    changes = []
    for k, v in (patch.get("booking") or {}).items():
        if k not in _BOOKING_NORM or v is None:
            continue
        nv = _BOOKING_NORM[k](v)
        if nv is None:
            continue
        old = getattr(b, k)
        if old != nv:
            setattr(b, k, nv)
            if k in st["derived"]:
                st["derived"].remove(k)
            changes.append(f"{k.replace('_', ' ')}: {_show(old)} → {_show(nv)}")
    for ip in patch.get("items") or []:
        ref = ip.get("ref")
        idx = None
        if isinstance(ref, str) and ref.upper().startswith("ITEM-"):
            try:
                idx = int(ref.split("-")[1]) - 1
            except ValueError:
                idx = None
            if idx is not None and not (0 <= idx < len(b.items)):
                idx = None
        if ip.get("action") == "remove":
            if idx is not None:
                gone = b.items.pop(idx)
                changes.append(f"removed item {gone.sku or gone.description}")
            continue
        if idx is None:
            b.items.append(Item(booking_id=b.booking_id))
            idx = len(b.items) - 1
            changes.append(f"added item {ip.get('description') or ip.get('sku') or idx + 1}")
        it = b.items[idx]
        for k, v in ip.items():
            if k not in _ITEM_NORM or v is None:
                continue
            nv = _ITEM_NORM[k](v)
            if nv is None:
                continue
            old = getattr(it, k)
            if old != nv:
                setattr(it, k, nv)
                tag = f"ITEM-{idx + 1}.{k}"
                if tag in st["derived"]:
                    st["derived"].remove(tag)
                changes.append(f"{it.sku or it.description or f'item {idx + 1}'} {k.replace('_', ' ')}: "
                               f"{_show(old)} → {_show(nv)}")
    for f in patch.get("declined") or []:
        if f not in st["declined"]:
            st["declined"].append(f)
    derive(st)
    return changes


def derive(st):
    """Fill in values that follow logically from others (marked as 'calculated' in the UI)."""
    b: Booking = st["booking"]
    D = st["derived"]
    if b.dest_city in DEST_CITIES and DEST_CITIES[b.dest_city] != b.dest_country:
        b.dest_country = DEST_CITIES[b.dest_city]
    b.origin_country, b.currency = "United Kingdom", "GBP"
    if b.dest_type == "Business address" and b.appointment is None:
        b.appointment = False
        if "appointment" not in D:
            D.append("appointment")
    for i, it in enumerate(b.items):
        it.booking_id = b.booking_id
        if not it.sku:
            it.sku = f"ITEM-{i + 1}"
        tc, tu, tq = (f"ITEM-{i + 1}.{k}" for k in ("cartons", "units_per_carton", "quantity"))
        q, u, c = it.quantity, it.units_per_carton, it.cartons
        if (c is None or tc in D) and q and u and tu not in D and (q / u).is_integer():
            it.cartons = q / u
            D.append(tc) if tc not in D else None
        elif (u is None or tu in D) and q and c and tc not in D and (q / c).is_integer():
            it.units_per_carton = q / c
            D.append(tu) if tu not in D else None
        elif (q is None or tq in D) and u and c and tc not in D and tu not in D:
            it.quantity = u * c
            D.append(tq) if tq not in D else None
    if b.items and all(it.cartons is not None for it in b.items):
        tot = sum(it.cartons for it in b.items)
        if b.cartons is None or ("cartons" in D and b.cartons != tot):
            b.cartons = tot
            if "cartons" not in D:
                D.append("cartons")
    if b.items and all(it.quantity is not None and it.unit_price is not None for it in b.items):
        tot = round(sum(it.quantity * it.unit_price for it in b.items), 2)
        if b.declared_value is None or ("declared_value" in D and b.declared_value != tot):
            b.declared_value = tot
            if "declared_value" not in D:
                D.append("declared_value")


def missing_fields(st) -> list[str]:
    """Human-readable list of what still needs asking, in a natural order."""
    b: Booking = st["booking"]
    dec = set(st["declined"])
    out = []
    for k in ["origin_city", "dest_city", "dest_type"]:
        if getattr(b, k) in (None, "") and k not in dec:
            out.append(BOOKING_FIELDS[k])
    if not b.items:
        out.append("what you're shipping (product, units, price per unit)")
    for i, it in enumerate(b.items):
        name = it.description or it.sku or f"item {i + 1}"
        need = []
        for k in ["description", "quantity", "unit_price", "units_per_carton", "unit_weight", "origin_country",
                  "hs_code"]:
            if getattr(it, k) in (None, "") and k not in dec and f"ITEM-{i + 1}.{k}" not in dec:
                if k == "units_per_carton" and it.cartons is not None:
                    continue
                need.append(ITEM_FIELDS[k])
        if need:
            out.append(f"for {name}: " + ", ".join(need))
    for k in ["pallets", "gross_weight", "ready_date", "priority"]:
        if getattr(b, k) in (None, "") and k not in dec:
            out.append(BOOKING_FIELDS[k])
    if b.dest_type == "Warehouse" and b.appointment is None and "appointment" not in dec:
        out.append(BOOKING_FIELDS["appointment"])
    if not b.seller_name and "seller_name" not in dec:
        out.append(BOOKING_FIELDS["seller_name"])
    return out


# ------------------------------------------------------------- reply
REPLY_SYSTEM = """You are a friendly, efficient freight booking assistant for UK sellers shipping to the EU.
Write the next chat message to the seller. Use ONLY the facts below; never invent numbers, carriers or prices.

FACTS (computed by the booking engine, which is always right):
{facts}

How to write it:
- If something changed this turn, confirm it in one short line (e.g. "Updated: 4 pallets").
- If fields are still missing: ask for the next 2-4 of them, grouped naturally, as short numbered questions.
  Do not ask for anything not in the missing list. If an HS code is missing, offer a likely 6-digit code based on
  the description as a suggestion for them to confirm (say it's a suggestion).
- If nothing is missing: give the result. Status, then each red/amber issue in one line with the fix,
  then the recommended carrier with the reason, then "What happens next" in 2-3 bullets.
  Keep it short; the side panel shows the full details.
- If issues exist mid-conversation, mention new red issues briefly as soon as they appear.
- Plain English, no jargon without a 3-word explanation, under 170 words, markdown allowed."""


def facts(st, res, changes) -> str:
    b = st["booking"]
    miss = missing_fields(st)
    rec = res["rec"]
    c = rec.get("chosen")
    lines = [f"Changes this turn: {'; '.join(changes) or 'none'}",
             f"Calculated by the app (tell the seller if relevant): {', '.join(st['derived']) or 'none'}",
             f"Still missing (ask for these): {miss or 'NOTHING, booking complete'}",
             f"Seller can't provide: {st['declined'] or 'none'}",
             f"Overall status: {res['status']}"]
    for f in res["findings"]:
        if f.rule_id == "DATA" and miss:
            continue
        lines.append(f"- {f.severity} {f.rule_id}: {f.problem} FIX: {f.fix}")
    if c:
        lines.append(f"Recommended carrier: {c['carrier']} {c['service']}, cost {gbp(c['cost'])}, "
                     f"{c['transit_days']} working days, {c['on_time']}% on time, ETA {fmt_date(c['eta'])}. "
                     f"Reason: {rec['reason']}")
    elif rec.get("reason"):
        lines.append(f"Carrier: {rec['reason']}")
    lines.append(f"Booking so far: {_state_json(st)}")
    return "\n".join(lines)


def fallback_reply(st, res, changes) -> str:
    miss = missing_fields(st)
    parts = []
    if changes:
        parts.append("Updated: " + "; ".join(changes[:4]) + ".")
    if miss:
        parts.append("To finish the booking I need:\n" + "\n".join(f"{i + 1}. {m}" for i, m in enumerate(miss[:4])))
    else:
        for f in res["findings"]:
            if f.severity in ("Red", "Amber"):
                parts.append(f"**{f.severity} · {f.rule_id}**: {f.problem} *Fix:* {f.fix}")
        if res["rec"].get("reason"):
            parts.append(res["rec"]["reason"])
        parts.append(res["confirmation"])
    return "\n\n".join(parts)


def visible_findings(st, findings):
    """While details are still being collected, hide 'missing' findings we simply haven't asked about yet."""
    if not missing_fields(st):
        return findings
    dec = set(st["declined"])
    out = []
    for f in findings:
        if f.rule_id == "DATA":
            continue
        if f.rule_id == "R-01" and "has no HS code" in f.problem and "hs_code" not in dec:
            continue
        if f.rule_id == "R-09" and "origin_country" not in dec:
            continue
        out.append(f)
    return out


def turn(st, user_msg: str, today: date) -> tuple[str, dict]:
    st["turn"] += 1
    st["messages"].append({"role": "user", "content": user_msg})
    patch = extract(st, user_msg, today)
    changes = apply_patch(st, patch)
    for c in changes:
        st["changelog"].append((st["turn"], c))
    res = analyse(st["booking"], today)
    try:
        hist = st["messages"][-8:]
        while hist and hist[0]["role"] != "user":
            hist = hist[1:]
        reply = llm.complete(REPLY_SYSTEM.format(facts=facts(st, res, changes)), hist, max_tokens=700).strip()
    except Exception:
        reply = fallback_reply(st, res, changes)
    st["messages"].append({"role": "assistant", "content": reply})
    return reply, res
