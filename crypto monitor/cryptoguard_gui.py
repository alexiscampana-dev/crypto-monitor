#!/usr/bin/env python3
"""
CRYPTOGUARD - Cryptocurrency Monitoring and Risk Alert Platform (Desktop GUI edition)

A native desktop window built with tkinter (included with Python - no extra
install needed beyond 'requests', which you already have).

Run it:
    python cryptoguard_gui.py

Optional, for real OS desktop popups when an alert fires:
    pip install plyer
"""

from __future__ import annotations

import json
import os
import queue
import statistics
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field, asdict
from datetime import datetime
from tkinter import ttk, simpledialog, messagebox
from typing import Dict, List, Optional, Tuple

try:
    import requests
except ImportError:
    print("This tool needs the 'requests' package. Install it with: pip install requests")
    sys.exit(1)


# =========================================================================
# DESIGN TOKENS
# =========================================================================
class T:
    BG = "#0A0C10"
    PANEL = "#12151C"
    PANEL_ALT = "#171B24"
    LINE = "#232834"
    INK = "#E9EBF0"
    INK_DIM = "#8B93A3"
    INK_FAINT = "#565D6C"
    AMBER = "#F2A93B"
    CYAN = "#3FD0C9"
    GREEN = "#4ADE80"
    YELLOW = "#F2C94C"
    ORANGE = "#F2994A"
    RED = "#F0555A"
    BLUE = "#4FB3F0"
    VIOLET = "#B385F0"
    TEAL = "#2DD4BF"


FONT_DISPLAY = ("Consolas", 11)
FONT_DISPLAY_BOLD = ("Consolas", 12, "bold")
FONT_TITLE = ("Consolas", 15, "bold")
FONT_BODY = ("Segoe UI", 10)
FONT_BODY_BOLD = ("Segoe UI", 10, "bold")
FONT_SMALL = ("Segoe UI", 9)


# =========================================================================
# MARKET / SIGNAL DATA
# =========================================================================
COINS: Dict[str, Dict[str, str]] = {
    "bitcoin":       {"symbol": "BTC",  "name": "Bitcoin",   "color": "#F2A93B"},
    "ethereum":      {"symbol": "ETH",  "name": "Ethereum",  "color": "#4FB3F0"},
    "solana":        {"symbol": "SOL",  "name": "Solana",    "color": "#B385F0"},
    "ripple":        {"symbol": "XRP",  "name": "XRP",       "color": "#3FD0C9"},
    "cardano":       {"symbol": "ADA",  "name": "Cardano",   "color": "#6FE3B4"},
    "dogecoin":      {"symbol": "DOGE", "name": "Dogecoin",  "color": "#E3C23C"},
    "binancecoin":   {"symbol": "BNB",  "name": "BNB",       "color": "#F0B24A"},
    "litecoin":      {"symbol": "LTC",  "name": "Litecoin",  "color": "#B8C0CC"},
    "polkadot":      {"symbol": "DOT",  "name": "Polkadot",  "color": "#F088B6"},
    "avalanche-2":   {"symbol": "AVAX", "name": "Avalanche", "color": "#E8637A"},
}

SIGNALS: Dict[str, Dict[str, str]] = {
    "LOW":      {"emoji": "\U0001F7E2", "label": "LOW RISK",     "color": T.GREEN},
    "WATCH":    {"emoji": "\U0001F7E1", "label": "WATCH",        "color": T.YELLOW},
    "HIGH":     {"emoji": "\U0001F7E0", "label": "HIGH RISK",    "color": T.ORANGE},
    "CRITICAL": {"emoji": "\U0001F534", "label": "CRITICAL",     "color": T.RED},
    "SURGE":    {"emoji": "\U0001F680", "label": "SURGE",        "color": T.TEAL},
    "PROFIT":   {"emoji": "\U0001F535", "label": "PROFIT ALERT", "color": T.BLUE},
    "SELL":     {"emoji": "\U0001F7E3", "label": "SELL REVIEW",  "color": T.VIOLET},
}

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

# Rough offline multipliers vs USD - used to (1) scale the sample portfolio
# into a plausible starting point for a chosen currency on first run, and
# (2) drive the offline simulated feed. Not for real conversion.
FX_APPROX = {
    "usd": 1, "eur": 0.92, "gbp": 0.79, "jpy": 149, "php": 56,
    "aud": 1.52, "cad": 1.36, "sgd": 1.34, "hkd": 7.8, "inr": 83,
    "cny": 7.2, "krw": 1330, "myr": 4.4, "idr": 15600, "thb": 33,
    "vnd": 24500, "chf": 0.88,
}


def fmt_money(amount: Optional[float], currency: str, show_sign: bool = False) -> str:
    if amount is None:
        return "\u2014"
    info = CURRENCIES.get(currency, CURRENCIES[DEFAULT_CURRENCY])
    decimals = info["decimals"]
    sign = "+" if (show_sign and amount >= 0) else ""
    return f"{sign}{info['symbol']}{amount:,.{decimals}f}"


DEFAULT_CONFIG = {
    "currency": DEFAULT_CURRENCY,
    "holdings": [
        {"id": "bitcoin",  "amount": 0.12, "avg_price": 61200, "profit_target": 20, "loss_threshold": -10},
        {"id": "ethereum", "amount": 1.4,  "avg_price": 3350,  "profit_target": 20, "loss_threshold": -10},
        {"id": "solana",   "amount": 18,   "avg_price": 168,   "profit_target": 15, "loss_threshold": -12},
    ]
}
CONFIG_PATH = "portfolio.json"


def sample_config_for(currency: str) -> dict:
    fx = FX_APPROX.get(currency, 1)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["currency"] = currency
    for h in cfg["holdings"]:
        h["avg_price"] = round(h["avg_price"] * fx, 2)
    return cfg


# =========================================================================
# PORTFOLIO / MARKET MODELS  (same logic as the CLI edition)
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
    sparkline: List[float] = field(default_factory=list)


class Portfolio:
    def __init__(self, holdings: Optional[List[Holding]] = None, currency: str = DEFAULT_CURRENCY):
        self.holdings: List[Holding] = holdings or []
        self.currency: str = currency if currency in CURRENCIES else DEFAULT_CURRENCY

    def add_or_topup(self, coin_id: str, amount: float, avg_price: float,
                      profit_target: float, loss_threshold: float) -> None:
        """Add a new holding, or - if this coin is already held - blend the
        new purchase into the existing position using a weighted-average
        cost basis (the same math as real 'average purchase price' tracking:
        e.g. buy 1 ETH at 100, then 1 ETH at 200 -> 2 ETH at avg 150)."""
        existing = next((h for h in self.holdings if h.id == coin_id), None)
        if existing:
            total_amount = existing.amount + amount
            existing.avg_price = round(
                (existing.amount * existing.avg_price + amount * avg_price) / total_amount, 8
            )
            existing.amount = total_amount
            existing.profit_target = profit_target
            existing.loss_threshold = loss_threshold
        else:
            self.holdings.append(Holding(coin_id, amount, avg_price, profit_target, loss_threshold))

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
            "total_value": total_value, "total_cost": total_cost,
            "total_pl": total_pl, "total_pl_pct": total_pl_pct,
            "day_delta": day_delta, "day_delta_pct": day_delta_pct,
        }

    @classmethod
    def load(cls, path: str, default_currency: str = DEFAULT_CURRENCY) -> "Portfolio":
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    data = json.load(f)
            except Exception:
                data = sample_config_for(default_currency)
        else:
            data = sample_config_for(default_currency)
        holdings = [Holding(**h) for h in data.get("holdings", [])]
        currency = data.get("currency", default_currency)
        return cls(holdings, currency=currency)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(
                {"currency": self.currency, "holdings": [asdict(h) for h in self.holdings]},
                f, indent=2,
            )


class MarketDataFetcher:
    BASE_URL = "https://api.coingecko.com/api/v3/coins/markets"

    def __init__(self):
        self._sim_state: Dict[str, Dict] = {}

    def fetch(self, coin_ids: List[str], currency: str = DEFAULT_CURRENCY) -> Tuple[Dict[str, MarketSnapshot], bool]:
        if not coin_ids:
            return {}, False
        currency = currency if currency in CURRENCIES else DEFAULT_CURRENCY
        params = {
            "vs_currency": currency, "ids": ",".join(coin_ids),
            "sparkline": "true", "price_change_percentage": "24h",
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
                    sparkline=(c.get("sparkline_in_7d") or {}).get("price", [])[-48:],
                )
            return snapshots, False
        except Exception:
            return self._simulate(coin_ids, currency), True

    def _simulate(self, coin_ids: List[str], currency: str = DEFAULT_CURRENCY) -> Dict[str, MarketSnapshot]:
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
            out[cid] = MarketSnapshot(
                price=state["price"],
                change_24h=(state["price"] - first) / first * 100,
                sparkline=list(state["series"]),
            )
        return out


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
        # Strong upward move first - this used to fall through to the
        # volatility checks below and get mislabeled CRITICAL/HIGH just for
        # moving fast, even though moving up fast isn't the same risk as
        # moving down fast.
        if change_24h >= 8:
            return "SURGE"
        # Everything past this point is about downside / choppiness, so the
        # volatility-only triggers only count when the coin isn't currently
        # in solid positive territory.
        if change_24h <= -8 or (volatility > 6 and change_24h < 0):
            return "CRITICAL"
        if change_24h <= -5 or (volatility > 4 and change_24h < 0):
            return "HIGH"
        if change_24h <= -2 or (volatility > 2 and change_24h < 0):
            return "WATCH"
        return "LOW"


@dataclass
class Alert:
    coin_id: str
    symbol: str
    signal: str
    message: str
    timestamp: datetime


class AlertEngine:
    def __init__(self):
        self._recent: Dict[str, float] = {}
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
            elif market_risk == "SURGE":
                message = (
                    f"{h.symbol} is up {m.change_24h:+.2f}% in 24h - a fast move worth watching. "
                    f"Your position is currently {'up' if pl_amount >= 0 else 'down'} "
                    f"{fmt_money(abs(pl_amount), currency)}. Fast moves can reverse quickly, "
                    f"so this isn't a signal to act on by itself."
                )

            if signal == "LOW":
                continue
            key = f"{h.id}:{signal}"
            if now - self._recent.get(key, 0) < self._cooldown_seconds:
                continue
            self._recent[key] = now
            alerts.append(Alert(h.id, h.symbol, signal, message, datetime.now()))
        return alerts


class NotificationService:
    def __init__(self):
        self._backend = self._detect_backend()

    def _detect_backend(self):
        try:
            from plyer import notification
            return notification
        except ImportError:
            return None

    def send(self, alert: Alert) -> None:
        if self._backend is None:
            return
        sig = SIGNALS[alert.signal]
        try:
            self._backend.notify(
                title=f"{sig['emoji']} {alert.symbol} - {sig['label']}",
                message=alert.message, timeout=8,
            )
        except Exception:
            pass


# =========================================================================
# GUI
# =========================================================================
class CryptoGuardGUI(tk.Tk):
    REFRESH_MS = 30_000

    def __init__(self):
        super().__init__()
        self.title("CryptoGuard")
        self.geometry("980x640")
        self.minsize(860, 560)
        self.configure(bg=T.BG)

        config_existed = os.path.exists(CONFIG_PATH)
        self.portfolio = Portfolio.load(CONFIG_PATH)
        if not config_existed:
            self.portfolio.save(CONFIG_PATH)

        self.fetcher = MarketDataFetcher()
        self.alert_engine = AlertEngine()
        self.notifier = NotificationService()

        self.market: Dict[str, MarketSnapshot] = {}
        self.alerts: List[Alert] = []
        self._ui_queue: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()

        self._build_style()
        self._build_layout()
        self._poll_queue()

        self._worker = threading.Thread(target=self._background_loop, daemon=True)
        self._worker.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=T.PANEL)
        style.configure("Card.TFrame", background=T.PANEL, relief="flat")
        style.configure("TLabel", background=T.PANEL, foreground=T.INK, font=FONT_BODY)
        style.configure("Dim.TLabel", background=T.PANEL, foreground=T.INK_FAINT, font=FONT_SMALL)
        style.configure("TButton", background=T.PANEL_ALT, foreground=T.INK, font=FONT_BODY_BOLD, borderwidth=0)
        style.map("TButton", background=[("active", T.LINE)])
        style.configure("Accent.TButton", background=T.AMBER, foreground="#1A1300", font=FONT_BODY_BOLD)
        style.map("Accent.TButton", background=[("active", "#d99b34")])

    # ---------------------------------------------------------------
    def _build_layout(self):
        header = tk.Frame(self, bg=T.BG)
        header.pack(fill="x", padx=16, pady=(14, 8))

        left = tk.Frame(header, bg=T.BG)
        left.pack(side="left")
        tk.Label(left, text="CRYPTOGUARD", bg=T.BG, fg=T.INK, font=FONT_TITLE).pack(anchor="w")
        self.status_lbl = tk.Label(left, text="starting\u2026", bg=T.BG, fg=T.INK_FAINT, font=FONT_SMALL)
        self.status_lbl.pack(anchor="w")

        right = tk.Frame(header, bg=T.BG)
        right.pack(side="right")
        ttk.Button(right, text="+ Add coin", style="Accent.TButton", command=self._open_add_dialog).pack(side="right", padx=(6, 0))
        ttk.Button(right, text="Refresh now", command=self._refresh_now).pack(side="right", padx=(6, 0))

        currency_codes = sorted(CURRENCIES.keys())
        self.currency_var = tk.StringVar(
            value=f"{self.portfolio.currency.upper()} \u00b7 {CURRENCIES[self.portfolio.currency]['name']}"
        )
        currency_menu = ttk.Combobox(
            right, textvariable=self.currency_var, state="readonly", width=20,
            values=[f"{c.upper()} \u00b7 {CURRENCIES[c]['name']}" for c in currency_codes],
        )
        currency_menu.pack(side="right", padx=(6, 6))
        currency_menu.bind("<<ComboboxSelected>>", lambda e: self._on_currency_change(currency_menu.get()))
        self._currency_codes = currency_codes

        # --- stat strip ---
        stats = tk.Frame(self, bg=T.BG)
        stats.pack(fill="x", padx=16, pady=(0, 10))
        self.stat_value = self._make_stat(stats, "PORTFOLIO VALUE")
        self.stat_today = self._make_stat(stats, "TODAY'S P/L")
        self.stat_total = self._make_stat(stats, "TOTAL P/L")
        self.stat_alerts = self._make_stat(stats, "ACTIVE ALERTS")

        # --- main split ---
        main = tk.Frame(self, bg=T.BG)
        main.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        # holdings panel
        holdings_panel = tk.Frame(main, bg=T.PANEL, highlightbackground=T.LINE, highlightthickness=1)
        holdings_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(holdings_panel, text="MY CRYPTO", bg=T.PANEL, fg=T.INK_DIM, font=FONT_SMALL).pack(anchor="w", padx=14, pady=(12, 6))
        self.holdings_container = tk.Frame(holdings_panel, bg=T.PANEL)
        self.holdings_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # alerts panel
        alerts_panel = tk.Frame(main, bg=T.PANEL, highlightbackground=T.LINE, highlightthickness=1)
        alerts_panel.grid(row=0, column=1, sticky="nsew")
        tk.Label(alerts_panel, text="RECENT ALERTS", bg=T.PANEL, fg=T.INK_DIM, font=FONT_SMALL).pack(anchor="w", padx=14, pady=(12, 6))

        alerts_scroll = tk.Frame(alerts_panel, bg=T.PANEL)
        alerts_scroll.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.alerts_text = tk.Text(
            alerts_scroll, bg=T.PANEL, fg=T.INK, font=FONT_SMALL, wrap="word",
            borderwidth=0, highlightthickness=0, state="disabled", padx=6, pady=4,
        )
        self.alerts_text.pack(fill="both", expand=True)
        for name, color in [(k, v["color"]) for k, v in SIGNALS.items()]:
            self.alerts_text.tag_configure(name, foreground=color, font=FONT_BODY_BOLD)
        self.alerts_text.tag_configure("time", foreground=T.INK_FAINT, font=FONT_SMALL)
        self.alerts_text.tag_configure("msg", foreground=T.INK_DIM, font=FONT_SMALL)

        # footer
        tk.Label(
            self,
            text="CryptoGuard reads market data only \u2014 it never asks for wallet keys or seed phrases, "
                 "and can't move funds. Signals describe conditions, not certainties.",
            bg=T.BG, fg=T.INK_FAINT, font=FONT_SMALL, wraplength=940, justify="left",
        ).pack(fill="x", padx=18, pady=(0, 12))

    def _make_stat(self, parent, label):
        card = tk.Frame(parent, bg=T.PANEL, highlightbackground=T.LINE, highlightthickness=1)
        card.pack(side="left", fill="both", expand=True, padx=4)
        tk.Label(card, text=label, bg=T.PANEL, fg=T.INK_FAINT, font=FONT_SMALL).pack(anchor="w", padx=12, pady=(10, 2))
        value = tk.Label(card, text="\u2014", bg=T.PANEL, fg=T.INK, font=FONT_DISPLAY_BOLD)
        value.pack(anchor="w", padx=12)
        sub = tk.Label(card, text="", bg=T.PANEL, fg=T.INK_FAINT, font=FONT_SMALL)
        sub.pack(anchor="w", padx=12, pady=(0, 10))
        return {"value": value, "sub": sub}

    # ---------------------------------------------------------------
    def _open_add_dialog(self):
        AddCoinDialog(self, on_add=self._add_holding)

    def _add_holding(self, holding: Holding):
        self.portfolio.add_or_topup(
            holding.id, holding.amount, holding.avg_price,
            holding.profit_target, holding.loss_threshold,
        )
        self.portfolio.save(CONFIG_PATH)
        self._refresh_now()

    def _remove_holding(self, coin_id: str):
        if messagebox.askyesno("Remove coin", f"Stop monitoring {COINS.get(coin_id, {}).get('symbol', coin_id)}?"):
            self.portfolio.remove(coin_id)
            self.portfolio.save(CONFIG_PATH)
            self._render_holdings()

    def _on_currency_change(self, selected_label: str):
        idx = [f"{c.upper()} \u00b7 {CURRENCIES[c]['name']}" for c in self._currency_codes].index(selected_label)
        new_currency = self._currency_codes[idx]
        if new_currency == self.portfolio.currency:
            return
        if self.portfolio.holdings:
            proceed = messagebox.askyesno(
                "Switch currency",
                f"Switching to {CURRENCIES[new_currency]['name']} changes how prices are displayed, "
                f"but each coin's saved average purchase price is NOT converted automatically \u2014 "
                f"it stays whatever number you entered. If those prices were entered in a different "
                f"currency, your P/L figures will be wrong until you edit or re-add those holdings.\n\n"
                f"Continue?",
            )
            if not proceed:
                self.currency_var.set(f"{self.portfolio.currency.upper()} \u00b7 {CURRENCIES[self.portfolio.currency]['name']}")
                return
        self.portfolio.currency = new_currency
        self.portfolio.save(CONFIG_PATH)
        self._refresh_now()

    def _refresh_now(self):
        threading.Thread(target=self._fetch_once, daemon=True).start()

    # ---------------------------------------------------------------
    def _background_loop(self):
        while not self._stop.is_set():
            self._fetch_once()
            self._stop.wait(self.REFRESH_MS / 1000)

    def _fetch_once(self):
        coin_ids = [h.id for h in self.portfolio.holdings]
        market, fallback = self.fetcher.fetch(coin_ids, self.portfolio.currency)
        new_alerts = self.alert_engine.generate(self.portfolio, market)
        self._ui_queue.put(("update", market, fallback, new_alerts))

    def _poll_queue(self):
        try:
            while True:
                kind, market, fallback, new_alerts = self._ui_queue.get_nowait()
                self.market = market
                if new_alerts:
                    self.alerts = (new_alerts + self.alerts)[:30]
                    for a in new_alerts:
                        self.notifier.send(a)
                self.status_lbl.config(
                    text=f"{'OFFLINE SIMULATION MODE' if fallback else 'LIVE MARKET FEED'}  \u00b7  "
                         f"updated {datetime.now().strftime('%H:%M:%S')}",
                    fg=T.ORANGE if fallback else T.CYAN,
                )
                self._render_all()
        except queue.Empty:
            pass
        self.after(300, self._poll_queue)

    # ---------------------------------------------------------------
    def _render_all(self):
        self._render_stats()
        self._render_holdings()
        self._render_alerts()

    def _render_stats(self):
        totals = self.portfolio.totals(self.market)
        cur = self.portfolio.currency
        self.stat_value["value"].config(text=fmt_money(totals['total_value'], cur))
        self.stat_value["sub"].config(text=f"cost basis {fmt_money(totals['total_cost'], cur)}")

        day = totals["day_delta"]
        self.stat_today["value"].config(text=fmt_money(day, cur, show_sign=True), fg=T.GREEN if day >= 0 else T.RED)
        self.stat_today["sub"].config(text=f"{totals['day_delta_pct']:+.2f}%")

        tot = totals["total_pl"]
        self.stat_total["value"].config(text=fmt_money(tot, cur, show_sign=True), fg=T.GREEN if tot >= 0 else T.RED)
        self.stat_total["sub"].config(text=f"{totals['total_pl_pct']:+.2f}%")

        self.stat_alerts["value"].config(text=str(len(self.alerts)), fg=T.AMBER if self.alerts else T.INK)
        self.stat_alerts["sub"].config(text="review below" if self.alerts else "all quiet")

    def _render_holdings(self):
        for w in self.holdings_container.winfo_children():
            w.destroy()

        if not self.portfolio.holdings:
            tk.Label(self.holdings_container, text="Nothing being watched yet. Add a coin to start monitoring.",
                     bg=T.PANEL, fg=T.INK_FAINT, font=FONT_SMALL).pack(pady=20)
            return

        cur = self.portfolio.currency
        for h in self.portfolio.holdings:
            m = self.market.get(h.id)
            row = tk.Frame(self.holdings_container, bg=T.PANEL_ALT, highlightbackground=T.LINE, highlightthickness=1)
            row.pack(fill="x", pady=4, padx=2)

            left = tk.Frame(row, bg=T.PANEL_ALT)
            left.pack(side="left", padx=12, pady=10)
            coin_color = COINS.get(h.id, {}).get("color", T.AMBER)
            tk.Label(left, text=h.symbol, bg=T.PANEL_ALT, fg=coin_color, font=FONT_DISPLAY_BOLD).pack(anchor="w")
            tk.Label(left, text=f"{h.amount:g} {h.symbol} \u00b7 avg {fmt_money(h.avg_price, cur)}",
                     bg=T.PANEL_ALT, fg=T.INK_FAINT, font=FONT_SMALL).pack(anchor="w")

            right = tk.Frame(row, bg=T.PANEL_ALT)
            right.pack(side="right", padx=12, pady=10)
            ttk.Button(right, text="Remove", command=lambda cid=h.id: self._remove_holding(cid)).pack(side="right")

            if m and m.price:
                vol = RiskAnalyzer.volatility_pct(m.sparkline)
                risk = RiskAnalyzer.classify(m.change_24h, vol)
                pl_pct = (m.price - h.avg_price) / h.avg_price * 100
                position_value = h.amount * m.price
                sig = SIGNALS[risk]

                mid = tk.Frame(row, bg=T.PANEL_ALT)
                mid.pack(side="right", padx=16, pady=10)

                # --- mini price-history chart ---
                spark_color = T.GREEN if m.change_24h >= 0 else T.RED
                spark = tk.Canvas(mid, width=90, height=34, bg=T.PANEL_ALT, highlightthickness=0)
                spark.pack(side="left", padx=10)
                self._draw_sparkline(spark, 90, 34, m.sparkline, spark_color)

                price_lbl = tk.Frame(mid, bg=T.PANEL_ALT)
                price_lbl.pack(side="left", padx=10)
                tk.Label(price_lbl, text=fmt_money(m.price, cur), bg=T.PANEL_ALT, fg=T.INK, font=FONT_DISPLAY).pack(anchor="e")
                tk.Label(price_lbl, text=f"{m.change_24h:+.2f}%", bg=T.PANEL_ALT,
                         fg=T.GREEN if m.change_24h >= 0 else T.RED, font=FONT_SMALL).pack(anchor="e")

                pos_lbl = tk.Frame(mid, bg=T.PANEL_ALT)
                pos_lbl.pack(side="left", padx=10)
                tk.Label(pos_lbl, text=fmt_money(position_value, cur), bg=T.PANEL_ALT, fg=T.INK, font=FONT_DISPLAY).pack(anchor="e")
                tk.Label(pos_lbl, text=f"{pl_pct:+.2f}%", bg=T.PANEL_ALT,
                         fg=T.GREEN if pl_pct >= 0 else T.RED, font=FONT_SMALL).pack(anchor="e")

                badge = tk.Label(mid, text=f" {sig['emoji']} {sig['label']} ", bg=T.PANEL_ALT,
                                  fg=sig["color"], font=FONT_BODY_BOLD)
                badge.pack(side="left", padx=10)

                # --- risk gauge bar ---
                gauge_bg = tk.Frame(row, bg=T.BG, height=4)
                gauge_bg.pack(fill="x", side="bottom")
                pct = {"LOW": 0.2, "WATCH": 0.45, "HIGH": 0.7, "CRITICAL": 0.95, "SURGE": 0.6}[risk]
                canvas = tk.Canvas(gauge_bg, height=4, bg=T.BG, highlightthickness=0)
                canvas.pack(fill="x")
                # Draw immediately using the container's already-known width
                # (don't rely solely on <Configure>, which doesn't reliably
                # fire for every row on every refresh), then keep it bound
                # so the bar still redraws correctly if the window is resized.
                self.holdings_container.update_idletasks()
                initial_width = gauge_bg.winfo_width() or self.holdings_container.winfo_width() or 400
                self._draw_gauge(canvas, initial_width, pct, sig["color"])
                canvas.bind("<Configure>", lambda e, c=canvas, p=pct, col=sig["color"]: self._draw_gauge(c, e.width, p, col))
            else:
                tk.Label(row, text="no data yet", bg=T.PANEL_ALT, fg=T.INK_FAINT, font=FONT_SMALL).pack(side="right", padx=16)

    @staticmethod
    def _draw_gauge(canvas: tk.Canvas, width: int, pct: float, color: str):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, width, 4, fill=T.BG, width=0)
        canvas.create_rectangle(0, 0, max(2, int(width * pct)), 4, fill=color, width=0)

    @staticmethod
    def _draw_sparkline(canvas: tk.Canvas, width: int, height: int, series: List[float], color: str):
        canvas.delete("all")
        if not series or len(series) < 2:
            canvas.create_text(width / 2, height / 2, text="\u2014", fill=T.INK_FAINT, font=FONT_SMALL)
            return
        lo, hi = min(series), max(series)
        span = (hi - lo) or 1.0
        pad = 3
        n = len(series)
        points = []
        for i, v in enumerate(series):
            x = pad + (width - 2 * pad) * (i / (n - 1))
            y = height - pad - (height - 2 * pad) * ((v - lo) / span)
            points.extend([x, y])
        canvas.create_line(*points, fill=color, width=1.5, smooth=True)

    def _render_alerts(self):
        self.alerts_text.config(state="normal")
        self.alerts_text.delete("1.0", "end")
        if not self.alerts:
            self.alerts_text.insert("end", "No signals yet. CryptoGuard checks every 30 seconds.\n", "msg")
        else:
            for a in self.alerts:
                sig = SIGNALS[a.signal]
                self.alerts_text.insert("end", f"{sig['emoji']} {a.symbol} \u2014 {sig['label']}  ", a.signal)
                self.alerts_text.insert("end", f"{a.timestamp.strftime('%H:%M:%S')}\n", "time")
                self.alerts_text.insert("end", f"{a.message}\n\n", "msg")
        self.alerts_text.config(state="disabled")

    # ---------------------------------------------------------------
    def _on_close(self):
        self._stop.set()
        self.destroy()


class AddCoinDialog(tk.Toplevel):
    def __init__(self, parent: CryptoGuardGUI, on_add):
        super().__init__(parent)
        self.title("Add a coin to watch")
        self.configure(bg=T.PANEL)
        self.geometry("340x420")
        self.resizable(False, False)
        self.on_add = on_add
        self.parent_portfolio = parent.portfolio
        self.transient(parent)
        self.grab_set()

        # Show every coin, including ones already held - picking an
        # already-held coin tops it up (weighted-average cost basis)
        # instead of replacing it.
        self._available = list(COINS.keys())
        self._holdings_by_id = {h.id: h for h in parent.portfolio.holdings}

        pad = {"padx": 18, "pady": (10, 0)}

        tk.Label(self, text="Coin", bg=T.PANEL, fg=T.INK_FAINT, font=FONT_SMALL).pack(anchor="w", **pad)
        self.coin_var = tk.StringVar()
        coin_menu = ttk.Combobox(
            self, textvariable=self.coin_var, state="readonly",
            values=[
                f"{COINS[c]['name']} ({COINS[c]['symbol']})" + (" \u2014 already held" if c in self._holdings_by_id else "")
                for c in self._available
            ],
        )
        coin_menu.current(0)
        coin_menu.pack(fill="x", padx=18, pady=(2, 0))
        coin_menu.bind("<<ComboboxSelected>>", lambda e: self._update_hint())
        self._coin_menu = coin_menu

        self.hint_lbl = tk.Label(self, text="", bg=T.PANEL, fg=T.CYAN, font=FONT_SMALL,
                                  wraplength=300, justify="left")
        self.hint_lbl.pack(anchor="w", padx=18, pady=(6, 0))

        cur = parent.portfolio.currency
        self.amount_var = self._labeled_entry("Amount to add", "e.g. 0.5")
        self.avg_price_var = self._labeled_entry(
            f"Price paid for this batch ({cur.upper()}, {CURRENCIES[cur]['symbol']})", "e.g. 61200"
        )
        self.profit_var = self._labeled_entry("Profit target %", "20")
        self.loss_var = self._labeled_entry("Loss threshold %", "-10")

        ttk.Button(self, text="Save", style="Accent.TButton", command=self._submit).pack(fill="x", padx=18, pady=18)
        self._update_hint()

    def _update_hint(self):
        idx = self._coin_menu.current()
        if idx < 0:
            return
        coin_id = self._available[idx]
        existing = self._holdings_by_id.get(coin_id)
        cur = self.parent_portfolio.currency
        cur_symbol = CURRENCIES[cur]["symbol"]
        if existing:
            self.hint_lbl.config(
                text=(
                    f"You already hold {existing.amount:g} {COINS[coin_id]['symbol']} at avg "
                    f"{cur_symbol}{existing.avg_price:,.2f}. What you enter below will be added on top, "
                    f"and your average purchase price will be recalculated automatically."
                )
            )
            self.profit_var.set(str(existing.profit_target))
            self.loss_var.set(str(existing.loss_threshold))
        else:
            self.hint_lbl.config(text="")
            self.profit_var.set("")
            self.loss_var.set("")

    def _labeled_entry(self, label, placeholder):
        tk.Label(self, text=label, bg=T.PANEL, fg=T.INK_FAINT, font=FONT_SMALL).pack(anchor="w", padx=18, pady=(12, 0))
        var = tk.StringVar()
        entry = tk.Entry(self, textvariable=var, bg=T.PANEL_ALT, fg=T.INK, insertbackground=T.INK,
                          relief="flat", font=FONT_BODY)
        entry.pack(fill="x", padx=18, pady=(2, 0), ipady=4)
        return var

    def _submit(self):
        try:
            idx = self._coin_menu.current()
            coin_id = self._available[idx]
            amount = float(self.amount_var.get())
            avg_price = float(self.avg_price_var.get())
            profit_target = float(self.profit_var.get() or 20)
            loss_threshold = float(self.loss_var.get() or -10)
            if amount <= 0 or avg_price <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid input", "Please enter valid positive numbers for amount and price.")
            return

        self.on_add(Holding(coin_id, amount, avg_price, profit_target, loss_threshold))
        self.destroy()


if __name__ == "__main__":
    app = CryptoGuardGUI()
    app.mainloop()