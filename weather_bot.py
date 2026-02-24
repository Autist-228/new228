import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone, timedelta

from config import (
    CITIES,
    EDGE_THRESHOLD,
    MIN_LIQUIDITY,
    SCAN_INTERVAL_SECONDS,
)
from weather_forecast import (
    fetch_hourly_forecast,
    fetch_ensemble_daily_maxes,
    get_daily_max_from_hourly,
    get_hourly_temps_for_day,
    RateLimitError,
)
from polymarket_api import discover_all_weather_events
from opportunity_detector import (
    analyze_temperature_event,
    Opportunity,
)
from real_trader import (
    load_portfolio,
    save_portfolio,
    place_real_bet,
    get_portfolio_summary,
    resolve_bet,
    get_trader,
    MAX_BETS_PER_SCAN,
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
ENSEMBLE_CACHE_TTL = 1800
_ensemble_global_cache: dict[str, tuple[float, dict[str, list[float]]]] = {}


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
    ensemble_cache: dict[str, dict[str, list[float]]] = {}
    ensemble_rate_limited = False

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

        if city_key not in ensemble_cache and not ensemble_rate_limited:
            now_ts = time.time()
            cached = _ensemble_global_cache.get(city_key)
            if cached and (now_ts - cached[0]) < ENSEMBLE_CACHE_TTL:
                ensemble_cache[city_key] = cached[1]
                logger.info("ENSEMBLE: %s using cached data (age %ds)",
                            city_info["name"], int(now_ts - cached[0]))
            else:
                try:
                    ens_data = fetch_ensemble_daily_maxes(
                        lat=city_info["lat"], lon=city_info["lon"],
                        unit=city_info["unit"], forecast_days=DAYS_AHEAD,
                    )
                    if ens_data:
                        ensemble_cache[city_key] = ens_data
                        _ensemble_global_cache[city_key] = (now_ts, ens_data)
                        logger.info("ENSEMBLE: %s loaded %d members (fresh)",
                                    city_info["name"],
                                    len(next(iter(ens_data.values()), [])))
                    time.sleep(2)
                except RateLimitError:
                    ensemble_rate_limited = True
                    logger.warning("CIRCUIT BREAKER: ensemble API rate limited, "
                                   "skipping remaining cities this scan")

        forecast_data = forecast_cache.get(city_key)
        if not forecast_data:
            continue

        hourly_temps = get_hourly_temps_for_day(forecast_data, date_str)
        forecast_max = get_daily_max_from_hourly(forecast_data, date_str)
        if not hourly_temps or forecast_max is None:
            continue

        unit_label = "\u00b0F" if city_info["unit"] == "fahrenheit" else "\u00b0C"
        logger.info("TEMP: %s %s -> max %.1f%s", city_info["name"], date_str, forecast_max, unit_label)

        ens_temps_for_date = None
        if city_key in ensemble_cache:
            ens_temps_for_date = ensemble_cache[city_key].get(date_str)

        opps = analyze_temperature_event(
            event=ev, hourly_temps=hourly_temps,
            forecast_max=forecast_max,
            edge_threshold=EDGE_THRESHOLD, min_liquidity=MIN_LIQUIDITY,
            ensemble_temps=ens_temps_for_date,
        )
        all_opportunities.extend(opps)

    if not all_opportunities:
        logger.info("No opportunities with edge >= %.0f%%", EDGE_THRESHOLD * 100)
        portfolio = load_portfolio()
        portfolio.last_scan = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        save_portfolio(portfolio)
        return all_opportunities, []

    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")

    all_opportunities.sort(key=lambda o: (0 if o.date == today_str else 1, -o.edge))
    today_count = sum(1 for o in all_opportunities if o.date == today_str)
    tomorrow_count = len(all_opportunities) - today_count

    logger.info(
        "Found %d opps (today: %d, tmrw: %d)",
        len(all_opportunities), today_count, tomorrow_count,
    )

    usdc_bal = trader.get_usdc_balance()
    logger.info("USDC: $%.2f", usdc_bal)

    portfolio = load_portfolio()
    bets_placed: list[dict] = []
    for opp in all_opportunities:
        if len(bets_placed) >= MAX_BETS_PER_SCAN:
            break
        opp_dict = asdict(opp)
        bet = place_real_bet(portfolio, opp_dict, trader)
        if bet:
            bets_placed.append(bet)
            time.sleep(1)

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
    logger.info("SCAN DONE | Opps: %d | Bets: %d", len(all_opportunities), len(bets_placed))
    logger.info(get_portfolio_summary(portfolio))
    logger.info(SEPARATOR)
    return all_opportunities, bets_placed


def main() -> None:
    logger.info("Starting Polymarket Weather Bot - REAL MONEY")
    logger.info("Edge: %.0f%% | Scan: %ds", EDGE_THRESHOLD * 100, SCAN_INTERVAL_SECONDS)
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
