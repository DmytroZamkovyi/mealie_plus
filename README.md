# Shopping Sync

Keep one shared shopping list in Home Assistant, fed by the shopping lists of [Mealie](https://mealie.io), with smart merging and two-way ticking.

[Українська версія](README.uk.md)

> **Status: early development.** The engine and the Home Assistant part are written, but not yet confirmed on a live system and not released, so there is nothing to install from HACS yet.

## What it will do

- Reads each Mealie shopping list and writes **one merged list** into Home Assistant `todo` lists. A list named `Mealie: <Mealie list name>` (the prefix is configurable) is synced automatically with that Mealie list, for every user who has such a list. Lists are not merged with each other.
- Ticking an item in Mealie or in any of those lists ticks it everywhere.
- Other platforms can be attached to a list as extra targets (`async_register_external_target`), and a webhook (`/api/webhook/<id>`, shown in the options) triggers a sync right away.
- **Merges what Mealie does not**: `1 tsp + 1 tbsp` of salt becomes `Salt, 20 ml`; `1 head + 7 cloves` of garlic becomes `13 cloves`; sunflower and vegetable oil are one product; "to taste" lines collapse into one.
- **Two-way**: tick an item in Home Assistant and every Mealie item behind it is ticked (and the other way round). Delete a line and its Mealie items go with it (with a mass-deletion guard).
- Text typed or dictated in Home Assistant (`2 kg potatoes`) is parsed and added to a Mealie list.
- Ticked items are removed once a week from both sides, so the list does not grow forever.
- Units, conversions, synonyms and densities are approximate on purpose and can be edited.
- Everything is configured in the Home Assistant UI. No YAML, no custom cards.

## Development

The integration lives in the repository root (HACS `content_in_root`). Tests:

```
python -m pytest -c tests/pytest.ini tests
```

## License

MIT
