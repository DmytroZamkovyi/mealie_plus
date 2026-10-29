"""Parse free text such as "2 кг картоплі" or "сіль за смаком"."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .units import TASTE_PHRASES, lookup_unit, norm

_NUM = re.compile(r"^(\d+(?:[.,]\d+)?)$")
_FRAC = re.compile(r"^(\d+)/(\d+)$")
_GLUED = re.compile(r"^(\d+(?:[.,]\d+)?)([^\W\d_][^\s]*)$")
_VULGAR = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3}
_FILLER = {"з", "із", "зі", "of"}


@dataclass
class Parsed:
    qty: float | None
    unit: str | None  # canonical unit name
    taste: bool
    food_text: str


def _number(tok: str) -> float | None:
    if tok in _VULGAR:
        return _VULGAR[tok]
    if _NUM.match(tok):
        return float(tok.replace(",", "."))
    m = _FRAC.match(tok)
    if m and int(m.group(2)):
        return int(m.group(1)) / int(m.group(2))
    return None


def parse(text: str, extra_units: dict[str, str] | None = None) -> Parsed:
    t = norm(text)
    taste = False
    for phrase in TASTE_PHRASES:
        if phrase in t:
            taste = True
            t = t.replace(phrase, " ")
    tokens = [w.strip(",;") for w in t.split() if w.strip(",;")]

    # first token that starts a number: "2", "1/2", "½", or glued "500г"
    start = None
    glued_unit = None
    for i, tok in enumerate(tokens):
        if _number(tok) is not None:
            start = i
            break
        m = _GLUED.match(tok)
        if m and lookup_unit(m.group(2), extra_units):
            start = i
            glued_unit = m.group(2)
            break
    if start is None:
        return Parsed(None, None, taste, " ".join(tokens))

    qty = 0.0
    i = start
    if glued_unit is not None:
        qty = float(_GLUED.match(tokens[i]).group(1).replace(",", "."))
        i += 1
        unit = lookup_unit(glued_unit, extra_units)
    else:
        while i < len(tokens) and (v := _number(tokens[i])) is not None:
            qty += v
            i += 1
        unit = None
        if i + 1 < len(tokens):
            u = lookup_unit(tokens[i] + " " + tokens[i + 1], extra_units)
            if u:
                unit = u
                i += 2
        if unit is None and i < len(tokens):
            u = lookup_unit(tokens[i], extra_units)
            if u:
                unit = u
                i += 1
    rest = tokens[:start] + tokens[i:]
    while rest and rest[0] in _FILLER:
        rest = rest[1:]
    return Parsed(qty, unit.name if unit else None, taste, " ".join(rest))
