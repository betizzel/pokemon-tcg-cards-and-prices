"""Pokémon TCG price data mining: main working script.

Question: can we look at a card and predict whether its price will go up or down?

Run `python main.py`. The first run downloads the price history from Kaggle and
builds the combined table (~1.5 min); after that it loads the cached
data/combined.parquet in a few seconds. Delete that file to force a rebuild.

`load_data()` returns one row per (PriceCharting product, month):
  pc_id, card_id, variant, name_match   which card/printing the price series is
  month                                 "YYYY-MM", 2020-12 .. 2024-11
  price_ungraded, price_psa7, price_psa8, price_psa9, price_bgs9_5, price_psa10
                                        USD; NaN when there was no price that month
  volume                                PriceCharting sales volume that month
  name, supertype, subtypes, hp, types, attacks, rarity, artist, ...
                                        card stats (JSON-looking columns are strings)
  set_id, set_name, set_series, set_release_date

Put the project's analysis in `analyze()` at the bottom.
"""

import json
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
HISTORIC = DATA / "historic.csv"
COMBINED = DATA / "combined.parquet"
KAGGLE_URL = "https://www.kaggle.com/api/v1/datasets/download/davidkim2003/pokemon-pricecharting-historic-data"

GRADES = {
    "Ungraded": "price_ungraded",
    "PSA7": "price_psa7",
    "PSA8": "price_psa8",
    "PSA9": "price_psa9",
    "BGS9.5": "price_bgs9_5",
    "PSA10": "price_psa10",
}
STAT_COLUMNS = [
    "name", "supertype", "subtypes", "level", "hp", "types", "evolvesTo", "attacks",
    "weaknesses", "resistances", "retreatCost", "convertedRetreatCost", "number",
    "artist", "rarity", "nationalPokedexNumbers", "legalities",
]


# ---------------------------------------------------------------- data loading

def download_historic() -> None:
    """Fetch historic.csv (176 MB, too big for GitHub) from Kaggle; no login needed."""
    print("downloading price history from Kaggle (~19 MB zip)...")
    with urllib.request.urlopen(KAGGLE_URL) as r:
        archive = zipfile.ZipFile(BytesIO(r.read()))
    HISTORIC.write_bytes(archive.read("historic.csv"))


def long_series(hist: pd.DataFrame, column: str, value_name: str) -> pd.DataFrame:
    """Explode a JSON [[unix_ms, value], ...] column into (pc_id, month, value) rows."""
    ids, months, values = [], [], []
    for pid, raw in zip(hist["id"], hist[column]):
        if not isinstance(raw, str):
            continue
        for ts, value in json.loads(raw):
            ids.append(pid)
            months.append(ts)
            values.append(value)
    df = pd.DataFrame({"pc_id": ids, "month": months, value_name: values})
    # Points are month starts in US time (06:00/07:00 UTC on the 1st).
    df["month"] = pd.to_datetime(df["month"], unit="ms").dt.strftime("%Y-%m")
    return df.drop_duplicates(["pc_id", "month"], keep="last")


def build_combined() -> pd.DataFrame:
    """Join monthly prices (historic.csv) with card stats via card_links.csv."""
    links = pd.read_csv(DATA / "card_links.csv", dtype={"pc_id": str}, keep_default_na=False)
    links["variant"] = links["variant"].replace("", "base")
    hist = pd.read_csv(HISTORIC, dtype={"id": str})
    hist = hist[hist["id"].isin(links["pc_id"])]

    prices = None
    for column, name in GRADES.items():
        part = long_series(hist, column, name)
        part[name] = part[name].where(part[name] > 0) / 100  # cents -> USD, 0 = no price
        prices = part if prices is None else prices.merge(part, on=["pc_id", "month"], how="outer")
    prices = prices.merge(long_series(hist, "volume", "volume"), on=["pc_id", "month"], how="left")

    cards = pd.read_csv(DATA / "tpot.csv", usecols=["id", *STAT_COLUMNS], dtype={"level": str, "number": str})
    cards["set_id"] = cards["id"].str.rsplit("-", n=1).str[0]
    sets = pd.read_csv(DATA / "sets.csv", usecols=["id", "name", "series", "releaseDate"]).rename(
        columns={"id": "set_id", "name": "set_name", "series": "set_series", "releaseDate": "set_release_date"}
    )
    sets["set_release_date"] = pd.to_datetime(sets["set_release_date"], format="%Y/%m/%d")
    cards = cards.merge(sets, on="set_id", how="left").rename(columns={"id": "card_id"})

    df = prices.merge(links, on="pc_id").merge(cards, on="card_id")
    front = ["pc_id", "card_id", "variant", "name_match", "month", *GRADES.values(), "volume"]
    df = df[front + [c for c in df.columns if c not in front]]
    return df.sort_values(["card_id", "variant", "pc_id", "month"], ignore_index=True)


def load_data() -> pd.DataFrame:
    if COMBINED.exists():
        return pd.read_parquet(COMBINED)
    if not HISTORIC.exists():
        download_historic()
    print("building combined dataset (first run only, ~1.5 min)...")
    df = build_combined()
    df.to_parquet(COMBINED, index=False)
    return df


# ---------------------------------------------------------------- analysis

def analyze(df: pd.DataFrame) -> None:
    print(f"{len(df):,} rows x {df.shape[1]} columns | {df['pc_id'].nunique():,} price series | "
          f"{df['card_id'].nunique():,} cards | {df['month'].min()} to {df['month'].max()}")
    print(df[["card_id", "name", "variant", "month", "price_ungraded", "price_psa10", "volume"]].tail())

    # Team analysis goes here: target = "ungraded price up > X% in the next 6 months",
    # features from card stats + recent price history; split train/test by month.


if __name__ == "__main__":
    analyze(load_data())
