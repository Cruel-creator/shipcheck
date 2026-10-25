"""ShipCheck: conversational shipment booking + pre-flight error checker (Mesa Ops Hackathon, Case 2).

Run locally:  streamlit run app.py
"""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from engine import chat, llm
from engine.analyse import analyse, today_ist
from engine.excel_io import load_workbooks
from engine.models import fmt_date, fmt_num, gbp
from engine.reference import CARRIER_OPTIONS, RULES, BALANCED_WEIGHTS

ROOT = Path(__file__).parent
SAMPLE = ROOT / "samples" / "sample_test_bookings.xlsx"

st.set_page_config(page_title="ShipCheck · UK→EU booking & pre-flight check", page_icon="📦", layout="wide")

COLORS = {"Red": "#d93025", "Amber": "#e8a000", "Green": "#188038", "Info": "#5f6368"}
LABEL = {"Red": "RED · must fix", "Amber": "AMBER · check", "Green": "GREEN · ready", "Info": "INFO"}


def chip(sev: str) -> str:
    return (f"<span style='background:{COLORS[sev]};color:white;padding:2px 8px;border-radius:10px;"
            f"font-size:0.8em;font-weight:600'>{LABEL[sev]}</span>")


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown("### 📦 ShipCheck")
    st.caption("Book a UK → EU pallet shipment in plain English, and catch the mistakes that cause customs "
               "holds and missing units **before** it leaves.")
    check_date = st.date_input("Check dates against", value=today_ist(), format="DD/MM/YYYY",
                               help="R-10 flags ready dates before this day. Defaults to today (IST).")
    with st.expander("How it works"):
        st.markdown(
            "1. **AI only reads and writes.** It turns the seller's words or the uploaded sheet into a structured booking.\n"
            "2. **Code does every check.** All 10 rulebook rules (R-01 to R-10) run in plain code, so the same "
            "booking always gets the same result and the maths is exact.\n"
            "3. **Carrier choice.** Drop carriers that don't run the route or can't take pallets this heavy, "
            "then rank the rest by the seller's priority.\n"
            "4. **Explain.** For each issue: what's wrong, how serious, the exact fix, and what happens next.")
    with st.expander("Rulebook"):
        st.dataframe(pd.DataFrame([{"Rule": k, "Check": v[0], "Severity": v[1]} for k, v in RULES.items()]),
                     hide_index=True, width="stretch")
    with st.expander("Carrier rate card"):
        st.dataframe(pd.DataFrame([{"Carrier": c["carrier"], "Service": c["service"], "To": c["dest_country"],
                                    "£/pallet": c["price_per_pallet"], "Days": c["transit_days"],
                                    "On-time %": c["on_time"], "Max kg/pallet": c["max_kg_per_pallet"]}
                                   for c in CARRIER_OPTIONS]), hide_index=True, width="stretch")
        st.caption(f"Balanced = weighted score: cost {int(BALANCED_WEIGHTS['cost']*100)}%, speed "
                   f"{int(BALANCED_WEIGHTS['speed']*100)}%, reliability {int(BALANCED_WEIGHTS['reliability']*100)}% "
                   f"(min-max normalised across eligible options). ETA counts working days from collection.")


# ------------------------------------------------------------------ shared renderers
def render_findings(findings):
    if not findings:
        st.success("No issues found. All 10 rulebook checks passed.")
        return
    order = {"Red": 0, "Amber": 1, "Info": 2}
    for f in sorted(findings, key=lambda f: order.get(f.severity, 3)):
        rule = f"{f.rule_id}: {f.rule_text}" if f.rule_id != "DATA" else "Data completeness"
        st.markdown(f"{chip(f.severity)} &nbsp; **{rule}**<br>"
                    f"<span style='margin-left:4px'>❗ {f.problem}</span><br>"
                    f"<span style='margin-left:4px'>🔧 <b>Fix:</b> {f.fix}</span>", unsafe_allow_html=True)
        st.write("")


def render_recommendation(res):
    rec = res["rec"]
    b = res["booking"]
    c = rec.get("chosen")
    if c:
        st.markdown(f"**Recommended: {c['carrier']} · {c['service']}**, {gbp(c['cost'])}, "
                    f"{c['transit_days']} working days, {c['on_time']}% on-time, ETA {fmt_date(c['eta']) or 'TBC'}")
    st.markdown(rec.get("reason") or "")
    if rec.get("options"):
        wpp = rec.get("weight_per_pallet")
        rows = []
        for o in rec["options"]:
            chosen = c and o["carrier"] == c["carrier"]
            rows.append({"": "✅" if chosen else ("⛔" if not o["fits_weight"] else ""),
                         "Carrier": f"{o['carrier']} · {o['service']}",
                         "Cost": gbp(o["cost"]), "Transit (days)": o["transit_days"], "On-time": f"{o['on_time']}%",
                         "Max kg/pallet": o["max_kg_per_pallet"],
                         "Your kg/pallet": f"{wpp:,.0f}" if wpp else "—",
                         "ETA": fmt_date(o["eta"]) or "—",
                         "Note": "" if o["fits_weight"] else "Pallets too heavy"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    rp = rec.get("repallet")
    if rp and rp.get("if_repalletised"):
        st.info("If re-palletised: " + (rp["if_repalletised"].get("reason") or ""))


def results_workbook(results) -> bytes:
    summary, issues = [], []
    for r in results:
        b, c = r["booking"], r["rec"].get("chosen")
        summary.append({"Booking ID": b.booking_id, "Seller": b.seller_name, "Route": f"{b.origin_city} → {b.dest_city}",
                        "Status": r["status"], "Red": sum(f.severity == "Red" for f in r["findings"]),
                        "Amber": sum(f.severity == "Amber" for f in r["findings"]), "Priority": b.priority,
                        "Recommended carrier": f"{c['carrier']} · {c['service']}" if c else "None (fix R-05)",
                        "Cost (GBP)": c["cost"] if c else None, "ETA": fmt_date(c["eta"]) if c else None,
                        "Why": r["rec"].get("reason", "").replace("**", "")})
        for f in r["findings"]:
            issues.append({"Booking ID": b.booking_id, "Rule": f.rule_id, "Severity": f.severity, "SKU": f.sku,
                           "Problem": f.problem, "Fix": f.fix})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(summary).to_excel(xw, sheet_name="Summary", index=False)
        pd.DataFrame(issues or [{"Booking ID": "", "Problem": "No issues"}]).to_excel(xw, sheet_name="Issues", index=False)
    return buf.getvalue()


def booking_workbook(b) -> bytes:
    """Export a chat booking in the judges' Bookings + Items format."""
    bk = pd.DataFrame([{"Booking ID": b.booking_id, "Seller name": b.seller_name, "Origin city": b.origin_city,
                        "Origin country": b.origin_country, "Destination city": b.dest_city,
                        "Destination country": b.dest_country, "Destination type": b.dest_type,
                        "Ready to ship date": fmt_date(b.ready_date), "Seller priority": b.priority,
                        "Pallets": b.pallets, "Cartons": b.cartons, "Total declared value": b.declared_value,
                        "Currency": b.currency, "Total gross weight (kg)": b.gross_weight,
                        "Delivery appointment booked": {True: "Yes", False: "No"}.get(b.appointment)}])
    it = pd.DataFrame([{"Booking ID": i.booking_id, "SKU": i.sku, "Description": i.description, "HS code": i.hs_code,
                        "Quantity (units)": i.quantity, "Unit price": i.unit_price,
                        "Units per carton": i.units_per_carton, "Cartons": i.cartons,
                        "Unit weight (kg)": i.unit_weight, "Country of origin": i.origin_country} for i in b.items])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        bk.to_excel(xw, sheet_name="Bookings", index=False)
        it.to_excel(xw, sheet_name="Items", index=False)
    return buf.getvalue()


# ------------------------------------------------------------------ header + tabs
st.markdown("## 📦 ShipCheck: book UK → EU shipments and catch errors before they leave")
tab_chat, tab_file = st.tabs(["💬  Book by chat", "📄  Check a bookings file"])

# ================================================================== FILE TAB
with tab_file:
    st.markdown("Upload a workbook with the **Bookings** and **Items** sheets (the hackathon template format). "
                "Every booking gets checked against all 10 rules and gets a carrier recommendation.")
    c1, c2 = st.columns([3, 1])
    with c1:
        ups = st.file_uploader("Bookings + Items workbook (.xlsx)", type=["xlsx", "xlsm"], accept_multiple_files=True)
    with c2:
        st.write("")
        use_sample = st.button("Try the sample file", help="10 bookings with planted mistakes")
        st.download_button("Download sample", SAMPLE.read_bytes(), "sample_test_bookings.xlsx")
    if use_sample:
        st.session_state["file_bytes"] = [SAMPLE.read_bytes()]
        st.session_state["file_name"] = "sample_test_bookings.xlsx"
    if ups:
        st.session_state["file_bytes"] = [u.getvalue() for u in ups]
        st.session_state["file_name"] = ", ".join(u.name for u in ups)

    if st.session_state.get("file_bytes"):
        try:
            bookings, notes = load_workbooks(st.session_state["file_bytes"])
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")
            bookings, notes = [], []
        for n in notes:
            st.caption("ℹ️ " + n)
        if bookings:
            results = [analyse(b, check_date) for b in bookings]
            n_red = sum(r["status"] == "Red" for r in results)
            n_amb = sum(r["status"] == "Amber" for r in results)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Bookings checked", len(results))
            m2.metric("🔴 On hold", n_red)
            m3.metric("🟠 Warnings", n_amb)
            m4.metric("🟢 Ready", len(results) - n_red - n_amb)

            tbl = []
            for r in results:
                b, c = r["booking"], r["rec"].get("chosen")
                icon = {"Red": "🔴", "Amber": "🟠", "Green": "🟢"}[r["status"]]
                tbl.append({"Status": f"{icon} {r['status']}", "Booking": b.booking_id, "Seller": b.seller_name,
                            "Route": f"{b.origin_city} → {b.dest_city}",
                            "Issues": ", ".join(sorted({f.rule_id for f in r["findings"] if f.severity != "Info"})) or "—",
                            "Priority": b.priority,
                            "Recommended": f"{c['carrier']} · {c['service']}" if c else "— (pallets too heavy)",
                            "Cost": gbp(c["cost"]) if c else "—", "ETA": fmt_date(c["eta"]) if c else "—"})
            st.dataframe(pd.DataFrame(tbl), hide_index=True, width="stretch")
            st.download_button("⬇️ Download full results (Excel)", results_workbook(results),
                               "shipcheck_results.xlsx")

            st.markdown("#### Booking details")
            for r in results:
                b = r["booking"]
                icon = {"Red": "🔴", "Amber": "🟠", "Green": "🟢"}[r["status"]]
                with st.expander(f"{icon} {b.booking_id} · {b.seller_name or ''} · {b.origin_city} → {b.dest_city} "
                                 f"· {len(r['findings'])} issue(s)", expanded=(r["status"] == "Red" and len(results) <= 3)):
                    st.markdown(f"**1. What's wrong** &nbsp; {chip(r['status'])}", unsafe_allow_html=True)
                    render_findings(r["findings"])
                    st.markdown("**2. Recommended carrier**")
                    render_recommendation(r)
                    st.markdown("**3. Confirmation**")
                    st.markdown(r["confirmation"])
                    with st.popover("See parsed data"):
                        st.json(b.to_dict())

# ================================================================== CHAT TAB
with tab_chat:
    if "chat" not in st.session_state:
        st.session_state.chat = chat.new_state()
        st.session_state.chat["messages"].append({"role": "assistant", "content":
            "Hi! Tell me about the shipment in your own words: what you're sending, from where to where, and "
            "roughly how much. I'll only ask for what's missing, then check it and pick a carrier."})
    S = st.session_state.chat

    left, right = st.columns([5, 4], gap="large")
    with left:
        if not llm.available():
            st.warning("Chat needs an LLM API key (ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY) in the "
                       "app secrets. The file checker works without one.")
        examples = ["I need to send 3 pallets of ceramic mugs from Manchester to an Amazon warehouse in Frankfurt",
                    "Shipping 40 boxes of cotton towels and some phone power banks from London to a shop in Paris next Friday"]
        ex_cols = st.columns(2)
        clicked = None
        for col, ex in zip(ex_cols, examples):
            if col.button(f"Try: “{ex[:60]}…”", key=ex, width="stretch"):
                clicked = ex
        box = st.container(height=520)
        with box:
            for m in S["messages"]:
                with st.chat_message(m["role"]):
                    st.markdown(m["content"])
        prompt = st.chat_input("Describe your shipment, answer a question, or change a detail…") or clicked
        if prompt:
            with box:
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("Updating booking and re-running checks…"):
                        try:
                            reply, _ = chat.turn(S, prompt, check_date)
                        except Exception as e:
                            S["messages"].append({"role": "assistant", "content":
                                f"Sorry, I couldn't process that ({type(e).__name__}). Could you rephrase?"})
            st.rerun()
        if st.button("↺ Start a new booking"):
            del st.session_state["chat"]
            st.rerun()

    with right:
        b = S["booking"]
        res = analyse(b, check_date)
        miss = chat.missing_fields(S)
        shown = chat.visible_findings(S, res["findings"])
        status = "Collecting" if miss else res["status"]
        badge = (f"<span style='background:#5f6368;color:white;padding:2px 8px;border-radius:10px;font-size:0.8em;white-space:nowrap'>"
                 f"COLLECTING · {len(miss)} to go</span>") if miss else chip(res["status"])
        st.markdown(f"#### Live booking {b.booking_id} &nbsp; {badge}", unsafe_allow_html=True)
        D = set(S["derived"])

        def val(k, v):
            if v in (None, ""):
                return "❓ missing"
            s = fmt_date(v) if isinstance(v, date) else ({True: "Yes", False: "No"}.get(v) if isinstance(v, bool)
                                                       else (fmt_num(v) if isinstance(v, float) else str(v)))
            return s + ("  (calculated)" if k in D else "")

        fields = [("Seller", "seller_name"), ("From", "origin_city"), ("To", "dest_city"), ("Country", "dest_country"),
                  ("Destination type", "dest_type"), ("Ready date", "ready_date"), ("Priority", "priority"),
                  ("Pallets", "pallets"), ("Cartons", "cartons"), ("Declared value £", "declared_value"),
                  ("Gross weight kg", "gross_weight"), ("Appointment booked", "appointment")]
        st.dataframe(pd.DataFrame([{"Field": n, "Value": val(k, getattr(b, k))} for n, k in fields]),
                     hide_index=True, width="stretch", height=458)
        if b.items:
            st.dataframe(pd.DataFrame([{"SKU": i.sku, "Description": i.description, "HS": i.hs_code or "❓",
                                        "Qty": fmt_num(i.quantity), "£/unit": fmt_num(i.unit_price),
                                        "Units/ctn": fmt_num(i.units_per_carton), "Ctns": fmt_num(i.cartons),
                                        "kg/unit": fmt_num(i.unit_weight), "Origin": i.origin_country or "❓"}
                                       for i in b.items]), hide_index=True, width="stretch")
        if miss:
            st.markdown("**Still needed:** " + "; ".join(miss))
        st.markdown("**Checks**" + (" (so far)" if miss else ""))
        render_findings(shown)
        if b.dest_country and b.pallets:
            st.markdown("**Carrier**")
            render_recommendation(res)
        if not miss:
            st.markdown("**Confirmation**")
            st.markdown(res["confirmation"])
            st.download_button("⬇️ Download booking (Bookings + Items format)", booking_workbook(b),
                               f"{b.booking_id}.xlsx")
        if S["changelog"]:
            with st.expander(f"Change log ({len(S['changelog'])})"):
                for t, c in S["changelog"]:
                    st.markdown(f"- turn {t}: {c}")
