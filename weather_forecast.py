import logging
import re
import time
from typing import Optional

import requests

from config import OPEN_METEO_URL, FORECAST_DAYS

ENSEMBLE_API_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODELS = ["gfs_seamless", "icon_seamless", "ecmwf_ifs025"]

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
        "hourly": "temperature_2m,precipitation",
        "temperature_unit": unit,
        "precipitation_unit": "inch",
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


def fetch_monthly_precipitation(
    lat: float,
    lon: float,
    timezone_str: str,
    year: int,
    month: int,
) -> Optional[dict]:
    from datetime import date
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1).isoformat()
    end_date = date(year, month, last_day).isoformat()
    today = date.today()

    if date(year, month, last_day) <= today:
        base_url = "https://archive-api.open-meteo.com/v1/archive"
    else:
        base_url = OPEN_METEO_URL

    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "precipitation_sum",
        "precipitation_unit": "inch",
        "timezone": timezone_str,
        "start_date": start_date,
        "end_date": end_date,
    }
    try:
        resp = requests.get(base_url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Open-Meteo precipitation request failed: %s", exc)
        return None


def estimate_monthly_precipitation(
    daily_data: dict,
) -> Optional[float]:
    daily = daily_data.get("daily", {})
    precip_values = daily.get("precipitation_sum", [])
    if not precip_values:
        return None
    valid = [p for p in precip_values if p is not None]
    if not valid:
        return None
    return sum(valid)


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



def forecast_hits_bucket(
    forecast_max: float,
    bucket_low: "Optional[float]",
    bucket_high: "Optional[float]",
) -> bool:
    """Check if the forecast point estimate actually falls in the bucket.

    Returns True only when the rounded forecast lands inside the bucket range.
    This prevents betting on buckets where our own forecast says NO.
    """
    rounded = round(forecast_max)
    if bucket_low is not None and rounded < bucket_low:
        return False
    if bucket_high is not None and rounded > bucket_high:
        return False
    return True


def is_exact_bucket(bucket_low: "Optional[float]", bucket_high: "Optional[float]") -> bool:
    """Return True for exact single-degree buckets (e.g. '16°C')."""
    if bucket_low is not None and bucket_high is not None and bucket_low == bucket_high:
        return True
    return False

def _request_with_retry(
    url: str,
    params: dict,
    max_retries: int = 3,
    base_delay: float = 5.0,
) -> Optional[requests.Response]:
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 429:
                delay = base_delay * (2 ** attempt)
                logger.info("Rate limited (429), waiting %.0fs before retry %d/%d",
                            delay, attempt + 1, max_retries)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning("Request failed (%s), retry %d/%d in %.0fs",
                               exc, attempt + 1, max_retries, delay)
                time.sleep(delay)
            else:
                raise
    return None


def fetch_ensemble_daily_maxes(
    lat: float,
    lon: float,
    unit: str,
    forecast_days: int = FORECAST_DAYS,
) -> Optional[dict[str, list[float]]]:
    all_member_maxes: dict[str, list[float]] = {}
    tu = "fahrenheit" if unit == "fahrenheit" else "celsius"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max",
        "temperature_unit": tu,
        "timezone": "auto",
        "forecast_days": forecast_days,
        "models": ",".join(ENSEMBLE_MODELS),
    }
    try:
        resp = _request_with_retry(ENSEMBLE_API_URL, params, max_retries=4,
                                   base_delay=10.0)
        if resp is None:
            logger.warning("Ensemble: all retries exhausted for %s,%s", lat, lon)
            return None
        data = resp.json()
        dates = data.get("daily", {}).get("time", [])
        daily = data.get("daily", {})
        for key in daily:
            if not key.startswith("temperature_2m_max"):
                continue
            vals = daily[key]
            if not isinstance(vals, list):
                continue
            for i, d in enumerate(dates):
                if i < len(vals) and vals[i] is not None:
                    all_member_maxes.setdefault(d, []).append(vals[i])
    except requests.RequestException as exc:
        logger.warning("Ensemble failed for %s,%s: %s", lat, lon, exc)
    if not all_member_maxes:
        return None
    return all_member_maxes


def estimate_bucket_probability_ensemble(
    ensemble_temps: list[float],
    bucket_low: Optional[float],
    bucket_high: Optional[float],
) -> float:
    if not ensemble_temps:
        return 0.0
    hits = 0
    for temp in ensemble_temps:
        rounded = round(temp)
        in_bucket = True
        if bucket_low is not None and rounded < bucket_low:
            in_bucket = False
        if bucket_high is not None and rounded > bucket_high:
            in_bucket = False
        if in_bucket:
            hits += 1
    return hits / len(ensemble_temps)


def estimate_bucket_probability(
    hourly_temps: list[float],
    bucket_low: Optional[float],
    bucket_high: Optional[float],
    std_dev: float = 2.0,
    n_simulations: int = 5000,
    ensemble_temps: Optional[list[float]] = None,
) -> float:
    if ensemble_temps:
        return estimate_bucket_probability_ensemble(
            ensemble_temps, bucket_low, bucket_high
        )

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


def parse_precipitation_range(question: str) -> tuple[Optional[float], Optional[float]]:
    question = question.lower()
    m = re.search(r'less than (\d+)', question)
    if m:
        return None, float(m.group(1))
    m = re.search(r'more than (\d+)', question)
    if m:
        return float(m.group(1)), None
    m = re.search(r'between (\d+) and (\d+)', question)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def estimate_precipitation_probability(
    forecast_total: float,
    bucket_low: Optional[float],
    bucket_high: Optional[float],
    std_dev: float = 0.8,
    n_simulations: int = 5000,
) -> float:
    import random

    hits = 0
    for _ in range(n_simulations):
        simulated = forecast_total + random.gauss(0, std_dev)
        if simulated < 0:
            simulated = 0
        in_bucket = True
        if bucket_low is not None and simulated < bucket_low:
            in_bucket = False
        if bucket_high is not None and simulated > bucket_high:
            in_bucket = False
        if in_bucket:
            hits += 1
    return hits / n_simulations
