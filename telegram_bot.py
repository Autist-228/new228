import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except requests.RequestException as exc:
        logger.error("Telegram send failed: %s", exc)
        return False


def format_scan_start(events_count: int, markets_count: int) -> str:
    return (
        "\U0001F50D <b>SCAN STARTED</b>\n"
        f"\U0001F30D Events: {events_count}\n"
        f"\U0001F4CA Markets: {markets_count}\n"
        f"\U0001F551 {_now_str()}"
    )


def format_new_bet(bet: dict) -> str:
    edge_pct = bet["edge"] * 100
    prob_pct = bet["forecast_probability"] * 100
    price_pct = bet["yes_price"] * 100

    if edge_pct >= 50:
        fire = "\U0001F525\U0001F525\U0001F525"
    elif edge_pct >= 30:
        fire = "\U0001F525\U0001F525"
    else:
        fire = "\U0001F525"

    unit = "\u00b0F" if bet.get("event_type") == "temperature" else ""
    city_flag = _city_flag(bet.get("city", ""))

    return (
        f"{fire} <b>NEW BET PLACED</b> {fire}\n"
        f"\n"
        f"{city_flag} <b>{bet['city']}</b> \u2014 {bet['date']}\n"
        f"\U0001F3AF Bucket: <code>{bet['bucket_label']}</code>\n"
        f"\U0001F4B0 Cost: <b>${bet['cost']:.2f}</b> ({bet['shares']:.0f} shares @ ${bet['yes_price']:.3f})\n"
        f"\n"
        f"\U0001F4CA Market: {price_pct:.1f}% | Forecast: {prob_pct:.1f}%\n"
        f"\U0001F4C8 Edge: <b>+{edge_pct:.1f}%</b>\n"
        f"\U0001F4B5 EV: ${bet['expected_value']:.3f}/share\n"
        f"\n"
        f"\U0001F3F7 {bet['bet_id']} | Side: YES"
    )


def format_bet_resolved(bet: dict) -> str:
    if bet["outcome"] == "WIN":
        emoji = "\U00002705\U0001F389"
        result = "WIN"
    else:
        emoji = "\U0000274C\U0001F4A8"
        result = "LOSS"

    pnl = bet["pnl"]
    pnl_emoji = "\U0001F4B0" if pnl > 0 else "\U0001F4B8"

    return (
        f"{emoji} <b>BET {result}</b> {emoji}\n"
        f"\n"
        f"\U0001F3F7 {bet['bet_id']}\n"
        f"\U0001F3AF {bet['city']} \u2014 {bet['date']}\n"
        f"\U0001F4CB Bucket: <code>{bet['bucket_label']}</code>\n"
        f"{pnl_emoji} P&L: <b>${pnl:+.2f}</b>\n"
        f"\U0001F4B0 Cost: ${bet['cost']:.2f} | Payout: ${bet['cost'] + pnl:.2f}"
    )


def format_portfolio_summary(portfolio_data: dict) -> str:
    balance = portfolio_data["balance"]
    starting = portfolio_data["starting_balance"]
    pnl = portfolio_data["total_pnl"]
    wins = portfolio_data["wins"]
    losses = portfolio_data["losses"]
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    roi = ((balance - starting) / starting * 100)
    active = len(portfolio_data["active_bets"])
    active_cost = sum(b["cost"] for b in portfolio_data["active_bets"])

    if roi > 0:
        trend = "\U0001F4C8"
    elif roi < 0:
        trend = "\U0001F4C9"
    else:
        trend = "\U00002796"

    if win_rate >= 70:
        wr_emoji = "\U0001F3C6"
    elif win_rate >= 50:
        wr_emoji = "\U0001F44D"
    else:
        wr_emoji = "\U0001F914"

    return (
        f"\U0001F4BC <b>PORTFOLIO STATUS</b>\n"
        f"\n"
        f"\U0001F4B5 Balance: <b>${balance:.2f}</b>\n"
        f"{trend} P&L: <b>${pnl:+.2f}</b> ({roi:+.1f}% ROI)\n"
        f"\n"
        f"\U0001F3B2 Active bets: {active} (${active_cost:.2f} at risk)\n"
        f"{wr_emoji} Record: {wins}W / {losses}L ({win_rate:.0f}%)\n"
        f"\U0001F4B8 Total wagered: ${portfolio_data['total_wagered']:.2f}\n"
        f"\n"
        f"\U0001F551 {_now_str()}"
    )


def format_no_opportunities() -> str:
    return (
        "\U0001F50D <b>SCAN COMPLETE</b>\n"
        f"\n"
        f"\U00002705 No opportunities with edge >= 15%\n"
        f"\U0001F551 {_now_str()}\n"
        f"\n"
        f"\U0001F504 Next scan in 5 minutes..."
    )


def format_scan_summary(
    total_events: int,
    temp_count: int,
    precip_count: int,
    climate_count: int,
    opportunities_count: int,
    bets_placed: int,
) -> str:
    return (
        f"\U0001F4CA <b>SCAN SUMMARY</b>\n"
        f"\n"
        f"\U0001F321 Temperature: {temp_count} events\n"
        f"\U0001F327 Precipitation: {precip_count} events\n"
        f"\U0001F30D Climate: {climate_count} events\n"
        f"\n"
        f"\U0001F4A1 Opportunities found: {opportunities_count}\n"
        f"\U0001F3B2 Bets placed: {bets_placed}\n"
        f"\n"
        f"\U0001F551 {_now_str()}"
    )


def format_error(error_msg: str) -> str:
    return (
        f"\U000026A0 <b>ERROR</b>\n"
        f"\n"
        f"{error_msg}\n"
        f"\n"
        f"\U0001F551 {_now_str()}"
    )


def format_bot_started() -> str:
    return (
        "\U0001F680 <b>WEATHER BOT v3 STARTED</b> \U0001F680\n"
        f"\n"
        f"\U0001F3AF Mode: Paper Trading\n"
        f"\U0001F4B5 Starting Balance: $500.00\n"
        f"\U0001F4CA Bet Size: 5% of balance\n"
        f"\U0001F321 Markets: Temperature + Precipitation + Climate\n"
        f"\U0001F504 Scan Interval: 5 minutes\n"
        f"\U0001F4C5 Days: Today + Tomorrow\n"
        f"\n"
        f"\U0001F551 {_now_str()}"
    )


def _now_str() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _city_flag(city: str) -> str:
    flags = {
        "New York City": "\U0001F1FA\U0001F1F8",
        "Miami": "\U0001F1FA\U0001F1F8",
        "Dallas": "\U0001F1FA\U0001F1F8",
        "Seattle": "\U0001F1FA\U0001F1F8",
        "Chicago": "\U0001F1FA\U0001F1F8",
        "Atlanta": "\U0001F1FA\U0001F1F8",
        "Toronto": "\U0001F1E8\U0001F1E6",
        "London": "\U0001F1EC\U0001F1E7",
        "Paris": "\U0001F1EB\U0001F1F7",
        "Seoul": "\U0001F1F0\U0001F1F7",
        "Buenos Aires": "\U0001F1E6\U0001F1F7",
        "Ankara": "\U0001F1F9\U0001F1F7",
        "Wellington": "\U0001F1F3\U0001F1FF",
        "Sao Paulo": "\U0001F1E7\U0001F1F7",
    }
    return flags.get(city, "\U0001F30D")
