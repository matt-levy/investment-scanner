"use client";

import { useEffect, useState } from "react";
import { API, money, pct } from "../lib/market";

type Quality = { observations: number; days: number; first: string; last: string; unusable_bid_ask: number; missing_or_nonpositive_iv: number; note: string };
type Trade = { signal_date: string; entry_date: string; exit_date: string; kind: string; strike: number; expiration: string; entry_ask: number; exit_bid: number; net_profit: number };
type Result = { start: string; end: string; initial_cash: number; final_equity: number; total_return: number; benchmark_return: number; trade_count: number; fee_per_side: number; holding_sessions: number; trades: Trade[]; limitations: string[] };
type Comparison = { sample_rows: number; estimated_rows: number; mean_absolute_difference: number | null; missing_sample_rows: number; missing_estimable: number; note: string };

export function OptionsDxResearch() {
  const [quality, setQuality] = useState<Quality | null>(null);
  const [ticker, setTicker] = useState("AAPL");
  const [qualityError, setQualityError] = useState("");
  const [start, setStart] = useState("2023-07-03");
  const [end, setEnd] = useState("2023-12-29");
  const [fee, setFee] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [comparisonError, setComparisonError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API}/backtests/optionsdx/quality?ticker=${ticker}`, { signal: controller.signal }).then(async r => {
      const data = await r.json();
      if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Imported data unavailable.");
      if (!data || typeof data.observations !== "number" || typeof data.unusable_bid_ask !== "number" || typeof data.missing_or_nonpositive_iv !== "number") throw new Error("Imported data unavailable.");
      return data;
    }).then(data => { if (!controller.signal.aborted) { setQuality(data); setQualityError(""); } }).catch(e => { if (!controller.signal.aborted) { setQuality(null); setQualityError(e instanceof Error ? e.message : "Imported data unavailable."); } });
    return () => controller.abort();
  }, [ticker]);
  async function run() {
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await fetch(`${API}/backtests/optionsdx/exploratory`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticker, start, end, transaction_cost: Number(fee) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The experiment could not be completed.");
      setResult(data);
    } catch (e) { setError(e instanceof Error ? e.message : "The experiment could not be completed."); }
    finally { setBusy(false); }
  }
  async function compareIv() {
    setComparisonError(""); setComparison(null);
    try {
      const response = await fetch(`${API}/backtests/optionsdx/iv-comparison`);
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Comparison unavailable.");
      setComparison(data);
    } catch (e) { setComparisonError(e instanceof Error ? e.message : "Comparison unavailable."); }
  }
  return <div className="panel paper-panel">
    <div className="panel-top"><strong>Historical experiment</strong><span className="tag">EXPLORATORY</span></div>
    <label>Stock <select aria-label="Historical experiment stock" value={ticker} disabled={busy} onChange={e => { setTicker(e.target.value); setQuality(null); setQualityError(""); setResult(null); setError(""); }}><option>AAPL</option><option>NVDA</option><option>TSLA</option></select></label>
    {qualityError && <p className="research-muted" role="status">{qualityError} Import the matching OptionsDX archives to make this stock available.</p>}
    {quality && <p className="research-muted">Imported OptionsDX data: {quality.first} to {quality.last}, {quality.days} recorded days. {quality.unusable_bid_ask.toLocaleString()} of {quality.observations.toLocaleString()} observations have unusable bid or ask; {quality.missing_or_nonpositive_iv.toLocaleString()} have missing or nonpositive implied volatility. {quality.note}</p>}
    {ticker === "AAPL" && <>
    <button className="verify-button" onClick={compareIv}>Compare volatility estimates</button>
    <p className="research-muted">Compares a small sample with a European pricing model using illustrative 5% interest and 0.5% annual dividend assumptions. Apple options permit early exercise; these are approximations, not verified historical estimates.</p>
    {comparisonError && <p className="research-muted" role="alert">{comparisonError}</p>}
    {comparison && <p className="research-muted" role="status">Estimates produced for {comparison.estimated_rows} of {comparison.sample_rows} sample quotes. Average absolute difference from the supplied volatility: {pct(comparison.mean_absolute_difference)}. Estimates were also possible for {comparison.missing_estimable} of {comparison.missing_sample_rows} sampled quotes with missing or nonpositive volatility. {comparison.note}</p>}
    </>}
    <p className="research-muted">Simulates one contract at a time with $10,000 starting cash, a five-session holding period and a maximum 20% bid-ask spread. It uses the scanner’s ranking, enters on the next recorded day at the ask and exits at the bid. Enter the fee charged per contract on each side. Periods spanning a stock split must be tested separately.</p>
    <div className="assumption-fields"><label>Start date<input type="date" value={start} onChange={e => setStart(e.target.value)} /></label><label>End date<input type="date" value={end} onChange={e => setEnd(e.target.value)} /></label><label>Fee per side ($)<input type="number" min="0" step="any" value={fee} onChange={e => setFee(e.target.value)} /></label><button className="primary" disabled={!quality || busy || fee === "" || !Number.isFinite(Number(fee)) || Number(fee) < 0 || !start || !end} onClick={run}>{busy ? "Running..." : `Run ${ticker} experiment`}</button></div>
    {error && <p className="research-muted" role="alert">{error}</p>}
    {result && <div role="status"><div className="paper-values"><span>Starting cash: {money(result.initial_cash)}</span><span>Ending cash: {money(result.final_equity)}</span><span>Simulated return: {pct(result.total_return)}</span><span>SPY price return: {pct(result.benchmark_return)}</span><span>Closed trades: {result.trade_count}</span></div>
      <p className="research-muted">This comparison is descriptive: the fund price return excludes dividends and fund-investment costs, and the options experiment is not independently validated.</p>
      <ul className="readiness-list">{result.limitations.map(item => <li key={item}>{item}</li>)}</ul>
      <details><summary>View simulated trades ({result.trade_count})</summary>{result.trades.map((trade, index) => <p className="research-muted" key={index}>Signal {trade.signal_date}; bought {trade.entry_date}, sold {trade.exit_date}: {trade.kind} ${trade.strike}, expires {trade.expiration}. Entry {money(trade.entry_ask)} / share, exit {money(trade.exit_bid)} / share, net {money(trade.net_profit)}.</p>)}</details>
    </div>}
  </div>;
}
