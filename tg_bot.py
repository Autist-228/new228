#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from paper_trader import load_portfolio, save_portfolio, Portfolio

logger = logging.getLogger(__name__)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
AUTHORIZED_ID = int(CHAT_ID) if CHAT_ID else 0

LINE = "\u2501" * 22
SCAN_INTERVAL = 300
ITEMS_PER_PAGE = 5

SET_BALANCE, SET_MAX_BET = range(2)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def _kelly_bet(balance: float, edge: float, yes_price: float, max_pct: float) -> float:
    if yes_price <= 0 or yes_price >= 1 or edge <= 0:
        return 0.0
    b = (1.0 / yes_price) - 1.0
    p = yes_price + edge
    if p > 1:
        p = 0.99
    q = 1.0 - p
    kelly_frac = (b * p - q) / b
    if kelly_frac <= 0:
        return 0.0
    kelly_frac = kelly_frac * 0.5
    frac = min(kelly_frac, max_pct)
    bet_amt = round(balance * frac, 2)
    return max(bet_amt, 0.0)


def _load_settings() -> dict:
    defaults = {"max_bet_pct": 0.05, "session_active": False}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            for k, v in defaults.items():
                if k not in data:
                    data[k] = v
            return data
        except Exception:
            pass
    return defaults


def _save_settings(s: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)


def _wr(history: list, hours: int) -> tuple:
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
    return "{0}W / {1}L ({2}%)".format(w, l, w * 100 // t) if t > 0 else "\u2014"


def _daily_pnl(history: list) -> dict:
    daily = {}
    for b in history:
        ra = b.get("resolved_at", "")
        if not ra:
            continue
        day = ra[:10]
        daily[day] = daily.get(day, 0.0) + b.get("pnl", 0.0)
    return daily


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


def _main_text() -> str:
    p = load_portfolio()
    s = _load_settings()
    roi = (p.balance - p.starting_balance) / p.starting_balance * 100 if p.starting_balance else 0
    ac = sum(b["cost"] for b in p.active_bets)
    w24, l24 = _wr(p.history, 24)
    w7, l7 = _wr(p.history, 168)
    pe = "\U0001F4C8" if p.total_pnl >= 0 else "\U0001F4C9"
    status = "\U0001F7E2 \u0410\u043a\u0442\u0438\u0432\u043d\u0430" if s.get("session_active") else "\U0001F534 \u041e\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u0430"
    max_pct = s.get("max_bet_pct", 0.05)
    last_scan = p.last_scan or "\u2014"

    return (
        "\U0001F3E6 <b>POLYMARKET WEATHER BOT</b>\n"
        "{line}\n\n"
        "\U0001F4B0 <b>\u0411\u0430\u043b\u0430\u043d\u0441: ${bal:.2f}</b>\n"
        "{pe} P&L: <b>${pnl:+.2f}</b> ({roi:+.1f}%)\n\n"
        "{line}\n\n"
        "\U0001F4CA \u041e\u0442\u043a\u0440\u044b\u0442\u043e: <b>{active}</b> \u0441\u0442\u0430\u0432\u043e\u043a (${ac:.2f})\n"
        "\u2705 \u0417\u0430\u043a\u0440\u044b\u0442\u043e: <b>{closed}</b> \u0441\u0442\u0430\u0432\u043e\u043a\n"
        "\U0001F3AF \u0412\u0438\u043d\u0440\u0435\u0439\u0442 24\u0447: {wr24}\n"
        "\U0001F3AF \u0412\u0438\u043d\u0440\u0435\u0439\u0442 7\u0434: {wr7}\n\n"
        "{line}\n\n"
        "\U0001F4CE \u041c\u0430\u043a\u0441. \u0441\u0442\u0430\u0432\u043a\u0430: <b>{mpct:.0f}%</b> (\u043e\u0442 \u0431\u0430\u043b\u0430\u043d\u0441\u0430)\n"
        "\U0001F916 \u0421\u0435\u0441\u0441\u0438\u044f: {status}\n"
        "\U0001F504 \u0421\u043a\u0430\u043d: \u043a\u0430\u0436\u0434\u044b\u0435 5 \u043c\u0438\u043d\n"
        "\u23F1 \u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0439: {last}"
    ).format(
        line=LINE, bal=p.balance, pe=pe, pnl=p.total_pnl, roi=roi,
        active=len(p.active_bets), ac=ac, closed=len(p.history),
        wr24=_fmt_wr(w24, l24), wr7=_fmt_wr(w7, l7),
        mpct=max_pct * 100, status=status, last=last_scan,
    )


def _main_kb() -> InlineKeyboardMarkup:
    s = _load_settings()
    if s.get("session_active"):
        session_btn = InlineKeyboardButton(
            "\U0001F534 \u0421\u0442\u043e\u043f \u0441\u0435\u0441\u0441\u0438\u044e", callback_data="stop_session"
        )
    else:
        session_btn = InlineKeyboardButton(
            "\U0001F7E2 \u0421\u0442\u0430\u0440\u0442 \u0441\u0435\u0441\u0441\u0438\u044e", callback_data="start_session"
        )
    return InlineKeyboardMarkup([
        [session_btn,
         InlineKeyboardButton("\U0001F504 \u0421\u0431\u0440\u043e\u0441\u0438\u0442\u044c", callback_data="reset_confirm")],
        [InlineKeyboardButton("\U0001F4CA \u041e\u0442\u043a\u0440\u044b\u0442\u044b\u0435", callback_data="pos:0"),
         InlineKeyboardButton("\U0001F4CB \u0417\u0430\u043a\u0440\u044b\u0442\u044b\u0435", callback_data="hist:0")],
        [InlineKeyboardButton("\U0001F4C8 \u0421\u0442\u0430\u0442\u0438\u0441\u0442\u0438\u043a\u0430", callback_data="stats"),
         InlineKeyboardButton("\U0001F4C5 P&L \u043f\u043e \u0434\u043d\u044f\u043c", callback_data="daily_pnl")],
        [InlineKeyboardButton("\U0001F4B0 \u0411\u0430\u043b\u0430\u043d\u0441", callback_data="set_balance"),
         InlineKeyboardButton("\U0001F4CE \u041c\u0430\u043a\u0441. \u0441\u0442\u0430\u0432\u043a\u0430", callback_data="set_maxbet")],
        [InlineKeyboardButton("\U0001F504 \u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c", callback_data="refresh")],
    ])


def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("\u25C0\uFE0F \u041d\u0430\u0437\u0430\u0434", callback_data="refresh")]
    ])


def _positions_text(page: int) -> str:
    p = load_portfolio()
    total = len(p.active_bets)
    if not total:
        return (
            "\U0001F4CA <b>\u041e\u0422\u041a\u0420\u042b\u0422\u042b\u0415 \u041f\u041e\u0417\u0418\u0426\u0418\u0418</b>\n"
            "{line}\n\n"
            "\u041d\u0435\u0442 \u043e\u0442\u043a\u0440\u044b\u0442\u044b\u0445 \u0441\u0442\u0430\u0432\u043e\u043a."
        ).format(line=LINE)

    start = page * ITEMS_PER_PAGE
    end = min(start + ITEMS_PER_PAGE, total)
    total_pages = math.ceil(total / ITEMS_PER_PAGE)
    bets = p.active_bets[start:end]

    lines = [
        "\U0001F4CA <b>\u041e\u0422\u041a\u0420\u042b\u0422\u042b\u0415 \u041f\u041e\u0417\u0418\u0426\u0418\u0418</b> ({cur}/{tot})\n{line}\n".format(
            cur=page + 1, tot=total_pages, line=LINE
        )
    ]
    for b in bets:
        edge_pct = b["edge"] * 100
        flag = _city_flag(b.get("city", ""))
        bid = b["bet_id"]
        city = b["city"]
        date = b["date"]
        blabel = b["bucket_label"]
        cost = b["cost"]
        shares = b["shares"]
        yprice = b["yes_price"]
        lines.append(
            "\n\U0001F3AB <b>{bid}</b>\n"
            "   {flag} {city} \u2014 {date}\n"
            "   \U0001F3AF {blabel}\n"
            "   \U0001F4B5 ${cost:.2f} | {shares:.0f} \u0430\u043a\u0446. @ ${yp:.3f}\n"
            "   \U0001F4C8 Edge: <b>+{edge:.1f}%</b>\n".format(
                bid=bid, flag=flag, city=city, date=date,
                blabel=blabel, cost=cost, shares=shares, yp=yprice, edge=edge_pct,
            )
        )
    return "".join(lines)


def _positions_kb(page: int) -> InlineKeyboardMarkup:
    p = load_portfolio()
    total = len(p.active_bets)
    total_pages = math.ceil(total / ITEMS_PER_PAGE) if total else 1
    btns = []
    if page > 0:
        btns.append(InlineKeyboardButton("\u25C0\uFE0F", callback_data="pos:{0}".format(page - 1)))
    if page < total_pages - 1:
        btns.append(InlineKeyboardButton("\u25B6\uFE0F", callback_data="pos:{0}".format(page + 1)))
    rows = []
    if btns:
        rows.append(btns)
    rows.append([InlineKeyboardButton("\u25C0\uFE0F \u0413\u043b\u0430\u0432\u043d\u0430\u044f", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)


def _history_text(page: int) -> str:
    p = load_portfolio()
    total = len(p.history)
    if not total:
        return (
            "\U0001F4CB <b>\u0418\u0421\u0422\u041e\u0420\u0418\u042f \u0421\u0414\u0415\u041b\u041e\u041a</b>\n"
            "{line}\n\n"
            "\u0418\u0441\u0442\u043e\u0440\u0438\u044f \u043f\u0443\u0441\u0442\u0430."
        ).format(line=LINE)

    rev = list(reversed(p.history))
    start = page * ITEMS_PER_PAGE
    end = min(start + ITEMS_PER_PAGE, total)
    total_pages = math.ceil(total / ITEMS_PER_PAGE)
    bets = rev[start:end]

    lines = [
        "\U0001F4CB <b>\u0418\u0421\u0422\u041e\u0420\u0418\u042f \u0421\u0414\u0415\u041b\u041e\u041a</b> ({cur}/{tot})\n{line}\n".format(
            cur=page + 1, tot=total_pages, line=LINE
        )
    ]
    for b in bets:
        e = "\u2705" if b.get("outcome") == "WIN" else "\u274C"
        bid = b["bet_id"]
        outcome = b.get("outcome", "?")
        pnl = b.get("pnl", 0)
        city = b["city"]
        date = b["date"]
        blabel = b["bucket_label"]
        resolved = b.get("resolved_at") or "\u2014"
        lines.append(
            "\n{e} <b>{bid}</b> {out} | <b>${pnl:+.2f}</b>\n"
            "   {city} {date} | {blabel}\n"
            "   \u23F1 {res}\n".format(
                e=e, bid=bid, out=outcome, pnl=pnl,
                city=city, date=date, blabel=blabel, res=resolved,
            )
        )
    return "".join(lines)


def _history_kb(page: int) -> InlineKeyboardMarkup:
    p = load_portfolio()
    total = len(p.history)
    total_pages = math.ceil(total / ITEMS_PER_PAGE) if total else 1
    btns = []
    if page > 0:
        btns.append(InlineKeyboardButton("\u25C0\uFE0F", callback_data="hist:{0}".format(page - 1)))
    if page < total_pages - 1:
        btns.append(InlineKeyboardButton("\u25B6\uFE0F", callback_data="hist:{0}".format(page + 1)))
    rows = []
    if btns:
        rows.append(btns)
    rows.append([InlineKeyboardButton("\u25C0\uFE0F \u0413\u043b\u0430\u0432\u043d\u0430\u044f", callback_data="refresh")])
    return InlineKeyboardMarkup(rows)


def _stats_text() -> str:
    p = load_portfolio()
    roi = (p.balance - p.starting_balance) / p.starting_balance * 100 if p.starting_balance else 0
    w24, l24 = _wr(p.history, 24)
    w7, l7 = _wr(p.history, 168)
    ac = sum(b["cost"] for b in p.active_bets)
    bp = max((b.get("pnl", 0) for b in p.history), default=0)
    wp = min((b.get("pnl", 0) for b in p.history), default=0)
    avg = (p.total_pnl / len(p.history)) if p.history else 0

    return (
        "\U0001F4C8 <b>\u0421\u0422\u0410\u0422\u0418\u0421\u0422\u0418\u041a\u0410</b>\n{line}\n\n"
        "\U0001F4B0 \u0411\u0430\u043b\u0430\u043d\u0441: <b>${bal:.2f}</b>\n"
        "\U0001F4CA P&L: <b>${pnl:+.2f}</b> ({roi:+.1f}%)\n"
        "\U0001F4B5 \u0412 \u0441\u0442\u0430\u0432\u043a\u0430\u0445: ${ac:.2f}\n\n"
        "{line}\n\n"
        "\U0001F3AF <b>\u0412\u0418\u041d\u0420\u0415\u0419\u0422</b>\n"
        "   24\u0447: {wr24}\n"
        "   7\u0434: {wr7}\n"
        "   \u0412\u0441\u0451: {wrall}\n\n"
        "{line}\n\n"
        "\U0001F4CA <b>\u0421\u0414\u0415\u041b\u041a\u0418</b>\n"
        "   \u0412\u0441\u0435\u0433\u043e: {total}\n"
        "   \u041e\u0442\u043a\u0440\u044b\u0442\u043e: {active}\n"
        "   \u0417\u0430\u043a\u0440\u044b\u0442\u043e: {closed}\n"
        "   \u041e\u0431\u043e\u0440\u043e\u0442: ${wag:.2f}\n\n"
        "\U0001F4B2 \u0421\u0440\u0435\u0434\u043d. P&L/\u0441\u0434\u0435\u043b\u043a\u0430: <b>${avg:+.2f}</b>\n"
        "\U0001F3C6 \u041b\u0443\u0447\u0448\u0430\u044f: <b>${bp:+.2f}</b>\n"
        "\U0001F480 \u0425\u0443\u0434\u0448\u0430\u044f: <b>${wp:+.2f}</b>"
    ).format(
        line=LINE, bal=p.balance, pnl=p.total_pnl, roi=roi, ac=ac,
        wr24=_fmt_wr(w24, l24), wr7=_fmt_wr(w7, l7),
        wrall=_fmt_wr(p.wins, p.losses),
        total=p.total_bets, active=len(p.active_bets), closed=len(p.history),
        wag=p.total_wagered, avg=avg, bp=bp, wp=wp,
    )


def _daily_pnl_text() -> str:
    p = load_portfolio()
    daily = _daily_pnl(p.history)
    if not daily:
        return (
            "\U0001F4C5 <b>P&L \u041f\u041e \u0414\u041d\u042f\u041c</b>\n"
            "{line}\n\n"
            "\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445."
        ).format(line=LINE)

    sorted_days = sorted(daily.keys(), reverse=True)[:14]
    lines = [
        "\U0001F4C5 <b>P&L \u041f\u041e \u0414\u041d\u042f\u041c</b>\n{line}\n".format(line=LINE)
    ]
    cumulative = 0.0
    for day in reversed(sorted_days):
        val = daily[day]
        cumulative += val
        icon = "\U0001F7E2" if val >= 0 else "\U0001F534"
        lines.append(
            "\n{icon} {day}: <b>${val:+.2f}</b> (\u0438\u0442\u043e\u0433: ${cum:+.2f})".format(
                icon=icon, day=day, val=round(val, 2), cum=round(cumulative, 2),
            )
        )
    total_pnl = sum(daily.values())
    lines.append(
        "\n\n{line}\n\U0001F4CA \u0418\u0422\u041e\u0413\u041e: <b>${tot:+.2f}</b>".format(
            line=LINE, tot=round(total_pnl, 2),
        )
    )
    return "".join(lines)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if AUTHORIZED_ID and update.effective_chat.id != AUTHORIZED_ID:
        return ConversationHandler.END
    await update.message.reply_text(
        _main_text(), parse_mode=ParseMode.HTML, reply_markup=_main_kb()
    )
    return ConversationHandler.END


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    if AUTHORIZED_ID and q.from_user.id != AUTHORIZED_ID:
        await q.answer()
        return ConversationHandler.END

    await q.answer()
    d = q.data

    if d == "refresh":
        text, kb = _main_text(), _main_kb()
    elif d.startswith("pos:"):
        page = int(d.split(":")[1])
        text, kb = _positions_text(page), _positions_kb(page)
    elif d.startswith("hist:"):
        page = int(d.split(":")[1])
        text, kb = _history_text(page), _history_kb(page)
    elif d == "stats":
        text, kb = _stats_text(), _back_kb()
    elif d == "daily_pnl":
        text, kb = _daily_pnl_text(), _back_kb()
    elif d == "start_session":
        s = _load_settings()
        s["session_active"] = True
        _save_settings(s)
        text, kb = _main_text(), _main_kb()
    elif d == "stop_session":
        s = _load_settings()
        s["session_active"] = False
        _save_settings(s)
        text, kb = _main_text(), _main_kb()
    elif d == "reset_confirm":
        text = (
            "\u26A0\uFE0F <b>\u0421\u0411\u0420\u041e\u0421 \u0421\u0415\u0421\u0421\u0418\u0418</b>\n\n"
            "\u0412\u0441\u0435 \u0441\u0442\u0430\u0432\u043a\u0438 \u0438 \u0438\u0441\u0442\u043e\u0440\u0438\u044f \u0431\u0443\u0434\u0443\u0442 \u0443\u0434\u0430\u043b\u0435\u043d\u044b.\n"
            "\u0411\u0430\u043b\u0430\u043d\u0441 \u0432\u0435\u0440\u043d\u0451\u0442\u0441\u044f \u043a \u043d\u0430\u0447\u0430\u043b\u044c\u043d\u043e\u043c\u0443.\n\n"
            "\u0422\u044b \u0443\u0432\u0435\u0440\u0435\u043d?"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("\u2705 \u0414\u0430, \u0441\u0431\u0440\u043e\u0441\u0438\u0442\u044c", callback_data="reset_yes"),
             InlineKeyboardButton("\u274C \u041e\u0442\u043c\u0435\u043d\u0430", callback_data="refresh")],
        ])
    elif d == "reset_yes":
        p = load_portfolio()
        new_p = Portfolio(
            balance=p.starting_balance,
            starting_balance=p.starting_balance,
            total_bets=0, wins=0, losses=0,
            total_wagered=0.0, total_pnl=0.0,
            active_bets=[], history=[], last_scan="",
        )
        save_portfolio(new_p)
        s = _load_settings()
        s["session_active"] = False
        _save_settings(s)
        text, kb = _main_text(), _main_kb()
    elif d == "set_balance":
        text = (
            "\U0001F4B0 <b>\u0418\u0417\u041c\u0415\u041d\u0418\u0422\u042c \u0411\u0410\u041b\u0410\u041d\u0421</b>\n\n"
            "\u0412\u0432\u0435\u0434\u0438 \u043d\u043e\u0432\u044b\u0439 \u0431\u0430\u043b\u0430\u043d\u0441 (\u0447\u0438\u0441\u043b\u043e):"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        return SET_BALANCE
    elif d == "set_maxbet":
        text = (
            "\U0001F4CE <b>\u041c\u0410\u041a\u0421. \u0421\u0422\u0410\u0412\u041a\u0410</b>\n\n"
            "\u0412\u0432\u0435\u0434\u0438 \u043c\u0430\u043a\u0441\u0438\u043c\u0430\u043b\u044c\u043d\u044b\u0439 % \u0441\u0442\u0430\u0432\u043a\u0438\n"
            "(\u043d\u0430\u043f\u0440\u0438\u043c\u0435\u0440 5 = 5% \u043e\u0442 \u0431\u0430\u043b\u0430\u043d\u0441\u0430):"
        )
        await q.edit_message_text(text, parse_mode=ParseMode.HTML)
        return SET_MAX_BET
    else:
        return ConversationHandler.END

    try:
        await q.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    except Exception:
        pass
    return ConversationHandler.END


async def handle_set_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if AUTHORIZED_ID and update.effective_chat.id != AUTHORIZED_ID:
        return ConversationHandler.END
    txt = update.message.text.strip().replace(",", ".").replace("$", "")
    try:
        new_bal = float(txt)
        if new_bal < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "\u274C \u041d\u0435\u0432\u0435\u0440\u043d\u043e\u0435 \u0447\u0438\u0441\u043b\u043e. \u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439 \u0435\u0449\u0451:",
        )
        return SET_BALANCE

    p = load_portfolio()
    p.balance = new_bal
    p.starting_balance = new_bal
    save_portfolio(p)

    await update.message.reply_text(
        _main_text(), parse_mode=ParseMode.HTML, reply_markup=_main_kb()
    )
    return ConversationHandler.END


async def handle_set_maxbet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if AUTHORIZED_ID and update.effective_chat.id != AUTHORIZED_ID:
        return ConversationHandler.END
    txt = update.message.text.strip().replace("%", "").replace(",", ".")
    try:
        pct = float(txt)
        if pct <= 0 or pct > 100:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "\u274C \u0412\u0432\u0435\u0434\u0438 \u0447\u0438\u0441\u043b\u043e \u043e\u0442 1 \u0434\u043e 100:",
        )
        return SET_MAX_BET

    s = _load_settings()
    s["max_bet_pct"] = pct / 100.0
    _save_settings(s)

    await update.message.reply_text(
        _main_text(), parse_mode=ParseMode.HTML, reply_markup=_main_kb()
    )
    return ConversationHandler.END


async def scan_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    s = _load_settings()
    if not s.get("session_active"):
        return

    from weather_bot import run_scan, run_resolve_cycle

    try:
        await asyncio.to_thread(run_resolve_cycle)
        await asyncio.to_thread(run_scan)
    except Exception as exc:
        logger.error("Scan error: %s", exc, exc_info=True)
        try:
            await context.bot.send_message(
                chat_id=CHAT_ID,
                text="\u26A0\uFE0F <b>\u041e\u0428\u0418\u0411\u041a\u0410 \u0421\u041a\u0410\u041d\u0410</b>\n\n{err}".format(err=exc),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def startup_notify(context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "\U0001F680 <b>\u0411\u041e\u0422 \u0417\u0410\u041f\u0423\u0429\u0415\u041d</b> \U0001F680\n\n"
                + _main_text()
                + "\n\n\U0001F4E1 \u0413\u043e\u0442\u043e\u0432 \u043a \u0440\u0430\u0431\u043e\u0442\u0435. \u041d\u0430\u0436\u043c\u0438 /start"
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

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
            CallbackQueryHandler(on_button),
        ],
        states={
            SET_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_balance)],
            SET_MAX_BET: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_maxbet)],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )

    app.add_handler(conv_handler)

    if app.job_queue:
        app.job_queue.run_once(startup_notify, when=2)
        app.job_queue.run_repeating(scan_job, interval=SCAN_INTERVAL, first=10)

    logger.info("Bot starting... Scan interval: %ds", SCAN_INTERVAL)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
