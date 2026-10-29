from custom_components.shopping_sync.core.foods import FoodIndex, FoodRef

FOODS = [
    FoodRef("f1", "картопля"),
    FoodRef("f2", "Молоко", ("whole milk", "milk")),
    FoodRef("f3", "мед", ("г. Мед", "ст. ложка Мед")),
    FoodRef("f4", "Яйце", ("eggs", "шт. Яйця", "штука Яйця")),
    FoodRef("f5", "Томатна паста", ("Паста томатна", "грам Томатна паста")),
    FoodRef("f6", "Куряче філе"),
    FoodRef("f7", "Куряча грудка"),
    FoodRef("f8", "Сир сулугуні"),
    FoodRef("f9", "Сир імеретинський"),
]
IDX = FoodIndex(FOODS)


def food(text):
    r = IDX.resolve(text)
    return r.kind, (r.food.id if r.food else None)


def test_exact_and_inflected_forms():
    assert food("картопля") == ("exact", "f1")
    assert food("картоплі") == ("stem", "f1")
    assert food("молока") == ("stem", "f2")
    assert food("яйця") == ("stem", "f4")


def test_aliases_with_quantity_or_unit_are_cleaned():
    assert food("мед") == ("exact", "f3")
    assert food("меду") == ("stem", "f3")
    assert food("томатна паста")[1] == "f5"


def test_unknown_and_ambiguous():
    assert food("пампушки") == ("none", None)
    kind, _ = food("сир")
    assert kind == "none"  # "сир" alone is not a stem of either full name
    assert IDX.resolve("куряч").kind in ("none", "ambiguous")


def test_user_alias_wins():
    idx = FoodIndex(FOODS, extra_aliases={"картошка": "f1"})
    assert idx.resolve("картошка").food.id == "f1"
