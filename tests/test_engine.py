import asyncio
from datetime import datetime, timedelta, timezone

from custom_components.mealie_plus.core.engine import execute, plan_sync
from custom_components.mealie_plus.core.foods import FoodIndex, FoodRef
from custom_components.mealie_plus.core.models import Config, HaItem, SrcItem, State
from custom_components.mealie_plus.core.tables import default_tables

FOODS = [
    FoodRef("f_garlic", "часник"),
    FoodRef("f_salt", "сіль"),
    FoodRef("f_potato", "картопля"),
    FoodRef("f_milk", "молоко"),
    FoodRef("f_dill", "кріп"),
    FoodRef("f_tomato", "томатна паста"),
    FoodRef("f_sausage_a", "Сир сулугуні"),
    FoodRef("f_sausage_b", "Сир сулугуні копчений"),
]
TABLES = default_tables(FoodIndex(FOODS))
CFG = Config(inbox_list_id="inbox")
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


class World:
    """Both sides in memory; implements the source and target APIs."""

    def __init__(self):
        self.src: dict[str, SrcItem] = {}
        self.ha: dict[str, HaItem] = {}
        self.state = State()
        self._n = 0
        self.fail_src_create = False
        self.fail_ha_add = False

    # --- source API
    async def create(self, items):
        if self.fail_src_create:
            raise RuntimeError("mealie down")
        out = {}
        for n in items:
            self._n += 1
            new_id = f"m{self._n}"
            self.src[new_id] = SrcItem(new_id, n.list_id, n.food_id, n.food, n.unit, n.qty, n.note, False)
            out[n.tmp] = new_id
        return out

    async def set_checked(self, ids, checked):
        for i in ids:
            self.src[i].checked = checked

    async def delete(self, ids):
        for i in ids:
            self.src.pop(i, None)

    # --- target API
    async def add(self, summary, description, done):
        if self.fail_ha_add:
            raise RuntimeError("ha down")
        self._n += 1
        uid = f"h{self._n}"
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

    # --- helpers
    def add_src(self, id, food, qty, unit, checked=False, note="", food_id=None):
        self.src[id] = SrcItem(id, "list", food_id, food, unit, qty, note, checked)

    def cycle(self, now=T0, cfg=CFG, tables=TABLES):
        plan = plan_sync(list(self.src.values()), list(self.ha.values()), self.state, cfg, tables, now)
        res = asyncio.run(execute(plan, self, self))
        assert not res.errors, res.errors
        self.state = res.state
        return plan

    def view(self):
        return sorted((h.summary, h.done) for h in self.ha.values())


def test_initial_sync_merges_into_lines():
    w = World()
    w.add_src("a", "часник", 1, "голівка")
    w.add_src("b", "часник", 7, "зубчик")
    w.add_src("c", "сіль", 1, "ч. ложка")
    w.add_src("d", "сіль", 1, "ст. ложка")
    w.cycle()
    assert w.view() == [("Сіль, 20 мл", False), ("Часник, 13 зубчиків", False)]


def test_second_cycle_changes_nothing():
    w = World()
    w.add_src("a", "часник", 1, "голівка")
    w.add_src("b", "кріп", 1, "пучок")
    w.cycle()
    plan = w.cycle()
    assert not plan.has_changes and not plan.issues


def test_new_source_item_updates_the_same_line():
    w = World()
    w.add_src("a", "сіль", 1, "ч. ложка")
    w.cycle()
    uid = next(iter(w.ha))
    w.add_src("b", "сіль", 1, "ст. ложка")
    w.cycle()
    assert list(w.ha) == [uid]  # same target item, new amount
    assert w.ha[uid].summary == "Сіль, 20 мл"


def test_ticking_in_target_ticks_all_source_items_and_keeps_the_line():
    w = World()
    w.add_src("a", "сіль", 1, "ч. ложка")
    w.add_src("b", "сіль", 1, "ст. ложка")
    w.cycle()
    uid = next(iter(w.ha))
    w.ha[uid].done = True
    w.cycle()
    assert w.src["a"].checked and w.src["b"].checked
    assert list(w.ha) == [uid] and w.ha[uid].done  # one ticked line, no flicker
    assert not w.cycle().has_changes


def test_new_item_after_ticking_makes_a_separate_open_line():
    w = World()
    w.add_src("a", "сіль", 1, "ч. ложка")
    w.cycle()
    uid = next(iter(w.ha))
    w.ha[uid].done = True
    w.cycle()
    w.add_src("b", "сіль", 2, "ч. ложка")
    w.cycle()
    assert w.view() == [("Сіль, 1 ч. л.", True), ("Сіль, 2 ч. л.", False)]


def test_ticking_in_source_ticks_the_target_line():
    w = World()
    w.add_src("a", "кріп", 1, "пучок")
    w.cycle()
    uid = next(iter(w.ha))
    w.src["a"].checked = True
    w.cycle()
    assert list(w.ha) == [uid] and w.ha[uid].done
    w.src["a"].checked = False
    w.cycle()
    assert not w.ha[uid].done


def test_unticking_in_target_unticks_source():
    w = World()
    w.add_src("a", "кріп", 1, "пучок", checked=True)
    w.cycle()
    uid = next(iter(w.ha))
    assert w.ha[uid].done
    w.ha[uid].done = False
    w.cycle()
    assert not w.src["a"].checked


def test_deleting_a_line_in_target_deletes_source_items():
    w = World()
    w.add_src("a", "сіль", 1, "ч. ложка")
    w.add_src("b", "сіль", 1, "ст. ложка")
    w.add_src("c", "кріп", 1, "пучок")
    w.cycle()
    uid = next(u for u, h in w.ha.items() if h.summary.startswith("Сіль"))
    del w.ha[uid]
    w.cycle()
    assert set(w.src) == {"c"}


def test_mass_deletion_is_blocked_and_lines_come_back():
    w = World()
    for i, food in enumerate(["сіль", "кріп", "картопля", "молоко", "часник"]):
        w.add_src(str(i), food, 1, "штука")
    w.cycle()
    w.ha.clear()  # e.g. the to-do list was wiped
    plan = w.cycle()
    assert plan.blocked_deletes == 5
    assert len(w.src) == 5 and len(w.ha) == 5  # nothing lost, lines restored


def test_delete_propagation_can_be_switched_off():
    w = World()
    w.add_src("a", "кріп", 1, "пучок")
    w.cycle()
    w.ha.clear()
    cfg = Config(inbox_list_id="inbox", propagate_deletes=False)
    w.cycle(cfg=cfg)
    assert "a" in w.src and len(w.ha) == 1


def test_item_removed_in_source_disappears_from_target():
    w = World()
    w.add_src("a", "кріп", 1, "пучок")
    w.cycle()
    del w.src["a"]
    w.cycle()
    assert not w.ha


def test_typed_item_is_created_in_source_and_adopted():
    w = World()
    w.ha["t1"] = HaItem("t1", "2 кг картоплі", "", False)
    w.cycle()
    assert [(s.food, s.qty, s.unit, s.list_id) for s in w.src.values()] == [
        ("картопля", 2, "кілограм", "inbox")
    ]
    assert list(w.ha) == ["t1"] and w.ha["t1"].summary == "Картопля, 2 кг"
    assert not w.cycle().has_changes


def test_typed_item_merges_into_an_existing_line():
    w = World()
    w.add_src("a", "картопля", 700, "грам", food_id="f_potato")
    w.cycle()
    line_uid = next(iter(w.ha))
    w.ha["t1"] = HaItem("t1", "1 кг картоплі", "", False)
    w.cycle()
    assert list(w.ha) == [line_uid]  # the typed text became part of the line
    assert w.ha[line_uid].summary == "Картопля, 1,7 кг"
    assert len(w.src) == 2


def test_typed_taste_item_and_unknown_text():
    w = World()
    w.ha["t1"] = HaItem("t1", "сіль за смаком", "", False)
    w.ha["t2"] = HaItem("t2", "пампушки до борщу", "", False)
    w.cycle()
    assert w.view() == [("Пампушки до борщу", False), ("Сіль, за смаком", False)]
    assert not w.cycle().has_changes


def test_typed_items_are_ignored_without_inbox_list():
    w = World()
    w.ha["t1"] = HaItem("t1", "молоко", "", False)
    w.cycle(cfg=Config(inbox_list_id=None))
    assert w.ha["t1"].summary == "молоко" and not w.src


def test_ambiguous_typed_food_raises_an_issue_but_still_adds_text():
    foods = [FoodRef("x1", "Ковбаса мисливська", ("ковбаса",)), FoodRef("x2", "Ковбаса варена", ("ковбаса",))]
    tables = default_tables(FoodIndex(foods))
    w = World()
    w.ha["t1"] = HaItem("t1", "ковбаса", "", False)
    plan = w.cycle(tables=tables)
    assert [(i.kind, i.ha_uid, sorted(c.id for c in i.candidates)) for i in plan.issues] == [
        ("ambiguous_food", "t1", ["x1", "x2"])
    ]
    assert w.ha["t1"].summary == "Ковбаса"  # kept as free text until the person picks


def test_user_edit_of_a_line_is_reverted():
    w = World()
    w.add_src("a", "кріп", 1, "пучок")
    w.cycle()
    uid = next(iter(w.ha))
    w.ha[uid].summary = "щось своє"
    w.cycle()
    assert w.ha[uid].summary == "Кріп, 1 пучок"


def test_weekly_purge_removes_ticked_items_everywhere():
    w = World()
    w.add_src("a", "кріп", 1, "пучок", checked=True)
    w.add_src("b", "сіль", 1, "ч. ложка")
    w.cycle(now=T0)  # first run only stamps the purge clock
    assert len(w.src) == 2
    w.cycle(now=T0 + timedelta(days=3))
    assert len(w.src) == 2
    plan = w.cycle(now=T0 + timedelta(days=7, minutes=1))
    assert plan.purged == 1 and set(w.src) == {"b"}
    assert w.view() == [("Сіль, 1 ч. л.", False)]
    assert not w.cycle(now=T0 + timedelta(days=8)).has_changes


def test_purge_can_be_disabled():
    w = World()
    w.add_src("a", "кріп", 1, "пучок", checked=True)
    cfg = Config(inbox_list_id="inbox", purge_days=0)
    w.cycle(now=T0, cfg=cfg)
    w.cycle(now=T0 + timedelta(days=30), cfg=cfg)
    assert "a" in w.src


def test_state_survives_json_round_trip():
    w = World()
    w.add_src("a", "часник", 1, "голівка")
    w.add_src("b", "часник", 7, "зубчик")
    w.cycle()
    w.state = State.from_json(w.state.to_json())
    assert not w.cycle().has_changes


def test_failed_source_create_does_not_duplicate_or_lose_the_typed_item():
    w = World()
    w.ha["t1"] = HaItem("t1", "2 кг картоплі", "", False)
    w.fail_src_create = True
    plan = plan_sync([], list(w.ha.values()), w.state, CFG, TABLES, T0)
    res = asyncio.run(execute(plan, w, w))
    assert res.errors
    w.state = res.state
    assert "t1" in w.ha and not w.src
    w.fail_src_create = False
    w.cycle()  # next cycle retries cleanly
    assert len(w.src) == 1 and list(w.ha) == ["t1"]


def test_failed_target_add_is_retried():
    w = World()
    w.add_src("a", "кріп", 1, "пучок")
    w.fail_ha_add = True
    plan = plan_sync(list(w.src.values()), [], w.state, CFG, TABLES, T0)
    res = asyncio.run(execute(plan, w, w))
    assert res.errors and not res.state.links
    w.state = res.state
    w.fail_ha_add = False
    w.cycle()
    assert w.view() == [("Кріп, 1 пучок", False)]


def test_failed_create_keeps_a_typed_item_that_would_have_merged():
    w = World()
    w.add_src("a", "картопля", 700, "грам", food_id="f_potato")
    w.cycle()
    w.ha["t1"] = HaItem("t1", "1 кг картоплі", "", False)
    w.fail_src_create = True
    plan = plan_sync(list(w.src.values()), list(w.ha.values()), w.state, CFG, TABLES, T0)
    res = asyncio.run(execute(plan, w, w))
    assert res.errors
    w.state = res.state
    assert "t1" in w.ha and w.ha["t1"].summary == "1 кг картоплі"
    w.fail_src_create = False
    w.cycle()
    assert [h.summary for h in w.ha.values()] == ["Картопля, 1,7 кг"]
