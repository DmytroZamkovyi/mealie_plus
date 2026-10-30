from custom_components.mealie_plus.core.merge import Entry, build_lines, render
from custom_components.mealie_plus.core.tables import default_tables

T = default_tables()


def E(i, food, qty=None, unit=None, taste=False, note=""):
    return Entry(i, T.food_key(food), T.display_name(food), qty, unit, taste, note)


def merged(*entries):
    return sorted((render(ln)[0], sorted(ln.members)) for ln in build_lines(list(entries), T))


def test_same_food_same_unit_adds_up():
    assert merged(E("1", "чорний перець", 0.5, "ч. ложка"), E("2", "чорний перець", 0.5, "ч. ложка")) == [
        ("Чорний перець, 1 ч. л.", ["1", "2"])
    ]


def test_spoons_merge_into_millilitres():
    # 1 tsp + 1 tbsp of salt: the case Mealie leaves as two lines
    assert merged(E("1", "сіль", 1, "ч. ложка"), E("2", "сіль", 1, "ст. ложка")) == [("Сіль, 20 мл", ["1", "2"])]


def test_garlic_head_is_six_cloves():
    # the real example: 1 head + 7 cloves
    out = merged(E("1", "часник", 1, "голівка"), E("2", "часник", 7, "зубчик"))
    assert out == [("Часник, 13 зубчиків", ["1", "2"])]


def test_oil_synonyms_are_one_food():
    out = merged(E("1", "Соняшникова олія", 2, "ст. ложка"), E("2", "Рослинна олія", 60, "мілілітр"))
    assert out == [("Соняшникова олія, 90 мл", ["1", "2"])]


def test_mass_and_volume_merge_only_with_density():
    assert merged(E("1", "борошно", 1, "склянка"), E("2", "борошно", 200, "грам")) == [
        ("Борошно, 337,5 г", ["1", "2"])
    ]
    # no density for yoghurt: two separate lines
    assert len(merged(E("1", "йогурт", 1, "склянка"), E("2", "йогурт", 200, "грам"))) == 2


def test_pieces_and_grams_for_known_foods():
    assert merged(E("1", "цибуля", 600, "грам"), E("2", "жовта цибуля", 2, "штука")) == [
        ("Цибуля, 800 г", ["1", "2"])
    ]


def test_kilograms_roll_over():
    assert merged(E("1", "картопля", 700, "грам"), E("2", "картопля", 700, "грам")) == [
        ("Картопля, 1,4 кг", ["1", "2"])
    ]
    assert merged(E("1", "картопля", 0.4, "кілограм"), E("2", "картопля", 0.3, "кілограм")) == [
        ("Картопля, 0,7 кг", ["1", "2"])
    ]


def test_taste_collapses_to_one_line():
    assert merged(E("1", "сіль", taste=True), E("2", "сіль", None, "трохи", taste=True)) == [
        ("Сіль, за смаком", ["1", "2"])
    ]


def test_taste_is_absorbed_by_quantified_line():
    out = merged(E("1", "сіль", 2, "ч. ложка"), E("2", "сіль", taste=True))
    assert out == [("Сіль, 2 ч. л.", ["1", "2"])]  # still ticked together


def test_bare_item_is_just_a_name():
    assert merged(E("1", "молоко")) == [("Молоко", ["1"])]


def test_unknown_unit_gets_its_own_line():
    out = merged(E("1", "пампушки", 2, "порції"), E("2", "пампушки", 3, "порції"))
    assert out == [("Пампушки, 5 порції", ["1", "2"])]


def test_description_lists_parts_and_notes():
    ln = build_lines([E("1", "печериці", 300, "грам", note="або лісових грибів"), E("2", "печериці", 100, "грам")], T)[0]
    summary, description = render(ln)
    assert summary == "Печериці, 400 г"
    assert "300 г; 100 г" in description and "або лісових грибів" in description
