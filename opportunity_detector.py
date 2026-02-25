import logging
from dataclasses import dataclass
from typing import Optional

from config import SPREAD_MAX_PRICE, MIN_LIQUIDITY
from weather_forecast import parse_bucket_range

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    event_type: str
    city: str
    date: str
    bucket_label: str
    market_yes_price: float
    forecast_probability: float
    edge: float
    expected_value: float
    forecast_value: float
    liquidity: float
    market_id: str
    market_slug: str
    event_title: str
    yes_token_id: str = ""


def _bucket_center(
    bucket_low: Optional[float], bucket_high: Optional[float],
) -> Optional[float]:
    if bucket_low is not None and bucket_high is not None:
        return (bucket_low + bucket_high) / 2.0
    if bucket_low is not None and bucket_high is None:
        return bucket_low + 1.0
    if bucket_low is None and bucket_high is not None:
        return bucket_high - 1.0
    return None


def find_spread_bet_opportunities(
    event: dict,
    forecast_max: float,
    max_price: float = SPREAD_MAX_PRICE,
    min_liquidity: float = MIN_LIQUIDITY,
) -> list[Opportunity]:
    markets = event.get("markets", [])

    parsed = []
    for m in markets:
        if m.get("closed", False) or not m.get("active", True):
            continue
        label = m.get("bucket_label", "")
        yes_price = m.get("yes_price", 0.0)
        liquidity = m.get("liquidity", 0)
        token_id = m.get("yes_token_id", "")
        if not token_id:
            continue

        bucket_low, bucket_high = parse_bucket_range(label)
        if bucket_low is None and bucket_high is None:
            continue

        center = _bucket_center(bucket_low, bucket_high)
        if center is None:
            continue

        parsed.append({
            "market": m,
            "label": label,
            "yes_price": yes_price,
            "liquidity": liquidity,
            "bucket_low": bucket_low,
            "bucket_high": bucket_high,
            "center": center,
            "token_id": token_id,
        })

    if not parsed:
        return []

    parsed.sort(key=lambda x: x["center"])

    forecast_rounded = round(forecast_max)
    best_idx = None
    best_dist = float("inf")
    for i, p in enumerate(parsed):
        dist = abs(p["center"] - forecast_rounded)
        if dist < best_dist:
            best_dist = dist
            best_idx = i

    if best_idx is None:
        return []

    spread_indices = []
    if best_idx > 0:
        spread_indices.append(best_idx - 1)
    spread_indices.append(best_idx)
    if best_idx < len(parsed) - 1:
        spread_indices.append(best_idx + 1)

    opportunities = []
    for idx in spread_indices:
        p = parsed[idx]
        if p["yes_price"] < 0.01 or p["yes_price"] > max_price:
            continue
        if p["liquidity"] < min_liquidity:
            continue

        opp = Opportunity(
            event_type="temperature",
            city=event.get("city_name", ""),
            date=event.get("date", ""),
            bucket_label=p["label"],
            market_yes_price=p["yes_price"],
            forecast_probability=0.0,
            edge=0.0,
            expected_value=0.0,
            forecast_value=forecast_max,
            liquidity=p["liquidity"],
            market_id=p["market"]["id"],
            market_slug=p["market"].get("slug", ""),
            event_title=event.get("title", ""),
            yes_token_id=p["token_id"],
        )
        opportunities.append(opp)

    if opportunities:
        labels = ", ".join(o.bucket_label for o in opportunities)
        prices = ", ".join(f"{o.market_yes_price*100:.0f}c" for o in opportunities)
        logger.info(
            "SPREAD BET: %s %s | forecast=%.1f | buckets=[%s] prices=[%s]",
            event.get("city_name", ""), event.get("date", ""),
            forecast_max, labels, prices,
        )

    return opportunities
