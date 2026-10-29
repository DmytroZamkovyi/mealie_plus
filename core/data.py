"""Default conversion tables. Approximate on purpose: good enough for a shopping list.

Three kinds of knowledge:
- SYNONYMS: different foods that are the same thing when shopping.
- BASE_EQUIV: per-food equivalents between countable units (always applied).
- BRIDGES: conversions between two different bases of one food (applied only when
  both are present in the merged line): density (ml -> g), piece weight (pcs -> g).
Everything here can be extended by the user through the integration options.
"""

from __future__ import annotations

# canonical name -> names treated as the same food
SYNONYMS: dict[str, tuple[str, ...]] = {
    "соняшникова олія": ("рослинна олія", "олія для смаження", "олія"),
    "оливкова олія": ("оливкова олія extra virgin", "olive oil", "extra virgin olive oil"),
    "яйце": ("яйця", "яйця курячі", "яйце куряче"),
    "цибуля": ("цибуля ріпчаста", "жовта цибуля", "цибуля жовта ріпчаста"),
}

# food -> {unit base: (target base, factor)}; always applied
BASE_EQUIV: dict[str, dict[str, tuple[str, float]]] = {
    "часник": {"голівка": ("зубчик", 6)},
}

# grams per millilitre
DENSITY: dict[str, float] = {
    "сіль": 1.2,
    "цукор": 0.85,
    "цукрова пудра": 0.6,
    "борошно": 0.55,
    "соняшникова олія": 0.92,
    "оливкова олія": 0.92,
    "молоко": 1.03,
    "вода": 1.0,
    "мед": 1.4,
    "сметана": 1.0,
    "вершки": 1.0,
    "вершкове масло": 0.95,
    "рис": 0.8,
    "томатна паста": 1.1,
    "кетчуп": 1.1,
    "майонез": 0.95,
    "соєвий соус": 1.15,
    "оцет": 1.0,
}

# grams per piece ("шт")
PIECE_GRAMS: dict[str, float] = {
    "цибуля": 100,
    "червона цибуля": 100,
    "морква": 100,
    "картопля": 100,
    "помідор": 120,
    "помідор чері": 15,
    "огірок": 120,
    "болгарський перець": 150,
    "перець солодкий": 150,
    "лимон": 100,
    "лайм": 60,
    "апельсин": 200,
    "яблуко": 180,
    "яйце": 55,
    "авокадо": 170,
    "баклажан": 300,
    "редис": 15,
}

# food -> {(from base, to base): factor}; applied only when both bases are present
FOOD_BRIDGES: dict[str, dict[tuple[str, str], float]] = {}
for _food, _d in DENSITY.items():
    FOOD_BRIDGES.setdefault(_food, {})[("мл", "г")] = _d
for _food, _g in PIECE_GRAMS.items():
    FOOD_BRIDGES.setdefault(_food, {})[("шт", "г")] = _g
FOOD_BRIDGES.setdefault("часник", {})[("зубчик", "г")] = 5

# applied to any food when both bases are present (rough averages)
GLOBAL_BRIDGES: dict[tuple[str, str], float] = {
    ("дрібка", "г"): 0.5,
    ("жменя", "г"): 30,
    ("пучок", "г"): 50,
}
