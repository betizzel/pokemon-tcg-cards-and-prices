# Pokémon TCG cards and prices

## Research questions

1. Can historical pricing trends and card characteristics predict whether an individual Pokémon card's value will increase or decrease?
2. Which Pokémon card characteristics, such as rarity, age, and grading condition, are most strongly associated with market value?
3. Have individual Pokémon card prices increased faster than general consumer inflation?

The inflation question is possible future work. We'd need a consumer price
index for the same currency and months.

So far, we've done initial EDA and exploratory clustering. We haven't built a
price-direction predictor or established which characteristics cause value.

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

`main.py` loads the combined data and prints a small overview. On the first run
it downloads `data/historic.csv` from Kaggle and builds
`data/combined.parquet`. Later runs use the cache.

## Reading the analysis

1. **[EDA.ipynb](EDA.ipynb)** — what a row represents, prices by rarity, a first
   grade comparison, and missing prices versus missing months.
2. **[Clustering_Characteristics.ipynb](Clustering_Characteristics.ipynb)** —
   the main model, preprocessing, elbow/silhouette checks, and K=2/3/4
   comparison. The subtype experiment is kept in Appendix A.
3. **[Clustering_History_Interpretation.ipynb](Clustering_History_Interpretation.ipynb)** —
   price history and coverage, matched base/reverse-holo prices, and one-year
   changes for the same products.
4. **[Clustering_Feature_Experiments.ipynb](Clustering_Feature_Experiments.ipynb)** —
   the 17 extra feature trials. This is the experiment log, not a list of
   features we've decided to keep.

### Working choices

- One row per product/printing, not per monthly price observation.
- Inputs: **set age, rarity, and printing**. Prices are compared after fitting.
- **K=4 is the working reference.** K=2 and K=3 were also fitted on the same
  29,877 products; their tradeoffs are in Section 9 of the main notebook.
- Missing prices don't exclude a product from a characteristics cluster.
  Missing required characteristics do, with the exclusions recorded.
- Age is measured at November 2024. Price comparisons are mainly ungraded;
  grades aren't treated as the condition of a particular physical copy.

### Observations so far

- In this setup, the groups mostly follow age and printing. Price ranges still
  overlap, so a group isn't a fixed value tier.
- Equal group medians can hide a matched printing difference. Among 6,702
  card IDs with one eligible base/reverse-holo pair and both November 2024
  prices, reverse-holo was higher in 82.1% of pairs. This isn't a market-wide
  or causal premium.
- Higher price and faster price growth are different questions. The history
  notebook separates those comparisons and shows coverage alongside prices.

### Running the notebooks

Select the Python environment where the requirements are installed, and run
from the project directory. Run the main clustering notebook before the
history or feature notebooks if the saved assignments don't exist.

Generated tables and assignments are under `results/`. Rerunning a notebook
replaces its outputs, not the source data.

## Files

| File | Contents |
|---|---|
| `data/historic.csv` | `id` + one JSON column per grade (`Ungraded`, `PSA7`, `PSA8`, `PSA9`, `BGS9.5`, `PSA10`, `volume`), each a list of `[unix_ms, price]` monthly points. Prices are in **cents** (base Charizard unlimited, Nov 2024: `20468` = $204.68). `0` means no price that month. |
| `data/tpot.csv`, `data/sets.csv` | Card stats and set metadata. Card `id` is `<set id>-<number>`, e.g. `base1-4`. |
| `data/id_map.csv` | Mapping to a slug the other dataset has. PriceCharting `id` → `set_slug`, `card_slug` for 67,548 products (99.9% of `historic.csv`. 39 ids no longer exist, listed in `data/id_unmapped.txt`). |
| `data/card_links.csv` | CSV of links: `pc_id` (PriceCharting id) → `card_id` (stats id), `variant`, `name_match`. 30,165 price series linked to 16,812 distinct cards. |
| `data/card_unmatched.csv` | The 73 price series that could not be linked. |

### `card_links.csv` columns

- `variant`: printing tag from PriceCharting, `""` for the base printing. 
  - Most common: `reverse-holo`, `1st-edition`, `holo`, `cosmos-holo`, `jumbo`, `shadowless`, `prize-pack`, `stamped`. 
  - Several PriceCharting products can map to the same card (one per printing).
- `name_match`: `True` if the card name agrees with PriceCharting's `False` means it was matched on set + number plus at least one shared name word (98.7% are `True`).

### Combined table (`main.py`)

`load_data()` in `main.py` returns one row per (PriceCharting product, month): 1,241,631 rows × 33 columns for 30,165 price series / 16,812 cards, 2020-12 to 2024-11.

- `pc_id`, `card_id`, `variant` (`base` for the base printing), `name_match`
- `month` (`YYYY-MM`)
- `price_ungraded`, `price_psa7`, `price_psa8`, `price_psa9`, `price_bgs9_5`, `price_psa10`: **USD** (already converted from cents), `NaN` when there was no price that month
- `volume`: PriceCharting sales volume that month
- card stats from `tpot.csv` (`name`, `supertype`, `subtypes`, `hp`, `types`, `attacks`, `weaknesses`, `rarity`, `artist`, …; list-like columns are JSON strings) and set info (`set_id`, `set_name`, `set_series`, `set_release_date`)

It is cached as `data/combined.parquet` (git-ignored because it's too big. Delete it to rebuild).

## Reproducing the mapping (if you want to)

Outputs are already commited, here for historical purposes.

- `resolve_ids.py`: crawls PriceCharting's Pokémon set pages (~400 requests at 1 req/s), falling back to `/game/<id>` redirects for ids not listed on a set page. 
  - Writes `data/id_map.csv`. 
  - Took me about an hour.
- `match_cards.py`: 
  - Maps PriceCharting set names to stats sets (with hand-written overrides for subsets and promos in `SET_OVERRIDES`), normalises card numbers (`SWSH005` = `swsh5`), and uses the name to break ties and to reject wrong same-number matches. 
  - Writes `data/card_links.csv` and `data/card_unmatched.csv`.
  - ~20s to run.
