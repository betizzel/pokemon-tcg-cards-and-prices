"""Pokémon TCG price data mining: main working script.

Question: can we look at a card and predict whether its price will go up or down?
"""

import json
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
HISTORIC_CSV = DATA_DIR / "historic.csv"
COMBINED_PARQUET = DATA_DIR / "combined.parquet"
KAGGLE_URL = "https://www.kaggle.com/api/v1/datasets/download/davidkim2003/pokemon-pricecharting-historic-data"

# Grade column in historic.csv -> our price column name
GRADE_COLUMNS = {
    "Ungraded": "price_ungraded",
    "PSA7": "price_psa7",
    "PSA8": "price_psa8",
    "PSA9": "price_psa9",
    "BGS9.5": "price_bgs9_5",
    "PSA10": "price_psa10",
}

# Card stat columns kept from tpot.csv
STAT_COLUMNS = [
    "name", "supertype", "subtypes", "level", "hp", "types", "evolvesTo", "attacks",
    "weaknesses", "resistances", "retreatCost", "convertedRetreatCost", "number",
    "artist", "rarity", "nationalPokedexNumbers", "legalities",
]

# Columns kept from sets.csv, renamed so they don't clash with the card columns
SET_COLUMNS = {
    "id": "set_id",
    "name": "set_name",
    "series": "set_series",
    "releaseDate": "set_release_date",
}


def download_historic() -> None:
    """Download historic.csv from Kaggle (it's too big for GitHub, no login needed)"""
    print("downloading price history from Kaggle (~19 MB zip)...")
    with urllib.request.urlopen(KAGGLE_URL) as response:
        zip_bytes = response.read()

    archive = zipfile.ZipFile(BytesIO(zip_bytes))
    HISTORIC_CSV.write_bytes(archive.read("historic.csv"))


def explode_json_column(history: pd.DataFrame, column: str, value_name: str) -> pd.DataFrame:
    """Turn a JSON [[unix_ms, value], ...] column into one row per (pc_id, month)"""
    pc_ids = []
    timestamps = []
    values = []

    for pc_id, raw_json in zip(history["id"], history[column]):
        # Products with no data in this column have NaN instead of a JSON string
        if not isinstance(raw_json, str):
            continue

        for timestamp, value in json.loads(raw_json):
            pc_ids.append(pc_id)
            timestamps.append(timestamp)
            values.append(value)

    df = pd.DataFrame({"pc_id": pc_ids, "month": timestamps, value_name: values})

    # Points are month starts in US time (06:00/07:00 UTC on the 1st), so just keep "YYYY-MM"
    df["month"] = pd.to_datetime(df["month"], unit="ms").dt.strftime("%Y-%m")

    return df.drop_duplicates(["pc_id", "month"], keep="last")


def load_prices(pc_ids: pd.Series) -> pd.DataFrame:
    """Load monthly prices for every grade plus sales volume, one row per (pc_id, month)"""
    history = pd.read_csv(HISTORIC_CSV, dtype={"id": str})
    history = history[history["id"].isin(pc_ids)]

    prices = None
    for grade_column, price_column in GRADE_COLUMNS.items():
        grade_prices = explode_json_column(history, grade_column, price_column)

        # Prices are in cents, and 0 means there was no price that month
        has_price = grade_prices[price_column] > 0
        grade_prices[price_column] = grade_prices[price_column].where(has_price) / 100

        if prices is None:
            prices = grade_prices
        else:
            prices = prices.merge(grade_prices, on=["pc_id", "month"], how="outer")

    volume = explode_json_column(history, "volume", "volume")
    prices = prices.merge(volume, on=["pc_id", "month"], how="left")

    return prices


def load_cards() -> pd.DataFrame:
    """Load card stats from tpot.csv with their set info attached"""
    cards = pd.read_csv(
        DATA_DIR / "tpot.csv",
        usecols=["id", *STAT_COLUMNS],
        dtype={"level": str, "number": str},
    )

    # Card ids look like "base1-4", so the set id is helps differentiate them
    cards["set_id"] = cards["id"].str.rsplit("-", n=1).str[0]

    sets = pd.read_csv(DATA_DIR / "sets.csv", usecols=list(SET_COLUMNS))
    sets = sets.rename(columns=SET_COLUMNS)
    sets["set_release_date"] = pd.to_datetime(sets["set_release_date"], format="%Y/%m/%d")

    cards = cards.merge(sets, on="set_id", how="left")
    cards = cards.rename(columns={"id": "card_id"})

    return cards


def build_combined() -> pd.DataFrame:
    """Join monthly prices (historic.csv) with card stats via card_links.csv"""
    links = pd.read_csv(DATA_DIR / "card_links.csv", dtype={"pc_id": str}, keep_default_na=False)

    # card_links.csv uses "" for the base printing
    links["variant"] = links["variant"].replace("", "base")

    prices = load_prices(links["pc_id"])
    cards = load_cards()

    combined = prices.merge(links, on="pc_id")
    combined = combined.merge(cards, on="card_id")

    # Put the id and price columns first, card stats after
    front_columns = ["pc_id", "card_id", "variant", "name_match", "month", *GRADE_COLUMNS.values(), "volume"]
    other_columns = [column for column in combined.columns if column not in front_columns]
    combined = combined[front_columns + other_columns]

    return combined.sort_values(["card_id", "variant", "pc_id", "month"], ignore_index=True)


def load_data() -> pd.DataFrame:
    """
    returns one row per (PriceCharting product, month):

    pc_id, card_id, variant, name_match     which card/printing the price series is
    month                                   "YYYY-MM", 2020-12 .. 2024-11
    price_ungraded, price_psa7, price_psa8,
    price_psa9, price_bgs9_5, price_psa10   USD: NaN when there was no price that month
    volume                                  PriceCharting sales volume that month
    name, supertype, subtypes, hp, types, 
    attacks, rarity, artist, ...            card stats (JSON-looking columns are strings)

    set_id, set_name, set_series, 
    set_release_date
    """
    if COMBINED_PARQUET.exists():
        return pd.read_parquet(COMBINED_PARQUET)

    if not HISTORIC_CSV.exists():
        download_historic()

    print("building combined dataset (first run only, ~1.5 min)...")
    df = build_combined()
    df.to_parquet(COMBINED_PARQUET, index=False)

    return df


def analyze(df: pd.DataFrame) -> None:

    print(f"{len(df):,} rows x {df.shape[1]} columns | {df['pc_id'].nunique():,} price series | "
          f"{df['card_id'].nunique():,} cards | {df['month'].min()} to {df['month'].max()}")

    print(df[["card_id", "name", "variant", "month", "price_ungraded", "price_psa10", "volume"]].tail())


if __name__ == "__main__":
    analyze(load_data())
