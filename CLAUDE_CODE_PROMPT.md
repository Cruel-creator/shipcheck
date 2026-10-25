# Prompts to paste into Claude Code

Open Claude Code in this `shipcheck/` folder, then paste these one at a time.

---

## Prompt 1: get it running and test the chat for real

```
Read README.md and CLAUDE.md. Then:
1. Create a venv, install requirements.txt, and run `python -m pytest -q`. All tests must pass.
2. I've put my API key in .streamlit/secrets.toml. Start the app with `streamlit run app.py`.
3. Test the chat engine without the UI: write a short script (scripts/chat_smoke.py) that calls engine.chat.turn()
   with these seller messages in order, and prints the reply, the status, the rule IDs found and the change log
   after each turn:
   a) "Hi, I need to send 3 pallets of ceramic mugs from Manchester to an Amazon warehouse in Frankfurt"
   b) "1080 mugs, £5 each, 12 per carton, each mug is 0.5kg, made in the UK. Don't know the HS code"
   c) "Total weight about 620 kg, ready on 5th November, cheapest please, no slot booked yet. We're Northfield Goods"
   d) "Actually add a pallet"
   e) "Oh and we're adding 200 power banks, £8 each, 20 per carton, 0.3 kg, made in China, HS 850760"
4. Check that: it only asks for missing things; turn d changes pallets 3→4 and the cost updates; turn e raises R-06 Red;
   "don't know the HS code" stops it asking again and R-01 shows as Red with a suggestion.
   If anything fails, fix the prompts in engine/chat.py (EXTRACT_SYSTEM / REPLY_SYSTEM) rather than the rules engine.
```

## Prompt 2: harden against judges' files

```
Create 3 more test workbooks in samples/ using the same generator approach as samples/make_samples.py, then make
the parser and checks pass on them. Cover:
- real Excel dates instead of text in "Ready to ship date", plus "5/11/2026" and "2026-11-05" strings
- HS codes stored as text with leading zeros ("090121"), and with dots ("6912.00")
- numbers typed as text ("£5,400", "620 kg"), trailing spaces in city names, lowercase "warehouse"/"yes"
- an item whose Booking ID isn't on the Bookings sheet, a booking with no items, a duplicate Booking ID
- the grey example row deleted entirely (data starting on row 3)
- multiple planted errors in one booking (e.g. R-02 + R-03 + R-04 + R-07 together)
- dangerous goods phrased indirectly: "Bluetooth speaker", "deodorant 150ml spray", "nail varnish", and false
  positives that must NOT trigger: "battery-free clock", "non-aerosol pump spray", "scented candle"
Add each as a pytest case with the exact expected rule IDs.
```

## Prompt 3: polish for the demo

```
Improve the demo without touching the engine's logic:
1. File tab: add a "Copy fix list" text box per booking (plain text the seller could paste into an email).
2. Chat tab: when the booking first becomes complete, show a "Confirm booking" button. On click, show a
   booking reference, the confirmation text and a "Download commercial invoice (PDF)" button. Build the PDF with
   reportlab from the item lines: seller, consignee city, SKU, description, HS code, qty, unit price, line total,
   origin, total value GBP and gross weight.
3. Add a tiny "Why this carrier?" explainer under the recommendation showing the Balanced score maths.
Run pytest and the smoke script again afterwards.
```

## Prompt 4: deploy

```
Prepare for Streamlit Community Cloud: make sure requirements.txt is complete, no secrets are committed
(.gitignore covers .streamlit/secrets.toml), and README deploy steps are right. Initialise git, commit, and
create a public GitHub repo with `gh repo create shipcheck --public --source=. --push`. Then tell me exactly what
to click on share.streamlit.io and what to paste into Secrets.
```
