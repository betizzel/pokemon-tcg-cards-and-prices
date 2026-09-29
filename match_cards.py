"""link PriceCharting products to card-stats rows.

Reads from data/:
    id_map.csv    PriceCharting id -> set_slug, card_slug (made by resolve_ids.py)
    historic.csv  PriceCharting price history (only its ids are used here)
    tpot.csv      card stats (pokemontcg.io export, HF tpot1515/pokemoncards)
    sets.csv      set info for tpot.csv

Writes data/card_links.csv with columns pc_id, card_id, variant, name_match:
    variant     the printing tag left in PriceCharting's slug after removing the card
                name and number, e.g. "reverse-holo", "1st-edition"; "" for the base printing
    name_match  False if the card was matched on set + number only, not by name

Price-history ids that couldn't be linked go to data/card_unmatched.csv with a reason.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"

# Stats set id -> PriceCharting set slug, for sets where slugifying the name doesn't work.
# PriceCharting folds subsets (trainer galleries, shiny vaults, classic collection,
# galarian gallery) into the parent set.
SET_OVERRIDES = {
    "base1": "base-set",
    "ecard1": "expedition",
    "ex4": "team-magma-&-team-aqua",
    "ex6": "fire-red-&-leaf-green",
    "hgss2": "unleashed",
    "hgss3": "undaunted",
    "hgss4": "triumphant",
    "xy0": "kalos-starter",
    "pgo": "go",
    "sv3pt5": "scarlet-&-violet-151",
    "sve": "scarlet-&-violet-energy",
    "sma": "hidden-fates",
    "swsh45sv": "shining-fates",
    "cel25c": "celebrations",
    "swsh9tg": "brilliant-stars",
    "swsh10tg": "astral-radiance",
    "swsh11tg": "lost-origin",
    "swsh12tg": "silver-tempest",
    "swsh12pt5gg": "crown-zenith",
    # PriceCharting keeps all black star promos in one "promo" set
    "basep": "promo",
    "np": "promo",
    "dpp": "promo",
    "hsp": "promo",
    "bwp": "promo",
    "xyp": "promo",
    "smp": "promo",
    "swshp": "promo",
    "svp": "promo",
    "mcd11": "mcdonalds-2011",
    "mcd12": "mcdonalds-2012",
    "mcd14": "mcdonalds-2014",
    "mcd15": "mcdonalds-2015",
    "mcd16": "mcdonalds-2016",
    "mcd17": "mcdonalds-2017",
    "mcd18": "mcdonalds-2018",
    "mcd19": "mcdonalds-2019",
    "mcd21": "mcdonalds-2021",
    "mcd22": "mcdonalds-2022",
}

# A card number: optional letter prefix, digits with leading zeros, optional letter suffix
CARD_NUMBER_PATTERN = re.compile(r"^([a-z]*)0*(\d+)([a-z]?)$")

# A PriceCharting card slug: "<name and printing tag>-<card number>"
CARD_SLUG_PATTERN = r"^(.*)-([a-z]*\d+[a-z]?)$"

# Words too common to prove two card names are the same card
GENERIC_WORDS = {"energy", "basic", "holo", "reverse", "ex", "gx", "v", "vmax", "vstar", "the"}


@dataclass
class CardLink:
    pc_id: str
    card_id: str
    variant: str
    name_match: bool


@dataclass
class Unmatched:
    pc_id: str
    set_slug: str
    reason: str


@dataclass
class NumberOnlyMatch:
    """A product whose set + number points at exactly one card, but whose name didn't match"""
    pc_id: str
    set_slug: str
    name_part: str
    card: pd.Series


def slugify(text: str) -> str:
    """Turn a name into PriceCharting's slug form, e.g. "Nidoran♀" -> "nidoranf" """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = text.replace("♀", "f").replace("♂", "m")
    text = re.sub(r"[^a-z0-9'&]+", "-", text)
    return text.strip("-")


def normalize_card_number(number) -> str | None:
    """'SWSH005' -> 'swsh5', 'TG01' -> 'tg1', '067' -> '67'. None if it isn't a card number."""
    if not isinstance(number, str):
        return None

    match = CARD_NUMBER_PATTERN.match(number.lower())
    if not match:
        return None

    prefix, digits, suffix = match.groups()
    return f"{prefix}{int(digits)}{suffix}"


def load_sets(pricecharting_set_slugs: set[str]) -> pd.DataFrame:
    """Load sets.csv and work out each set's PriceCharting slug"""
    sets = pd.read_csv(DATA_DIR / "sets.csv", dtype=str)

    pc_sets = []
    for set_id, set_name in zip(sets["id"], sets["name"]):
        set_slug = SET_OVERRIDES.get(set_id, slugify(set_name))
        pc_sets.append("pokemon-" + set_slug)
    sets["pc_set"] = pc_sets

    unmapped_sets = sets[~sets["pc_set"].isin(pricecharting_set_slugs)]
    if len(unmapped_sets) > 0:
        print("stats sets with no PriceCharting set:", ", ".join(unmapped_sets["id"]))

    return sets


def load_cards(sets: pd.DataFrame) -> pd.DataFrame:
    """Load card stats with their PriceCharting set, normalized number and name slug"""
    cards = pd.read_csv(DATA_DIR / "tpot.csv", dtype=str, usecols=["id", "name", "number"])

    # Card ids look like "base1-4", so the set id is everything before the last dash
    cards["set_id"] = cards["id"].str.rsplit("-", n=1).str[0]

    set_slugs = sets[["id", "pc_set"]].rename(columns={"id": "set_id"})
    cards = cards.merge(set_slugs, on="set_id")

    cards["card_number"] = cards["number"].apply(normalize_card_number)
    cards["name_slug"] = cards["name"].apply(slugify)

    return cards


def load_products(id_map: pd.DataFrame) -> pd.DataFrame:
    """Get the PriceCharting products that have price history, with their slug split up"""
    history = pd.read_csv(DATA_DIR / "historic.csv", usecols=["id"], dtype=str)
    products = id_map[id_map["id"].isin(history["id"])].copy()

    # Split a slug like "charizard-reverse-holo-4" into "charizard-reverse-holo" and "4"
    slug_parts = products["card_slug"].str.extract(CARD_SLUG_PATTERN)
    products["name_part"] = slug_parts[0]
    products["card_number"] = slug_parts[1].apply(normalize_card_number)

    return products


def is_name_match(name_part: str, name_slug: str) -> bool:
    """True if the slug's name part is the card name, optionally followed by a printing tag"""
    return name_part == name_slug or name_part.startswith(name_slug + "-")


def find_variant(name_part: str, known_variants: list[str]) -> str:
    """Return the known printing tag the slug ends with, or "" if none"""
    for variant in known_variants:
        if name_part.endswith("-" + variant):
            return variant
    return ""


def match_by_name(products: pd.DataFrame, cards_by_set_and_number: dict):
    """First pass: link products to the card with the same set, number and name"""
    links = []
    unmatched = []
    number_only_matches = []

    for product in products.itertuples(index=False):
        # Sealed products and unnumbered cards have no number in their slug
        if pd.isna(product.card_number):
            unmatched.append(Unmatched(product.id, product.set_slug, "no card number (sealed product or unnumbered)"))
            continue

        candidates = cards_by_set_and_number.get((product.set_slug, product.card_number))
        if candidates is None:
            unmatched.append(Unmatched(product.id, product.set_slug, "no stats card with this set + number"))
            continue

        name_matches = [is_name_match(product.name_part, name_slug) for name_slug in candidates["name_slug"]]
        named_candidates = candidates[name_matches]

        if len(named_candidates) > 0:
            # If several names fit (e.g. "mew" and "mew-ex"), the longest one is the real card name
            longest_name_index = named_candidates["name_slug"].str.len().idxmax()
            card = named_candidates.loc[longest_name_index]

            # Whatever comes after the card name is the printing tag
            variant = product.name_part[len(card["name_slug"]):].strip("-")
            links.append(CardLink(product.id, card["id"], variant, True))

        elif len(candidates) == 1:
            # Only one card has this set + number; checked more carefully in match_by_number()
            card = candidates.iloc[0]
            number_only_matches.append(NumberOnlyMatch(product.id, product.set_slug, product.name_part, card))

        else:
            unmatched.append(Unmatched(product.id, product.set_slug, "several stats cards share this number, none match by name"))

    return links, unmatched, number_only_matches


def match_by_number(number_only_matches: list[NumberOnlyMatch], known_variants: list[str]):
    """Second pass: accept a set + number match only if the names share a distinctive word

    This stops e.g. a Skyridge Charizard box topper from being linked to Forretress,
    which has the same number.
    """
    links = []
    unmatched = []

    for match in number_only_matches:
        # Strip the printing tag off the end before comparing names
        variant = find_variant(match.name_part, known_variants)
        product_name = match.name_part[:len(match.name_part) - len(variant)].strip("-")

        product_words = set(product_name.split("-")) - GENERIC_WORDS
        card_words = set(match.card["name_slug"].split("-"))

        if product_words & card_words:
            links.append(CardLink(match.pc_id, match.card["id"], variant, False))
        else:
            reason = f"same set + number as {match.card['id']} ({match.card['name']}) but different card"
            unmatched.append(Unmatched(match.pc_id, match.set_slug, reason))

    return links, unmatched


def main() -> None:
    id_map = pd.read_csv(DATA_DIR / "id_map.csv", dtype=str)

    sets = load_sets(set(id_map["set_slug"]))
    cards = load_cards(sets)
    products = load_products(id_map)

    # Group the cards so each (set, number) lookup is instant
    cards_by_set_and_number = {}
    for key, group in cards.groupby(["pc_set", "card_number"]):
        cards_by_set_and_number[key] = group

    links, unmatched, number_only_matches = match_by_name(products, cards_by_set_and_number)

    # Printing tags seen on name-verified links, longest first so "1st-edition-holo" wins over "holo"
    variants = {link.variant for link in links if link.variant}
    known_variants = sorted(variants, key=len, reverse=True)

    number_links, number_unmatched = match_by_number(number_only_matches, known_variants)
    links += number_links
    unmatched += number_unmatched

    # Write the results
    links_df = pd.DataFrame(links, columns=["pc_id", "card_id", "variant", "name_match"])
    links_df.to_csv(DATA_DIR / "card_links.csv", index=False)

    unmatched_df = pd.DataFrame(unmatched, columns=["pc_id", "set_slug", "reason"])
    unmatched_df.to_csv(DATA_DIR / "card_unmatched.csv", index=False)

    # Print a summary
    print(f"price-history ids: {len(products)}  linked: {len(links_df)}  unmatched: {len(unmatched_df)}")
    print(f"distinct stats cards linked: {links_df['card_id'].nunique()} / {len(cards)}")
    print(f"name agrees: {links_df['name_match'].mean():.1%}")

    variant_names = links_df["variant"].replace("", "(base)")
    print("top variants:", variant_names.value_counts().head(12).to_dict())

    # Count all "same set + number as <some card>" reasons together
    reasons = unmatched_df["reason"].str.replace(r" as .*", " as another card", regex=True)
    print(reasons.value_counts().to_string())


if __name__ == "__main__":
    main()
