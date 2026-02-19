import logging
import sys
import time
from datetime import datetime, timedelta, timezone

from config import CITIES, EDGE_THRESHOLD, MIN_LIQUIDITY, FORECAST_DAYS
from weather_forecast import (
    fetch_hourly_forecast,
    get_daily_max_from_hourly,
    get_hourly_temps_for_day,
)
from polymarket_api import discover_weather_events
from opportunity_detector import analyze_event, Opportunity

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SEPARATOR = "=" * 80


def run_scan() -> list[Opportunity]:
    logger.info(SEPARATOR)
    logger.info("POLYMARKET WEATHER BOT - DRY RUN SCAN")
    logger.info("Scan time: %s UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(SEPARATOR)

    logger.info("Discovering weather events on Polymarket...")
    events = discover_weather_events(days_ahead=FORECAST_DAYS)
    logger.info("Found %d active weather events", len(events))

    if not events:
        logger.warning("No active weather events found. Markets may be closed or not yet created.")
        return []

    logger.info(SEPARATOR)
    logger.info("EVENTS SUMMARY")
    logger.info(SEPARATOR)
    for ev in events:
        logger.info(
            "  %s | %s | %d buckets | vol=$%.0f | liq=$%.0f",
            ev["city_name"],
            ev["date"],
            len(ev["markets"]),
            ev["volume"],
            ev["liquidity"],
        )

    all_opportunities: list[Opportunity] = []
    forecast_cache: dict[str, dict] = {}

    for ev in events:
        city_key = ev["city_key"]
        city_info = CITIES[city_key]
        date_str = ev["date"]

        cache_key = city_key
        if cache_key not in forecast_cache:
            logger.info("Fetching forecast for %s...", city_info["name"])
            forecast_data = fetch_hourly_forecast(
                lat=city_info["lat"],
                lon=city_info["lon"],
                unit=city_info["unit"],
                timezone=city_info["timezone"],
            )
            if forecast_data:
                forecast_cache[cache_key] = forecast_data
            else:
                logger.error("Failed to fetch forecast for %s", city_info["name"])
                continue
            time.sleep(0.5)

        forecast_data = forecast_cache.get(cache_key)
        if not forecast_data:
            continue

        hourly_temps = get_hourly_temps_for_day(forecast_data, date_str)
        forecast_max = get_daily_max_from_hourly(forecast_data, date_str)

        if not hourly_temps or forecast_max is None:
            logger.warning(
                "No forecast data for %s on %s", city_info["name"], date_str
            )
            continue

        unit_label = "\u00b0F" if city_info["unit"] == "fahrenheit" else "\u00b0C"
        logger.info(SEPARATOR)
        logger.info(
            "ANALYZING: %s on %s (forecast max: %.1f%s)",
            city_info["name"],
            date_str,
            forecast_max,
            unit_label,
        )

        for m in ev["markets"]:
            if m.get("closed", False):
                continue
            logger.info(
                "  Bucket: %-20s | Market YES: %5.1f%% | Liq: $%.0f",
                m["bucket_label"],
                m["yes_price"] * 100,
                m["liquidity"],
            )

        opps = analyze_event(
            event=ev,
            hourly_temps=hourly_temps,
            forecast_max=forecast_max,
            edge_threshold=EDGE_THRESHOLD,
            min_liquidity=MIN_LIQUIDITY,
        )
        all_opportunities.extend(opps)

    logger.info(SEPARATOR)
    logger.info("SCAN RESULTS")
    logger.info(SEPARATOR)

    if all_opportunities:
        all_opportunities.sort(key=lambda o: o.edge, reverse=True)
        logger.info("Found %d trading opportunities:", len(all_opportunities))
        for i, opp in enumerate(all_opportunities, 1):
            logger.info(SEPARATOR)
            logger.info("OPPORTUNITY #%d", i)
            logger.info("  City:              %s", opp.city)
            logger.info("  Date:              %s", opp.date)
            logger.info("  Bucket:            %s", opp.bucket_label)
            logger.info("  Forecast Max:      %.1f", opp.forecast_max_temp)
            logger.info("  Market YES Price:  %.1f%% ($%.3f)", opp.market_yes_price * 100, opp.market_yes_price)
            logger.info("  Forecast Prob:     %.1f%%", opp.forecast_probability * 100)
            logger.info("  Edge:              +%.1f%%", opp.edge * 100)
            logger.info("  Expected Value:    $%.3f per $1", opp.expected_value)
            logger.info("  Liquidity:         $%.0f", opp.liquidity)
            logger.info("  Market ID:         %s", opp.market_id)
            action = "BUY YES" if opp.edge > 0 else "SKIP"
            logger.info("  [DRY RUN] Action:  %s @ $%.3f", action, opp.market_yes_price)
    else:
        logger.info("No opportunities found with edge >= %.0f%%", EDGE_THRESHOLD * 100)
        logger.info("This is normal - opportunities appear when forecast diverges from market prices.")

    logger.info(SEPARATOR)
    logger.info("SCAN COMPLETE | Events: %d | Opportunities: %d", len(events), len(all_opportunities))
    logger.info(SEPARATOR)

    return all_opportunities


def main() -> None:
    logger.info("Starting Polymarket Weather Bot (DRY RUN MODE)")
    logger.info("Edge threshold: %.0f%% | Min liquidity: $%.0f", EDGE_THRESHOLD * 100, MIN_LIQUIDITY)
    logger.info("Cities monitored: %s", ", ".join(c["name"] for c in CITIES.values()))

    opportunities = run_scan()

    logger.info("Bot scan finished. Found %d opportunities total.", len(opportunities))


if __name__ == "__main__":
    main()
