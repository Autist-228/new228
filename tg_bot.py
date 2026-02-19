#!/usr/bin/env python3
"""Interactive Telegram Dashboard for Polymarket Weather Bot v3.

Run this as the main entry point instead of weather_bot.py.
Provides button-based dashboard + auto-scanning every 5 minutes.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from telegram.constants import ParseMode

from paper_trader import load_portfolio

logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
AUTHORIZED_ID = int(CHAT_ID) if CHAT_ID else 0

LINE = "\u2501" * 24
SCAN_INTERVAL = 300


def _wr(history: list[dict], hours: int) -> tuple[int, int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    w = l = 0
    for b in history:
        ra = b.get("resolved_at", "")
        if not ra:
            continue
        try:
            ts = datetime.strptime(
                ra.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts >= cutoff:
            if b.get("outcome") == "WIN":
                w += 1
            else:
                l += 1
    return w, l


def _fmt_wr(w: int, l: int) -> str:
    t = w + l
    return f"{w}W/{l}L ({w * 100 // t}%)" if t > 0 else "\u2014"


def _dashboard() -> str:
    p = load_portfolio()
    roi = (p.balance - p.starting_balance) / p.starting_balance * 100
    w24, l24 = _wr(p.history, 24)
    w7, l7 = _wr(p.history, 168)
    ac = sum(b["cost"] for b in p.active_bets)
    pe = "\U0001F4C8" if p.total_pnl >= 0 else "\U0001F4C9"

    return (
        f"\U0001F3E6 <b>POLYMARKET WEATHER BOT</b>\n"
        f"{LINE}\n\n"
        f"\U0001F4B0 \u0411\u0430\u043B\u0430\u043D\u0441: <b>${p.balance:.2f}</b>\n"
        f"{pe} P&L: <b>${p.total_pnl:+.2f}</b> ({roi:+.1f}%)\n\n"
        f"{LINE}\n\n"
        f"\U0001F4CA \u041E\u0442\u043A\u0440\u044B\u0442\u043E: <b>{len(p.active_bets)}</b> \u0441\u0442\u0430\u0432\u043E\u043A (${ac:.2f})\n"
        f"\u2705 \u0417\u0430\u043A\u0440\u044B\u0442\u043E: <b>{len(p.history)}</b> \u0441\u0442\u0430\u0432\u043E\u043A\n"
        f"\U0001F3AF \u0412\u0438\u043D\u0440\u0435\u0439\u0442 24\u0447: {_fmt_wr(w24, l24)}\n"
        f"\U0001F3AF \u0412\u0438\u043D\u0440\u0435\u0439\u0442 7\u0434: {_fmt_wr(w7, l7)}\n\n"
        f"{LINE}\n\n"
        f"\U0001F504 \u0410\u0432\u0442\u043E-\u0441\u043A\u0430\u043D: \u043A\u0430\u0436\u0434\u044B\u0435 5 \u043C\u0438\u043D\n"
        f"\u23F1 \u041F\u043E\u0441\u043B\u0435\u0434\u043D\u0438\u0439: {p.last_scan or '\u2014'}"
    )


def _main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("\U0001F4CA \u041F\u043E\u0437\u0438\u0446\u0438\u0438", callback_data="pos"),
            InlineKeyboardButton("\U0001F4CB \u0418\u0441\u0442\u043E\u0440\u0438\u044F", callback_data="hist"),
        ],
        [
            InlineKeyboardButton("\U0001F4C8 \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043A\u0430", callback_data="stats"),
            InlineKeyboardButton("\U0001F504 \u041E\u0431\u043D\u043E\u0432\u0438\u0442\u044C", callback_data="back"),
        ],
    ])


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u25C0\uFE0F \u041D\u0430\u0437\u0430\u0434", callback_data="back")]
    ])


def _positions() -> str:
    p = load_portfolio()
    if not p.active_bets:
        return (
            f"\U0001F4CA <b>\u041E\u0422\u041A\u0420\u042B\u0422\u042B\u0415 \u041F\u041E\u0417\u0418\u0426\u0418\u0418</b>\n"
            f"{LINE}\n\n"
            f"\u041D\u0435\u0442 \u043E\u0442\u043A\u0440\u044B\u0442\u044B\u0445 \u0441\u0442\u0430\u0432\u043E\u043A."
        )

    show = p.active_bets[:8]
    lines = [
        f"\U0001F4CA <b>\u041E\u0422\u041A\u0420\u042B\u0422\u042B\u0415 \u041F\u041E\u0417\u0418\u0426\u0418\u0418 ({len(p.active_bets)})</b>\n{LINE}\n"
    ]
    for b in show:
        edge_pct = b["edge"] * 100
        flag = _city_flag(b.get("city", ""))
        lines.append(
            f"\n\U0001F3AB <b>{b['bet_id']}</b>\n"
            f"   {flag} {b['city']} \u2014 {b['date']}\n"
            f"   \U0001F3AF {b['bucket_label']}\n"
            f"   \U0001F4B5 ${b['cost']:.2f} | {b['shares']:.0f} \u0430\u043A\u0446\u0438\u0439 @ ${b['yes_price']:.3f}\n"
            f"   \U0001F4C8 Edge: <b>+{edge_pct:.1f}%</b>\n"
        )
    if len(p.active_bets) > 8:
        lines.append(f"\n<i>...\u0438 \u0435\u0449\u0451 {len(p.active_bets) - 8}</i>")
    return "".join(lines)


def _history() -> str:
    p = load_portfolio()
    if not p.history:
        return (
            f"\U0001F4CB <b>\u0418\u0421\u0422\u041E\u0420\u0418\u042F \u0421\u0414\u0415\u041B\u041E\u041A</b>\n"
            f"{LINE}\n\n"
            f"\u0418\u0441\u0442\u043E\u0440\u0438\u044F \u043F\u0443\u0441\u0442\u0430."
        )

    recent = list(reversed(p.history[-10:]))
    lines = [
        f"\U0001F4CB <b>\u0418\u0421\u0422\u041E\u0420\u0418\u042F (\u043F\u043E\u0441\u043B\u0435\u0434\u043D\u0438\u0435 {len(recent)})</b>\n{LINE}\n"
    ]
    for b in recent:
        e = "\u2705" if b.get("outcome") == "WIN" else "\u274C"
        lines.append(
            f"\n{e} <b>{b['bet_id']}</b> {b.get('outcome', '?')} | "
            f"<b>${b.get('pnl', 0):+.2f}</b>\n"
            f"   {b['city']} {b['date']} | {b['bucket_label']}\n"
            f"   \u23F1 {b.get('resolved_at', '\u2014')}\n"
        )
    return "".join(lines)


def _stats() -> str:
    p = load_portfolio()
    roi = (p.balance - p.starting_balance) / p.starting_balance * 100
    w24, l24 = _wr(p.history, 24)
    w7, l7 = _wr(p.history, 168)
    ac = sum(b["cost"] for b in p.active_bets)
    bp = max((b.get("pnl", 0) for b in p.history), default=0)
    wp = min((b.get("pnl", 0) for b in p.history), default=0)

    return (
        f"\U0001F4C8 <b>\u0421\u0422\u0410\u0422\u0418\u0421\u0422\u0418\u041A\u0410</b>\n{LINE}\n\n"
        f"\U0001F4B0 \u0411\u0430\u043B\u0430\u043D\u0441: <b>${p.balance:.2f}</b>\n"
        f"\U0001F4CA P&L: <b>${p.total_pnl:+.2f}</b> ({roi:+.1f}%)\n"
        f"\U0001F4B5 \u0412 \u0441\u0442\u0430\u0432\u043A\u0430\u0445: ${ac:.2f}\n\n"
        f"{LINE}\n\n"
        f"\U0001F3AF <b>\u0412\u0418\u041D\u0420\u0415\u0419\u0422</b>\n"
        f"   24\u0447: {_fmt_wr(w24, l24)}\n"
        f"   7\u0434: {_fmt_wr(w7, l7)}\n"
        f"   \u0412\u0441\u0451: {_fmt_wr(p.wins, p.losses)}\n\n"
        f"{LINE}\n\n"
        f"\U0001F4CA <b>\u0421\u0414\u0415\u041B\u041A\u0418</b>\n"
        f"   \u0412\u0441\u0435\u0433\u043E: {p.total_bets}\n"
        f"   \u041E\u0442\u043A\u0440\u044B\u0442\u043E: {len(p.active_bets)}\n"
        f"   \u0417\u0430\u043A\u0440\u044B\u0442\u043E: {len(p.history)}\n"
        f"   \u041E\u0431\u043E\u0440\u043E\u0442: ${p.total_wagered:.2f}\n\n"
        f"\U0001F3C6 \u041B\u0443\u0447\u0448\u0430\u044F: <b>${bp:+.2f}</b>\n"
        f"\U0001F480 \u0425\u0443\u0434\u0448\u0430\u044F: <b>${wp:+.2f}</b>"
    )


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


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if AUTHORIZED_ID and update.effective_chat.id != AUTHORIZED_ID:
        return
    await update.message.reply_text(
        _dashboard(), parse_mode=ParseMode.HTML, reply_markup=_main_kb()
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if AUTHORIZED_ID and q.from_user.id != AUTHORIZED_ID:
        await q.answer()
        return

    await q.answer()
    d = q.data

    if d == "back":
        text, kb = _dashboard(), _main_kb()
    elif d == "pos":
        text, kb = _positions(), _back_kb()
    elif d == "hist":
        text, kb = _history(), _back_kb()
    elif d == "stats":
        text, kb = _stats(), _back_kb()
    else:
        return

    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        pass


async def scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    from weather_bot import run_scan, run_resolve_cycle

    try:
        await asyncio.to_thread(run_resolve_cycle)
        await asyncio.to_thread(run_scan)
    except Exception as exc:
        logger.error("Scan error: %s", exc, exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text=f"\u26A0\uFE0F <b>\u041E\u0428\u0418\u0411\u041A\u0410 \u0421\u041A\u0410\u041D\u0410</b>\n\n{exc}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def startup_notify(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        p = load_portfolio()
        n_active = len(p.active_bets)
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "\U0001F680 <b>\u0411\u041E\u0422 \u0417\u0410\u041F\u0423\u0429\u0415\u041D</b> \U0001F680\n\n"
                + _dashboard()
                + f"\n\n\U0001F4E1 \u041F\u0435\u0440\u0432\u044B\u0439 \u0441\u043A\u0430\u043D \u0447\u0435\u0440\u0435\u0437 10 \u0441\u0435\u043A..."
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_kb(),
        )
    except Exception as exc:
        logger.error("Startup notify failed: %s", exc)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not TOKEN:
        logger.error("Set TELEGRAM_BOT_TOKEN env var!")
        return
    if not CHAT_ID:
        logger.error("Set TELEGRAM_CHAT_ID env var!")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(on_button))

    if app.job_queue:
        app.job_queue.run_once(startup_notify, when=2)
        app.job_queue.run_repeating(scan_job, interval=SCAN_INTERVAL, first=10)

    logger.info("Bot starting... Scan interval: %ds", SCAN_INTERVAL)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
