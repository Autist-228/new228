import json
import logging
import os
import time
from typing import Optional

import requests
from web3 import Web3

logger = logging.getLogger(__name__)

CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
CHAIN_ID = 137

RPCS = [
    "https://polygon-rpc.com",
    "https://rpc-mainnet.matic.quiknode.pro",
    "https://polygon.llamarpc.com",
    "https://1rpc.io/matic",
]

CTF_ABI = json.loads(
    '[{"inputs":[{"name":"account","type":"address"},{"name":"id","type":"uint256"}],'
    '"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],'
    '"stateMutability":"view","type":"function"},'
    '{"inputs":[{"name":"owner","type":"address"},{"name":"operator","type":"address"}],'
    '"name":"isApprovedForAll","outputs":[{"name":"","type":"bool"}],'
    '"stateMutability":"view","type":"function"},'
    '{"inputs":[{"name":"operator","type":"address"},{"name":"approved","type":"bool"}],'
    '"name":"setApprovalForAll","outputs":[],'
    '"stateMutability":"nonpayable","type":"function"}]'
)

NEG_RISK_ABI = json.loads(
    '[{"inputs":[{"name":"conditionId","type":"bytes32"},{"name":"amounts","type":"uint256[]"}],'
    '"name":"redeemPositions","outputs":[],'
    '"stateMutability":"nonpayable","type":"function"}]'
)

ERC20_ABI = json.loads(
    '[{"inputs":[{"name":"account","type":"address"}],'
    '"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],'
    '"stateMutability":"view","type":"function"}]'
)


def _get_web3() -> Optional[Web3]:
    for rpc in RPCS:
        try:
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
            if w3.is_connected():
                return w3
        except Exception:
            continue
    return None


def _get_condition_id(market_id: str) -> Optional[str]:
    try:
        resp = requests.get(
            "{0}/markets/{1}".format(GAMMA_API_URL, market_id), timeout=15
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("conditionId", None)
    except Exception as exc:
        logger.error("Failed to get conditionId for market %s: %s", market_id, exc)
        return None


def _ensure_approval(w3: Web3, wallet: str, private_key: str) -> bool:
    ctf = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI
    )
    approved = ctf.functions.isApprovedForAll(
        Web3.to_checksum_address(wallet),
        Web3.to_checksum_address(NEG_RISK_ADAPTER),
    ).call()

    if approved:
        return True

    logger.info("Setting CTF approval for NegRiskAdapter...")
    try:
        nonce = w3.eth.get_transaction_count(Web3.to_checksum_address(wallet))
        tx = ctf.functions.setApprovalForAll(
            Web3.to_checksum_address(NEG_RISK_ADAPTER), True
        ).build_transaction(
            {
                "chainId": CHAIN_ID,
                "from": Web3.to_checksum_address(wallet),
                "nonce": nonce,
                "gasPrice": w3.eth.gas_price,
                "gas": 100000,
            }
        )
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 1:
            logger.info("CTF approval set: %s", tx_hash.hex())
            return True
        logger.error("CTF approval TX failed: %s", tx_hash.hex())
        return False
    except Exception as exc:
        logger.error("Failed to set CTF approval: %s", exc)
        return False


def redeem_winning_tokens(
    bet: dict, private_key: str, wallet: str
) -> Optional[float]:
    token_id = bet.get("token_id", "")
    market_id = bet.get("market_id", "")
    if not token_id or not market_id:
        logger.warning("Missing token_id or market_id for bet %s", bet.get("bet_id"))
        return None

    w3 = _get_web3()
    if not w3:
        logger.error("No RPC available for redemption")
        return None

    wallet_cs = Web3.to_checksum_address(wallet)

    ctf = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS), abi=CTF_ABI
    )
    balance = ctf.functions.balanceOf(wallet_cs, int(token_id)).call()
    if balance == 0:
        logger.info("No tokens to redeem for bet %s", bet.get("bet_id"))
        return 0.0

    condition_id = _get_condition_id(market_id)
    if not condition_id:
        logger.error("Cannot get conditionId for market %s", market_id)
        return None

    if not _ensure_approval(w3, wallet, private_key):
        return None

    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_ABI
    )
    usdc_before = usdc.functions.balanceOf(wallet_cs).call()

    neg_risk = w3.eth.contract(
        address=Web3.to_checksum_address(NEG_RISK_ADAPTER), abi=NEG_RISK_ABI
    )
    cid_bytes = bytes.fromhex(
        condition_id[2:] if condition_id.startswith("0x") else condition_id
    )

    try:
        nonce = w3.eth.get_transaction_count(wallet_cs)
        tx = neg_risk.functions.redeemPositions(
            cid_bytes, [balance, 0]
        ).build_transaction(
            {
                "chainId": CHAIN_ID,
                "from": wallet_cs,
                "nonce": nonce,
                "gasPrice": w3.eth.gas_price,
                "gas": 500000,
            }
        )
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        logger.info("Redemption TX sent: %s", tx_hash.hex())

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status != 1:
            logger.error("Redemption TX failed: %s", tx_hash.hex())
            return None

        time.sleep(3)
        usdc_after = usdc.functions.balanceOf(wallet_cs).call()
        gained = (usdc_after - usdc_before) / 1e6

        logger.info(
            "REDEEMED %s | %s | +$%.4f USDC | tx=%s",
            bet.get("bet_id"),
            bet.get("city"),
            gained,
            tx_hash.hex(),
        )
        return gained

    except Exception as exc:
        logger.error("Redemption failed for bet %s: %s", bet.get("bet_id"), exc)
        return None
