import json
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from config import CITIES, GAMMA_API_URL

logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_actual_max_temperature(
    lat: float,
    lon: float,
    date_str: str,
    unit: str,
    timezone_str: str,
) -> Optional[float]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "temperature_unit": unit,
        "timezone": timezone_str,
        "start_date": date_str,
        "end_date": date_str,
    }
    try:
        resp = requests.get(ARCHIVE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        temps = daily.get("temperature_2m_max", [])
        if temps and temps[0] is not None:
            return temps[0]
        return None
    except requests.RequestException as exc:
        logger.error("Archive API failed for %s: %s", date_str, exc)
        return None


def check_market_resolution(market_id: str) -> Optional[str]:
    url = f"{GAMMA_API_URL}/markets/{market_id}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("closed", False):
            winning = data.get("winningOutcome", "")
            return winning
        return None
    except requests.RequestException as exc:
        logger.error("Failed to check market %s: %s", market_id, exc)
        return None


def resolve_temperature_bet(bet: dict) -> Optional[bool]:
    city_key = None
    city_name = bet.get("city", "")
    for key, info in CITIES.items():
        if info["name"] == city_name:
            city_key = key
            break

    if not city_key:
        logger.warning("Cannot find city key for %s", city_name)
        return _resolve_via_market(bet)

    city_info = CITIES[city_key]
    date_str = bet.get("date", "")
    if not date_str:
        return _resolve_via_market(bet)

    today = datetime.now(timezone.utc).date()
    bet_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    if bet_date > today:
        return None

    actual_max = fetch_actual_max_temperature(
        lat=city_info["lat"],
        lon=city_info["lon"],
        date_str=date_str,
        unit=city_info["unit"],
        timezone_str=city_info["timezone"],
    )

    if actual_max is None:
        return _resolve_via_market(bet)

    bucket_label = bet.get("bucket_label", "")
    rounded_max = round(actual_max)

    import re
    m = re.match(r"(-?\d+)[°]?[FC]?\s+or\s+below", bucket_label, re.IGNORECASE)
    if m:
        threshold = int(m.group(1))
        won = rounded_max <= threshold
        logger.info(
            "Resolve %s: actual max=%d, bucket='%s' -> %s",
            bet["bet_id"], rounded_max, bucket_label, "WIN" if won else "LOSS",
        )
        return won

    m = re.match(r"(-?\d+)[°]?[FC]?\s+or\s+higher", bucket_label, re.IGNORECASE)
    if m:
        threshold = int(m.group(1))
        won = rounded_max >= threshold
        logger.info(
            "Resolve %s: actual max=%d, bucket='%s' -> %s",
            bet["bet_id"], rounded_max, bucket_label, "WIN" if won else "LOSS",
        )
        return won

    m = re.match(r"(-?\d+)\s*[-–]\s*(-?\d+)", bucket_label)
    if m:
        low = int(m.group(1))
        high = int(m.group(2))
        won = low <= rounded_max <= high
        logger.info(
            "Resolve %s: actual max=%d, bucket='%s' -> %s",
            bet["bet_id"], rounded_max, bucket_label, "WIN" if won else "LOSS",
        )
        return won

    m = re.match(r"(-?\d+)[°]?[FC]?$", bucket_label)
    if m:
        val = int(m.group(1))
        won = rounded_max == val
        logger.info(
            "Resolve %s: actual max=%d, bucket='%s' -> %s",
            bet["bet_id"], rounded_max, bucket_label, "WIN" if won else "LOSS",
        )
        return won

    return _resolve_via_market(bet)


def _resolve_via_market(bet: dict) -> Optional[bool]:
    market_id = bet.get("market_id", "")
    if not market_id:
        return None
    result = check_market_resolution(market_id)
    if result is None:
        return None
    won = result.lower() == "yes"
    logger.info(
        "Resolve %s via market API: outcome=%s -> %s",
        bet["bet_id"], result, "WIN" if won else "LOSS",
    )
    return won


def try_resolve_bet(bet: dict) -> Optional[bool]:
    event_type = bet.get("event_type", "")
    if event_type == "temperature":
        return resolve_temperature_bet(bet)
    return _resolve_via_market(bet)
