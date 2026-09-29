"""Step 2: link PriceCharting products to card-stats rows.

Inputs (data/):
  id_map.csv    PriceCharting id -> set_slug, card_slug   (from resolve_ids.py)
  historic.csv  PriceCharting price history (only its ids are used here)
  tpot.csv      card stats (pokemontcg.io export, HF tpot1515/pokemoncards)
  sets.csv      set metadata for tpot.csv

Output: data/card_links.csv
  pc_id, card_id, variant, name_match
    variant    PriceCharting's edition/printing tag left after removing the
               card name and number from its slug, e.g. "reverse-holo",
               "1st-edition", "shadowless"; "" for the base printing.
    name_match whether the stats card name also agrees with the slug
               (False = matched on set + number only).
Unmatched price-history ids, with a reason, go to data/card_unmatched.csv.
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"

# Stats set id -> PriceCharting set slug, where the name alone does not map.
# PriceCharting folds subsets (trainer galleries, shiny vaults, classic
# collection, galarian gallery) into the parent set and keeps all black star
# promos in one "promo" set.
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
    **{p: "promo" for p in ("basep", "np", "dpp", "hsp", "bwp", "xyp", "smp", "swshp", "svp")},
    **{f"mcd{y}": f"mcdonalds-20{y}" for y in ("11", "12", "14", "15", "16", "17", "18", "19", "21", "22")},
}

NUM = re.compile(r"^([a-z]*)0*(\d+)([a-z]?)$")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = text.replace("♀", "f").replace("♂", "m")
    text = re.sub(r"[^a-z0-9'&]+", "-", text)
    return text.strip("-")


def norm_number(num: str) -> str | None:
    """'SWSH005' -> 'swsh5', 'TG01' -> 'tg1', '067' -> '67'."""
    m = NUM.match(num.lower())
    return f"{m.group(1)}{int(m.group(2))}{m.group(3)}" if m else None


GENERIC_WORDS = {"energy", "basic", "holo", "reverse", "ex", "gx", "v", "vmax", "vstar", "the"}


def main() -> None:
    sets = pd.read_csv(DATA / "sets.csv", dtype=str)
    cards = pd.read_csv(DATA / "tpot.csv", dtype=str, usecols=["id", "name", "number"])
    idmap = pd.read_csv(DATA / "id_map.csv", dtype=str)
    hist_ids = set(pd.read_csv(DATA / "historic.csv", usecols=["id"], dtype=str).id)

    pc_sets = set(idmap.set_slug)
    sets["pc_set"] = [
        "pokemon-" + SET_OVERRIDES.get(i, slugify(n)) for i, n in zip(sets.id, sets.name)
    ]
    unmapped_sets = sets[~sets.pc_set.isin(pc_sets)]
    if len(unmapped_sets):
        print("stats sets with no PriceCharting set:", ", ".join(unmapped_sets.id))

    cards["set_id"] = cards.id.str.rsplit("-", n=1).str[0]
    cards = cards.merge(sets[["id", "pc_set"]].rename(columns={"id": "set_id"}), on="set_id")
    cards["num"] = cards.number.map(norm_number)
    cards["name_slug"] = cards.name.map(slugify)
    by_key = {k: g for k, g in cards.groupby(["pc_set", "num"])}

    pc = idmap[idmap.id.isin(hist_ids)].copy()
    tail = pc.card_slug.str.extract(r"^(.*)-([a-z]*\d+[a-z]?)$")
    pc["stem"], pc["num"] = tail[0], tail[1].map(lambda n: norm_number(n) if isinstance(n, str) else None)

    links, unmatched, fallback = [], [], []
    for pid, set_slug, stem, num in pc[["id", "set_slug", "stem", "num"]].itertuples(index=False):
        if num is None:
            unmatched.append((pid, set_slug, "no card number (sealed product or unnumbered)"))
            continue
        cand = by_key.get((set_slug, num))
        if cand is None:
            unmatched.append((pid, set_slug, "no stats card with this set + number"))
            continue
        named = cand[[stem == s or stem.startswith(s + "-") for s in cand.name_slug]]
        if len(named):
            row = named.loc[named.name_slug.str.len().idxmax()]
            variant = stem[len(row.name_slug):].strip("-")
            links.append((pid, row.id, variant, True))
        elif len(cand) == 1:
            fallback.append((pid, set_slug, stem, cand.iloc[0]))
        else:
            unmatched.append((pid, set_slug, "several stats cards share this number, none match by name"))

    # Number-only matches: strip a printing tag seen on name-verified links,
    # then require a shared distinctive word so e.g. a Skyridge Charizard box
    # topper is not linked to Forretress, which has the same number.
    known_variants = sorted({v for _, _, v, _ in links if v}, key=len, reverse=True)
    for pid, set_slug, stem, row in fallback:
        variant = next((v for v in known_variants if stem.endswith("-" + v)), "")
        words = set(stem[: len(stem) - len(variant)].strip("-").split("-")) - GENERIC_WORDS
        if words & set(row.name_slug.split("-")):
            links.append((pid, row.id, variant, False))
        else:
            unmatched.append((pid, set_slug, f"same set + number as {row.id} ({row['name']}) but different card"))

    out = pd.DataFrame(links, columns=["pc_id", "card_id", "variant", "name_match"])
    out.to_csv(DATA / "card_links.csv", index=False)
    miss = pd.DataFrame(unmatched, columns=["pc_id", "set_slug", "reason"])
    miss.to_csv(DATA / "card_unmatched.csv", index=False)

    print(f"price-history ids: {len(pc)}  linked: {len(out)}  unmatched: {len(miss)}")
    print(f"distinct stats cards linked: {out.card_id.nunique()} / {len(cards)}")
    print(f"name agrees: {out.name_match.mean():.1%}")
    print("top variants:", out.variant.replace("", "(base)").value_counts().head(12).to_dict())
    print(miss.reason.str.replace(r" as .*", " as another card", regex=True).value_counts().to_string())


if __name__ == "__main__":
    main()
