import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from config import GAMMA_API_URL, CITIES

logger = logging.getLogger(__name__)


def build_event_slug(city_slug: str, date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    month = dt.strftime("%B").lower()
    day = dt.day
    year = dt.year
    return f"highest-temperature-in-{city_slug}-on-{month}-{day}-{year}"


def fetch_event_by_slug(slug: str) -> Optional[dict]:
    url = f"{GAMMA_API_URL}/events"
    params = {"slug": slug}
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data:
            return data[0]
        return None
    except requests.RequestException as exc:
        logger.error("Gamma API request failed for slug %s: %s", slug, exc)
        return None


def extract_markets_from_event(event: dict) -> list[dict]:
    markets = event.get("markets", [])
    result = []
    for m in markets:
        try:
            prices = json.loads(m.get("outcomePrices", "[]"))
            yes_price = float(prices[0]) if prices else 0.0
        except (json.JSONDecodeError, IndexError, ValueError):
            yes_price = 0.0

        result.append({
            "id": m.get("id", ""),
            "question": m.get("question", ""),
            "slug": m.get("slug", ""),
            "bucket_label": m.get("groupItemTitle", ""),
            "yes_price": yes_price,
            "volume": m.get("volumeNum", 0),
            "liquidity": m.get("liquidityNum", 0),
            "closed": m.get("closed", False),
            "active": m.get("active", True),
            "accepting_orders": m.get("acceptingOrders", True),
        })
    return result


def discover_weather_events(days_ahead: int = 3) -> list[dict]:
    events = []
    today = datetime.now(timezone.utc).date()
    for day_offset in range(days_ahead):
        target_date = today + timedelta(days=day_offset)
        date_str = target_date.strftime("%Y-%m-%d")
        for city_key, city_info in CITIES.items():
            slug = build_event_slug(city_info["slug_name"], date_str)
            event = fetch_event_by_slug(slug)
            if event and not event.get("closed", False):
                markets = extract_markets_from_event(event)
                if markets:
                    events.append({
                        "city_key": city_key,
                        "city_name": city_info["name"],
                        "date": date_str,
                        "slug": slug,
                        "event_id": event.get("id", ""),
                        "title": event.get("title", ""),
                        "volume": event.get("volume", 0),
                        "liquidity": event.get("liquidity", 0),
                        "markets": markets,
                    })
            time.sleep(0.3)
    return events
