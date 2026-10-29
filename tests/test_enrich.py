from custom_components.shopping_sync.core.enrich import (
    empty_nutrition_keys,
    food_prompt,
    parse_json,
    recipe_prompt,
    validate_foods,
    validate_recipe,
    validate_units,
)

LABELS = {"Овочі": "L1", "Молочні": "L2"}
FOODS = [("f1", "морква"), ("f2", "сир")]


def test_parse_json_tolerates_fences_and_noise():
    assert parse_json('```json\n{"0": {"label": "Овочі"}}\n```') == {"0": {"label": "Овочі"}}
    assert parse_json('Ось: {"0": 1} готово') == {"0": 1}
    assert parse_json("нічого") is None


def test_food_labels_only_from_known_names_and_aliases_are_clean():
    ans = {
        "0": {"label": "овочі", "aliases": ["Морквина", "морква", "2 моркви", "", "x" * 50, "корінь", 5]},
        "1": {"label": "Вигадана", "aliases": []},
        "9": {"label": "Овочі"},  # unknown index is ignored
        "x": {},
    }
    out = validate_foods(ans, FOODS, LABELS, {"морква", "сир"}, True, True)
    assert out["f1"].label_id == "L1"
    assert out["f1"].aliases == ["морквина", "корінь"]  # existing name, digits, empty, long, non-string dropped
    assert "f2" not in out  # unknown label and no aliases: nothing to apply


def test_food_toggles_are_respected():
    ans = {"0": {"label": "Овочі", "aliases": ["корінь"]}}
    only_labels = validate_foods(ans, FOODS, LABELS, set(), True, False)
    assert only_labels["f1"].label_id == "L1" and only_labels["f1"].aliases == []
    only_aliases = validate_foods(ans, FOODS, LABELS, set(), False, True)
    assert only_aliases["f1"].label_id is None and only_aliases["f1"].aliases == ["корінь"]


def test_units_must_be_known_and_null_is_skipped():
    out = validate_units({"0": "штука", "1": None, "2": "парсек", "3": "ШТУКА"}, ["a", "b", "c", "d"], {"штука": "U1"})
    assert out == {"a": "U1", "d": "U1"}


def test_recipe_answer_is_cleaned():
    ans = {
        "description": "  Смачний   борщ.  ",
        "nutrition": {"calories": 250.4, "proteinContent": "7,5 г", "fatContent": -1, "sugarContent": True, "other": 1},
        "tools": ["Каструля", "каструля", "", "x" * 40, 5, "Блендер"],
    }
    keys = ["calories", "proteinContent", "fatContent", "sugarContent"]
    p = validate_recipe(ans, True, keys, True)
    assert p.description == "Смачний борщ."
    assert p.nutrition == {"calories": "250", "proteinContent": "7.5"}
    assert p.tools == ["Каструля", "Блендер"]
    assert not validate_recipe({"description": "x"}, False, [], False)


def test_only_empty_nutrition_keys_are_requested():
    keys = empty_nutrition_keys({"calories": "300", "fatContent": "", "proteinContent": None})
    assert "calories" not in keys and "fatContent" in keys and "proteinContent" in keys


def test_prompts_mention_only_what_is_wanted():
    assert "aliases" not in food_prompt(["морква"], ["Овочі"], True, False)
    p = recipe_prompt("Борщ", ["буряк"], 4, ["Каструля"], False, ["calories"], False)
    assert "description" not in p and "calories" in p and "tools" not in p


def test_tools_prompt_is_strict_and_sees_the_steps():
    p = recipe_prompt("Шакшука", ["яйце"], 2, [], False, [], True, ["Розбийте яйця.", "Смажте 5 хв."])
    assert "Never list basic items" in p and "Розбийте яйця." in p
