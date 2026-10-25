"""Run: python -m pytest -q"""
from datetime import date
from pathlib import Path

from engine.analyse import analyse
from engine.checks import detect_dangerous_goods
from engine.excel_io import load_workbooks
from engine.models import to_date, to_hs

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 28)
EXPECTED = {  # planted errors in samples/sample_test_bookings.xlsx
    "BK-101": set(), "BK-102": {"R-01", "R-09"}, "BK-103": {"R-02"}, "BK-104": {"R-03", "R-04"},
    "BK-105": {"R-05"}, "BK-106": {"R-06"}, "BK-107": {"R-07", "R-08"}, "BK-108": {"R-10"},
    # BK-109/110: priority's carrier (C, 400 kg) can't take the pallets -> Amber R-05 note, booked on B
    "BK-109": {"R-05"}, "BK-110": {"R-01", "R-05"},
}


def results():
    bks, notes = load_workbooks([(ROOT / "samples" / "sample_test_bookings.xlsx").read_bytes()])
    return {b.booking_id: analyse(b, TODAY) for b in bks}, notes


def test_planted_errors_found_exactly():
    res, notes = results()
    assert set(res) == set(EXPECTED)  # example row skipped
    for bid, exp in EXPECTED.items():
        got = {f.rule_id for f in res[bid]["findings"] if f.severity in ("Red", "Amber")}
        assert got == exp, (bid, got)


def test_carrier_logic():
    res, _ = results()
    assert res["BK-101"]["rec"]["chosen"]["carrier"] == "Carrier A"            # cheapest
    assert res["BK-109"]["rec"]["chosen"]["carrier"] == "Carrier B"            # fastest C excluded (450kg > 400)
    assert res["BK-105"]["rec"]["chosen"] is None                              # 820kg > all limits
    assert res["BK-104"]["rec"]["chosen"]["carrier"] == "Carrier B"            # balanced
    r05 = [f for f in res["BK-109"]["findings"] if f.rule_id == "R-05"]
    assert len(r05) == 1 and r05[0].severity == "Amber" and "Carrier C" in r05[0].problem
    assert not [f for f in res["BK-101"]["findings"] if f.rule_id == "R-05"]  # cheapest carrier fits -> no note


def test_parsers():
    assert to_date("05-11-2026") == date(2026, 11, 5)
    assert to_date("2026-11-05") == date(2026, 11, 5)
    assert to_hs(691200.0) == "691200" and to_hs("6912.00") == "691200" and to_hs(None) is None


def test_dangerous_goods():
    assert detect_dangerous_goods("Bluetooth speaker, rechargeable")
    assert detect_dangerous_goods("Hairspray 300ml")
    assert not detect_dangerous_goods("Battery-free kitchen timer")
    assert not detect_dangerous_goods("Ceramic coffee mug")
    assert not detect_dangerous_goods("Soy wax candle in glass jar")


def test_dangerous_goods_no_false_alarms():
    for clean in ["Laptop sleeve, neoprene", "Laptop stand aluminium", "Mobile phone case, silicone",
                  "Smartphone screen protector", "Smartwatch strap, leather", "Wooden balance bike",
                  "Large bike lock", "Pipe cigars", "Fuel-efficient kettle", "Solid perfume balm",
                  "AA alkaline batteries", "Spray bottle, empty, 500 ml", "Whisky glass 30cl",
                  "Rum and raisin fudge 200g", "Ginger biscuits", "Electric toothbrush heads, pack of 4"]:
        assert not detect_dangerous_goods(clean), clean


def test_dangerous_goods_catches_more():
    for dg in ["Phone battery replacement 3.7V", "Portable charger 20000mAh", "Drone with camera",
               "Electric toothbrush", "Insect repellent spray", "London dry gin 70cl",
               "Spiced spirit drink 40% ABV", "Bluetooth speaker with carry case", "Electric scooter",
               "Laptop 15 inch"]:
        assert detect_dangerous_goods(dg), dg
