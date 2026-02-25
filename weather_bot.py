import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone

from config import (
    CITIES,
    SCAN_INTERVAL_SECONDS,
    SPREAD_BET_AMOUNT,
)
from weather_forecast import (
    fetch_hourly_forecast,
    get_daily_max_from_hourly,
)
from polymarket_api import discover_all_weather_events
from opportunity_detector import (
    find_spread_bet_opportunities,
    Opportunity,
)
from real_trader import (
    load_portfolio,
    save_portfolio,
    place_real_bet,
    get_portfolio_summary,
    resolve_bet,
    get_trader,
)
from bet_resolver import try_resolve_bet, fetch_actual_max_temperature
from token_redeemer import redeem_winning_tokens

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

    trader = get_trader()
    private_key = getattr(trader, "private_key", "") if trader else ""
    wallet_address = getattr(trader, "wallet_address", "") if trader else ""

    bets_to_check = list(portfolio.active_bets)
    for bet in bets_to_check:
        result = try_resolve_bet(bet)
        if result is not None:
            resolve_bet(portfolio, bet, won=result)
            resolved.append(bet)
            if result and private_key and wallet_address and bet.get("token_id"):
                try:
                    gained = redeem_winning_tokens(bet, private_key, wallet_address)
                    if gained is not None and gained > 0:
                        bet["redeemed_usdc"] = round(gained, 4)
                        logger.info("AUTO-REDEEM: %s +$%.4f USDC", bet.get("bet_id"), gained)
                    elif gained == 0:
                        logger.info("AUTO-REDEEM: %s no tokens to redeem", bet.get("bet_id"))
                    else:
                        logger.warning("AUTO-REDEEM: %s redemption failed, will retry next cycle", bet.get("bet_id"))
                except Exception as exc:
                    logger.error("AUTO-REDEEM error for %s: %s", bet.get("bet_id"), exc)
            time.sleep(0.5)
    if resolved:
        save_portfolio(portfolio)
        logger.info("Resolved %d bets", len(resolved))
    return resolved


def run_scan() -> tuple[list[Opportunity], list[dict]]:
    logger.info(SEPARATOR)
    logger.info("POLYMARKET WEATHER BOT - REAL MONEY")
    logger.info("Scan: %s UTC", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    logger.info(SEPARATOR)

    trader = get_trader()
    if not trader.is_ready:
        if not trader.initialize():
            logger.error("Trader not ready, skip scan")
            return [], []

    trader.check_and_refill_gas()

    events = discover_all_weather_events(days_ahead=DAYS_AHEAD)
    if not events:
        logger.warning("No active weather events found.")
        return [], []

    temp_events = [e for e in events if e["type"] == "temperature"]
    total_markets = sum(len(e["markets"]) for e in temp_events)
    logger.info("EVENTS: temp=%d, total=%d markets", len(temp_events), total_markets)

    all_opportunities: list[Opportunity] = []
    today_date = datetime.now(timezone.utc).date()
    resolved_cache: dict[str, bool] = {}
    forecast_cache: dict[str, dict] = {}

    for ev in temp_events:
        city_key = ev["city_key"]
        city_info = CITIES[city_key]
        date_str = ev["date"]

        ev_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if ev_date < today_date:
            cache_key = "{0}_{1}".format(city_key, date_str)
            if cache_key not in resolved_cache:
                actual = fetch_actual_max_temperature(
                    lat=city_info["lat"], lon=city_info["lon"],
                    date_str=date_str, unit=city_info["unit"],
                    timezone_str=city_info["timezone"],
                )
                resolved_cache[cache_key] = actual is not None
                time.sleep(0.3)
            if resolved_cache[cache_key]:
                logger.info("SKIP %s %s - actual temp known", city_info["name"], date_str)
                continue

        if city_key not in forecast_cache:
            forecast_data = fetch_hourly_forecast(
                lat=city_info["lat"], lon=city_info["lon"],
                unit=city_info["unit"], timezone=city_info["timezone"],
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

        forecast_max = get_daily_max_from_hourly(forecast_data, date_str)
        if forecast_max is None:
            continue

        unit_label = "\u00b0F" if city_info["unit"] == "fahrenheit" else "\u00b0C"
        logger.info("TEMP: %s %s -> max %.1f%s", city_info["name"], date_str, forecast_max, unit_label)

        opps = find_spread_bet_opportunities(
            event=ev,
            forecast_max=forecast_max,
        )
        all_opportunities.extend(opps)

    if not all_opportunities:
        logger.info("No spread bet opportunities found")
        portfolio = load_portfolio()
        portfolio.last_scan = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        save_portfolio(portfolio)
        return all_opportunities, []

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    all_opportunities.sort(key=lambda o: (0 if o.date == today_str else 1, o.market_yes_price))
    today_count = sum(1 for o in all_opportunities if o.date == today_str)
    tomorrow_count = len(all_opportunities) - today_count

    logger.info(
        "SPREAD BET: %d bucket opps (today: %d, tmrw: %d)",
        len(all_opportunities), today_count, tomorrow_count,
    )

    usdc_bal = trader.get_usdc_balance()
    logger.info("USDC: $%.2f", usdc_bal)

    portfolio = load_portfolio()
    bets_placed: list[dict] = []
    for opp in all_opportunities:
        opp_dict = asdict(opp)
        bet = place_real_bet(portfolio, opp_dict, trader)
        if bet:
            bets_placed.append(bet)
            time.sleep(1)

    portfolio.last_scan = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    save_portfolio(portfolio)

    for i, opp in enumerate(all_opportunities[:15], 1):
        logger.info(
            "  #%d %s %s | %s @ %.0f¢",
            i, opp.city, opp.date,
            opp.bucket_label, opp.market_yes_price * 100,
        )

    logger.info(SEPARATOR)
    logger.info("SCAN DONE | Spread opps: %d | Bets placed: %d", len(all_opportunities), len(bets_placed))
    logger.info(get_portfolio_summary(portfolio))
    logger.info(SEPARATOR)
    return all_opportunities, bets_placed


def main() -> None:
    logger.info("Starting Polymarket Weather Bot - SPREAD BET STRATEGY")
    logger.info("Bet: $%.2f/bucket | Max price: 20c | Scan: %ds", SPREAD_BET_AMOUNT, SCAN_INTERVAL_SECONDS)
    logger.info("Cities: %s", ", ".join(c["name"] for c in CITIES.values()))
    while True:
        try:
            resolved = run_resolve_cycle()
            if resolved:
                logger.info("Resolved %d bets", len(resolved))
            run_scan()
            logger.info("Next scan in %d seconds...", SCAN_INTERVAL_SECONDS)
            time.sleep(SCAN_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("Bot stopped.")
            break
        except Exception as exc:
            logger.error("Scan error: %s", exc, exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    main()
