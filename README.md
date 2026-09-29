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
python main.py
```

`main.py` is the working script for the project. On the first run it downloads
`data/historic.csv` from Kaggle (176 MB, too big for GitHub; no login needed),
builds the combined table and caches it as `data/combined.parquet` (~1.5 min).
Later runs load the cache in seconds. Put analysis in `analyze()`.

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

### Combined table (`main.py`)

`load_data()` in `main.py` returns one row per (PriceCharting product, month): 1,241,631 rows × 33 columns for 30,165 price series / 16,812 cards, 2020-12 to 2024-11.

- `pc_id`, `card_id`, `variant` (`base` for the base printing), `name_match`
- `month` (`YYYY-MM`)
- `price_ungraded`, `price_psa7`, `price_psa8`, `price_psa9`, `price_bgs9_5`, `price_psa10`: **USD** (already converted from cents), `NaN` when there was no price that month
- `volume`: PriceCharting sales volume that month
- card stats from `tpot.csv` (`name`, `supertype`, `subtypes`, `hp`, `types`, `attacks`, `weaknesses`, `rarity`, `artist`, …; list-like columns are JSON strings) and set info (`set_id`, `set_name`, `set_series`, `set_release_date`)

It is cached as `data/combined.parquet` (git-ignored; delete it to rebuild).

## Reproducing the mapping

You don't need to rerun these; their outputs are committed.

- `resolve_ids.py` (step 1): crawls PriceCharting's Pokémon set pages (~400 requests at 1 req/s), falling back to `/game/<id>` redirects for ids not listed on a set page. Writes `data/id_map.csv`. Takes about an hour.
- `match_cards.py` (step 2): offline, ~20 s. Maps PriceCharting set names to stats sets (with hand-written overrides for subsets and promos in `SET_OVERRIDES`), normalises card numbers (`SWSH005` = `swsh5`), and uses the name to break ties and to reject wrong same-number matches. Writes `data/card_links.csv` and `data/card_unmatched.csv`.

## Next steps

- Target: did the ungraded price rise more than X% over the next 6 months? (build it in `analyze()` in `main.py`)
- Split train/test **by time** (e.g. train 2021–2023, test 2024), not randomly, to avoid leaking the future.
