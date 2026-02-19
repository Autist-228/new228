import logging
import time
from datetime import datetime, timezone

from config import (
    CITIES,
    PRECIPITATION_CITIES,
    EDGE_THRESHOLD,
    MIN_LIQUIDITY,
    FORECAST_DAYS,
)
from weather_forecast import (
    fetch_hourly_forecast,
    fetch_monthly_precipitation,
    estimate_monthly_precipitation,
    get_daily_max_from_hourly,
    get_hourly_temps_for_day,
)
from polymarket_api import discover_all_weather_events
from opportunity_detector import (
    analyze_temperature_event,
    analyze_precipitation_event,
    Opportunity,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SEPARATOR = "=" * 80


def run_scan() -> list[Opportunity]:
    logger.info(SEPARATOR)
    logger.info("POLYMARKET WEATHER BOT v2 - UNIVERSAL SCANNER (DRY RUN)")
    logger.info("Scan time: %s UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(SEPARATOR)

    events = discover_all_weather_events(days_ahead=FORECAST_DAYS)

    if not events:
        logger.warning("No active weather events found.")
        return []

    temp_events = [e for e in events if e["type"] == "temperature"]
    precip_events = [e for e in events if e["type"] == "precipitation"]
    climate_events = [e for e in events if e["type"] == "climate"]

    logger.info(SEPARATOR)
    logger.info("EVENTS SUMMARY")
    logger.info(SEPARATOR)
    logger.info("  Temperature events: %d", len(temp_events))
    logger.info("  Precipitation events: %d", len(precip_events))
    logger.info("  Climate/Science events: %d", len(climate_events))
    logger.info("  TOTAL: %d events, %d markets",
                len(events),
                sum(len(e["markets"]) for e in events))
    logger.info(SEPARATOR)

    for ev in events:
        logger.info(
            "  [%s] %s | %s | %d markets | vol=$%.0f",
            ev["type"].upper(),
            ev.get("city_name", "Global"),
            ev.get("date", ev.get("title", "")),
            len(ev["markets"]),
            ev.get("volume", 0),
        )

    all_opportunities: list[Opportunity] = []

    forecast_cache: dict[str, dict] = {}
    for ev in temp_events:
        city_key = ev["city_key"]
        city_info = CITIES[city_key]
        date_str = ev["date"]

        if city_key not in forecast_cache:
            logger.info("Fetching forecast for %s...", city_info["name"])
            forecast_data = fetch_hourly_forecast(
                lat=city_info["lat"],
                lon=city_info["lon"],
                unit=city_info["unit"],
                timezone=city_info["timezone"],
            )
            if forecast_data:
                forecast_cache[city_key] = forecast_data
            else:
                logger.error("Failed to fetch forecast for %s", city_info["name"])
                continue
            time.sleep(0.5)

        forecast_data = forecast_cache.get(city_key)
        if not forecast_data:
            continue

        hourly_temps = get_hourly_temps_for_day(forecast_data, date_str)
        forecast_max = get_daily_max_from_hourly(forecast_data, date_str)

        if not hourly_temps or forecast_max is None:
            continue

        unit_label = "\u00b0F" if city_info["unit"] == "fahrenheit" else "\u00b0C"
        logger.info(SEPARATOR)
        logger.info(
            "ANALYZING TEMP: %s on %s (forecast max: %.1f%s)",
            city_info["name"], date_str, forecast_max, unit_label,
        )

        for m in ev["markets"]:
            if not m.get("closed", False):
                logger.info(
                    "  Bucket: %-20s | YES: %5.1f%% | Liq: $%.0f",
                    m["bucket_label"], m["yes_price"] * 100, m["liquidity"],
                )

        opps = analyze_temperature_event(
            event=ev,
            hourly_temps=hourly_temps,
            forecast_max=forecast_max,
            edge_threshold=EDGE_THRESHOLD,
            min_liquidity=MIN_LIQUIDITY,
        )
        all_opportunities.extend(opps)

    precip_cache: dict[str, float] = {}
    now = datetime.now(timezone.utc)
    for ev in precip_events:
        city_key = ev["city_key"]
        if city_key not in precip_cache:
            p_info = PRECIPITATION_CITIES.get(city_key)
            if not p_info:
                continue
            logger.info("Fetching precipitation forecast for %s...", ev["city_name"])
            precip_data = fetch_monthly_precipitation(
                lat=p_info["lat"],
                lon=p_info["lon"],
                timezone_str=p_info["timezone"],
                year=now.year,
                month=now.month,
            )
            if precip_data:
                total = estimate_monthly_precipitation(precip_data)
                if total is not None:
                    precip_cache[city_key] = total
            time.sleep(0.5)

        forecast_total = precip_cache.get(city_key)
        if forecast_total is None:
            continue

        logger.info(SEPARATOR)
        logger.info(
            "ANALYZING PRECIP: %s (forecast total: %.1f inches so far + remaining days)",
            ev["city_name"], forecast_total,
        )

        for m in ev["markets"]:
            if not m.get("closed", False):
                question = m.get("question", m.get("bucket_label", ""))
                logger.info(
                    "  %-50s | YES: %5.1f%% | Liq: $%.0f",
                    question[:50], m["yes_price"] * 100, m["liquidity"],
                )

        opps = analyze_precipitation_event(
            event=ev,
            forecast_total=forecast_total,
            edge_threshold=EDGE_THRESHOLD,
            min_liquidity=MIN_LIQUIDITY,
        )
        all_opportunities.extend(opps)

    if climate_events:
        logger.info(SEPARATOR)
        logger.info("CLIMATE/SCIENCE EVENTS (info only, no forecast model):")
        for ev in climate_events:
            logger.info(SEPARATOR)
            logger.info("  %s", ev["title"])
            logger.info("  Vol: $%.0f | Markets: %d", ev.get("volume", 0), len(ev["markets"]))
            for m in ev["markets"]:
                if not m.get("closed", False):
                    question = m.get("question", m.get("bucket_label", ""))
                    logger.info(
                        "    %-60s | YES: %5.1f%%",
                        question[:60], m["yes_price"] * 100,
                    )

    logger.info(SEPARATOR)
    logger.info("SCAN RESULTS")
    logger.info(SEPARATOR)

    if all_opportunities:
        all_opportunities.sort(key=lambda o: o.edge, reverse=True)
        logger.info("Found %d trading opportunities:", len(all_opportunities))
        for i, opp in enumerate(all_opportunities, 1):
            logger.info(SEPARATOR)
            logger.info("OPPORTUNITY #%d [%s]", i, opp.event_type.upper())
            logger.info("  City:              %s", opp.city)
            logger.info("  Date:              %s", opp.date)
            logger.info("  Bucket:            %s", opp.bucket_label)
            logger.info("  Forecast Value:    %.1f", opp.forecast_value)
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

    logger.info(SEPARATOR)
    logger.info(
        "SCAN COMPLETE | Events: %d (temp=%d, precip=%d, climate=%d) | Opportunities: %d",
        len(events), len(temp_events), len(precip_events), len(climate_events),
        len(all_opportunities),
    )
    logger.info(SEPARATOR)

    return all_opportunities


def main() -> None:
    logger.info("Starting Polymarket Weather Bot v2 - UNIVERSAL SCANNER (DRY RUN)")
    logger.info("Edge threshold: %.0f%% | Min liquidity: $%.0f", EDGE_THRESHOLD * 100, MIN_LIQUIDITY)
    logger.info("Temperature cities: %s", ", ".join(c["name"] for c in CITIES.values()))
    logger.info("Precipitation cities: %s", ", ".join(PRECIPITATION_CITIES.keys()))

    opportunities = run_scan()
    logger.info("Bot scan finished. Found %d opportunities total.", len(opportunities))


if __name__ == "__main__":
    main()
