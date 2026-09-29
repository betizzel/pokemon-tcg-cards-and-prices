# Pokémon TCG cards and prices

Data mining project: **can we look at a card and predict whether its price will go up or down?**

This repo links two public datasets:

| Dataset | What it has | Source |
|---|---|---|
| Card stats | 18,210 English cards, 162 sets (to Sep 2024): HP, types, attacks, weaknesses, retreat cost, rarity, artist, number; set release dates | [HF `tpot1515/pokemoncards`](https://huggingface.co/datasets/tpot1515/pokemoncards) → `data/tpot.csv`, `data/sets.csv` |
| Price history | 30,277 PriceCharting products, monthly Dec 2020 – Nov 2024: Ungraded, PSA 7/8/9/10, BGS 9.5 prices and sales volume | [Kaggle `davidkim2003/pokemon-pricecharting-historic-data`](https://www.kaggle.com/datasets/davidkim2003/pokemon-pricecharting-historic-data) → `data/historic.csv` (**not in git**, see setup) |

The price history only identifies cards by PriceCharting product id, so the
scripts here map those ids to cards in the stats table.

## Setup

```sh
pip install -r requirements.txt

# historic.csv is 176 MB (over GitHub's file limit); download it once:
curl -L -o historic.zip https://www.kaggle.com/api/v1/datasets/download/davidkim2003/pokemon-pricecharting-historic-data
unzip historic.zip -d data && rm historic.zip
```

## Files

| File | Contents |
|---|---|
| `data/historic.csv` | `id` + one JSON column per grade (`Ungraded`, `PSA7`, `PSA8`, `PSA9`, `BGS9.5`, `PSA10`, `volume`), each a list of `[unix_ms, price]` monthly points. Prices are in **cents** (base Charizard unlimited, Nov 2024: `20468` = $204.68); `0` means no price that month. |
| `data/tpot.csv`, `data/sets.csv` | Card stats and set metadata. Card `id` is `<set id>-<number>`, e.g. `base1-4`. |
| `data/id_map.csv` | Step 1 output: PriceCharting `id` → `set_slug`, `card_slug` for 67,548 products (99.9% of `historic.csv`; 39 ids no longer exist, listed in `data/id_unmapped.txt`). |
| `data/card_links.csv` | Step 2 output: `pc_id` (PriceCharting id) → `card_id` (stats id), `variant`, `name_match`. 30,165 price series linked to 16,812 distinct cards. |
| `data/card_unmatched.csv` | The 73 price series that could not be linked, with the reason. |

### `card_links.csv` columns

- `variant`: printing tag from PriceCharting, `""` for the base printing. Most common: `reverse-holo`, `1st-edition`, `holo`, `cosmos-holo`, `jumbo`, `shadowless`, `prize-pack`, `stamped`. Several PriceCharting products can map to the same card (one per printing).
- `name_match`: `True` if the card name agrees with PriceCharting's; `False` means it was matched on set + number plus at least one shared name word (98.7% are `True`).

### Joining everything

```python
import json
import pandas as pd

links = pd.read_csv("data/card_links.csv", dtype={"pc_id": str}, keep_default_na=False)
cards = pd.read_csv("data/tpot.csv")
hist = pd.read_csv("data/historic.csv", dtype={"id": str})

df = links.merge(cards, left_on="card_id", right_on="id").merge(hist, left_on="pc_id", right_on="id", suffixes=("", "_pc"))
df["Ungraded"] = df["Ungraded"].map(json.loads)  # [[unix_ms, price], ...]
```

## Reproducing the mapping

You don't need to rerun these; their outputs are committed.

- `resolve_ids.py` (step 1): crawls PriceCharting's Pokémon set pages (~400 requests at 1 req/s), falling back to `/game/<id>` redirects for ids not listed on a set page. Writes `data/id_map.csv`. Takes about an hour.
- `match_cards.py` (step 2): offline, ~20 s. Maps PriceCharting set names to stats sets (with hand-written overrides for subsets and promos in `SET_OVERRIDES`), normalises card numbers (`SWSH005` = `swsh5`), and uses the name to break ties and to reject wrong same-number matches. Writes `data/card_links.csv` and `data/card_unmatched.csv`.

## Next steps

- Reshape to one row per card per month (≈1.24M rows).
- Target: did the ungraded price rise more than X% over the next 6 months?
- Split train/test **by time** (e.g. train 2021–2023, test 2024), not randomly, to avoid leaking the future.
