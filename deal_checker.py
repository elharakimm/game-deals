"""Game deal checker.

Fetches current prices from the Steam storefront API and free games from
the Epic Games Store public endpoint, tracks a lightweight price history
in data/history.json and reports all-time lows (ATL) and free giveaways.

Usage:
    python deal_checker.py --update        # fetch + update history.json
    python deal_checker.py --show          # print today's highlights
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests

from popular_games import POPULAR_GAMES

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "data", "history.json")

STEAM_API = "https://store.steampowered.com/api/appdetails"
EPIC_API = "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Mozilla/5.0 (compatible; game-deal-tracker/1.0)"
    )
}

WORKERS = 12


def fmt_price(cents: int | None, currency: str = "USD") -> str:
    if cents is None:
        return "N/A"
    return f"{cents / 100:.2f} {currency}"


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- fetching

def fetch_steam() -> dict[int, dict]:
    """Return {appid: {name, is_free, final, initial, discount_pct, url}}.

    Steam no longer accepts comma-separated appids, so each game is fetched
    individually (in parallel) and failures are skipped.
    """
    results: dict[int, dict] = {}
    ids = list(POPULAR_GAMES.keys())

    def _one(appid: int) -> tuple[int, dict | None]:
        try:
            resp = requests.get(
                STEAM_API, params={"appids": appid},
                headers=HEADERS, timeout=30,
            )
            payload = resp.json()
        except (requests.RequestException, ValueError):
            return appid, None
        if not isinstance(payload, dict):
            return appid, None
        entry = payload.get(str(appid), {})
        if not entry.get("success") or not entry.get("data"):
            return appid, None
        data = entry["data"]
        price = data.get("price_overview") or {}
        return appid, {
            "name": data.get("name", POPULAR_GAMES.get(appid, f"App {appid}")),
            "is_free": bool(data.get("is_free")),
            "final": price.get("final") if price else None,
            "initial": price.get("initial") if price else None,
            "discount_pct": price.get("discount_percent", 0) if price else 0,
            "currency": price.get("currency", "USD") if price else "USD",
            "final_formatted": price.get("final_formatted") if price else None,
            "url": f"https://store.steampowered.com/app/{appid}/",
        }

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(_one, appid): appid for appid in ids}
        for future in as_completed(futures):
            appid, info = future.result()
            if info:
                results[appid] = info
    return results


def fetch_epic() -> dict[str, list[dict]]:
    """Return {"current": [...], "upcoming": [...]} free games on Epic."""
    try:
        resp = requests.get(EPIC_API, params={
            "locale": "en-US", "country": "US", "allowCountries": "US",
        }, headers=HEADERS, timeout=30)
        elements = resp.json()["data"]["Catalog"]["searchStore"]["elements"]
    except (requests.RequestException, ValueError, KeyError):
        return {"current": [], "upcoming": []}

    def _slug(game: dict) -> str:
        if game.get("catalogNs", {}).get("mappings"):
            return game["catalogNs"]["mappings"][0].get("pageSlug", "")
        return game.get("urlSlug", "")

    current, upcoming = [], []
    for game in elements:
        promos = game.get("promotions") or {}
        title = game.get("title", "Unknown")
        slug = _slug(game)
        url = f"https://store.epicgames.com/en-US/p/{slug}" if slug else None
        fmt = game.get("price", {}).get("totalPrice", {}).get("fmtPrice", {})
        original = fmt.get("originalPrice", "Free")
        is_free = game.get("price", {}).get("totalPrice", {}).get("discountPrice", 1) == 0

        for offer in promos.get("promotionalOffers", []):
            for promo in offer.get("promotionalOffers", []):
                current.append({
                    "title": title,
                    "url": url,
                    "original_price": original,
                    "start": promo.get("startDate", ""),
                    "end": promo.get("endDate", ""),
                    "is_free": is_free,
                })
        for offer in promos.get("upcomingPromotionalOffers", []):
            for promo in offer.get("promotionalOffers", []):
                upcoming.append({
                    "title": title,
                    "url": url,
                    "original_price": original,
                    "start": promo.get("startDate", ""),
                    "end": promo.get("endDate", ""),
                })

    current.sort(key=lambda g: g["title"].lower())
    upcoming.sort(key=lambda g: g["start"])
    return {"current": current, "upcoming": upcoming}


# ---------------------------------------------------------------- history

def load_history(path: str = HISTORY_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"steam": {}, "epic": {"seen": []}, "updated": ""}


def save_history(history: dict, path: str = HISTORY_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(history, fh, indent=2, ensure_ascii=False)


def update_history(history: dict, steam: dict[int, dict], epic: dict, day: str) -> dict:
    """Merge today's prices into history and flag all-time lows.

    Returns {"steam": [...updated games...], "epic_free_new": [...]}.
    """
    reports = []
    for appid, game in steam.items():
        record = history["steam"].setdefault(str(appid), {
            "name": game["name"],
            "url": game["url"],
            "currency": None,
            "min_price": None,
            "min_date": None,
            "prices": {},
        })
        record["name"] = game["name"]
        record["url"] = game["url"]

        price = game["final"]
        if price is None or game["is_free"]:
            continue

        # Avoid mixing currencies in one game's history (Steam geo-locates
        # prices). Once a currency is recorded, ignore differing ones.
        if record["currency"] is not None and game["currency"] != record["currency"]:
            continue
        record["currency"] = game["currency"]

        prev_min = record["min_price"]
        is_new_low = prev_min is None or price < prev_min

        record["prices"][day] = price
        if is_new_low:
            record["min_price"] = price
            record["min_date"] = day

        reports.append({
            "appid": appid,
            "name": game["name"],
            "url": game["url"],
            "final": price,
            "final_formatted": game["final_formatted"] or f"{game['currency']} {price}",
            "initial": game["initial"],
            "discount_pct": game["discount_pct"],
            "currency": game["currency"],
            "min_price": record["min_price"],
            "min_date": record["min_date"],
            "is_new_atl": is_new_low,
        })

    new_free = []
    for free_game in epic["current"]:
        title = free_game["title"]
        if title not in history["epic"]["seen"]:
            history["epic"]["seen"].append(title)
            new_free.append(title)

    history["updated"] = datetime.now(timezone.utc).isoformat()
    return {"steam": reports, "epic_free_new": new_free}


def run_check(history_path: str = HISTORY_PATH) -> dict:
    """Fetch prices, update history and return a full report."""
    steam = fetch_steam()
    epic = fetch_epic()
    history = load_history(history_path)
    report = update_history(history, steam, epic, today_utc())
    save_history(history, history_path)
    report["history"] = history
    return report


# ---------------------------------------------------------------- CLI

def main() -> None:
    parser = argparse.ArgumentParser(description="Game deal checker")
    parser.add_argument("--update", action="store_true", help="Fetch and update history")
    parser.add_argument("--show", action="store_true", help="Print today's highlights")
    args = parser.parse_args()

    if args.update:
        report = run_check()
        deals = sorted(
            (g for g in report["steam"] if g["discount_pct"] > 0),
            key=lambda g: g["discount_pct"], reverse=True,
        )
        print(f"Checked {len(report['steam'])} Steam games, {len(deals)} on sale.")
        if report["epic_free_new"]:
            print("New free games on Epic:", ", ".join(report["epic_free_new"]))
    elif args.show:
        report = run_check()
        print("=== Epic free right now ===")
        for g in report["history"]["epic"]["seen"]:
            print(f"  - {g}")
        print("=== Steam on sale ===")
        deals = sorted(
            (g for g in report["steam"] if g["discount_pct"] > 0),
            key=lambda g: g["discount_pct"], reverse=True,
        )
        for g in deals[:20]:
            atl = " [ATL!]" if g["is_new_atl"] else ""
            print(
                f"  - {g['name']}: {g['final_formatted']} "
                f"({g['discount_pct']}% off){atl}"
            )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
