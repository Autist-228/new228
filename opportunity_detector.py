import logging
from dataclasses import dataclass

from config import EDGE_THRESHOLD, MIN_LIQUIDITY, LOTTERY_MIN_PRICE, LOTTERY_MAX_PRICE
from weather_forecast import (
    parse_bucket_range,
    estimate_bucket_probability,
    parse_precipitation_range,
    estimate_precipitation_probability,
)

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


def analyze_temperature_event(
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

        if yes_price < LOTTERY_MIN_PRICE or yes_price > LOTTERY_MAX_PRICE:
            continue

        forecast_prob = estimate_bucket_probability(
            hourly_temps, bucket_low, bucket_high
        )

        edge = forecast_prob - yes_price

        if yes_price > 0:
            ev = (forecast_prob * (1.0 - yes_price)) - ((1.0 - forecast_prob) * yes_price)
        else:
            ev = 0.0

        if edge >= edge_threshold and liquidity >= min_liquidity:
            opp = Opportunity(
                event_type="temperature",
                city=event.get("city_name", ""),
                date=event.get("date", ""),
                bucket_label=label,
                market_yes_price=yes_price,
                forecast_probability=forecast_prob,
                edge=edge,
                expected_value=ev,
                forecast_value=forecast_max,
                liquidity=liquidity,
                market_id=m.get("id", ""),
                market_slug=m.get("slug", ""),
                event_title=event.get("title", ""),
                yes_token_id=m.get("yes_token_id", ""),
            )
            opportunities.append(opp)
            logger.info(
                "LOTTERY OPP: %s %s | %s @ %.1f¢ | fcst=%.0f%% edge=+%.0f%% | x%.0f",
                event.get("city_name", ""), event.get("date", ""),
                label, yes_price * 100, forecast_prob * 100, edge * 100,
                1.0 / yes_price if yes_price > 0 else 0,
            )

    return opportunities


def analyze_precipitation_event(
    event: dict,
    forecast_total: float,
    edge_threshold: float = EDGE_THRESHOLD,
    min_liquidity: float = MIN_LIQUIDITY,
) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    markets = event.get("markets", [])

    for m in markets:
        if m.get("closed", False) or not m.get("active", True):
            continue

        question = m.get("question", "")
        yes_price = m.get("yes_price", 0.0)
        liquidity = m.get("liquidity", 0)

        bucket_low, bucket_high = parse_precipitation_range(question)
        if bucket_low is None and bucket_high is None:
            continue

        forecast_prob = estimate_precipitation_probability(
            forecast_total, bucket_low, bucket_high
        )

        edge = forecast_prob - yes_price

        if yes_price > 0:
            ev = (forecast_prob * (1.0 - yes_price)) - ((1.0 - forecast_prob) * yes_price)
        else:
            ev = 0.0

        if edge >= edge_threshold and liquidity >= min_liquidity and yes_price > 0.01:
            label = m.get("bucket_label", "") or question
            opp = Opportunity(
                event_type="precipitation",
                city=event.get("city_name", ""),
                date=event.get("date", ""),
                bucket_label=label,
                market_yes_price=yes_price,
                forecast_probability=forecast_prob,
                edge=edge,
                expected_value=ev,
                forecast_value=forecast_total,
                liquidity=liquidity,
                market_id=m.get("id", ""),
                market_slug=m.get("slug", ""),
                event_title=event.get("title", ""),
                yes_token_id=m.get("yes_token_id", ""),
            )
            opportunities.append(opp)

    return opportunities
