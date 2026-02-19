import logging
from dataclasses import dataclass, field

from config import EDGE_THRESHOLD, MIN_LIQUIDITY
from weather_forecast import (
    parse_bucket_range,
    estimate_bucket_probability,
)

logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    city: str
    date: str
    bucket_label: str
    market_yes_price: float
    forecast_probability: float
    edge: float
    expected_value: float
    forecast_max_temp: float
    liquidity: float
    market_id: str
    market_slug: str


def analyze_event(
    event: dict,
    hourly_temps: list[float],
    forecast_max: float,
    edge_threshold: float = EDGE_THRESHOLD,
    min_liquidity: float = MIN_LIQUIDITY,
) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    markets = event.get("markets", [])

    for m in markets:
        if m.get("closed", False) or not m.get("active", True):
            continue

        label = m.get("bucket_label", "")
        yes_price = m.get("yes_price", 0.0)
        liquidity = m.get("liquidity", 0)

        bucket_low, bucket_high = parse_bucket_range(label)
        if bucket_low is None and bucket_high is None:
            continue

        forecast_prob = estimate_bucket_probability(
            hourly_temps, bucket_low, bucket_high
        )

        edge = forecast_prob - yes_price

        if yes_price > 0:
            ev = (forecast_prob * (1.0 - yes_price)) - ((1.0 - forecast_prob) * yes_price)
        else:
            ev = 0.0

        if edge >= edge_threshold and liquidity >= min_liquidity and yes_price > 0.01:
            opp = Opportunity(
                city=event.get("city_name", ""),
                date=event.get("date", ""),
                bucket_label=label,
                market_yes_price=yes_price,
                forecast_probability=forecast_prob,
                edge=edge,
                expected_value=ev,
                forecast_max_temp=forecast_max,
                liquidity=liquidity,
                market_id=m.get("id", ""),
                market_slug=m.get("slug", ""),
            )
            opportunities.append(opp)
            logger.info(
                "OPPORTUNITY: %s %s | bucket=%s | market=%.1f%% forecast=%.1f%% edge=%.1f%% EV=%.3f",
                event.get("city_name"),
                event.get("date"),
                label,
                yes_price * 100,
                forecast_prob * 100,
                edge * 100,
                ev,
            )

    return opportunities
