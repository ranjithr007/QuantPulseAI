import { useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import Pill from "../ui/Pill";
import { formatPrice } from "../../utils/formatters";

const WIDGET_URL = "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";

export default function AdvancedTradingViewPanel({
  currentPrice,
  symbol,
  timeframe,
  tradePlan,
  resistanceLevels,
  supportLevels,
  height = 420,
  embedded = false,
}) {
  const containerRef = useRef(null);
  const [status, setStatus] = useState("loading");
  const [reloadKey, setReloadKey] = useState(0);
  const tradingViewSymbol = useMemo(() => toTradingViewSymbol(symbol), [symbol]);
  const interval = useMemo(() => toTradingViewInterval(timeframe), [timeframe]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let mounted = true;
    let settled = false;
    let pollId = null;
    let timeoutId = null;
    let initId = null;
    setStatus("loading");

    initId = window.setTimeout(() => {
      if (!mounted || settled || !container.isConnected) return;

      container.innerHTML = "";

      const widgetHost = document.createElement("div");
      widgetHost.className = "tradingview-widget-container__widget h-full w-full";
      widgetHost.dataset.tradingviewHost = "true";

      const script = document.createElement("script");
      script.type = "text/javascript";
      script.src = WIDGET_URL;
      script.async = true;
      script.innerHTML = JSON.stringify({
        autosize: true,
        symbol: tradingViewSymbol,
        interval,
        timezone: "Asia/Kolkata",
        theme: "dark",
        style: "1",
        locale: "en",
        backgroundColor: "rgba(2, 6, 23, 1)",
        gridColor: "rgba(30, 41, 59, 0.55)",
        hide_top_toolbar: false,
        hide_legend: false,
        hide_side_toolbar: false,
        allow_symbol_change: false,
        save_image: false,
        calendar: false,
        withdateranges: true,
        support_host: "https://www.tradingview.com",
      });
      script.onerror = () => {
        if (mounted && !settled) setStatus("error");
      };
      script.onload = () => {
        if (!mounted || settled || !container.isConnected) return;

        pollId = window.setInterval(() => {
          if (!mounted || settled) return;
          if (widgetHost.querySelector("iframe") || container.querySelector("iframe")) {
            settled = true;
            window.clearInterval(pollId);
            window.clearTimeout(timeoutId);
            setStatus("ready");
          }
        }, 120);

        timeoutId = window.setTimeout(() => {
          if (!mounted || settled) return;
          window.clearInterval(pollId);
          setStatus("error");
        }, 12000);
      };

      widgetHost.appendChild(script);
      container.appendChild(widgetHost);
    }, 0);

    return () => {
      mounted = false;
      settled = true;
      if (initId) window.clearTimeout(initId);
      if (pollId) window.clearInterval(pollId);
      if (timeoutId) window.clearTimeout(timeoutId);
    };
  }, [interval, reloadKey, tradingViewSymbol]);

  const chart = (
    <>
      <div className="relative overflow-hidden bg-slate-950" style={{ height }}>
        <div ref={containerRef} className="tradingview-widget-container h-full w-full" />
        {status === "error" ? <ErrorState onRetry={() => setReloadKey((value) => value + 1)} /> : null}
      </div>

      <ReferenceLevels
        currentPrice={currentPrice}
        tradePlan={tradePlan}
        resistanceLevels={resistanceLevels}
        supportLevels={supportLevels}
      />
    </>
  );

  if (embedded) {
    return <div className="min-w-0 overflow-hidden rounded-lg border border-white/10 bg-slate-950/75">{chart}</div>;
  }

  return (
    <div className="min-w-0 overflow-hidden rounded-lg border border-white/10 bg-slate-950/75">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
        <div>
          <div className="text-sm font-medium text-white">{symbol} advanced real-time chart</div>
          <div className="text-xs text-slate-500">TradingView tools, indicators, drawings, and Binance market data</div>
        </div>
        <div className="flex items-center gap-2">
          <Pill tone="cyan">{String(timeframe || "1h").toUpperCase()}</Pill>
          <Pill tone="slate">{formatPrice(currentPrice)}</Pill>
        </div>
      </div>

      {chart}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 px-4 py-2 text-xs text-slate-500">
        <span>QuantPulse AI execution levels are shown below the exchange chart.</span>
        <a
          href={tradingViewMarketUrl(tradingViewSymbol)}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 font-medium text-cyan-300 transition hover:text-cyan-100"
        >
          Open in TradingView
          <ExternalLink className="h-3.5 w-3.5" />
        </a>
      </div>
    </div>
  );
}

function ErrorState({ onRetry }) {
  return (
    <div className="absolute inset-0 grid place-items-center bg-slate-950 px-4 text-center">
      <div>
        <div className="text-sm font-medium text-slate-200">TradingView could not load</div>
        <div className="mt-1 text-xs text-slate-500">Check the internet connection or browser content blocking.</div>
        <button
          type="button"
          onClick={onRetry}
          className="mx-auto mt-3 inline-flex h-9 items-center gap-2 rounded-lg border border-cyan-400/30 bg-cyan-500/10 px-3 text-xs font-medium text-cyan-200 transition hover:bg-cyan-500/20"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </button>
      </div>
    </div>
  );
}

function ReferenceLevels({ currentPrice, tradePlan, resistanceLevels, supportLevels }) {
  const levels = [
    ["R3", resistanceLevels?.r3, "text-blue-200"],
    ["R2", resistanceLevels?.r2, "text-blue-200"],
    ["R1", resistanceLevels?.r1, "text-blue-200"],
    ["Price", currentPrice, "text-cyan-200"],
    ["Entry", tradePlan?.entry, "text-amber-200"],
    ["Stop", tradePlan?.stop_loss, "text-rose-200"],
    ["T1", tradePlan?.target1, "text-emerald-200"],
    ["S1", supportLevels?.s1, "text-violet-200"],
    ["S2", supportLevels?.s2, "text-violet-200"],
    ["S3", supportLevels?.s3, "text-violet-200"],
  ];

  return (
    <div className="border-t border-white/10 bg-slate-950/90 px-3 py-2">
      <div className="flex gap-2 overflow-x-auto pb-0.5">
        {levels.map(([label, value, tone]) => (
          <div key={label} className="min-w-[88px] shrink-0 rounded-lg border border-white/10 bg-slate-900/70 px-2.5 py-1.5">
            <div className="text-[10px] uppercase tracking-[0.14em] text-slate-500">{label}</div>
            <div className={`mt-0.5 truncate text-xs font-semibold ${tone}`}>{formatLevelValue(value)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function toTradingViewSymbol(symbol) {
  const value = String(symbol || "BTCUSDT").trim().toUpperCase();
  if (value.includes(":")) return value;

  const compact = value.replace(/[^A-Z0-9]/g, "");
  const pair = /(?:USDT|USDC|USD|BTC|ETH)$/.test(compact) ? compact : `${compact}USDT`;
  return `BINANCE:${pair || "BTCUSDT"}`;
}

function formatLevelValue(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? formatPrice(number) : "N/A";
}

function toTradingViewInterval(timeframe) {
  return {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "1d": "D",
    "1w": "W",
  }[String(timeframe || "1h").toLowerCase()] || "60";
}

function tradingViewMarketUrl(tradingViewSymbol) {
  const [exchange, pair] = tradingViewSymbol.split(":");
  return `https://www.tradingview.com/symbols/${exchange}-${pair}/`;
}
