# ShipCheck: conversational shipment booking + pre-flight error checker

Mesa Ops Hackathon, Case 2. A Streamlit app with two tabs:

- **Book by chat**: the seller describes the shipment in plain English. The app asks only for what's missing, keeps a live booking panel, and re-runs every check when a detail changes (e.g. "add a pallet").
- **Check a bookings file**: upload the Bookings + Items workbook. Every booking gets checked against R-01 to R-10, then gets a status, the exact fix for each issue, a carrier recommendation with the reason, and a confirmation.

## Design principle
The LLM only reads (chat → structured booking) and writes (the reply). **All rule checks, maths and carrier ranking are plain Python.** That way results are exact and repeatable, which matters because judges plant errors.

```
app.py                  Streamlit UI (both tabs)
engine/reference.py     Fixed rate card + rulebook from the template (Sheets 3 & 4)
engine/models.py        Booking/Item dataclasses + tolerant parsers (dates day-first, HS codes as text, "£5,400" → 5400)
engine/checks.py        R-01…R-10 with problem + fix text; dangerous-goods detector for R-06
engine/carriers.py      Route filter → pallet-weight filter (R-05) → rank by priority; ETA in working days
engine/analyse.py       One call: findings + status + recommendation + confirmation
engine/excel_io.py      Reads judges' workbook (finds header row, skips grey example row, handles orphans)
engine/chat.py          LLM extraction → patch → derive values → missing-field list → reply
engine/llm.py           Anthropic / OpenAI / Gemini over HTTPS (whichever key is set)
samples/                Test workbook with planted errors + generator script
tests/test_engine.py    Asserts every planted error is caught, and nothing else
```

## Decisions (put these in the deck)
- **R-05 "chosen carrier"**: carriers whose max kg/pallet is below gross ÷ pallets are excluded *before* ranking. If the carrier the seller's priority would pick was excluded, the booking passes R-05 on the carrier we actually book, but gets an **Amber R-05 note**: which carrier was skipped, its kg limit, what the seller gives up (days, on-time %, £), and how many pallets would make it eligible. If *every* carrier is excluded, R-05 is Red, and the app shows the re-pallet count plus the recommendation for that scenario.
- **Balanced**: min-max normalised score, cost 40% / speed 30% / reliability 30%, among eligible carriers. The score is shown.
- **Ties**: Cheapest → more reliable; Fastest → cheaper; Most reliable → cheaper.
- **ETA**: collection on the ready date (next weekday if it falls on a weekend; today if the date is in the past), plus transit in working days.
- **R-01**: a 5-digit HS code is flagged, with a hint that Excel may have dropped a leading zero.
- **R-06**: keyword + HS heading detection (lithium/power bank/battery/mAh/drone, aerosol/spray, perfume/solvent/nail polish, spirits over 24% ABV…), with negations ("battery-free", "non-aerosol", "alkaline batteries", "solid perfume", "pump spray"). Device words only count when the line is the device itself, not an accessory for it ("laptop sleeve", "phone case", "bike lock", "whisky glass" are clean).
- **Status**: Red = on hold until fixed; Amber = can book, with warnings; Green = ready.
- **Chat derives** what follows logically (cartons = units ÷ units per carton, declared value = Σ qty × price, country from city) and marks it "(calculated)". It never "corrects" the seller's stated numbers. Checks catch those.

## Run locally
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # add ONE API key
streamlit run app.py
python -m pytest -q
```

## Deploy (free, public, no login): Streamlit Community Cloud
1. Push this folder to a **public** GitHub repo.
2. Go to share.streamlit.io → **Create app**, then pick the repo, branch `main`, file `app.py`.
3. **Advanced settings → Secrets**: paste `ANTHROPIC_API_KEY = "sk-ant-..."` (or OPENAI/GEMINI).
4. Deploy, open the URL in an incognito window to confirm there's no login, and submit that link.
5. Set a spend limit on your API key. Free apps sleep after inactivity, so open the link on the morning of 28 Oct.
