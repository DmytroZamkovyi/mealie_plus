# Shopping Sync

Keep one shared shopping list in Home Assistant, fed by the shopping lists of [Mealie](https://mealie.io), with smart merging and two-way ticking.

[Українська версія](README.uk.md)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=DmytroZamkovyi&repository=shopping_sync&category=integration)
[![Open your Home Assistant instance and start setting up this integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=shopping_sync)

> **Status: early development.** The engine and the Home Assistant part are written, but not yet confirmed on a live system and not released, so there is nothing to install from HACS yet.

## Installation

1. HACS → ⋮ → **Custom repositories** → add this repository, category **Integration** (or use the HACS button above).
2. Download **Shopping Sync**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → Shopping Sync** (or use the second button above). You need the Mealie address and an API token.
4. Create a to-do list named `Mealie: <Mealie list name>` (for example `Mealie: Metro`).

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
