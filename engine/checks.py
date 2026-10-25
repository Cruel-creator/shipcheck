"""Deterministic rulebook checks (R-01 … R-10) with plain-English problem + fix text."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .models import Booking, Item, fmt_date, fmt_num, gbp
from .reference import RULES, ORIGIN_CITIES, DEST_CITIES, DEST_TYPES, PRIORITIES, ITEM_ORIGINS


@dataclass
class Finding:
    rule_id: str           # "R-01" … or "DATA" for missing / unreadable input
    severity: str          # "Red" | "Amber" | "Info"
    problem: str
    fix: str
    sku: Optional[str] = None

    @property
    def rule_text(self):
        return RULES.get(self.rule_id, ("Data completeness", ""))[0]


# ------------------------------------------------------- dangerous goods (R-06)
NEGATIONS = [
    r"non[- ]?aerosol", r"battery[- ]?free", r"no batter(y|ies)", r"without batter(y|ies)",
    r"batter(y|ies) not included", r"alcohol[- ]?free", r"non[- ]?flammable", r"not flammable",
    r"solvent[- ]?free", r"lithium[- ]?free", r"alkaline batter(y|ies)", r"zinc[- ]carbon batter(y|ies)",
    r"ni[- ]?mh batter(y|ies)", r"solid (perfume|cologne)", r"(pump|trigger)[- ]spray",
]
# A device name only means "has a battery" when the line is the device itself, not an accessory
# for it: "laptop sleeve", "phone case", "smartwatch strap", "bike lock", "whisky glass".
ACCESSORY = (r"(?!\W+(\w+\W+)?(case|cases|cover|covers|sleeve|sleeves|bag|bags|backpack|stand|stands|"
             r"strap|straps|band|bands|holder|holders|mount|mounts|protector|protectors|skin|skins|cable|"
             r"cables|lead|leads|charger|chargers|adapter|adapters|dock|docks|lock|locks|helmet|helmets|"
             r"rack|racks|bell|bells|basket|baskets|head|heads|refill|refills|glass|glasses|tumbler|"
             r"tumblers|decanter|decanters|stones)\b)")
DG_TERMS = {
    "lithium battery": [r"lithium", r"\bli[- ]?ion\b", r"\bli[- ]?po\b", r"\blipo\b", r"power ?bank" + ACCESSORY,
                        r"rechargeable", r"cordless" + ACCESSORY, r"\be[- ]?cig" + ACCESSORY, r"\bvape",
                        r"\be[- ]?bikes?\b" + ACCESSORY, r"electric scooters?\b" + ACCESSORY,
                        r"\be[- ]?scooters?\b" + ACCESSORY, r"smart ?watch(es)?\b" + ACCESSORY,
                        r"smartphones?\b" + ACCESSORY, r"mobile phones?\b" + ACCESSORY, r"\blaptops?\b" + ACCESSORY,
                        r"\btablet (pc|computer)s?\b" + ACCESSORY,
                        r"wireless (earbuds|headphones)\b" + ACCESSORY,
                        r"bluetooth (speaker|headphones|earbuds)\b" + ACCESSORY, r"\bair ?pods\b" + ACCESSORY,
                        r"\bdrones?\b" + ACCESSORY, r"\bhoverboards?\b" + ACCESSORY,
                        r"electric toothbrush(es)?\b" + ACCESSORY, r"portable chargers?\b",
                        r"battery pack", r"button cell", r"\bcr2032\b", r"\b18650\b", r"\d\s*mah\b",
                        r"\bbatter(y|ies)\b" + ACCESSORY],
    "aerosol": [r"aerosol", r"spray can", r"spray paint", r"hair ?spray", r"deodorant spray",
                r"body spray", r"spray deodorant", r"air freshener spray", r"pressuri[sz]ed",
                r"compressed gas", r"dry shampoo", r"shaving foam", r"whipped cream charger",
                r"\bbutane\b", r"\bpropane\b", r"gas canister", r"gas cartridge",
                r"\bspray\b(?![- ](bottles?|nozzles?|guns?|heads?|mops?|tan)\b)"],
    "flammable liquid": [r"flammable", r"inflammable", r"perfume", r"eau de (parfum|toilette|cologne)",
                         r"\bcologne\b", r"nail (polish|varnish)", r"lighter (fluid|fuel|gas)",
                         r"\bpetrol\b", r"gasoline", r"kerosene", r"paraffin", r"lamp oil", r"\bthinners?\b",
                         r"\bsolvents?\b", r"acetone", r"methylated", r"isopropyl", r"rubbing alcohol",
                         r"\bethanol\b", r"hand saniti[sz]er", r"alcohol[- ]based", r"\bturpentine\b",
                         r"spirit[- ]based", r"oil[- ]based paint", r"\bvarnish\b", r"\blacquer\b",
                         r"reed diffuser",
                         r"\bfuel\b(?![- ](efficient|saving|economy|gauge|cap|filter|tank|line|pump|hose)\b)",
                         # bottled spirits: the spirit name followed by a bottle size ("gin 70cl")
                         r"\b(vodka|gin|whisk(e)?y|rum|tequila|brandy|cognac|absinthe)\b" + ACCESSORY
                         + r"[^,;]*?\b\d+(\.\d+)?\s*(cl|ml|l|litres?|liters?)\b"],
}
# Drinks over 24% alcohol by volume count as flammable liquids
ABV = re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(abv|vol|alc)")
# HS headings that are themselves dangerous-goods signals
DG_HS_PREFIXES = {
    "850650": "lithium battery", "850760": "lithium battery", "3303": "flammable liquid",
    "3208": "flammable liquid", "3814": "flammable liquid", "2710": "flammable liquid",
    "3606": "flammable liquid",
}


def detect_dangerous_goods(text: str, hs: Optional[str] = None) -> list[tuple[str, str]]:
    """Returns [(category, matched phrase)] for lithium batteries / aerosols / flammable liquids."""
    t = (text or "").lower()
    for neg in NEGATIONS:
        t = re.sub(neg, " ", t)
    hits = []
    for cat, pats in DG_TERMS.items():
        for p in pats:
            m = re.search(p, t)
            if m:
                hits.append((cat, m.group(0).strip()))
                break
    if "flammable liquid" not in [h[0] for h in hits]:
        for m in ABV.finditer(t):
            if float(m.group(1)) > 24:
                hits.append(("flammable liquid", m.group(0).strip()))
                break
    if hs:
        for pre, cat in DG_HS_PREFIXES.items():
            if hs.startswith(pre) and cat not in [h[0] for h in hits]:
                hits.append((cat, f"HS code {hs} (heading {pre})"))
    return hits


# ------------------------------------------------------------------- helpers
def _eq(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol


def _label(it: Item, i: int) -> str:
    return it.sku or f"item {i + 1}"


def item_net_weight(items):
    return sum((it.unit_weight or 0) * (it.quantity or 0) for it in items)


def _tradeoff(chosen: dict, preferred: dict) -> str:
    """How the booked carrier compares to the one the seller's priority wanted."""
    bits = []
    dd = chosen["transit_days"] - preferred["transit_days"]
    if dd:
        bits.append(f"{abs(dd)} day(s) {'slower' if dd > 0 else 'faster'}")
    if chosen["on_time"] != preferred["on_time"]:
        bits.append(f"{chosen['on_time']}% on-time vs {preferred['on_time']}%")
    dc = (chosen.get("cost") or 0) - (preferred.get("cost") or 0)
    if dc:
        bits.append(f"{gbp(abs(dc))} {'more' if dc > 0 else 'cheaper'}")
    return ", ".join(bits) or "similar service"


def item_value(items):
    return sum((it.quantity or 0) * (it.unit_price or 0) for it in items)


# ------------------------------------------------------------------ the rules
def run_checks(b: Booking, chosen_carrier: Optional[dict], today: date,
               weight_limits: Optional[list[dict]] = None,
               preferred: Optional[dict] = None) -> list[Finding]:
    """preferred = the carrier the seller's priority would pick if pallet weight didn't matter."""
    F: list[Finding] = []
    items = b.items

    # ---- data completeness (not a rulebook rule; reported so nothing is silently skipped)
    missing = [n for n, v in [("seller name", b.seller_name), ("origin city", b.origin_city),
                              ("destination city", b.dest_city), ("destination type", b.dest_type),
                              ("ready-to-ship date", b.ready_date), ("seller priority", b.priority),
                              ("pallets", b.pallets), ("cartons", b.cartons),
                              ("total declared value", b.declared_value),
                              ("total gross weight", b.gross_weight)] if v in (None, "")]
    if b.dest_type == "Warehouse" and b.appointment is None:
        missing.append("delivery appointment booked (Yes/No)")
    if missing:
        F.append(Finding("DATA", "Amber", f"Missing on the booking: {', '.join(missing)}.",
                         "Fill these in so every check can run."))
    if not items:
        F.append(Finding("DATA", "Red", "This booking has no item lines, so customs paperwork can't be built.",
                         "Add at least one item (SKU, description, quantity, unit price, packing and weight)."))
    for fld, val, ok in [("origin city", b.origin_city, ORIGIN_CITIES),
                         ("destination city", b.dest_city, list(DEST_CITIES)),
                         ("destination type", b.dest_type, DEST_TYPES),
                         ("seller priority", b.priority, PRIORITIES)]:
        if val and val not in ok:
            F.append(Finding("DATA", "Amber", f"'{val}' is not a recognised {fld}.",
                             f"Use one of: {', '.join(ok)}."))
    if b.dest_city in DEST_CITIES and b.dest_country and DEST_CITIES[b.dest_city] != b.dest_country:
        F.append(Finding("DATA", "Amber",
                         f"{b.dest_city} is in {DEST_CITIES[b.dest_city]}, but the booking says {b.dest_country}.",
                         f"Correct the destination country to {DEST_CITIES[b.dest_city]} (or fix the city)."))

    # ---- R-01 HS code
    for i, it in enumerate(items):
        hs = it.hs_code
        if not hs:
            F.append(Finding("R-01", "Red", f"{_label(it, i)} ('{it.description}') has no HS code.",
                             "Add the 6+ digit commodity code. Look it up on the UK Trade Tariff "
                             "(trade-tariff.service.gov.uk) using the product description.", it.sku))
        elif len(hs) < 6:
            extra = (f" If the real code starts with 0 (e.g. 0{hs}), Excel may have dropped the leading "
                     f"zero. Store HS codes as text.") if len(hs) == 5 else ""
            F.append(Finding("R-01", "Red", f"{_label(it, i)} has HS code {hs}, which is only {len(hs)} digits.",
                             "Give the full code to at least 6 digits (chapter + heading + subheading)." + extra,
                             it.sku))

    # ---- R-02 declared value
    total = item_value(items)
    if items and b.declared_value is not None:
        diff = b.declared_value - total
        pct = abs(diff) / total * 100 if total else 100.0
        if (total == 0 and b.declared_value != 0) or (total and pct > 1.0):
            F.append(Finding("R-02", "Red",
                             f"Declared value is {gbp(b.declared_value)}, but the items add up to {gbp(total)} "
                             f"({'over' if diff > 0 else 'under'} by {gbp(abs(diff))}, {pct:.1f}%).",
                             f"Change the declared value to {gbp(total)}, or correct the unit price / quantity "
                             f"of the line that is wrong. Customs compares the invoice total to the line items."))

    # ---- R-03 units per carton × cartons = quantity
    for i, it in enumerate(items):
        if None in (it.units_per_carton, it.cartons, it.quantity):
            continue
        packed = it.units_per_carton * it.cartons
        if not _eq(packed, it.quantity):
            opts = []
            if it.units_per_carton and (it.quantity / it.units_per_carton).is_integer():
                opts.append(f"cartons should be {fmt_num(it.quantity / it.units_per_carton)} "
                            f"(if {fmt_num(it.units_per_carton)} per carton and {fmt_num(it.quantity)} units are right)")
            opts.append(f"quantity should be {fmt_num(packed)} (if the carton count is right)")
            if it.cartons and (it.quantity / it.cartons).is_integer():
                opts.append(f"units per carton should be {fmt_num(it.quantity / it.cartons)}")
            F.append(Finding("R-03", "Red",
                             f"{_label(it, i)}: {fmt_num(it.units_per_carton)} per carton × {fmt_num(it.cartons)} "
                             f"cartons = {fmt_num(packed)} units, but quantity says {fmt_num(it.quantity)}.",
                             "Recount, then fix one of these: " + "; or ".join(opts) +
                             ". A mismatch here is what shows up as 'missing units' at the warehouse.", it.sku))

    # ---- R-04 total cartons
    item_cartons = sum(it.cartons or 0 for it in items)
    if items and b.cartons is not None and not _eq(b.cartons, item_cartons):
        F.append(Finding("R-04", "Red",
                         f"Booking says {fmt_num(b.cartons)} cartons, but the item lines add up to "
                         f"{fmt_num(item_cartons)}.",
                         f"Set total cartons to {fmt_num(item_cartons)}, or add the missing item line(s). "
                         f"The warehouse receives against this count."))

    # ---- R-05 weight per pallet vs chosen carrier
    if b.gross_weight and b.pallets:
        wpp = b.gross_weight / b.pallets
        if chosen_carrier is None and weight_limits:
            best = max(weight_limits, key=lambda c: c["max_kg_per_pallet"])
            need = math.ceil(b.gross_weight / best["max_kg_per_pallet"])
            F.append(Finding("R-05", "Red",
                             f"{fmt_num(b.gross_weight)} kg ÷ {fmt_num(b.pallets)} pallet(s) = {wpp:,.0f} kg per "
                             f"pallet. That is over every carrier's limit on this route (highest is "
                             f"{best['max_kg_per_pallet']} kg with {best['carrier']}).",
                             f"Re-palletise onto at least {need} pallets (≤ {best['max_kg_per_pallet']} kg each)."))
        elif chosen_carrier is not None and wpp > chosen_carrier["max_kg_per_pallet"] + 1e-9:
            need = math.ceil(b.gross_weight / chosen_carrier["max_kg_per_pallet"])
            F.append(Finding("R-05", "Red",
                             f"{wpp:,.0f} kg per pallet is over {chosen_carrier['carrier']}'s limit of "
                             f"{chosen_carrier['max_kg_per_pallet']} kg.",
                             f"Use at least {need} pallets, or pick a carrier with a higher limit."))
        elif (chosen_carrier is not None and preferred is not None
              and preferred["carrier"] != chosen_carrier["carrier"]
              and wpp > preferred["max_kg_per_pallet"] + 1e-9):
            # Passes on the carrier we booked, but the seller is not getting the carrier their priority asked for.
            need = math.ceil(b.gross_weight / preferred["max_kg_per_pallet"])
            F.append(Finding("R-05", "Amber",
                             f"{wpp:,.0f} kg per pallet is over {preferred['carrier']} · {preferred['service']}'s "
                             f"limit of {preferred['max_kg_per_pallet']} kg. That is the best match for your "
                             f"'{b.priority or 'Balanced'}' priority, so we booked {chosen_carrier['carrier']} · "
                             f"{chosen_carrier['service']} instead ({_tradeoff(chosen_carrier, preferred)}).",
                             f"Accept {chosen_carrier['carrier']}, or spread the load over at least {need} pallets "
                             f"(≤ {preferred['max_kg_per_pallet']} kg each) to use {preferred['carrier']}."))
    elif b.pallets == 0:
        F.append(Finding("DATA", "Red", "Pallets is 0, so weight per pallet can't be checked.",
                         "Enter the number of pallets."))

    # ---- R-06 dangerous goods
    for i, it in enumerate(items):
        for cat, phrase in detect_dangerous_goods(f"{it.sku} {it.description}", it.hs_code):
            F.append(Finding("R-06", "Red",
                             f"{_label(it, i)} ('{it.description}') looks like a {cat} (matched “{phrase}”). "
                             f"These are not allowed on this service.",
                             "Remove this line from the shipment and send it with a dangerous-goods (ADR) "
                             "specialist. If it is a false alarm (e.g. no battery inside), change the "
                             "description to say so clearly.", it.sku))

    # ---- R-07 gross weight >= net goods weight
    net = item_net_weight(items)
    if items and b.gross_weight is not None and b.gross_weight + 1e-9 < net:
        F.append(Finding("R-07", "Amber",
                         f"Gross weight is {fmt_num(b.gross_weight)} kg, but the goods alone weigh "
                         f"{fmt_num(net)} kg (unit weight × quantity), before cartons and pallets.",
                         f"Re-weigh the shipment. Gross weight must be at least {fmt_num(net)} kg plus packaging "
                         f"(pallets are typically 20–25 kg each). Under-declared weight leads to surcharges "
                         f"or refused collection."))

    # ---- R-08 warehouse appointment
    if b.dest_type == "Warehouse" and b.appointment is False:
        F.append(Finding("R-08", "Amber", "This is going to a warehouse, but no delivery appointment is booked.",
                         "Book a delivery slot with the receiving warehouse for the estimated arrival date. "
                         "Warehouses often refuse or delay deliveries that turn up without one."))

    # ---- R-09 country of origin
    for i, it in enumerate(items):
        if not it.origin_country:
            F.append(Finding("R-09", "Amber", f"{_label(it, i)} has no country of origin.",
                             "Add where the product was made (not where it ships from). Customs uses this "
                             "for duty and preferential-origin claims.", it.sku))
        elif it.origin_country not in ITEM_ORIGINS:
            F.append(Finding("DATA", "Info", f"{_label(it, i)}: country of origin '{it.origin_country}' "
                             f"is not in the allowed list.", f"Use one of: {', '.join(ITEM_ORIGINS)}.", it.sku))

    # ---- R-10 ready date
    if b.ready_date and b.ready_date < today:
        F.append(Finding("R-10", "Amber",
                         f"Ready-to-ship date {fmt_date(b.ready_date)} is in the past (today is {fmt_date(today)}).",
                         "Update it to the real date the goods will be packed and ready. Collection "
                         "and arrival dates are calculated from it."))
    return F


def status_of(findings: list[Finding]) -> str:
    sev = {f.severity for f in findings}
    if "Red" in sev:
        return "Red"
    if "Amber" in sev:
        return "Amber"
    return "Green"
