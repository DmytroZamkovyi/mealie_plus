"""Units, aliases and Ukrainian display forms. Pure Python, no Home Assistant."""

from __future__ import annotations

import re
from dataclasses import dataclass


def norm(text: str) -> str:
    """Lowercase, unify apostrophes, collapse whitespace (newlines included)."""
    t = (text or "").casefold().replace("ʼ", "'").replace("’", "'")
    return re.sub(r"\s+", " ", t).strip()


def unit_key(text: str) -> str:
    """Key for unit alias lookup: no dots, spaces or hyphens."""
    return re.sub(r"[\s.\-]+", "", norm(text))


@dataclass(frozen=True)
class Unit:
    name: str  # canonical name; equals the unit name used in Mealie
    base: str  # base key units of one dimension convert into
    factor: float  # 1 unit = factor base units
    forms: tuple[str, str, str]  # display for 1 / 2-4 / 5+
    aliases: tuple[str, ...] = ()


# Volume is in ml, mass in g; every countable unit is its own base.
UNITS: tuple[Unit, ...] = (
    Unit("мілілітр", "мл", 1, ("мл", "мл", "мл"), ("мл", "ml", "мілілітр", "мілілітри", "мілілітрів")),
    Unit("літр", "мл", 1000, ("л", "л", "л"), ("л", "l", "літр", "літри", "літрів")),
    Unit(
        "ч. ложка", "мл", 5, ("ч. л.", "ч. л.", "ч. л."),
        ("чл", "ч.л.", "ч. ложка", "ч. ложки", "ч. ложок", "чайна ложка", "чайні ложки", "чайних ложок", "tsp", "teaspoon"),
    ),
    Unit(
        "ст. ложка", "мл", 15, ("ст. л.", "ст. л.", "ст. л."),
        ("стл", "ст.л.", "ст. ложка", "ст. ложки", "ст. ложок", "столова ложка", "столові ложки", "столових ложок", "tbsp", "tablespoon"),
    ),
    Unit(
        "склянка", "мл", 250, ("склянка", "склянки", "склянок"),
        ("склянка", "склянки", "склянок", "стакан", "стакани", "стаканів", "cup", "чашка", "чашки", "чашок"),
    ),
    Unit("міліграм", "г", 0.001, ("мг", "мг", "мг"), ("мг", "mg", "міліграм", "міліграми", "міліграмів")),
    Unit("грам", "г", 1, ("г", "г", "г"), ("г", "гр", "g", "грам", "грами", "грамів")),
    Unit("кілограм", "г", 1000, ("кг", "кг", "кг"), ("кг", "kg", "кілограм", "кілограми", "кілограмів", "кіло")),
    Unit("штука", "шт", 1, ("шт", "шт", "шт"), ("шт", "штука", "штуки", "штук", "pcs", "pc")),
    Unit("пучок", "пучок", 1, ("пучок", "пучки", "пучків"), ("пучок", "пучки", "пучків", "пучка")),
    Unit(
        "пачка", "пачка", 1, ("пачка", "пачки", "пачок"),
        ("пачка", "пачки", "пачок", "упаковка", "упаковки", "упаковок"),
    ),
    Unit("банка", "банка", 1, ("банка", "банки", "банок"), ("банка", "банки", "банок")),
    Unit(
        "голівка", "голівка", 1, ("голівка", "голівки", "голівок"),
        ("голівка", "голівки", "голівок", "головка", "головки", "головок"),
    ),
    Unit(
        "зубчик", "зубчик", 1, ("зубчик", "зубчики", "зубчиків"),
        ("зубчик", "зубчики", "зубчиків", "зубок", "зубки", "зубків"),
    ),
    Unit("дрібка", "дрібка", 1, ("дрібка", "дрібки", "дрібок"), ("дрібка", "дрібки", "дрібок", "щіпка", "щіпки", "щіпок")),
    Unit("жменя", "жменя", 1, ("жменя", "жмені", "жмень"), ("жменя", "жмені", "жмень")),
)

# "to taste" markers: such lines are never summed.
TASTE_UNITS = ("трохи",)
TASTE_PHRASES = ("за смаком", "по смаку", "трохи")

UNIT_BY_NAME: dict[str, Unit] = {u.name: u for u in UNITS}
UNIT_BY_KEY: dict[str, Unit] = {}
for _u in UNITS:
    for _alias in (_u.name, *_u.aliases):
        UNIT_BY_KEY.setdefault(unit_key(_alias), _u)

# Display unit for a base key when a line mixes units.
BASE_DISPLAY_UNIT: dict[str, str] = {
    "шт": "штука",
    "пучок": "пучок",
    "пачка": "пачка",
    "банка": "банка",
    "голівка": "голівка",
    "зубчик": "зубчик",
    "дрібка": "дрібка",
    "жменя": "жменя",
}


def lookup_unit(text: str | None, extra: dict[str, str] | None = None) -> Unit | None:
    """Find a unit by name, abbreviation or alias. `extra` maps user aliases to a unit name."""
    if not text:
        return None
    key = unit_key(text)
    if extra and key in extra:
        return UNIT_BY_NAME.get(extra[key])
    return UNIT_BY_KEY.get(key)


def is_taste_unit(text: str | None) -> bool:
    return bool(text) and norm(text) in TASTE_UNITS


def plural_form(n: float, forms: tuple[str, str, str]) -> str:
    """Ukrainian plural form for a quantity (fractions use the genitive singular)."""
    if abs(n - round(n)) > 1e-9:
        return forms[1]
    i = abs(int(round(n)))
    if i % 100 in (11, 12, 13, 14):
        return forms[2]
    if i % 10 == 1:
        return forms[0]
    if i % 10 in (2, 3, 4):
        return forms[1]
    return forms[2]


def fmt_qty(n: float) -> str:
    """Quantity as short text with a decimal comma: 2, 1,5, 0,33."""
    r = round(n + 1e-12, 2)
    if abs(r - round(r)) < 1e-9:
        return str(int(round(r)))
    return f"{r:.2f}".rstrip("0").rstrip(".").replace(".", ",")
