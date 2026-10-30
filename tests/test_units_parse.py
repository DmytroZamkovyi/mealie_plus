import pytest

from custom_components.mealie_plus.core.parse import parse
from custom_components.mealie_plus.core.units import fmt_qty, lookup_unit, plural_form, unit_key


@pytest.mark.parametrize(
    "text,qty,unit,taste,food",
    [
        ("2 кг картоплі", 2, "кілограм", False, "картоплі"),
        ("картопля 2 кг", 2, "кілограм", False, "картопля"),
        ("2 ст. ложки меду", 2, "ст. ложка", False, "меду"),
        ("1 ст.л. олії", 1, "ст. ложка", False, "олії"),
        ("500г борошна", 500, "грам", False, "борошна"),
        ("1 1/2 л молока", 1.5, "літр", False, "молока"),
        ("2 ½ чл зіри", 2.5, "ч. ложка", False, "зіри"),
        ("1,5 кг цибулі", 1.5, "кілограм", False, "цибулі"),
        ("3 яйця", 3, None, False, "яйця"),
        ("молоко", None, None, False, "молоко"),
        ("сіль за смаком", None, None, True, "сіль"),
        ("з 2 зубчики часнику", 2, "зубчик", False, "часнику"),
    ],
)
def test_parse(text, qty, unit, taste, food):
    p = parse(text)
    assert (p.qty, p.unit, p.taste, p.food_text) == (qty, unit, taste, food)


def test_mealie_unit_names_resolve():
    # unit names and abbreviations as they exist in Mealie
    for name in ("ст. ложка", "ч. ложка", "штука", "пучок", "голівка", "зубчик", "мілілітр", "кілограм"):
        assert lookup_unit(name).name == name
    assert lookup_unit("стл").name == "ст. ложка"
    assert lookup_unit("чл").name == "ч. ложка"
    assert lookup_unit("шт").name == "штука"
    assert lookup_unit("не одиниця") is None


def test_unit_key_ignores_dots_and_spaces():
    assert unit_key("Ст. Л.") == unit_key("ст л") == "стл"


def test_plural_and_format():
    forms = ("зубчик", "зубчики", "зубчиків")
    assert [plural_form(n, forms) for n in (1, 2, 5, 11, 12, 21, 22, 25, 1.5)] == [
        "зубчик", "зубчики", "зубчиків", "зубчиків", "зубчиків", "зубчик", "зубчики", "зубчиків", "зубчики",
    ]
    assert fmt_qty(2) == "2" and fmt_qty(1.5) == "1,5" and fmt_qty(0.3333) == "0,33"
