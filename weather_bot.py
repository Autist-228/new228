import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone

from config import (
    CITIES,
    EDGE_THRESHOLD,
    MIN_LIQUIDITY,
    SCAN_INTERVAL_SECONDS,
)
from weather_forecast import (
    fetch_hourly_forecast,
    get_daily_max_from_hourly,
    get_hourly_temps_for_day,
)
from polymarket_api import discover_all_weather_events
from opportunity_detector import (
    analyze_temperature_event,
    Opportunity,
)
from paper_trader import (
    load_portfolio,
    save_portfolio,
    place_paper_bet,
    get_portfolio_summary,
    resolve_bet,
    MAX_BETS_PER_SCAN,
)
from bet_resolver import try_resolve_bet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SEPARATOR = "=" * 80
DAYS_AHEAD = 2


def run_resolve_cycle() -> list[dict]:
    portfolio = load_portfolio()
    resolved = []

    if not portfolio.active_bets:
        return resolved

    logger.info("Checking %d active bets for resolution...", len(portfolio.active_bets))
    bets_to_check = list(portfolio.active_bets)

    for bet in bets_to_check:
        result = try_resolve_bet(bet)
        if result is not None:
            resolve_bet(portfolio, bet, won=result)
            resolved.append(bet)
            time.sleep(0.5)

    if resolved:
        save_portfolio(portfolio)
        logger.info("Resolved %d bets", len(resolved))

    return resolved


def run_scan() -> tuple[list[Opportunity], list[dict]]:
    logger.info(SEPARATOR)
    logger.info("POLYMARKET WEATHER BOT v3 - AUTO PAPER TRADER")
    logger.info("Scan time: %s UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(SEPARATOR)

    events = discover_all_weather_events(days_ahead=DAYS_AHEAD)

    if not events:
        logger.warning("No active weather events found.")
        return [], []

    temp_events = [e for e in events if e["type"] == "temperature"]

    total_markets = sum(len(e["markets"]) for e in temp_events)

    logger.info(
        "EVENTS: temp=%d, total=%d markets",
        len(temp_events), total_markets,
    )

    all_opportunities: list[Opportunity] = []

    forecast_cache: dict[str, dict] = {}
    for ev in temp_events:
        city_key = ev["city_key"]
        city_info = CITIES[city_key]
        date_str = ev["date"]

        if city_key not in forecast_cache:
            forecast_data = fetch_hourly_forecast(
                lat=city_info["lat"],
                lon=city_info["lon"],
                unit=city_info["unit"],
                timezone=city_info["timezone"],
                forecast_days=DAYS_AHEAD,
            )
            if forecast_data:
                forecast_cache[city_key] = forecast_data
            else:
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
        logger.info(
            "TEMP: %s %s -> max %.1f%s",
            city_info["name"], date_str, forecast_max, unit_label,
        )

        opps = analyze_temperature_event(
            event=ev,
            hourly_temps=hourly_temps,
            forecast_max=forecast_max,
            edge_threshold=EDGE_THRESHOLD,
            min_liquidity=MIN_LIQUIDITY,
        )
        all_opportunities.extend(opps)

    if not all_opportunities:
        logger.info("No opportunities found with edge >= %.0f%%", EDGE_THRESHOLD * 100)
        return all_opportunities, []

    all_opportunities.sort(key=lambda o: o.edge, reverse=True)
    logger.info("Found %d opportunities", len(all_opportunities))

    portfolio = load_portfolio()
    bets_placed: list[dict] = []

    for opp in all_opportunities:
        if len(bets_placed) >= MAX_BETS_PER_SCAN:
            break
        opp_dict = asdict(opp)
        bet = place_paper_bet(portfolio, opp_dict)
        if bet:
            bet_dict = asdict(bet)
            bets_placed.append(bet_dict)
            time.sleep(0.3)

    portfolio.last_scan = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    save_portfolio(portfolio)

    for i, opp in enumerate(all_opportunities[:10], 1):
        logger.info(
            "  #%d [%s] %s %s | %s | edge=+%.1f%% | mkt=%.1f%% fcst=%.1f%%",
            i, opp.event_type.upper(), opp.city, opp.date,
            opp.bucket_label, opp.edge * 100,
            opp.market_yes_price * 100, opp.forecast_probability * 100,
        )

    logger.info(SEPARATOR)
    logger.info("SCAN COMPLETE | Opps: %d | Bets: %d", len(all_opportunities), len(bets_placed))
    logger.info(get_portfolio_summary(portfolio))
    logger.info(SEPARATOR)

    return all_opportunities, bets_placed


def main() -> None:
    logger.info("Starting Polymarket Weather Bot v3 - AUTO PAPER TRADER")
    logger.info("Balance: $500 | Bet size: 5%% | Edge threshold: %.0f%%", EDGE_THRESHOLD * 100)
    logger.info("Days: today + tomorrow | Scan interval: %ds", SCAN_INTERVAL_SECONDS)
    logger.info("Cities: %s", ", ".join(c["name"] for c in CITIES.values()))

    while True:
        try:
            resolved = run_resolve_cycle()
            if resolved:
                logger.info("Resolved %d bets this cycle", len(resolved))

            run_scan()

            logger.info("Next scan in %d seconds...", SCAN_INTERVAL_SECONDS)
            time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("Bot stopped by user.")
            break
        except Exception as exc:
            logger.error("Error in scan cycle: %s", exc, exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
