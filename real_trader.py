#!/usr/bin/env python3
"""Real money trader for Polymarket using CLOB API."""

import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY
from web3 import Web3

logger = logging.getLogger(__name__)

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
POLYGON_RPC = os.environ.get("POLYGON_RPC_URL", "https://polygon-bor-rpc.publicnode.com")

USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_CTF_EXCHANGE = "0xC5d563A36AE78145C45a50134d48A1215220f80a"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

QUICKSWAP_ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
WPOL_ADDRESS = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"

GAS_REFILL_THRESHOLD_USD = 1.0
GAS_REFILL_TARGET_USD = 3.0

MAX_UINT256 = 2**256 - 1

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "real_portfolio.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

ERC20_ABI = json.loads(
    '[{"constant":true,"inputs":[{"name":"_owner","type":"address"}],'
    '"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},'
    '{"constant":false,"inputs":[{"name":"_spender","type":"address"},'
    '{"name":"_value","type":"uint256"}],"name":"approve",'
    '"outputs":[{"name":"","type":"bool"}],"type":"function"},'
    '{"constant":true,"inputs":[{"name":"_owner","type":"address"},'
    '{"name":"_spender","type":"address"}],"name":"allowance",'
    '"outputs":[{"name":"","type":"uint256"}],"type":"function"}]'
)

ERC1155_ABI = json.loads(
    '[{"inputs":[{"name":"operator","type":"address"},'
    '{"name":"approved","type":"bool"}],"name":"setApprovalForAll",'
    '"outputs":[],"type":"function"},'
    '{"inputs":[{"name":"account","type":"address"},'
    '{"name":"operator","type":"address"}],"name":"isApprovedForAll",'
    '"outputs":[{"name":"","type":"bool"}],"type":"function"}]'
)

ROUTER_ABI = json.loads(
    '[{"inputs":[{"name":"amountIn","type":"uint256"},'
    '{"name":"amountOutMin","type":"uint256"},'
    '{"name":"path","type":"address[]"},'
    '{"name":"to","type":"address"},'
    '{"name":"deadline","type":"uint256"}],'
    '"name":"swapExactTokensForETH",'
    '"outputs":[{"name":"amounts","type":"uint256[]"}],'
    '"stateMutability":"nonpayable","type":"function"},'
    '{"inputs":[{"name":"amountIn","type":"uint256"},'
    '{"name":"path","type":"address[]"}],'
    '"name":"getAmountsOut",'
    '"outputs":[{"name":"amounts","type":"uint256[]"}],'
    '"stateMutability":"view","type":"function"}]'
)

BET_FRACTION = 0.05
MAX_BETS_PER_SCAN = 20
MAX_BETS_PER_MARKET = 1
REBET_COOLDOWN_MINUTES = 15
MIN_BET_USDC = 1.0
MIN_POL_WARNING = 0.05


@dataclass
class RealPortfolio:
    total_bets: int
    wins: int
    losses: int
    total_wagered: float
    total_pnl: float
    active_bets: list
    history: list
    last_scan: str


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_portfolio() -> RealPortfolio:
    _ensure_data_dir()
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, "r") as f:
            data = json.load(f)
        return RealPortfolio(
            total_bets=data.get("total_bets", 0),
            wins=data.get("wins", 0),
            losses=data.get("losses", 0),
            total_wagered=data.get("total_wagered", 0.0),
            total_pnl=data.get("total_pnl", 0.0),
            active_bets=data.get("active_bets", []),
            history=data.get("history", []),
            last_scan=data.get("last_scan", ""),
        )
    return RealPortfolio(
        total_bets=0, wins=0, losses=0,
        total_wagered=0.0, total_pnl=0.0,
        active_bets=[], history=[], last_scan="",
    )


def save_portfolio(portfolio: RealPortfolio):
    _ensure_data_dir()
    data = {
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


def load_settings() -> dict:
    defaults = {
        "max_bet_pct": 0.05,
        "max_bet_usd": 15.0,
        "session_active": False,
        "session_started_at": "",
        "allowances_set": False,
        "main_message_id": None,
        "main_chat_id": None,
    }
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


def save_settings(s: dict):
    _ensure_data_dir()
    with open(SETTINGS_FILE, "w") as f:
        json.dump(s, f, indent=2)


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


def _already_bet_on(portfolio: RealPortfolio, market_id: str) -> bool:
    for bet in portfolio.active_bets:
        if bet["market_id"] == market_id:
            return True
    history_bets = [b for b in portfolio.history if b["market_id"] == market_id]
    if len(history_bets) >= MAX_BETS_PER_MARKET:
        return True
    if history_bets:
        last = history_bets[-1]
        resolved_at = last.get("resolved_at", "")
        if resolved_at:
            try:
                rt = datetime.strptime(
                    resolved_at.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - rt).total_seconds() / 60
                if elapsed < REBET_COOLDOWN_MINUTES:
                    return True
            except (ValueError, TypeError):
                pass
    return False


class Trader:
    def __init__(self):
        self.private_key = os.environ.get("PRIVATE_KEY", "")
        self.wallet_address = os.environ.get("WALLET_ADDRESS", "")
        self.web3 = Web3(Web3.HTTPProvider(POLYGON_RPC, request_kwargs={"timeout": 10}))
        self.clob: Optional[ClobClient] = None
        self._ready = False

    def initialize(self) -> bool:
        if not self.private_key or not self.wallet_address:
            logger.error("PRIVATE_KEY or WALLET_ADDRESS not set")
            return False
        try:
            pk = self.private_key
            if not pk.startswith("0x"):
                pk = "0x" + pk
            self.clob = ClobClient(
                CLOB_HOST,
                key=pk,
                chain_id=CHAIN_ID,
                signature_type=0,
                funder=self.wallet_address,
            )
            creds = self.clob.create_or_derive_api_creds()
            self.clob.set_api_creds(creds)
            self._ready = True
            logger.info("CLOB client ready: %s", self.wallet_address)
            return True
        except Exception as exc:
            logger.error("CLOB init failed: %s", exc, exc_info=True)
            return False

    @property
    def is_ready(self) -> bool:
        return self._ready

    def get_usdc_balance(self) -> float:
        try:
            contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(USDC_ADDRESS),
                abi=ERC20_ABI,
            )
            raw = contract.functions.balanceOf(
                Web3.to_checksum_address(self.wallet_address)
            ).call()
            return raw / 1e6
        except Exception as exc:
            logger.error("USDC balance fail: %s", exc)
            return 0.0

    def get_pol_balance(self) -> float:
        try:
            raw = self.web3.eth.get_balance(
                Web3.to_checksum_address(self.wallet_address)
            )
            return float(self.web3.from_wei(raw, "ether"))
        except Exception as exc:
            logger.error("POL balance fail: %s", exc)
            return 0.0

    def check_allowances(self) -> dict:
        results = {}
        try:
            wallet = Web3.to_checksum_address(self.wallet_address)
            usdc = self.web3.eth.contract(
                address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI,
            )
            ctf = self.web3.eth.contract(
                address=Web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_ABI,
            )
            results["usdc_ctf_exchange"] = usdc.functions.allowance(
                wallet, Web3.to_checksum_address(CTF_EXCHANGE)
            ).call() > 0
            results["usdc_neg_risk_exchange"] = usdc.functions.allowance(
                wallet, Web3.to_checksum_address(NEG_RISK_CTF_EXCHANGE)
            ).call() > 0
            results["usdc_neg_risk_adapter"] = usdc.functions.allowance(
                wallet, Web3.to_checksum_address(NEG_RISK_ADAPTER)
            ).call() > 0
            results["ctf_ctf_exchange"] = ctf.functions.isApprovedForAll(
                wallet, Web3.to_checksum_address(CTF_EXCHANGE)
            ).call()
            results["ctf_neg_risk_exchange"] = ctf.functions.isApprovedForAll(
                wallet, Web3.to_checksum_address(NEG_RISK_CTF_EXCHANGE)
            ).call()
        except Exception as exc:
            logger.error("Allowance check fail: %s", exc)
        return results

    def set_allowances(self) -> bool:
        try:
            wallet = Web3.to_checksum_address(self.wallet_address)
            pk = self.private_key
            if not pk.startswith("0x"):
                pk = "0x" + pk

            usdc = self.web3.eth.contract(
                address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI,
            )
            ctf = self.web3.eth.contract(
                address=Web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_ABI,
            )

            nonce = self.web3.eth.get_transaction_count(wallet)
            gas_price = self.web3.eth.gas_price

            txns = [
                ("USDC->CTF_EX", usdc.functions.approve(
                    Web3.to_checksum_address(CTF_EXCHANGE), MAX_UINT256
                )),
                ("USDC->NEG_EX", usdc.functions.approve(
                    Web3.to_checksum_address(NEG_RISK_CTF_EXCHANGE), MAX_UINT256
                )),
                ("USDC->NEG_AD", usdc.functions.approve(
                    Web3.to_checksum_address(NEG_RISK_ADAPTER), MAX_UINT256
                )),
                ("CTF->CTF_EX", ctf.functions.setApprovalForAll(
                    Web3.to_checksum_address(CTF_EXCHANGE), True
                )),
                ("CTF->NEG_EX", ctf.functions.setApprovalForAll(
                    Web3.to_checksum_address(NEG_RISK_CTF_EXCHANGE), True
                )),
            ]

            for label, fn in txns:
                tx = fn.build_transaction({
                    "chainId": CHAIN_ID,
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                })
                signed = self.web3.eth.account.sign_transaction(tx, pk)
                tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
                self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                logger.info("Allowance OK: %s tx=%s", label, tx_hash.hex())
                nonce += 1
                time.sleep(2)

            return True
        except Exception as exc:
            logger.error("Set allowances failed: %s", exc, exc_info=True)
            return False

    def place_market_buy(self, token_id: str, price: float, amount_usd: float) -> Optional[dict]:
        if not self._ready:
            logger.error("Trader not initialized")
            return None
        if amount_usd < MIN_BET_USDC:
            logger.warning("Bet too small: $%.2f", amount_usd)
            return None

        size = round(amount_usd / price, 2)
        buy_price = round(price, 2)
        if buy_price < 0.01:
            buy_price = 0.01
        if buy_price > 0.99:
            buy_price = 0.99

        try:
            order_args = OrderArgs(
                price=buy_price,
                size=size,
                side=BUY,
                token_id=token_id,
            )
            signed_order = self.clob.create_order(order_args)
            resp = self.clob.post_order(signed_order, OrderType.GTC)
            logger.info(
                "ORDER PLACED: token=%s price=%.2f size=%.1f resp=%s",
                token_id[:16] + "...", buy_price, size, resp,
            )
            return resp
        except Exception as exc:
            logger.error("Order failed: %s", exc, exc_info=True)
            return None

    def cancel_all(self) -> bool:
        if not self._ready:
            return False
        try:
            self.clob.cancel_all()
            return True
        except Exception as exc:
            logger.error("Cancel all failed: %s", exc)
            return False

    def get_pol_price_usd(self) -> float:
        try:
            router = self.web3.eth.contract(
                address=Web3.to_checksum_address(QUICKSWAP_ROUTER),
                abi=ROUTER_ABI,
            )
            one_pol = self.web3.to_wei(1, "ether")
            amounts = router.functions.getAmountsOut(
                one_pol,
                [
                    Web3.to_checksum_address(WPOL_ADDRESS),
                    Web3.to_checksum_address(USDC_ADDRESS),
                ],
            ).call()
            return amounts[1] / 1e6
        except Exception as exc:
            logger.error("POL price fetch fail: %s", exc)
            return 0.0

    def get_pol_balance_usd(self) -> float:
        pol = self.get_pol_balance()
        price = self.get_pol_price_usd()
        return pol * price if price > 0 else 0.0

    def needs_gas_refill(self) -> bool:
        usd_val = self.get_pol_balance_usd()
        return usd_val < GAS_REFILL_THRESHOLD_USD

    def refill_gas(self) -> bool:
        if not self._ready:
            return False
        try:
            wallet = Web3.to_checksum_address(self.wallet_address)
            pk = self.private_key
            if not pk.startswith("0x"):
                pk = "0x" + pk

            pol_price = self.get_pol_price_usd()
            if pol_price <= 0:
                logger.error("Cannot get POL price for gas refill")
                return False

            current_usd = self.get_pol_balance_usd()
            need_usd = GAS_REFILL_TARGET_USD - current_usd
            if need_usd <= 0.1:
                logger.info("Gas OK: $%.2f, no refill needed", current_usd)
                return True

            usdc_amount = round(need_usd, 2)
            usdc_raw = int(usdc_amount * 1e6)

            usdc_balance_raw = self.web3.eth.contract(
                address=Web3.to_checksum_address(USDC_ADDRESS),
                abi=ERC20_ABI,
            ).functions.balanceOf(wallet).call()

            if usdc_balance_raw < usdc_raw:
                logger.warning(
                    "Not enough USDC for gas refill: have $%.2f, need $%.2f",
                    usdc_balance_raw / 1e6, usdc_amount,
                )
                return False

            router_addr = Web3.to_checksum_address(QUICKSWAP_ROUTER)
            usdc_contract = self.web3.eth.contract(
                address=Web3.to_checksum_address(USDC_ADDRESS),
                abi=ERC20_ABI,
            )
            allowance = usdc_contract.functions.allowance(wallet, router_addr).call()
            nonce = self.web3.eth.get_transaction_count(wallet)
            gas_price = self.web3.eth.gas_price

            if allowance < usdc_raw:
                approve_tx = usdc_contract.functions.approve(
                    router_addr, MAX_UINT256,
                ).build_transaction({
                    "chainId": CHAIN_ID,
                    "from": wallet,
                    "nonce": nonce,
                    "gasPrice": gas_price,
                })
                signed = self.web3.eth.account.sign_transaction(approve_tx, pk)
                tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
                self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
                logger.info("USDC approved for QuickSwap: %s", tx_hash.hex())
                nonce += 1
                time.sleep(3)

            router = self.web3.eth.contract(address=router_addr, abi=ROUTER_ABI)
            deadline = int(time.time()) + 300

            min_out_pol = need_usd / pol_price * 0.95
            min_out_raw = self.web3.to_wei(min_out_pol, "ether")

            swap_tx = router.functions.swapExactTokensForETH(
                usdc_raw,
                int(min_out_raw),
                [
                    Web3.to_checksum_address(USDC_ADDRESS),
                    Web3.to_checksum_address(WPOL_ADDRESS),
                ],
                wallet,
                deadline,
            ).build_transaction({
                "chainId": CHAIN_ID,
                "from": wallet,
                "nonce": nonce,
                "gasPrice": gas_price,
            })
            signed = self.web3.eth.account.sign_transaction(swap_tx, pk)
            tx_hash = self.web3.eth.send_raw_transaction(signed.raw_transaction)
            receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            new_bal = self.get_pol_balance()
            new_usd = self.get_pol_balance_usd()
            logger.info(
                "GAS REFILL OK: swapped $%.2f USDC -> %.4f POL ($%.2f) tx=%s",
                usdc_amount, new_bal, new_usd, tx_hash.hex(),
            )
            return receipt.status == 1
        except Exception as exc:
            logger.error("Gas refill failed: %s", exc, exc_info=True)
            return False

    def check_and_refill_gas(self) -> None:
        if not self._ready:
            return
        try:
            if self.needs_gas_refill():
                usd = self.get_pol_balance_usd()
                logger.info("Gas low ($%.2f), refilling...", usd)
                self.refill_gas()
        except Exception as exc:
            logger.error("Gas check error: %s", exc)


_trader: Optional[Trader] = None


def get_trader() -> Trader:
    global _trader
    if _trader is None:
        _trader = Trader()
    return _trader


def place_real_bet(portfolio: RealPortfolio, opp: dict, trader: Trader) -> Optional[dict]:
    market_id = opp["market_id"]
    token_id = opp.get("yes_token_id", "")

    if not token_id:
        logger.warning("No token_id for market %s, skip", market_id)
        return None

    if _already_bet_on(portfolio, market_id):
        logger.info("Already bet on %s, skip", market_id)
        return None

    usdc_balance = trader.get_usdc_balance()
    if usdc_balance < MIN_BET_USDC:
        logger.warning("USDC too low: $%.2f", usdc_balance)
        return None

    settings = load_settings()
    max_usd = settings.get("max_bet_usd", 1.50)

    edge = opp.get("edge", 0)
    yes_price = opp.get("market_yes_price", 0)

    bet_amount = min(max_usd, usdc_balance * 0.10)
    bet_amount = round(bet_amount, 2)

    if bet_amount < MIN_BET_USDC:
        logger.warning("Bet too small: $%.2f", bet_amount)
        return None

    resp = trader.place_market_buy(token_id, yes_price, bet_amount)
    if resp is None:
        return None

    order_id = ""
    if isinstance(resp, dict):
        order_id = resp.get("orderID", resp.get("order_id", resp.get("id", "")))

    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bet_id = "REAL-{0:04d}".format(portfolio.total_bets + 1)
    shares = round(bet_amount / yes_price, 4) if yes_price > 0 else 0

    bet_dict = {
        "bet_id": bet_id,
        "timestamp": now_str,
        "event_type": opp.get("event_type", ""),
        "city": opp.get("city", ""),
        "date": opp.get("date", ""),
        "bucket_label": opp.get("bucket_label", ""),
        "market_id": market_id,
        "token_id": token_id,
        "market_slug": opp.get("market_slug", ""),
        "event_title": opp.get("event_title", ""),
        "side": "YES",
        "price": yes_price,
        "size": shares,
        "shares": shares,
        "cost": bet_amount,
        "yes_price": yes_price,
        "order_id": order_id,
        "forecast_probability": opp.get("forecast_probability", 0),
        "edge": edge,
        "expected_value": opp.get("expected_value", 0),
        "forecast_value": opp.get("forecast_value", 0),
        "status": "active",
        "resolved_at": "",
        "outcome": "",
        "pnl": 0.0,
    }

    portfolio.total_bets += 1
    portfolio.total_wagered += bet_amount
    portfolio.active_bets.append(bet_dict)

    logger.info(
        "REAL BET: %s | %s %s | %s | %.0f sh @ $%.3f = $%.2f",
        bet_id, bet_dict["city"], bet_dict["date"],
        bet_dict["bucket_label"], shares, yes_price, bet_amount,
    )
    return bet_dict


def resolve_bet(portfolio: RealPortfolio, bet_dict: dict, won: bool) -> float:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    bet_dict["resolved_at"] = now_str
    bet_dict["status"] = "resolved"

    if won:
        payout = bet_dict["shares"] * 1.0
        pnl = payout - bet_dict["cost"]
        bet_dict["outcome"] = "WIN"
        bet_dict["pnl"] = round(pnl, 2)
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
        "RESOLVED: %s | %s | P&L: $%.2f",
        bet_dict["bet_id"], bet_dict["outcome"], pnl,
    )
    return pnl


def get_portfolio_summary(portfolio: RealPortfolio) -> str:
    wr = (portfolio.wins / (portfolio.wins + portfolio.losses) * 100) if (portfolio.wins + portfolio.losses) > 0 else 0
    ac = sum(b["cost"] for b in portfolio.active_bets)
    return "\n".join([
        "Active: {0} (${1:.2f})".format(len(portfolio.active_bets), ac),
        "W/L: {0}/{1} ({2:.0f}%)".format(portfolio.wins, portfolio.losses, wr),
        "P&L: ${0:+.2f} | Wagered: ${1:.2f}".format(portfolio.total_pnl, portfolio.total_wagered),
    ])
