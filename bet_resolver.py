import logging
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
    """Fetch actual max temperature from Open-Meteo Archive API.
    
    WARNING: Only use for PAST dates (strictly before today).
    Archive API returns incomplete/partial data for the current day.
    """
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
    """Check if market is closed on Polymarket and get winning outcome."""
    url = "{0}/markets/{1}".format(GAMMA_API_URL, market_id)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("closed", False):
            winning = data.get("winningOutcome", "")
            if winning:
                return winning
        return None
    except requests.RequestException as exc:
        logger.error("Failed to check market %s: %s", market_id, exc)
        return None


def try_resolve_bet(bet: dict) -> Optional[bool]:
    """Resolve bet ONLY via Polymarket market status (closed=True).
    
    Never use Archive API or forecast data for resolution.
    Only trust Polymarket oracle. This prevents premature resolution
    on incomplete intraday data.
    """
    market_id = bet.get("market_id", "")
    if not market_id:
        logger.warning("No market_id for bet %s, skip resolve", bet.get("bet_id", "?"))
        return None

    result = check_market_resolution(market_id)
    if result is None:
        return None

    side = bet.get("side", "YES")
    if side == "YES":
        won = result.lower() == "yes"
    else:
        won = result.lower() == "no"

    logger.info(
        "RESOLVE %s | %s %s | market closed -> winner=%s side=%s -> %s",
        bet.get("bet_id", "?"),
        bet.get("city", "?"),
        bet.get("bucket_label", "?"),
        result, side,
        "WIN" if won else "LOSS",
    )
    return won
