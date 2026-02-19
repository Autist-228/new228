import logging
import re
import time
from typing import Optional

import requests

from config import OPEN_METEO_URL, FORECAST_DAYS

logger = logging.getLogger(__name__)


def fetch_hourly_forecast(
    lat: float,
    lon: float,
    unit: str,
    timezone: str,
    forecast_days: int = FORECAST_DAYS,
) -> Optional[dict]:
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "temperature_unit": unit,
        "timezone": timezone,
        "forecast_days": forecast_days,
    }
    try:
        resp = requests.get(OPEN_METEO_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Open-Meteo request failed: %s", exc)
        return None


def get_daily_max_from_hourly(hourly_data: dict, target_date: str) -> Optional[float]:
    times = hourly_data.get("hourly", {}).get("time", [])
    temps = hourly_data.get("hourly", {}).get("temperature_2m", [])
    day_temps = [t for ts, t in zip(times, temps) if ts.startswith(target_date)]
    if not day_temps:
        return None
    return max(day_temps)


def get_hourly_temps_for_day(hourly_data: dict, target_date: str) -> list[float]:
    times = hourly_data.get("hourly", {}).get("time", [])
    temps = hourly_data.get("hourly", {}).get("temperature_2m", [])
    return [t for ts, t in zip(times, temps) if ts.startswith(target_date)]


def parse_bucket_range(label: str) -> tuple[Optional[float], Optional[float]]:
    label = label.strip()
    m = re.match(r"(-?\d+)[°]?[FC]?\s+or\s+below", label, re.IGNORECASE)
    if m:
        return None, float(m.group(1))
    m = re.match(r"(-?\d+)[°]?[FC]?\s+or\s+higher", label, re.IGNORECASE)
    if m:
        return float(m.group(1)), None
    m = re.match(r"(-?\d+)\s*[-–]\s*(-?\d+)", label)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"(-?\d+)[°]?[FC]?$", label)
    if m:
        val = float(m.group(1))
        return val, val
    return None, None


def estimate_bucket_probability(
    hourly_temps: list[float],
    bucket_low: Optional[float],
    bucket_high: Optional[float],
    std_dev: float = 2.0,
    n_simulations: int = 5000,
) -> float:
    if not hourly_temps:
        return 0.0

    import random

    forecast_max = max(hourly_temps)
    hits = 0
    for _ in range(n_simulations):
        simulated_max = forecast_max + random.gauss(0, std_dev)
        rounded = round(simulated_max)
        in_bucket = True
        if bucket_low is not None and rounded < bucket_low:
            in_bucket = False
        if bucket_high is not None and rounded > bucket_high:
            in_bucket = False
        if in_bucket:
            hits += 1
    return hits / n_simulations
