"use client";

import { useCallback, useEffect, useState } from "react";
import { Term } from "./term";
import { definitions } from "../lib/financial-terms";
import { Metric, Panel } from "./primitives";
import { OptionsChain, PayoffChart } from "./options";
import { Research } from "./research";
import { Watchlist } from "./watchlist";
import { PaperPortfolio } from "./paper";
import { CandidateExplanation } from "./candidate-explanation";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";

import { API, money, pct, type Option, type Detail, type Health, type Verification } from "../lib/market";

export default function Dashboard() {
  const [ticker, setTicker] = useState("AAPL");
  const [health, setHealth] = useState<Health | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [chain, setChain] = useState<Option[]>([]);
  const [scan, setScan] = useState<Option[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [selected, setSelected] = useState<Option | null>(null);
  const [target, setTarget] = useState(150);
  const [filter, setFilter] = useState("");
  const [showAllTickers, setShowAllTickers] = useState(false);
  const [includeStale, setIncludeStale] = useState(false);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [watchlistRevision, setWatchlistRevision] = useState(0);
  const [watchMessage, setWatchMessage] = useState("");

  const load = useCallback(async (signal: AbortSignal) => {
    try {
      const responses = await Promise.all([fetch(`${API}/health`, { signal }), fetch(`${API}/securities/${ticker}`, { signal }), fetch(`${API}/securities/${ticker}/options`, { signal }), fetch(`${API}/scan?include_stale=${includeStale}`, { signal })]);
      if (responses.some(r => !r.ok)) throw new Error("The API could not load research data.");
      const [h, d, c, s] = await Promise.all(responses.map(r => r.json()));
      if (!signal.aborted) { setHealth(h); setDetail(d); setChain(c); setScan(s); setError(""); }
    } catch { if (!signal.aborted) { setHealth(null); setError("Backend unavailable. Start the API and database, then refresh this page."); } }
  }, [ticker, includeStale]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => { void load(controller.signal); }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [load, reloadVersion]);
  async function ingest() {
    setBusy(true); setError("");
    try {
      const response = await fetch(`${API}/ingest/${ticker}`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Ingestion failed.");
      setReloadVersion(value => value + 1);
    } catch (e) { setError(e instanceof Error ? e.message : "Ingestion failed."); }
    finally { setBusy(false); }
  }
  async function verify() {
    if (!selected) return;
    setVerifying(true); setError(""); setVerification(null);
    try {
      const response = await fetch(`${API}/securities/${ticker}/options/${encodeURIComponent(selected.symbol)}/verify`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Verification failed.");
      setVerification(data);
    } catch (e) { setError(e instanceof Error ? e.message : "Verification failed."); }
    finally { setVerifying(false); }
  }
  async function addToWatchlist() {
    if (!selected) return;
    setWatchMessage("");
    try {
      const response = await fetch(`${API}/watchlist`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticker, symbol: selected.symbol }) });
      if (!response.ok) throw new Error("Could not add this contract to the watchlist.");
      setWatchlistRevision(value => value + 1);
      setWatchMessage("Added to watchlist.");
    } catch (e) { setWatchMessage(e instanceof Error ? e.message : "Could not add contract."); }
  }
  const activeDetail = detail?.ticker === ticker ? detail : null;
  const currentChain = activeDetail ? chain : [];
  const last = activeDetail?.prices.at(-1);
  const premium = selected?.ask;
  const pnl = selected && premium != null ? (Math.max(selected.kind === "call" ? target - selected.strike : selected.strike - target, 0) - premium) * 100 : null;
  const matching = scan.filter(x => showAllTickers
    ? x.ticker?.includes(filter.trim().toUpperCase())
    : x.ticker === ticker);
  const filtered = matching.slice(0, 20);
  const chart = activeDetail?.prices.slice(-60) || [];

  return <div className="shell">
    <aside className="sidebar"><div className="brand"><span className="brandmark" aria-hidden="true">A</span><div>ASYMMETRY<small>RESEARCH TERMINAL</small></div></div>
      <div className="side-label">WORKSPACE</div><a className="nav active" href="#overview"><span aria-hidden="true">O</span> Overview</a><a className="nav" href="#explorer"><span aria-hidden="true">S</span> Opportunities</a><a className="nav" href="#detail"><span aria-hidden="true">P</span> Price history</a><a className="nav" href="#calculator"><span aria-hidden="true">C</span> Options &amp; payoff</a><a className="nav" href="#watchlist"><span aria-hidden="true">W</span> Watchlist</a><a className="nav" href="#research"><span aria-hidden="true">R</span> Research</a><a className="nav" href="#paper"><span aria-hidden="true">P</span> Paper portfolio</a>
      <div className="side-bottom"><div className="status-dot" /> {health ? "CONNECTED" : "OFFLINE"}<p>No live trading</p></div>
    </aside>
    <main className="main" id="overview">
      <header className="topbar"><div><span className="crumb">WORKSPACE</span><span className="slash">/</span><span>Market overview</span></div><div className="top-right"><span className="dot" /> MARKET DATA</div></header>
      <div className="content">
        <div className="heading"><div><div className="eyebrow">MARKET RESEARCH</div><h1>Market overview</h1></div><button className="primary" onClick={ingest} disabled={busy}>{busy ? "Refreshing..." : `Refresh ${ticker}`}</button></div>
        {error && <div className="notice error" role="alert">{error}</div>}
        {health && !health.provider_configured && <div className="notice"><strong>Market data not connected.</strong> Configure provider credentials to load data.</div>}
        <div className="metrics">
          <Metric label="SECURITIES" definition={definitions.security} value="5" detail="In the configured list"/>
          <Metric label="CANDIDATES" definition={definitions.candidate} value={scan.length} detail="Options matching the screen"/>
          <div className="metric"><Term label="SELECTED TICKER" definition={definitions.ticker}/><strong>{ticker} <small>{money(last?.close)}</small></strong><p>{last ? `Closing price: ${last.date}` : "No price data available"}</p></div>
          <div className="metric"><span>DATA PROVIDER</span><strong className={health?.provider_configured ? "green" : "muted"}>{health?.provider || "Unavailable"}</strong><p>{health?.provider_configured ? "Connected" : "Not configured"}</p></div>
        </div>
        <div className="section-heading" id="explorer"><div><h2>Opportunities</h2><p>Ordered by a transparent screening priority; not a valuation or recommendation.</p></div><div className="opportunity-controls"><label>Stock <select aria-label="Opportunity ticker" value={ticker} onChange={e => { setTicker(e.target.value); setSelected(null); setVerification(null); }}>{["AAPL","MSFT","NVDA","SPY","TSLA"].map(t => <option key={t}>{t}</option>)}</select></label><label className="stale-toggle"><input type="checkbox" checked={showAllTickers} onChange={e => { setShowAllTickers(e.target.checked); setFilter(""); }}/> Show all tickers</label>{showAllTickers && <label className="search"><input aria-label="Filter by ticker" placeholder="Filter ticker" value={filter} onChange={e => setFilter(e.target.value)} /></label>}</div></div>
        <Panel className="table-panel"><div className="panel-top"><div><span className="panel-title">{showAllTickers ? "All tickers" : ticker} screen results</span><span className="count">{matching.length} RESULTS</span></div><label className="stale-toggle"><input type="checkbox" checked={includeStale} onChange={e => setIncludeStale(e.target.checked)}/> Include stale quotes</label></div>
          <div className="table-wrap"><table><thead><tr><th><Term label="UNDERLYING" definition={definitions.underlying}/></th><th><Term label="CONTRACT" definition={definitions.contract}/></th><th><Term label="EXPIRATION" definition={definitions.expiration}/></th><th><Term label="IV" definition={definitions.iv}/></th><th><Term label="IV - RV" definition={definitions.gap}/></th><th><Term label="SPREAD" definition={definitions.spread}/></th><th><Term label="OPEN INTEREST" definition={definitions.interest}/></th><th><Term label="SCREEN SCORE" definition={definitions.screenScore}/></th><th>QUOTE TIME / FRESHNESS</th></tr></thead><tbody>{filtered.map(row => <tr key={row.symbol} onClick={() => { if (row.ticker) setTicker(row.ticker); setSelected(row); setVerification(null); }}><td className="strong">{row.ticker}</td><td><button className="table-select" type="button" onClick={() => { if (row.ticker) setTicker(row.ticker); setSelected(row); setVerification(null); }}>{row.kind.toUpperCase()} {money(row.strike)}</button></td><td>{row.expiration}</td><td>{pct(row.iv)}</td><td className="green">{pct(row.iv_minus_rv)}</td><td>{pct(row.spread)}</td><td>{row.open_interest ?? "-"}</td><td>{row.screen_factors?.score ?? "?"}</td><td>{row.quote_timestamp ? new Date(row.quote_timestamp).toLocaleString() : row.date || "Unknown"}{row.stale ? " - STALE" : ""}</td></tr>)}</tbody></table></div>
          {!filtered.length && <div className="empty"><strong>No matching options {showAllTickers ? "" : `for ${ticker}`}</strong><p>Refresh the ticker or include stale quotes to inspect older observations.</p></div>}
          <div className="panel-foot"><span>Screen results do not establish that an option is mispriced.</span><span>SHOWING {filtered.length} OF {matching.length}</span></div>
        </Panel>
        {selected && <CandidateExplanation key={`${ticker}:${selected.symbol}`} option={selected} ticker={ticker} referencePrice={last?.close ?? null} priceDate={last?.date ?? null}/>}
        <div className="section-heading" id="detail"><div><h2>Price history</h2></div><select value={ticker} onChange={e => { setTicker(e.target.value); setSelected(null); setVerification(null); }} aria-label="Select ticker">{["AAPL","MSFT","NVDA","SPY","TSLA"].map(t => <option key={t}>{t}</option>)}</select></div>
        <div className="detail-grid"><div className="panel chart-panel"><div className="panel-top"><div><span className="panel-title">{ticker} price history</span><p className="subtle"><Term label="Daily close" definition={definitions.close}/> - last 60 observations</p></div><div className="chart-price">{money(last?.close)}<small>{last?.date || "NO DATA"}</small></div></div>
          {chart.length ? <div className="chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={chart}><CartesianGrid stroke="#edf0ec" vertical={false}/><XAxis dataKey="date" tick={{fontSize: 10}} minTickGap={45}/><YAxis domain={["auto","auto"]} tick={{fontSize: 10}} width={45}/><Tooltip/><Line type="monotone" dataKey="close" stroke="#197b63" strokeWidth={2} dot={false}/></LineChart></ResponsiveContainer></div> : <div className="chart-empty">No price history available.</div>}
          <div className="chart-footer"><span><Term label="20-DAY REALIZED VOLATILITY (RV)" definition={definitions.rv}/> <strong>{pct(activeDetail?.realized_volatility)}</strong></span><span>SOURCE <strong>{health?.provider?.toUpperCase() || "-"}</strong></span></div></div>
          <div className="panel insight"><div className="panel-top"><span className="panel-title">Data status</span></div><div className="note-row"><Term label="OPTION SNAPSHOT" definition={definitions.snapshot}/><strong>{currentChain[0]?.date || "Unavailable"}</strong></div><p className="micro">Refresh is manual. Quotes older than 15 minutes are excluded from the screen; dates and feeds may differ.</p><p className="micro">Realized volatility uses unadjusted closes. Splits and dividends can distort this calculation.</p><div className="note-row"><span>LAST REFRESH</span><strong>{activeDetail?.last_ingestion?.status || "Not run"}</strong></div></div></div>
        <div className="section-heading" id="calculator"><div><h2>Options &amp; payoff</h2></div></div>
        <div className="detail-grid bottom-grid"><OptionsChain key={ticker} ticker={ticker} chain={currentChain} selected={selected} onSelect={row => { setSelected(row); setVerification(null); }}/>
        <div className="panel calculator"><div className="panel-top"><Term label="Expiration payoff" definition={definitions.payoff}/><span className="tag"><Term label="HYPOTHETICAL" definition={definitions.hypothetical}/></span></div>{selected ? <><p className="contract">{selected.kind.toUpperCase()} {money(selected.strike)} <span> - {selected.expiration}</span> <Term label="Option type" definition={definitions.type}/></p><div className="calculator-field"><div><label htmlFor="target-price">Underlying price at expiration</label><Term label="" accessibleLabel="Underlying price at expiration" definition={definitions.underlying}/></div><input id="target-price" type="number" min="0" value={target} onChange={e => setTarget(Math.max(0, Number(e.target.value)))} /></div><div className="calc-grid"><div><Term label="ESTIMATED P&L" definition={definitions.pnl}/><strong>{pnl == null ? "-" : money(pnl)}</strong></div><div><Term label="BREAK-EVEN" definition={definitions.breakeven}/><strong>{premium == null ? "-" : money(selected.strike + (selected.kind === "call" ? premium : -premium))}</strong></div><div><Term label="MAXIMUM LOSS" definition={definitions.loss}/><strong>{premium == null ? "-" : money(premium * 100)}</strong></div><div><Term label="PURCHASE PRICE" definition={definitions.premium}/><strong>Ask x 100</strong></div></div>
          <PayoffChart option={selected} target={target}/>{selected.screen_factors && <div className="quote-info"><strong>Screening factors (0?100)</strong><div>Volatility: {selected.screen_factors.volatility_factor ?? "?"} ? 40% ? Spread: {selected.screen_factors.spread_factor ?? "?"} ? 40% ? Data completeness: {selected.screen_factors.completeness_factor} ? 20%</div><div>Expected value, catalyst relevance, and research evidence: not assessed.</div></div>}<button className="verify-button" onClick={addToWatchlist}>Add to watchlist</button>{watchMessage && <p className="micro watch-message" role="status">{watchMessage}</p>}<div className="quote-info"><div><Term label="PROVIDER / FEED" definition={definitions.feed}/> {selected.source || "-"} / {selected.feed || "legacy snapshot"}</div><div><Term label="QUOTE TIME" definition={definitions.quote}/> {selected.quote_timestamp ? new Date(selected.quote_timestamp).toLocaleString() : "Unavailable"} {selected.stale ? " - STALE" : ""}</div><div><Term label="GREEKS" definition={definitions.greeks}/> <Term label="Delta" definition={definitions.delta}/> {selected.delta?.toFixed(3) ?? "-"} - <Term label="Gamma" definition={definitions.gamma}/> {selected.gamma?.toFixed(3) ?? "-"} - <Term label="Theta" definition={definitions.theta}/> {selected.theta?.toFixed(3) ?? "-"} - <Term label="Vega" definition={definitions.vega}/> {selected.vega?.toFixed(3) ?? "-"}</div><div><Term label="LIQUIDITY" definition={definitions.liquidity}/> <Term label="Spread" definition={definitions.spread}/> {pct(selected.spread)} - <Term label="Open interest" definition={definitions.interest}/> {selected.open_interest ?? "Unavailable"}</div>{selected.warning && <div className="micro">{selected.warning}</div>}</div>
          <button className="verify-button" onClick={verify} disabled={verifying}>{verifying ? "Checking..." : "Compare with MarketData.app"}</button>{verification && <div className="verification"><strong>{verification.significant_discrepancy ? "Large difference between providers" : "Provider comparison"}</strong><p>MarketData.app: <Term label="bid" definition={definitions.bid}/> {money(verification.secondary.bid)} / <Term label="ask" definition={definitions.ask}/> {money(verification.secondary.ask)} - <Term label="IV" definition={definitions.iv}/> {pct(verification.secondary.iv)}</p><p>Quote time: {verification.secondary.quote_timestamp ? new Date(verification.secondary.quote_timestamp).toLocaleString() : "Unavailable"} - <Term label="Feed" definition={definitions.feed}/>: {verification.secondary.feed}</p><p>Time between quotes: {verification.timestamp_difference_seconds == null ? "unknown" : `${Math.round(verification.timestamp_difference_seconds / 60)} minutes`}</p><p>MarketData.app minus primary: bid {money(verification.differences_secondary_minus_primary.bid)} - ask {money(verification.differences_secondary_minus_primary.ask)} - <Term label="midpoint" definition={definitions.midpoint}/> {money(verification.differences_secondary_minus_primary.midpoint)} - IV {pct(verification.differences_secondary_minus_primary.iv)}</p>{verification.warnings.map(w => <p key={w}>{w}</p>)}</div>}<p className="micro">One standard contract. Fees, exercise costs and early exercise are excluded.</p></> : <div className="empty compact">Select an option to calculate its payoff.</div>}</div></div>
        <Watchlist revision={watchlistRevision}/>
        <Research key={ticker} ticker={ticker}/>
        <PaperPortfolio selected={selected} ticker={ticker}/>
        <footer>RESEARCH ONLY <span>No real trades</span></footer>
      </div>
    </main>
  </div>;
}
