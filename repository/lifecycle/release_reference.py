"""Release reference: PostgreSQL major versions (V059) and operating system releases (V060).

Reference data, not Dictionary. Three ways keep it current (Hasan 2026-11-11):
  online   Keystone's own machine reaches the internet: postgresql.org's versioning page, then the
           endoflife.date API. Tried at the start of every health check and import; a failure is silent.
  file     a reference file (JSON, see export) for installations without internet, e.g. a quarterly
           package; imported with --import.
  seed     the values of migration V059, the fallback.
PG-LIFE-001 accepts a reference of at most 100 days (latest minors change every quarter); PG-LIFE-002
accepts any age (end-of-support dates are fixed by the versioning policy).
Operating systems (PG-LIFE-003) come from migrations and reference files only: their end-of-support
dates are fixed, and no single online source states "end of free security updates" for all of them.
Each product has its own source and as_of; a reference file carries every product.

Usage:
    python -m repository.lifecycle.release_reference --show
    python -m repository.lifecycle.release_reference --refresh
    python -m repository.lifecycle.release_reference --import reference.json
    python -m repository.lifecycle.release_reference --export reference.json
"""

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path
from datetime import date, datetime, timezone

PRODUCT = "PostgreSQL"
VERSIONING_URL = "https://www.postgresql.org/support/versioning/"
ENDOFLIFE_URL = "https://endoflife.date/api/v1/products/postgresql/"
FILE_FORMAT = 1
TIMEOUT_SECONDS = 5

MAJOR = re.compile(r"^(?:\d{2,}|\d\.\d)$")             # '17', '9.6'
MINOR = re.compile(r"^(?:\d{2,}\.\d+|\d\.\d\.\d+)$")   # '17.11', '9.6.24'


class ReferenceError(Exception):
    """A reference that cannot be read or is not plausible."""


def plausible(releases, product=PRODUCT):
    """The releases of a source, checked: enough majors, each minor of its own major, dates in order."""
    if product != PRODUCT:
        for r in releases:
            if not r.get("major_version") or len(r["major_version"]) > 10 or not r.get("end_of_support"):
                raise ReferenceError(f"{product}: release {r.get('major_version')!r}")
            if r.get("first_release") and r["end_of_support"] <= r["first_release"]:
                raise ReferenceError(f"{product}: end of support before first release for {r['major_version']}")
        if not releases:
            raise ReferenceError(f"{product}: no releases")
        return releases
    if len(releases) < 5:
        raise ReferenceError(f"only {len(releases)} major versions; not a release list")
    for r in releases:
        if not MAJOR.match(r["major_version"]):
            raise ReferenceError(f"major version {r['major_version']!r}")
        if r.get("latest_minor") and not (MINOR.match(r["latest_minor"])
                                          and r["latest_minor"].startswith(r["major_version"] + ".")):
            raise ReferenceError(f"latest minor {r['latest_minor']!r} of {r['major_version']}")
        if r.get("first_release") and r.get("end_of_support") and r["end_of_support"] <= r["first_release"]:
            raise ReferenceError(f"end of support before first release for {r['major_version']}")
    return releases


def parse_versioning_page(page):
    """Rows of postgresql.org's versioning table: version, current minor, supported, first, final."""
    releases = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        major = next((c for c in cells if MAJOR.match(c)), None)
        minor = next((c for c in cells if MINOR.match(c)), None)
        dates = []
        for c in cells:
            try:
                dates.append(datetime.strptime(c, "%B %d, %Y").date())
            except ValueError:
                pass
        if major and len(dates) >= 2:
            releases.append({"major_version": major, "latest_minor": minor,
                             "first_release": dates[0], "end_of_support": dates[1]})
    return plausible(releases)


def parse_endoflife(text):
    """endoflife.date's API v1: {result: {releases: [{name, releaseDate, eolFrom, latest: {name}}]}}."""
    result = json.loads(text).get("result", {})
    items = result.get("releases", []) if isinstance(result, dict) else result
    releases = []
    for item in items:
        eol, latest = item.get("eolFrom"), item.get("latest") or {}
        releases.append({"major_version": str(item["name"]), "latest_minor": latest.get("name"),
                         "first_release": date.fromisoformat(item["releaseDate"]) if item.get("releaseDate") else None,
                         "end_of_support": date.fromisoformat(eol) if isinstance(eol, str) else None})
    return plausible(releases)


def fetch(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "Keystone release reference"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def fetch_online(timeout=TIMEOUT_SECONDS):
    """(releases, url) from the first source that answers with a plausible list; ReferenceError if none."""
    errors = []
    for url, parse in ((VERSIONING_URL, parse_versioning_page), (ENDOFLIFE_URL, parse_endoflife)):
        try:
            return parse(fetch(url, timeout)), url
        except Exception as exc:                       # network, proxy, page changed: try the next
            errors.append(f"{url}: {exc}")
    raise ReferenceError("; ".join(errors))


def store(conn, releases, source, detail, as_of=None, product=PRODUCT):
    """Store a product's releases and where they came from (one transaction, by the caller)."""
    as_of = as_of or datetime.now(timezone.utc)
    for r in releases:
        conn.execute(
            """
            INSERT INTO keystone.release_reference
                (product, major_version, latest_minor, first_release, end_of_support)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (product, major_version) DO UPDATE
            SET latest_minor = EXCLUDED.latest_minor, first_release = EXCLUDED.first_release,
                end_of_support = EXCLUDED.end_of_support
            """, (product, r["major_version"], r.get("latest_minor"), r.get("first_release"),
                  r.get("end_of_support")))
    conn.execute(
        """
        INSERT INTO keystone.release_reference_source (product, as_of, source, source_detail)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (product) DO UPDATE
        SET as_of = EXCLUDED.as_of, source = EXCLUDED.source, source_detail = EXCLUDED.source_detail
        """, (product, as_of, source, detail))


def refresh(connect, timeout=TIMEOUT_SECONDS):
    """Refresh online; (True, url) or (False, reason). Never raises: callers go on without it."""
    try:
        releases, url = fetch_online(timeout)
        with connect() as conn:
            store(conn, releases, "ONLINE", url)
            conn.commit()
        return True, url
    except Exception as exc:
        return False, str(exc)


def import_file(conn, path):
    """A reference file written by export (a quarterly package, say): [(product, imported, why)].

    Each product is taken only if the file's copy is not older than the one in Keystone.
    """
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        if doc.get("format") != FILE_FORMAT or not isinstance(doc.get("products"), list):
            raise ReferenceError("not a Keystone release reference file")
        products = []
        for p in doc["products"]:
            releases = [{"major_version": r["major_version"], "latest_minor": r.get("latest_minor"),
                         "first_release": date.fromisoformat(r["first_release"]) if r.get("first_release") else None,
                         "end_of_support": date.fromisoformat(r["end_of_support"]) if r.get("end_of_support") else None}
                        for r in p["releases"]]
            products.append((p["product"], datetime.fromisoformat(p["as_of"]),
                             plausible(releases, p["product"])))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReferenceError(f"{path}: {exc}") from exc
    results = []
    for product, as_of, releases in products:
        current = conn.execute("SELECT as_of FROM keystone.release_reference_source WHERE product = %s",
                               (product,)).fetchone()
        if current and current["as_of"] > as_of:
            results.append((product, False, f"Keystone's reference ({current['as_of']:%Y-%m-%d}) is newer "
                                            f"than the file's ({as_of:%Y-%m-%d})"))
            continue
        store(conn, releases, "FILE", str(path), as_of, product)
        results.append((product, True, f"as of {as_of:%Y-%m-%d}"))
    return results


def load(conn, product=None):
    """(sources, releases) of one product or all, PostgreSQL first."""
    where, args = ("WHERE product = %s", (product,)) if product else ("", ())
    sources = conn.execute("SELECT product, as_of, source, source_detail "
                           f"FROM keystone.release_reference_source {where} "
                           "ORDER BY product <> 'PostgreSQL', product", args).fetchall()
    rows = conn.execute("SELECT product, major_version, latest_minor, first_release, end_of_support "
                        f"FROM keystone.release_reference {where} "
                        "ORDER BY product <> 'PostgreSQL', product, end_of_support DESC NULLS FIRST",
                        args).fetchall()
    return sources, rows


def export(conn, path):
    sources, rows = load(conn)
    day = lambda d: d.isoformat() if d else None
    doc = {"format": FILE_FORMAT,
           "products": [{"product": s["product"], "as_of": s["as_of"].isoformat(),
                         "taken_from": s["source_detail"],
                         "releases": [{"major_version": r["major_version"], "latest_minor": r["latest_minor"],
                                       "first_release": day(r["first_release"]),
                                       "end_of_support": day(r["end_of_support"])}
                                      for r in rows if r["product"] == s["product"]]}
                        for s in sources]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)


def main(argv=None):
    from repository.worker import worker

    parser = argparse.ArgumentParser(description="Keystone release reference (PostgreSQL versions).")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--show", action="store_true")
    action.add_argument("--refresh", action="store_true", help="take it from the internet now")
    action.add_argument("--import", dest="import_path", metavar="FILE", help="import a reference file")
    action.add_argument("--export", dest="export_path", metavar="FILE", help="write the reference to a file")
    args = parser.parse_args(argv)
    connect = worker.connect_repository
    if args.refresh:
        ok, detail = refresh(connect, timeout=15)
        print(("Refreshed from " if ok else "Not refreshed: ") + detail)
        if not ok:
            sys.exit(1)
    elif args.import_path:
        with connect() as conn:
            try:
                results = import_file(conn, args.import_path)
            except ReferenceError as exc:
                sys.exit(f"Not imported: {exc}")
            conn.commit()
        for product, imported, why in results:
            print(f"{'Imported' if imported else 'Kept'} {product}: {why}")
    elif args.export_path:
        with connect() as conn:
            export(conn, args.export_path)
        print(f"Written {args.export_path}")
    with connect() as conn:
        sources, rows = load(conn)
    for s in sources:
        print(f"{s['product']}: {s['source']} {s['source_detail']}, as of {s['as_of']:%Y-%m-%d}")
        for r in rows:
            if r["product"] == s["product"]:
                print(f"  {r['major_version']:>7}  latest {r['latest_minor'] or '-':<8}  "
                      f"end of support {r['end_of_support']}")


if __name__ == "__main__":
    main()
