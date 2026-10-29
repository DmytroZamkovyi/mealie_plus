"""Merge source items into shopping lines: unit conversion, bridges, rendering."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import SrcItem
from .parse import parse
from .tables import Tables, clean_name
from .units import (
    BASE_DISPLAY_UNIT,
    TASTE_PHRASES,
    UNIT_BY_NAME,
    fmt_qty,
    is_taste_unit,
    lookup_unit,
    norm,
    plural_form,
)

TASTE = "taste"  # "за смаком": never summed
BARE = "bare"  # no quantity at all


@dataclass
class Entry:
    id: str
    food_key: str
    display: str
    qty: float | None
    unit: str | None
    taste: bool
    note: str = ""


@dataclass
class Line:
    food_key: str
    base: str
    display: str
    amount: float = 0.0
    members: list[str] = field(default_factory=list)
    parts: list[tuple[float | None, str | None]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.food_key}|{self.base}"


def entry_for_item(item: SrcItem, tables: Tables) -> Entry:
    if item.food:
        name = item.food
        qty, unit = item.qty, item.unit
        taste = is_taste_unit(unit) or any(p in norm(item.note) for p in TASTE_PHRASES)
        note = clean_name(item.note)
    else:
        p = parse(item.note, tables.extra_unit_aliases)
        name = p.food_text or clean_name(item.note)
        if tables.foods and p.food_text:
            res = tables.foods.resolve(p.food_text)
            if res.food:
                name = res.food.name
        qty, unit, taste, note = p.qty, p.unit, p.taste, ""
    if qty is not None and qty <= 0:
        qty = None
    return Entry(
        id=item.id,
        food_key=tables.food_key(name),
        display=tables.display_name(name),
        qty=qty,
        unit=unit,
        taste=taste,
        note=note,
    )


def to_base(e: Entry, tables: Tables) -> tuple[str, float]:
    if e.taste:
        return TASTE, 0.0
    if e.qty is None:
        return BARE, 0.0
    u = lookup_unit(e.unit, tables.extra_unit_aliases) if e.unit else None
    if e.unit and not u:
        base, amount = "u:" + norm(e.unit), e.qty
    elif u:
        base, amount = u.base, e.qty * u.factor
    else:
        base, amount = "шт", e.qty
    eq = tables.base_equiv.get(e.food_key, {}).get(base)
    if eq:
        base, amount = eq[0], amount * eq[1]
    return base, amount


def _absorb(groups: dict[str, Line], src: str, dst: str, factor: float) -> None:
    a, b = groups[src], groups[dst]
    b.amount += a.amount * factor
    b.members += a.members
    b.parts += a.parts
    b.notes += a.notes
    del groups[src]


def build_lines(entries: list[Entry], tables: Tables) -> list[Line]:
    """Group entries (all with the same checked state) into lines."""
    by_food: dict[str, list[Entry]] = {}
    for e in entries:
        by_food.setdefault(e.food_key, []).append(e)
    lines: list[Line] = []
    for fk, es in by_food.items():
        groups: dict[str, Line] = {}
        for e in es:
            base, amount = to_base(e, tables)
            g = groups.setdefault(base, Line(fk, base, e.display))
            g.amount += amount
            g.members.append(e.id)
            if base not in (TASTE, BARE):
                g.parts.append((e.qty, e.unit))
            if e.note:
                g.notes.append(e.note)
        bridges = {**tables.global_bridges, **tables.food_bridges.get(fk, {})}
        changed = True
        while changed:
            changed = False
            for (frm, to), factor in bridges.items():
                if frm in groups and to in groups and frm != to:
                    _absorb(groups, frm, to, factor)
                    changed = True
        quantified = [b for b in groups if b not in (TASTE, BARE)]
        if quantified:
            for vague in (TASTE, BARE):
                if vague in groups:
                    _absorb(groups, vague, quantified[0], 0.0)
        elif TASTE in groups and BARE in groups:
            _absorb(groups, BARE, TASTE, 0.0)
        lines.extend(groups.values())
    return lines


def _unit_text(qty: float, unit: str | None) -> str:
    u = lookup_unit(unit) if unit else UNIT_BY_NAME["штука"]
    form = plural_form(qty, u.forms) if u else (unit or "")
    return f"{fmt_qty(qty)} {form}"


def quantity_text(line: Line) -> str:
    units = {(u or "штука") for q, u in line.parts if q is not None}
    if len(units) == 1:
        unit = next(iter(units))
        small = unit in ("грам", "мілілітр") and line.amount >= 1000  # 1400 г reads better as 1,4 кг
        if not small:
            return _unit_text(sum(q for q, _ in line.parts if q is not None), unit)
    if line.base == "мл":
        return f"{fmt_qty(line.amount / 1000)} л" if line.amount >= 1000 else f"{fmt_qty(line.amount)} мл"
    if line.base == "г":
        return f"{fmt_qty(line.amount / 1000)} кг" if line.amount >= 1000 else f"{fmt_qty(line.amount)} г"
    unit = BASE_DISPLAY_UNIT.get(line.base)
    if unit:
        return _unit_text(line.amount, unit)
    return fmt_qty(line.amount)


def render(line: Line) -> tuple[str, str]:
    """Summary and description of a line for the target list."""
    if line.base == TASTE:
        summary = f"{line.display}, за смаком"
    elif line.base == BARE:
        summary = line.display
    else:
        summary = f"{line.display}, {quantity_text(line)}"
    sections = []
    if len(line.parts) > 1:
        sections.append("Об'єднано: " + "; ".join(_unit_text(q, u) for q, u in line.parts if q is not None))
    notes = list(dict.fromkeys(line.notes))
    if notes:
        sections.append("Примітки: " + "; ".join(notes))
    return summary, "\n".join(sections)
