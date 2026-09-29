"""map PriceCharting product ids -> (set slug, card slug).

Crawls every Pokémon set page linked from https://www.pricecharting.com/category/pokemon-cards.
Each set page lists 150 products per page, and each product row has its id and a
/game/<set-slug>/<card-slug> link, so this takes ~400 requests instead of one per id.

Ids in data/historic.csv that aren't on any set page fall back to reading where
/game/<id> redirects to.

Writes data/id_map.csv (id, set_slug, card_slug). Ids that no longer exist (404)
go to data/id_unmapped.txt.
"""

import csv
import html
import http.client
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_CSV = DATA_DIR / "id_map.csv"
UNMAPPED_TXT = DATA_DIR / "id_unmapped.txt"

BASE_URL = "https://www.pricecharting.com"
USER_AGENT = "pokemon-tcg-datamining/0.2 (student project; 1 req/s)"
REQUEST_DELAY = 1.0  # seconds between requests
MAX_RETRIES = 5

SET_LINK_PATTERN = re.compile(r'href="/console/(pokemon-[^"]+)"')
PRODUCT_ROW_PATTERN = re.compile(r'<tr id="product-(\d+)"[^>]*>.*?href="[^"]*/game/([^/"]+)/([^/"]+)"', re.S)
CURSOR_PATTERN = re.compile(r'name="cursor" value="(\d+)"')
HIDDEN_INPUT_PATTERN = re.compile(r'<input type="hidden" name="([^"]+)" value="([^"]*)"')


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Makes urllib raise on a redirect instead of following it, so we can read where it points"""

    def redirect_request(self, *args, **kwargs):
        return None


no_redirect_opener = urllib.request.build_opener(NoRedirectHandler)


def fetch(url: str, form: dict[str, str] | None = None) -> str:
    """Fetch a page (POSTing the form if given), retrying on network errors and 429/5xx"""
    if form is None:
        post_data = None
    else:
        post_data = urllib.parse.urlencode(form).encode()

    request = urllib.request.Request(url, data=post_data, headers={"User-Agent": USER_AGENT})

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                page_html = response.read().decode("utf-8", "replace")
            time.sleep(REQUEST_DELAY)
            return page_html

        except urllib.error.HTTPError as error:
            # Errors like 404 won't go away by retrying, only rate limits (429) and server errors might
            if error.code != 429 and error.code < 500:
                raise RuntimeError(f"{url} returned HTTP {error.code}") from error
            print(f"  retry {attempt} for {url}: {error}")

        except (OSError, http.client.HTTPException) as error:
            print(f"  retry {attempt} for {url}: {error}")

        # Back off a bit longer after each failure
        time.sleep(30 * attempt)

    raise RuntimeError(f"giving up on {url}")


def parse_game_location(location: str) -> tuple[str, str] | None:
    """Get (set_slug, card_slug) from a URL like .../game/pokemon-base-set/charizard-4"""
    path = location.split("/game/", 1)[-1]
    parts = path.strip("/").split("/")
    if len(parts) != 2:
        return None

    set_slug = urllib.parse.unquote(parts[0])
    card_slug = urllib.parse.unquote(parts[1])
    return set_slug, card_slug


def resolve_redirect(pc_id: str) -> tuple[str, str] | None:
    """Fallback for ids not on any set page: /game/<id> redirects to /game/<set>/<card>

    Returns None if the id doesn't exist, and raises RuntimeError if the request keeps failing.
    """
    request = urllib.request.Request(f"{BASE_URL}/game/{pc_id}", headers={"User-Agent": USER_AGENT})

    for attempt in range(1, 4):
        try:
            no_redirect_opener.open(request, timeout=30).close()
            # The page loaded without redirecting, so there's no card page to point to
            return None

        except urllib.error.HTTPError as error:
            if error.code in (301, 302):
                time.sleep(REQUEST_DELAY)
                return parse_game_location(error.headers.get("Location", ""))

            if error.code == 404:
                time.sleep(REQUEST_DELAY)
                return None

            print(f"  retry {attempt} for id {pc_id}: {error}")

        except (OSError, http.client.HTTPException) as error:
            print(f"  retry {attempt} for id {pc_id}: {error}")

        # Back off a bit longer after each failure
        time.sleep(30 * attempt)

    raise RuntimeError(f"giving up on id {pc_id}")


def read_next_page_form(page_html: str) -> dict[str, str]:
    """Get the hidden input fields of a set page's "next page" form"""
    after_next_button = page_html.split('class="next_page', 1)[1]
    form_html = after_next_button.split("</form>", 1)[0]
    return dict(HIDDEN_INPUT_PATTERN.findall(form_html))


def crawl_set(set_slug: str) -> list[tuple[str, str, str]]:
    """Get (id, set_slug, card_slug) for every product on a set's pages"""
    set_url = f"{BASE_URL}/console/{urllib.parse.quote(set_slug)}"
    page_html = fetch(set_url)
    products = PRODUCT_ROW_PATTERN.findall(page_html)

    # The next page is loaded by POSTing the "next page" form with the page's cursor
    cursor_match = CURSOR_PATTERN.search(page_html)
    while cursor_match:
        form = read_next_page_form(page_html)
        form["cursor"] = cursor_match.group(1)

        page_html = fetch(set_url, form)
        page_products = PRODUCT_ROW_PATTERN.findall(page_html)
        if not page_products:
            break

        products += page_products
        cursor_match = CURSOR_PATTERN.search(page_html)

    return products


def find_set_slugs() -> list[str]:
    """Get the slug of every Pokémon set linked from the category page"""
    category_html = fetch(f"{BASE_URL}/category/pokemon-cards")

    set_slugs = set()
    for link in SET_LINK_PATTERN.findall(category_html):
        set_slug = urllib.parse.unquote(html.unescape(link))
        set_slugs.add(set_slug)

    return sorted(set_slugs)


def crawl_all_sets(set_slugs: list[str]) -> dict[str, tuple[str, str]]:
    """Crawl every set page and map each product id to its (set_slug, card_slug)"""
    id_map = {}
    failed_sets = []

    for number, set_slug in enumerate(set_slugs, 1):
        progress = f"[{number}/{len(set_slugs)}] {set_slug}"
        try:
            products = crawl_set(set_slug)
        except RuntimeError as error:
            failed_sets.append(set_slug)
            print(f"{progress}: FAILED ({error})")
            continue

        for pc_id, product_set_slug, card_slug in products:
            product_set_slug = html.unescape(urllib.parse.unquote(product_set_slug))
            card_slug = html.unescape(urllib.parse.unquote(card_slug))
            id_map[pc_id] = (product_set_slug, card_slug)

        print(f"{progress}: {len(products)} products")

    if failed_sets:
        print(f"failed sets: {failed_sets}")

    return id_map


def read_history_ids() -> list[str]:
    """Get every product id in historic.csv"""
    # historic.csv has huge JSON columns, bigger than csv's default field size limit
    csv.field_size_limit(sys.maxsize)

    with (DATA_DIR / "historic.csv").open(newline="") as f:
        return [row["id"] for row in csv.DictReader(f)]


def write_id_map(id_map: dict[str, tuple[str, str]]) -> None:
    """Write id_map.csv sorted by id"""
    with OUTPUT_CSV.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "set_slug", "card_slug"])

        for pc_id in sorted(id_map, key=int):
            set_slug, card_slug = id_map[pc_id]
            writer.writerow([pc_id, set_slug, card_slug])


def main() -> None:
    # Print progress right away, even when the output is redirected to a log file
    sys.stdout.reconfigure(line_buffering=True)

    set_slugs = find_set_slugs()
    print(f"{len(set_slugs)} sets")

    id_map = crawl_all_sets(set_slugs)

    # Some ids in the price history aren't listed on any set page
    history_ids = read_history_ids()
    missing_ids = [pc_id for pc_id in history_ids if pc_id not in id_map]
    print(f"set pages covered {len(history_ids) - len(missing_ids)}/{len(history_ids)}; "
          f"resolving {len(missing_ids)} via redirect")

    not_found_ids = []
    failed_ids = []
    for pc_id in missing_ids:
        try:
            slugs = resolve_redirect(pc_id)
        except RuntimeError as error:
            print(error)
            failed_ids.append(pc_id)
            continue

        if slugs is None:
            not_found_ids.append(pc_id)
        else:
            id_map[pc_id] = slugs

    write_id_map(id_map)
    UNMAPPED_TXT.write_text("\n".join(not_found_ids) + "\n")

    covered_count = len(history_ids) - len(not_found_ids) - len(failed_ids)
    print(f"finished: {len(id_map)} products mapped; historic ids covered "
          f"{covered_count}/{len(history_ids)} (not found -> {UNMAPPED_TXT.name})")

    # Network failures aren't the same as "doesn't exist", so they don't go in id_unmapped.txt
    if failed_ids:
        print(f"{len(failed_ids)} ids failed because of network errors, rerun to retry them: {failed_ids}")


if __name__ == "__main__":
    main()
