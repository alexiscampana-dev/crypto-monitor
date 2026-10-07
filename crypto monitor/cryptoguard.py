#!/usr/bin/env python3
"""
CRYPTOGUARD - Cryptocurrency Monitoring and Risk Alert Platform (Python / CLI edition)

Watches a portfolio of coins, scores risk in real time, and raises alerts using
the signal system from the project brief:

    LOW RISK / WATCH / HIGH RISK / CRITICAL / PROFIT ALERT / SELL REVIEW

CryptoGuard never asks for a wallet's private keys or seed phrase. Holdings are
entered manually, so the app can only *read* market data - it can't move funds.

Run it:
    pip install requests
    python cryptoguard.py                  # live dashboard, refreshes every 30s
    python cryptoguard.py --once            # single check, then exit
    python cryptoguard.py --interval 60     # custom refresh interval (seconds)
    python cryptoguard.py --config my.json  # load/save portfolio from a file
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("This tool needs the 'requests' package. Install it with: pip install requests")
    sys.exit(1)


# =========================================================================
# MODULE: Design tokens (terminal colors) - keeps the console readable
# =========================================================================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[38;5;114m"
    YELLOW = "\033[38;5;222m"
    ORANGE = "\033[38;5;215m"
    RED = "\033[38;5;203m"
    BLUE = "\033[38;5;110m"
    VIOLET = "\033[38;5;183m"
    AMBER = "\033[38;5;179m"
    GREY = "\033[38;5;245m"


# =========================================================================
# MODULE: Market Data (coin catalog + the signal legend from the brief)
# =========================================================================
COINS: Dict[str, Dict[str, str]] = {
    "bitcoin":     {"symbol": "BTC",  "name": "Bitcoin"},
    "ethereum":    {"symbol": "ETH",  "name": "Ethereum"},
    "solana":      {"symbol": "SOL",  "name": "Solana"},
    "ripple":      {"symbol": "XRP",  "name": "XRP"},
    "cardano":     {"symbol": "ADA",  "name": "Cardano"},
    "dogecoin":    {"symbol": "DOGE", "name": "Dogecoin"},
    "binancecoin": {"symbol": "BNB",  "name": "BNB"},
    "litecoin":    {"symbol": "LTC",  "name": "Litecoin"},
    "polkadot":    {"symbol": "DOT",  "name": "Polkadot"},
    "avalanche-2": {"symbol": "AVAX", "name": "Avalanche"},
}

SIGNALS: Dict[str, Dict[str, str]] = {
    "LOW":      {"emoji": "\U0001F7E2", "label": "LOW RISK",     "color": C.GREEN},
    "WATCH":    {"emoji": "\U0001F7E1", "label": "WATCH",        "color": C.YELLOW},
    "HIGH":     {"emoji": "\U0001F7E0", "label": "HIGH RISK",    "color": C.ORANGE},
    "CRITICAL": {"emoji": "\U0001F534", "label": "CRITICAL",     "color": C.RED},
    "PROFIT":   {"emoji": "\U0001F535", "label": "PROFIT ALERT", "color": C.BLUE},
    "SELL":     {"emoji": "\U0001F7E3", "label": "SELL REVIEW",  "color": C.VIOLET},
}

# CoinGecko's vs_currency codes it can price directly in. Add more here any
# time - CoinGecko supports 50+ fiat and a few metals; this covers the ones
# people ask for most. "decimals" is just display precision (JPY/KRW/IDR/VND
# don't normally use decimal subunits day-to-day).
CURRENCIES: Dict[str, Dict[str, object]] = {
    "usd": {"symbol": "$",    "name": "US Dollar",         "decimals": 2},
    "php": {"symbol": "\u20b1",    "name": "Philippine Peso",   "decimals": 2},
    "eur": {"symbol": "\u20ac",    "name": "Euro",              "decimals": 2},
    "gbp": {"symbol": "\u00a3",    "name": "British Pound",     "decimals": 2},
    "jpy": {"symbol": "\u00a5",    "name": "Japanese Yen",      "decimals": 0},
    "aud": {"symbol": "A$",   "name": "Australian Dollar", "decimals": 2},
    "cad": {"symbol": "C$",   "name": "Canadian Dollar",   "decimals": 2},
    "sgd": {"symbol": "S$",   "name": "Singapore Dollar",  "decimals": 2},
    "hkd": {"symbol": "HK$",  "name": "Hong Kong Dollar",  "decimals": 2},
    "inr": {"symbol": "\u20b9",    "name": "Indian Rupee",      "decimals": 2},
    "cny": {"symbol": "\u00a5",    "name": "Chinese Yuan",      "decimals": 2},
    "krw": {"symbol": "\u20a9",    "name": "South Korean Won",  "decimals": 0},
    "myr": {"symbol": "RM",   "name": "Malaysian Ringgit", "decimals": 2},
    "idr": {"symbol": "Rp",   "name": "Indonesian Rupiah", "decimals": 0},
    "thb": {"symbol": "\u0e3f",    "name": "Thai Baht",         "decimals": 2},
    "vnd": {"symbol": "\u20ab",    "name": "Vietnamese Dong",   "decimals": 0},
    "chf": {"symbol": "CHF ", "name": "Swiss Franc",       "decimals": 2},
}
DEFAULT_CURRENCY = "usd"


def fmt_money(amount: Optional[float], currency: str, show_sign: bool = False) -> str:
    """Format an amount using the given currency's symbol and decimal convention."""
    if amount is None:
        return "\u2014"
    info = CURRENCIES.get(currency, CURRENCIES[DEFAULT_CURRENCY])
    decimals = info["decimals"]
    sign = "+" if (show_sign and amount >= 0) else ""
    return f"{sign}{info['symbol']}{amount:,.{decimals}f}"


# Rough, fixed offline multipliers vs USD. Two uses: (1) scaling the sample
# portfolio below into a plausible starting point when someone picks a
# non-USD currency on first run, and (2) the offline simulated price feed
# when there's no network. Not for real conversion of a live position.
FX_APPROX = {
    "usd": 1, "eur": 0.92, "gbp": 0.79, "jpy": 149, "php": 56,
    "aud": 1.52, "cad": 1.36, "sgd": 1.34, "hkd": 7.8, "inr": 83,
    "cny": 7.2, "krw": 1330, "myr": 4.4, "idr": 15600, "thb": 33,
    "vnd": 24500, "chf": 0.88,
}

DEFAULT_CONFIG = {
    "currency": DEFAULT_CURRENCY,
    "holdings": [
        {"id": "bitcoin",  "amount": 0.12, "avg_price": 61200, "profit_target": 20, "loss_threshold": -10},
        {"id": "ethereum", "amount": 1.4,  "avg_price": 3350,  "profit_target": 20, "loss_threshold": -10},
        {"id": "solana",   "amount": 18,   "avg_price": 168,   "profit_target": 15, "loss_threshold": -12},
    ]
}


def sample_config_for(currency: str) -> dict:
    """The default demo portfolio, with avg_price scaled into the chosen
    currency so first-run numbers look plausible instead of raw USD figures
    mislabeled with a different symbol."""
    fx = FX_APPROX.get(currency, 1)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    cfg["currency"] = currency
    for h in cfg["holdings"]:
        h["avg_price"] = round(h["avg_price"] * fx, 2)
    return cfg


# =========================================================================
# MODULE: Portfolio Management
# =========================================================================
@dataclass
class Holding:
    id: str
    amount: float
    avg_price: float
    profit_target: float = 20.0
    loss_threshold: float = -10.0

    @property
    def symbol(self) -> str:
        return COINS.get(self.id, {}).get("symbol", self.id.upper())

    @property
    def name(self) -> str:
        return COINS.get(self.id, {}).get("name", self.id.title())


@dataclass
class MarketSnapshot:
    price: float
    change_24h: float
    high_24h: Optional[float]
    low_24h: Optional[float]
    volume: Optional[float]
    market_cap: Optional[float]
    sparkline: List[float] = field(default_factory=list)


class Portfolio:
    """MODULE: Portfolio Management - holdings, totals, profit/loss."""

    def __init__(self, holdings: Optional[List[Holding]] = None, currency: str = DEFAULT_CURRENCY):
        self.holdings: List[Holding] = holdings or []
        self.currency: str = currency if currency in CURRENCIES else DEFAULT_CURRENCY

    def add(self, holding: Holding) -> None:
        self.holdings = [h for h in self.holdings if h.id != holding.id]
        self.holdings.append(holding)

    def remove(self, coin_id: str) -> None:
        self.holdings = [h for h in self.holdings if h.id != coin_id]

    def totals(self, market: Dict[str, MarketSnapshot]):
        total_value = total_cost = day_delta = 0.0
        for h in self.holdings:
            m = market.get(h.id)
            if not m:
                continue
            total_value += h.amount * m.price
            total_cost += h.amount * h.avg_price
            day_delta += h.amount * m.price * (m.change_24h / 100)
        total_pl = total_value - total_cost
        total_pl_pct = (total_pl / total_cost * 100) if total_cost else 0.0
        prev_value = total_value - day_delta
        day_delta_pct = (day_delta / prev_value * 100) if prev_value else 0.0
        return {
            "total_value": total_value,
            "total_cost": total_cost,
            "total_pl": total_pl,
            "total_pl_pct": total_pl_pct,
            "day_delta": day_delta,
            "day_delta_pct": day_delta_pct,
        }

    @classmethod
    def load(cls, path: str) -> "Portfolio":
        if not os.path.exists(path):
            data = DEFAULT_CONFIG
        else:
            with open(path, "r") as f:
                data = json.load(f)
        holdings = [Holding(**h) for h in data.get("holdings", [])]
        currency = data.get("currency", DEFAULT_CURRENCY)
        return cls(holdings, currency=currency)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(
                {"currency": self.currency, "holdings": [asdict(h) for h in self.holdings]},
                f, indent=2,
            )


# =========================================================================
# MODULE: Market Data Fetching (CoinGecko, with an offline fallback)
# =========================================================================
class MarketDataFetcher:
    BASE_URL = "https://api.coingecko.com/api/v3/coins/markets"

    def __init__(self):
        self._sim_state: Dict[str, Dict] = {}

    def fetch(self, coin_ids: List[str], currency: str = DEFAULT_CURRENCY) -> Tuple[Dict[str, MarketSnapshot], bool]:
        """Returns (snapshots, used_fallback)."""
        if not coin_ids:
            return {}, False
        currency = currency if currency in CURRENCIES else DEFAULT_CURRENCY
        params = {
            "vs_currency": currency,
            "ids": ",".join(coin_ids),
            "sparkline": "true",
            "price_change_percentage": "24h",
        }
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            snapshots = {}
            for c in data:
                snapshots[c["id"]] = MarketSnapshot(
                    price=c.get("current_price") or 0.0,
                    change_24h=c.get("price_change_percentage_24h") or 0.0,
                    high_24h=c.get("high_24h"),
                    low_24h=c.get("low_24h"),
                    volume=c.get("total_volume"),
                    market_cap=c.get("market_cap"),
                    sparkline=(c.get("sparkline_in_7d") or {}).get("price", [])[-48:],
                )
            return snapshots, False
        except Exception:
            return self._simulate(coin_ids, currency), True

    def _simulate(self, coin_ids: List[str], currency: str = DEFAULT_CURRENCY) -> Dict[str, MarketSnapshot]:
        """Gentle random-walk fallback so the app keeps working without a network."""
        import random
        fx = FX_APPROX.get(currency, 1)
        out = {}
        for cid in coin_ids:
            state = self._sim_state.setdefault(cid, {"price": 100.0 * fx * (1 + random.random()), "series": []})
            drift = (random.random() - 0.5) * 0.02
            state["price"] = max(0.01, state["price"] * (1 + drift))
            state["series"].append(state["price"])
            if len(state["series"]) > 48:
                state["series"].pop(0)
            first = state["series"][0]
            change = (state["price"] - first) / first * 100
            out[cid] = MarketSnapshot(
                price=state["price"],
                change_24h=change,
                high_24h=max(state["series"]),
                low_24h=min(state["series"]),
                volume=None,
                market_cap=None,
                sparkline=list(state["series"]),
            )
        return out


# =========================================================================
# MODULE: Risk Analysis
# =========================================================================
class RiskAnalyzer:
    @staticmethod
    def volatility_pct(series: List[float]) -> float:
        if not series or len(series) < 2:
            return 0.0
        mean = statistics.fmean(series)
        if mean == 0:
            return 0.0
        return statistics.pstdev(series) / mean * 100

    @staticmethod
    def classify(change_24h: float, volatility: float) -> str:
        if change_24h <= -8 or volatility > 6:
            return "CRITICAL"
        if change_24h <= -5 or volatility > 4:
            return "HIGH"
        if change_24h <= -2 or volatility > 2:
            return "WATCH"
        return "LOW"


# =========================================================================
# MODULE: Alert & Notification
# =========================================================================
@dataclass
class Alert:
    coin_id: str
    symbol: str
    signal: str
    message: str
    timestamp: datetime


class AlertEngine:
    """Turns market + portfolio state into human-readable alerts, per the
    brief: explain the condition, never claim certainty about future price."""

    def __init__(self):
        self._recent: Dict[str, float] = {}  # key -> last-fired unix time
        self._cooldown_seconds = 5 * 60

    def generate(self, portfolio: Portfolio, market: Dict[str, MarketSnapshot]) -> List[Alert]:
        alerts: List[Alert] = []
        now = time.time()
        currency = portfolio.currency

        for h in portfolio.holdings:
            m = market.get(h.id)
            if not m or not m.price:
                continue

            volatility = RiskAnalyzer.volatility_pct(m.sparkline)
            market_risk = RiskAnalyzer.classify(m.change_24h, volatility)
            pl_pct = (m.price - h.avg_price) / h.avg_price * 100
            pl_amount = h.amount * (m.price - h.avg_price)

            signal = market_risk
            message = (
                f"{h.symbol} moved {pl_pct:+.2f}% vs your average, and {m.change_24h:+.2f}% "
                f"in the last 24h. Volatility is {'elevated' if volatility > 3 else 'normal'} "
                f"relative to its recent range."
            )

            if pl_pct >= h.profit_target:
                signal = "PROFIT"
                message = (
                    f"{h.symbol} has reached your {h.profit_target:g}% profit target. "
                    f"Estimated gain: {fmt_money(pl_amount, currency)}. Consider reviewing your position."
                )
            elif pl_pct <= h.loss_threshold and market_risk != "CRITICAL":
                signal = "SELL"
                message = (
                    f"{h.symbol} has crossed your {h.loss_threshold:g}% loss threshold. "
                    f"Estimated loss: {fmt_money(pl_amount, currency)}. Review whether this still fits your plan."
                )
            elif market_risk == "CRITICAL":
                message = (
                    f"{h.symbol} dropped {m.change_24h:+.2f}% in 24h. Your position is currently "
                    f"{'up' if pl_amount >= 0 else 'down'} {fmt_money(abs(pl_amount), currency)}."
                )

            if signal == "LOW":
                continue

            key = f"{h.id}:{signal}"
            last_fired = self._recent.get(key, 0)
            if now - last_fired < self._cooldown_seconds:
                continue
            self._recent[key] = now

            alerts.append(Alert(
                coin_id=h.id, symbol=h.symbol, signal=signal,
                message=message, timestamp=datetime.now(),
            ))

        return alerts


class NotificationService:
    """Desktop push notification if a backend is available, otherwise a
    clearly formatted console alert. Swap in smtplib/email or a webhook
    here for the 'Email' / 'Web Push' boxes in the architecture diagram."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._backend = self._detect_backend()

    def _detect_backend(self):
        try:
            from plyer import notification  # optional dependency
            return notification
        except ImportError:
            return None

    def send(self, alert: Alert) -> None:
        sig = SIGNALS[alert.signal]
        title = f"{sig['emoji']} {alert.symbol} - {sig['label']}"

        if self.enabled and self._backend is not None:
            try:
                self._backend.notify(title=title, message=alert.message, timeout=8)
            except Exception:
                pass  # fall through to console output below

        color = sig["color"]
        ts = alert.timestamp.strftime("%H:%M:%S")
        print(f"{color}{C.BOLD}{title}{C.RESET}  {C.GREY}{ts}{C.RESET}")
        print(f"  {alert.message}")


# =========================================================================
# MODULE: Dashboard & Visualization (terminal rendering)
# =========================================================================
def render_bar(risk: str, width: int = 10) -> str:
    filled = {"LOW": 2, "WATCH": 5, "HIGH": 7, "CRITICAL": 10}[risk]
    color = SIGNALS[risk]["color"]
    filled_block = "\u2588" * filled
    empty_block = "\u2591" * (width - filled)
    return f"{color}{filled_block}{C.GREY}{empty_block}{C.RESET}"


def render_dashboard(portfolio: Portfolio, market: Dict[str, MarketSnapshot],
                      alerts: List[Alert], fallback: bool) -> None:
    os.system("cls" if os.name == "nt" else "clear")
    totals = portfolio.totals(market)
    cur = portfolio.currency

    print(f"{C.BOLD}{C.AMBER}{'-' * 58}{C.RESET}")
    print(f"{C.BOLD}{'CRYPTOGUARD':^58}{C.RESET}")
    print(f"{C.AMBER}{'-' * 58}{C.RESET}")

    status = f"{C.ORANGE}OFFLINE SIMULATION MODE{C.RESET}" if fallback else f"{C.BLUE}LIVE MARKET FEED{C.RESET}"
    print(f" {status}   {C.GREY}{cur.upper()} \u00b7 updated {datetime.now().strftime('%H:%M:%S')}{C.RESET}\n")

    pl_color = C.GREEN if totals["total_pl"] >= 0 else C.RED
    day_color = C.GREEN if totals["day_delta"] >= 0 else C.RED
    print(f" Portfolio Value   {fmt_money(totals['total_value'], cur)}")
    print(f" Today's P/L       {day_color}{fmt_money(totals['day_delta'], cur, show_sign=True)} ({totals['day_delta_pct']:+.2f}%){C.RESET}")
    print(f" Total P/L         {pl_color}{fmt_money(totals['total_pl'], cur, show_sign=True)} ({totals['total_pl_pct']:+.2f}%){C.RESET}")

    print(f"\n{C.GREY}{'-' * 58}{C.RESET}")
    print(f"{C.BOLD} MY CRYPTO{C.RESET}")
    print(f"{C.GREY}{'-' * 58}{C.RESET}")

    for h in portfolio.holdings:
        m = market.get(h.id)
        if not m:
            print(f" {h.symbol:<6} {'no data yet':<40}")
            continue
        vol = RiskAnalyzer.volatility_pct(m.sparkline)
        risk = RiskAnalyzer.classify(m.change_24h, vol)
        change_color = C.GREEN if m.change_24h >= 0 else C.RED
        sig = SIGNALS[risk]
        print(
            f" {C.BOLD}{h.symbol:<5}{C.RESET} "
            f"{fmt_money(m.price, cur):>12}  "
            f"{change_color}{m.change_24h:>+7.2f}%{C.RESET}  "
            f"{sig['color']}{sig['emoji']} {sig['label']:<10}{C.RESET} "
            f"{render_bar(risk)}"
        )

    print(f"\n{C.GREY}{'-' * 58}{C.RESET}")
    print(f"{C.BOLD} RECENT ALERTS{C.RESET}")
    print(f"{C.GREY}{'-' * 58}{C.RESET}")
    if not alerts:
        print(f" {C.GREY}All quiet - no signals yet.{C.RESET}")
    else:
        for a in alerts[-6:][::-1]:
            sig = SIGNALS[a.signal]
            print(f" {sig['color']}{sig['emoji']} {a.symbol} {sig['label']}{C.RESET} - {a.message}")

    print(f"\n{C.GREY}CryptoGuard reads market data only. It never asks for wallet keys or seed"
          f" phrases, and can't move funds. Signals describe conditions, not certainties.{C.RESET}")


# =========================================================================
# APP ORCHESTRATION
# =========================================================================
class CryptoGuardApp:
    def __init__(self, portfolio: Portfolio, interval: int = 30, notify: bool = True):
        self.portfolio = portfolio
        self.interval = interval
        self.fetcher = MarketDataFetcher()
        self.alert_engine = AlertEngine()
        self.notifier = NotificationService(enabled=notify)
        self.alert_log: List[Alert] = []

    def run_once(self) -> None:
        coin_ids = [h.id for h in self.portfolio.holdings]
        market, fallback = self.fetcher.fetch(coin_ids, self.portfolio.currency)
        new_alerts = self.alert_engine.generate(self.portfolio, market)
        self.alert_log.extend(new_alerts)

        render_dashboard(self.portfolio, market, self.alert_log, fallback)

        for a in new_alerts:
            self.notifier.send(a)

    def run_forever(self) -> None:
        try:
            while True:
                self.run_once()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print(f"\n{C.GREY}CryptoGuard stopped.{C.RESET}")


# =========================================================================
# CLI
# =========================================================================
def main():
    parser = argparse.ArgumentParser(description="CryptoGuard - cryptocurrency monitoring and risk alerts")
    parser.add_argument("--config", default="portfolio.json", help="Path to portfolio JSON file")
    parser.add_argument("--interval", type=int, default=30, help="Refresh interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run a single check and exit")
    parser.add_argument("--no-notify", action="store_true", help="Disable desktop notifications")
    parser.add_argument(
        "--currency", choices=sorted(CURRENCIES.keys()), default=None,
        help="Display currency, e.g. usd, php, eur (default: whatever is saved in the config file, or usd)",
    )
    parser.add_argument("--list-currencies", action="store_true", help="List supported currencies and exit")
    args = parser.parse_args()

    if args.list_currencies:
        for code, info in sorted(CURRENCIES.items()):
            print(f"  {code:<5} {info['symbol']:<5} {info['name']}")
        return

    file_existed = os.path.exists(args.config)

    if not file_existed:
        # First run: build the sample portfolio pre-scaled into the chosen
        # (or default) currency, so the demo numbers aren't raw USD figures
        # mislabeled with a different symbol.
        cfg = sample_config_for(args.currency or DEFAULT_CURRENCY)
        holdings = [Holding(**h) for h in cfg["holdings"]]
        portfolio = Portfolio(holdings, currency=cfg["currency"])
        portfolio.save(args.config)
    else:
        portfolio = Portfolio.load(args.config)
        if args.currency and args.currency != portfolio.currency:
            print(
                f"{C.ORANGE}Note:{C.RESET} switching display currency to "
                f"{args.currency.upper()}, but each holding's average purchase "
                f"price is still whatever number is stored in {args.config} - "
                f"it is NOT auto-converted. Edit the file (or re-add the coin) "
                f"if those prices were entered in a different currency.\n"
            )
            portfolio.currency = args.currency
            portfolio.save(args.config)

    app = CryptoGuardApp(portfolio, interval=args.interval, notify=not args.no_notify)

    if args.once:
        app.run_once()
    else:
        app.run_forever()


if __name__ == "__main__":
    main()