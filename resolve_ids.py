"""Step 1: map PriceCharting product ids -> (set slug, card slug).

Crawls every Pokemon set page linked from
https://www.pricecharting.com/category/pokemon-cards (150 products per page,
paginated with a POST `cursor`). Each product row carries its id and its
/game/<set-slug>/<card-slug> link. ~400 requests instead of one per id. Ids
from data/historic.csv not listed on any set page (unlinked sets) fall back to
the 301 redirect of /game/<id>.

Writes data/id_map.csv (id, set_slug, card_slug); ids that no longer exist
(404) go to data/id_unmapped.txt.
"""

import csv
import html as htmlmod
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).parent / "data"
OUT = DATA / "id_map.csv"
BASE = "https://www.pricecharting.com"
DELAY = 1.0
UA = "pokemon-tcg-datamining/0.2 (student project; 1 req/s)"

SET_LINK = re.compile(r'href="/console/(pokemon-[^"]+)"')
ROW = re.compile(r'<tr id="product-(\d+)"[^>]*>.*?href="[^"]*/game/([^/"]+)/([^/"]+)"', re.S)
CURSOR = re.compile(r'name="cursor" value="(\d+)"')
FORM_FIELDS = re.compile(r'<input type="hidden" name="([^"]+)" value="([^"]*)"')


def fetch(url: str, form: dict[str, str] | None = None) -> str:
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                html = r.read().decode("utf-8", "replace")
            time.sleep(DELAY)
            return html
        except Exception as e:  # network hiccup or 429/5xx: back off and retry
            print(f"  retry {attempt + 1} for {url}: {e}", flush=True)
            time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_no_redirect = urllib.request.build_opener(_NoRedirect)


def resolve_redirect(pid: str) -> tuple[str, str] | None:
    """Fallback for ids not listed on any set page: /game/<id> 301s to /game/<set>/<card>."""
    req = urllib.request.Request(f"{BASE}/game/{pid}", headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            _no_redirect.open(req, timeout=30).close()
            return None
        except urllib.error.HTTPError as e:
            if e.code in (301, 302):
                parts = e.headers.get("Location", "").split("/game/", 1)[-1].strip("/").split("/")
                time.sleep(DELAY)
                if len(parts) == 2:
                    return urllib.parse.unquote(parts[0]), urllib.parse.unquote(parts[1])
                return None
            if e.code == 404:
                time.sleep(DELAY)
                return None
            time.sleep(30 * (attempt + 1))
        except OSError:
            time.sleep(30 * (attempt + 1))
    return None


def crawl_set(slug: str) -> list[tuple[str, str, str]]:
    url = f"{BASE}/console/{urllib.parse.quote(slug)}"
    html = fetch(url)
    rows = ROW.findall(html)
    while m := CURSOR.search(html):
        form = dict(FORM_FIELDS.findall(html.split('class="next_page', 1)[1].split("</form>", 1)[0]))
        form["cursor"] = m.group(1)
        html = fetch(url, form)
        page = ROW.findall(html)
        if not page:
            break
        rows += page
    return rows


def main() -> None:
    links = SET_LINK.findall(fetch(f"{BASE}/category/pokemon-cards"))
    sets = sorted({urllib.parse.unquote(htmlmod.unescape(s)) for s in links})
    print(f"{len(sets)} sets", flush=True)

    mapping: dict[str, tuple[str, str]] = {}
    failed: list[str] = []
    for n, slug in enumerate(sets, 1):
        try:
            rows = crawl_set(slug)
        except RuntimeError as e:
            failed.append(slug)
            print(f"[{n}/{len(sets)}] {slug}: FAILED ({e})", flush=True)
            continue
        for pid, s, c in rows:
            mapping[pid] = (htmlmod.unescape(urllib.parse.unquote(s)), htmlmod.unescape(urllib.parse.unquote(c)))
        print(f"[{n}/{len(sets)}] {slug}: {len(rows)} products", flush=True)
    if failed:
        print(f"failed sets: {failed}", flush=True)

    csv.field_size_limit(sys.maxsize)
    with (DATA / "historic.csv").open(newline="") as f:
        ids = [row["id"] for row in csv.DictReader(f)]
    missing = [i for i in ids if i not in mapping]
    print(f"set pages covered {len(ids) - len(missing)}/{len(ids)}; resolving {len(missing)} via redirect", flush=True)
    still_missing = []
    for pid in missing:
        if found := resolve_redirect(pid):
            mapping[pid] = found
        else:
            still_missing.append(pid)

    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "set_slug", "card_slug"])
        for pid, (s, c) in sorted(mapping.items(), key=lambda kv: int(kv[0])):
            w.writerow([pid, s, c])

    (DATA / "id_unmapped.txt").write_text("\n".join(still_missing) + "\n")
    print(f"finished: {len(mapping)} products mapped; historic ids covered "
          f"{len(ids) - len(still_missing)}/{len(ids)} (unmapped -> id_unmapped.txt)", flush=True)


if __name__ == "__main__":
    main()
