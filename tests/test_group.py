import asyncio
from datetime import timedelta

from custom_components.shopping_sync.core.group import GroupState, sync_group
from custom_components.shopping_sync.core.models import HaItem, SrcItem

from test_engine import CFG, T0, TABLES


class Source:
    def __init__(self):
        self.src: dict[str, SrcItem] = {}
        self._n = 0

    async def items(self):
        return list(self.src.values())

    async def create(self, items):
        out = {}
        for n in items:
            self._n += 1
            i = f"m{self._n}"
            self.src[i] = SrcItem(i, n.list_id, n.food_id, n.food, n.unit, n.qty, n.note, False)
            out[n.tmp] = i
        return out

    async def set_checked(self, ids, checked):
        for i in ids:
            self.src[i].checked = checked

    async def delete(self, ids):
        for i in ids:
            self.src.pop(i, None)

    def add(self, id, food, qty, unit, checked=False):
        self.src[id] = SrcItem(id, "list", None, food, unit, qty, "", checked)


class Target:
    """Any target platform: a to-do list in memory."""

    def __init__(self, tag):
        self.tag = tag
        self.ha: dict[str, HaItem] = {}
        self.down = False
        self._n = 0

    async def items(self):
        if self.down:
            raise RuntimeError("unavailable")
        return list(self.ha.values())

    async def add(self, summary, description, done):
        self._n += 1
        uid = f"{self.tag}{self._n}"
        self.ha[uid] = HaItem(uid, summary, description, done)
        return uid

    async def update(self, uid, summary, description, done):
        h = self.ha[uid]
        if summary is not None:
            h.summary = summary
        if description is not None:
            h.description = description
        if done is not None:
            h.done = done

    async def remove(self, uid):
        self.ha.pop(uid, None)

    def view(self):
        return sorted((h.summary, h.done) for h in self.ha.values())


def run(src, targets, state, now=T0, cfg=CFG):
    res = asyncio.run(sync_group(src, targets, state, cfg, TABLES, now))
    assert not res.errors, res.errors
    return res


def test_all_targets_get_the_merged_list():
    s, a, b = Source(), Target("a"), Target("b")
    s.add("1", "часник", 1, "голівка")
    s.add("2", "часник", 7, "зубчик")
    run(s, {"a": a, "b": b}, GroupState())
    assert a.view() == b.view() == [("Часник, 13 зубчиків", False)]


def test_tick_in_one_target_reaches_the_source_and_every_target():
    s, a, b, c = Source(), Target("a"), Target("b"), Target("c")
    s.add("1", "сіль", 1, "ч. ложка")
    ts = {"a": a, "b": b, "c": c}
    st = run(s, ts, GroupState()).state
    next(iter(b.ha.values())).done = True
    st = run(s, ts, st).state
    assert s.src["1"].checked
    # "a" was handled before "b": it catches up on the next cycle
    st = run(s, ts, st).state
    assert a.view() == b.view() == c.view() == [("Сіль, 1 ч. л.", True)]


def test_untick_and_delete_propagate():
    s, a, b = Source(), Target("a"), Target("b")
    s.add("1", "сіль", 1, "ч. ложка")
    s.add("2", "кріп", 1, "пучок")
    s.add("3", "молоко", 1, "л")
    s.add("4", "картопля", 1, "кг")
    ts = {"a": a, "b": b}
    st = run(s, ts, GroupState()).state
    uid = next(u for u, h in a.ha.items() if h.summary.startswith("Кріп"))
    a.ha[uid].done = True
    st = run(s, ts, st).state
    st = run(s, ts, st).state
    assert s.src["2"].checked and ("Кріп, 1 пучок", True) in b.view()
    b.ha[next(u for u, h in b.ha.items() if h.summary.startswith("Кріп"))].done = False
    st = run(s, ts, st).state
    st = run(s, ts, st).state
    assert not s.src["2"].checked and ("Кріп, 1 пучок", False) in a.view()
    # delete one line in "b": source items go away, "a" follows
    b.ha.pop(next(u for u, h in b.ha.items() if h.summary.startswith("Сіль")))
    st = run(s, ts, st).state
    st = run(s, ts, st).state
    assert "1" not in s.src
    assert not any(h.summary.startswith("Сіль") for h in a.ha.values())


def test_typed_item_in_one_target_reaches_the_others():
    s, a, b = Source(), Target("a"), Target("b")
    ts = {"a": a, "b": b}
    st = run(s, ts, GroupState()).state
    asyncio.run(a.add("2 кг картопля", "", False))
    st = run(s, ts, st).state
    st = run(s, ts, st).state
    assert len(s.src) == 1
    assert a.view() == b.view() and len(a.view()) == 1 and "артопл" in a.view()[0][0]


def test_new_target_gets_the_full_list_and_removed_target_loses_state():
    s, a, b = Source(), Target("a"), Target("b")
    s.add("1", "сіль", 1, "ч. ложка")
    st = run(s, {"a": a}, GroupState()).state
    st = run(s, {"a": a, "b": b}, st).state
    assert b.view() == a.view() == [("Сіль, 1 ч. л.", False)]
    st = run(s, {"b": b}, st).state
    assert set(st.targets) == {"b"}
    assert a.view() == [("Сіль, 1 ч. л.", False)] and "1" in s.src  # nothing deleted anywhere


def test_unavailable_target_is_skipped_and_never_treated_as_empty():
    s, a, b = Source(), Target("a"), Target("b")
    s.add("1", "сіль", 1, "ч. ложка")
    ts = {"a": a, "b": b}
    st = run(s, ts, GroupState()).state
    a.down = True
    res = asyncio.run(sync_group(s, ts, st, CFG, TABLES, T0))
    assert res.skipped == ["a"] and "1" in s.src
    a.down = False
    st = run(s, ts, res.state).state
    assert a.view() == b.view() == [("Сіль, 1 ч. л.", False)]


def test_purge_runs_once_per_group():
    s, a, b = Source(), Target("a"), Target("b")
    s.add("1", "сіль", 1, "ч. ложка", checked=True)
    s.add("2", "кріп", 1, "пучок")
    ts = {"a": a, "b": b}
    st = run(s, ts, GroupState()).state
    res = run(s, ts, st, now=T0 + timedelta(days=8))
    assert res.purged == 1 and set(s.src) == {"2"}
    run(s, ts, res.state, now=T0 + timedelta(days=8, hours=1))
    assert a.view() == b.view() == [("Кріп, 1 пучок", False)]


def test_group_state_json_round_trip():
    s, a = Source(), Target("a")
    s.add("1", "сіль", 1, "ч. ложка")
    st = run(s, {"a": a}, GroupState()).state
    back = GroupState.from_json(st.to_json())
    assert back.to_json() == st.to_json()
    assert not asyncio.run(sync_group(s, {"a": a}, back, CFG, TABLES, T0)).plans["a"].has_changes
