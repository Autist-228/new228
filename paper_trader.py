import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

STARTING_BALANCE = 500.0
BET_FRACTION = 0.05
MAX_BETS_PER_SCAN = 20


def _load_max_bet_pct() -> float:
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
            return data.get("max_bet_pct", BET_FRACTION)
        except Exception:
            pass
    return BET_FRACTION


def _kelly_fraction(edge: float, yes_price: float, max_pct: float) -> float:
    if yes_price <= 0 or yes_price >= 1 or edge <= 0:
        return max_pct
    b = (1.0 / yes_price) - 1.0
    p = yes_price + edge
    if p > 1:
        p = 0.99
    q = 1.0 - p
    kelly = (b * p - q) / b
    if kelly <= 0:
        return 0.0
    half_kelly = kelly * 0.5
    return min(half_kelly, max_pct)


@dataclass
class PaperBet:
    bet_id: str
    timestamp: str
    event_type: str
    city: str
    date: str
    bucket_label: str
    market_id: str
    market_slug: str
    event_title: str
    side: str
    yes_price: float
    shares: float
    cost: float
    forecast_probability: float
    edge: float
    expected_value: float
    forecast_value: float
    status: str
    resolved_at: str
    outcome: str
    pnl: float


@dataclass
class Portfolio:
    balance: float
    starting_balance: float
    total_bets: int
    wins: int
    losses: int
    total_wagered: float
    total_pnl: float
    active_bets: list[dict]
    history: list[dict]
    last_scan: str


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def load_portfolio() -> Portfolio:
    _ensure_data_dir()
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            data = json.load(f)
        return Portfolio(
            balance=data.get("balance", STARTING_BALANCE),
            starting_balance=data.get("starting_balance", STARTING_BALANCE),
            total_bets=data.get("total_bets", 0),
            wins=data.get("wins", 0),
            losses=data.get("losses", 0),
            total_wagered=data.get("total_wagered", 0.0),
            total_pnl=data.get("total_pnl", 0.0),
            active_bets=data.get("active_bets", []),
            history=data.get("history", []),
            last_scan=data.get("last_scan", ""),
        )
    return Portfolio(
        balance=STARTING_BALANCE,
        starting_balance=STARTING_BALANCE,
        total_bets=0,
        wins=0,
        losses=0,
        total_wagered=0.0,
        total_pnl=0.0,
        active_bets=[],
        history=[],
        last_scan="",
    )


def save_portfolio(portfolio: Portfolio) -> None:
    _ensure_data_dir()
    data = {
        "balance": portfolio.balance,
        "starting_balance": portfolio.starting_balance,
        "total_bets": portfolio.total_bets,
        "wins": portfolio.wins,
        "losses": portfolio.losses,
        "total_wagered": portfolio.total_wagered,
        "total_pnl": portfolio.total_pnl,
        "active_bets": portfolio.active_bets,
        "history": portfolio.history,
        "last_scan": portfolio.last_scan,
    }
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _already_bet_on(portfolio: Portfolio, market_id: str) -> bool:
    for bet in portfolio.active_bets:
        if bet["market_id"] == market_id:
            return True
    return False


def place_paper_bet(portfolio: Portfolio, opp: dict) -> Optional[PaperBet]:
    market_id = opp["market_id"]
    if _already_bet_on(portfolio, market_id):
        logger.info("Already have active bet on market %s, skipping", market_id)
        return None

    max_pct = _load_max_bet_pct()
    edge = opp.get("edge", 0)
    yes_price_val = opp.get("market_yes_price", 0)
    frac = _kelly_fraction(edge, yes_price_val, max_pct)
    if frac <= 0:
        logger.info("Kelly says skip (negative EV), market %s", market_id)
        return None
    bet_amount = round(portfolio.balance * frac, 2)
    if bet_amount < 1.0:
        logger.warning("Balance too low for betting: $%.2f", portfolio.balance)
        return None

    yes_price = opp["market_yes_price"]
    if yes_price <= 0:
        return None

    shares = round(bet_amount / yes_price, 4)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bet_id = f"BET-{portfolio.total_bets + 1:04d}"

    bet = PaperBet(
        bet_id=bet_id,
        timestamp=now_str,
        event_type=opp["event_type"],
        city=opp["city"],
        date=opp["date"],
        bucket_label=opp["bucket_label"],
        market_id=market_id,
        market_slug=opp["market_slug"],
        event_title=opp["event_title"],
        side="YES",
        yes_price=yes_price,
        shares=shares,
        cost=bet_amount,
        forecast_probability=opp["forecast_probability"],
        edge=opp["edge"],
        expected_value=opp["expected_value"],
        forecast_value=opp["forecast_value"],
        status="active",
        resolved_at="",
        outcome="",
        pnl=0.0,
    )

    portfolio.balance -= bet_amount
    portfolio.total_bets += 1
    portfolio.total_wagered += bet_amount
    portfolio.active_bets.append(asdict(bet))

    logger.info(
        "PAPER BET PLACED: %s | %s %s | %s | %.0f shares @ $%.3f = $%.2f",
        bet_id, bet.city, bet.date, bet.bucket_label, shares, yes_price, bet_amount,
    )
    return bet


def resolve_bet(portfolio: Portfolio, bet_dict: dict, won: bool) -> float:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bet_dict["resolved_at"] = now_str
    bet_dict["status"] = "resolved"

    if won:
        payout = bet_dict["shares"] * 1.0
        pnl = payout - bet_dict["cost"]
        bet_dict["outcome"] = "WIN"
        bet_dict["pnl"] = round(pnl, 2)
        portfolio.balance += payout
        portfolio.wins += 1
    else:
        pnl = -bet_dict["cost"]
        bet_dict["outcome"] = "LOSS"
        bet_dict["pnl"] = round(pnl, 2)
        portfolio.losses += 1

    portfolio.total_pnl += pnl
    portfolio.active_bets = [
        b for b in portfolio.active_bets if b["bet_id"] != bet_dict["bet_id"]
    ]
    portfolio.history.append(bet_dict)

    logger.info(
        "BET RESOLVED: %s | %s | P&L: $%.2f",
        bet_dict["bet_id"], bet_dict["outcome"], pnl,
    )
    return pnl


def get_portfolio_summary(portfolio: Portfolio) -> str:
    win_rate = (portfolio.wins / (portfolio.wins + portfolio.losses) * 100) if (portfolio.wins + portfolio.losses) > 0 else 0
    roi = ((portfolio.balance - portfolio.starting_balance) / portfolio.starting_balance * 100)
    active_cost = sum(b["cost"] for b in portfolio.active_bets)

    lines = [
        f"Balance: ${portfolio.balance:.2f}",
        f"Starting: ${portfolio.starting_balance:.2f}",
        f"P&L: ${portfolio.total_pnl:+.2f} ({roi:+.1f}%)",
        f"Active bets: {len(portfolio.active_bets)} (${active_cost:.2f} at risk)",
        f"Total bets: {portfolio.total_bets}",
        f"W/L: {portfolio.wins}/{portfolio.losses} ({win_rate:.0f}% win rate)",
        f"Total wagered: ${portfolio.total_wagered:.2f}",
    ]
    return "\n".join(lines)
