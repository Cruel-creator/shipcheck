"""Fixed reference data copied from the hackathon template (Sheets 3 & 4).
Judges upload only Bookings + Items, so these live in code."""

CARRIERS = [
    # carrier, service, origin, destination, price/pallet GBP, transit days, on-time %, max kg/pallet
    ("Carrier A", "Road economy", "United Kingdom", "Germany", 180, 5, 92, 500),
    ("Carrier B", "Road standard", "United Kingdom", "Germany", 220, 3, 95, 750),
    ("Carrier C", "Road express", "United Kingdom", "Germany", 340, 2, 98, 400),
    ("Carrier A", "Road economy", "United Kingdom", "France", 170, 5, 92, 500),
    ("Carrier B", "Road standard", "United Kingdom", "France", 210, 3, 95, 750),
    ("Carrier C", "Road express", "United Kingdom", "France", 330, 2, 98, 400),
    ("Carrier A", "Road economy", "United Kingdom", "Netherlands", 160, 5, 92, 500),
    ("Carrier B", "Road standard", "United Kingdom", "Netherlands", 200, 3, 95, 750),
    ("Carrier C", "Road express", "United Kingdom", "Netherlands", 320, 2, 98, 400),
]

CARRIER_KEYS = ["carrier", "service", "origin_country", "dest_country",
                "price_per_pallet", "transit_days", "on_time", "max_kg_per_pallet"]
CARRIER_OPTIONS = [dict(zip(CARRIER_KEYS, row)) for row in CARRIERS]

RULES = {
    "R-01": ("Every item must have an HS code of at least 6 digits", "Red"),
    "R-02": ("Total declared value must equal the sum of quantity × unit price across all items (within 1%)", "Red"),
    "R-03": ("For each item, units per carton × cartons must equal quantity", "Red"),
    "R-04": ("Total cartons on the booking must equal the sum of cartons across all items", "Red"),
    "R-05": ("Weight per pallet (total gross weight ÷ pallets) must not exceed the chosen carrier's max weight per pallet", "Red"),
    "R-06": ("No lithium batteries, aerosols or flammable liquids", "Red"),
    "R-07": ("Total gross weight must be at least the sum of unit weight × quantity across all items", "Amber"),
    "R-08": ("Shipments to a warehouse must have a delivery appointment booked", "Amber"),
    "R-09": ("Every item must have a country of origin", "Amber"),
    "R-10": ("Ready to ship date must not be in the past", "Amber"),
}

ORIGIN_CITIES = ["London", "Manchester", "Birmingham", "Leeds"]
DEST_CITIES = {
    "Berlin": "Germany", "Frankfurt": "Germany", "Hamburg": "Germany",
    "Paris": "France", "Lyon": "France",
    "Amsterdam": "Netherlands", "Rotterdam": "Netherlands",
}
DEST_COUNTRIES = ["Germany", "France", "Netherlands"]
DEST_TYPES = ["Warehouse", "Business address"]
PRIORITIES = ["Cheapest", "Fastest", "Most reliable", "Balanced"]
ITEM_ORIGINS = ["United Kingdom", "China", "India", "Vietnam", "Turkey", "Germany"]

# Weights used for the "Balanced" priority (shown to the user for transparency)
BALANCED_WEIGHTS = {"cost": 0.4, "speed": 0.3, "reliability": 0.3}
