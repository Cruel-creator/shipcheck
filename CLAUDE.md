# Project context for Claude Code

Hackathon MVP (deadline Mon 26 Oct 2026, 11:59 PM IST; link must stay live until 28 Oct). Read README.md first.

Hard rules:
- Rule checks, arithmetic and carrier ranking stay in deterministic Python (`engine/checks.py`, `engine/carriers.py`). The LLM never decides pass/fail.
- Reference data in `engine/reference.py` is copied from the official template (`data/template.xlsx`, sheets "Carrier options" and "Rulebook"). Do not change values.
- Judges upload only the Bookings and Items sheets, in the template's format (header on row 2, grey example on row 3, data from row 4).
- After any engine change, run `python -m pytest -q`. Every planted error in `samples/sample_test_bookings.xlsx` must still be caught, with no extra findings.
- Keep the app working with no login. Secrets go in `.streamlit/secrets.toml` (git-ignored) or the Streamlit Cloud secrets UI.
