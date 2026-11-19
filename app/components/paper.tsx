"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API, money, pct, type Option } from "../lib/market";
import { Term } from "./term";
import { OptionsDxResearch } from "./optionsdx-research";

type PaperFill = { side: string; quantity: number; price: number; fee: number; occurred_at: string };
type Position = { id: number; ticker: string; symbol: string; kind: string; strike: number; expiration: string; remaining_quantity: number; initial_quantity: number; entry_price: number; entry_fee: number; opened_at: string; realized_profit: number; unrealized_profit: number | null; mark_per_share: number | null; warnings: string[]; fills: PaperFill[] };
type Portfolio = { initial_cash?: number; cash?: number; equity?: number | null; total_return?: number | null; realized_profit?: number; closed_positions?: number; win_rate?: number | null; average_closed_return?: number | null; incomplete_marks?: number; sampled_max_drawdown?: number | null; sampled_valuation_count?: number; positions: Position[]; benchmark?: { status: string; reason: string } };
type SavedValuation = { id: number; observed_at: string; cash: number; equity: number | null };
type Readiness = { status: string; saved_quote_count: number; earliest_quote: string | null; latest_quote: string | null; blockers: string[] };
type Coverage = { sample_date: string; ticker: string; contract_count: number; fields: Record<string, boolean>; credits_consumed: string | null; note: string };

async function getJSON(path: string, options?: RequestInit) {
  const response = await fetch(`${API}${path}`, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "The request could not be completed.");
  return data;
}

export function PaperPortfolio({ selected, ticker }: { selected: Option | null; ticker: string }) {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [valuations, setValuations] = useState<SavedValuation[]>([]);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [coverage, setCoverage] = useState<Coverage | null>(null);
  const [checkingCoverage, setCheckingCoverage] = useState(false);
  const [coverageError, setCoverageError] = useState("");
  const [initialCash, setInitialCash] = useState("");
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [fee, setFee] = useState("");
  const [closing, setClosing] = useState<number | null>(null);
  const [closeQuantity, setCloseQuantity] = useState("");
  const [closePrice, setClosePrice] = useState("");
  const [closeFee, setCloseFee] = useState("");
  const [method, setMethod] = useState<"sale" | "settlement">("sale");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const openRequest = useRef<{ signature: string; id: string } | null>(null);
  const closeRequest = useRef<{ signature: string; id: string } | null>(null);
  function requestId(ref: { current: { signature: string; id: string } | null }, payload: object) {
    const signature = JSON.stringify(payload);
    if (!ref.current || ref.current.signature !== signature) ref.current = { signature, id: crypto.randomUUID() };
    return ref.current.id;
  }

  const load = useCallback(async (signal?: AbortSignal) => {
    const [account, saved, gate] = await Promise.all([getJSON("/paper", { signal }), getJSON("/paper/valuations", { signal }), getJSON("/backtests/readiness", { signal })]);
    if (!signal?.aborted) { setPortfolio(account); setValuations(saved); setReadiness(gate); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => { load(controller.signal).catch(() => { if (!controller.signal.aborted) setError("Paper portfolio could not be loaded."); }); }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [load]);

  async function post(path: string, data?: object) {
    setBusy(true); setError(""); setMessage("");
    try {
      await getJSON(path, { method: "POST", headers: { "Content-Type": "application/json" }, ...(data ? { body: JSON.stringify(data) } : {}) });
      await load();
      return true;
    } catch (e) { setError(e instanceof Error ? e.message : "Paper action failed."); return false; }
    finally { setBusy(false); }
  }
  async function createAccount() {
    if (await post("/paper/account", { initial_cash: Number(initialCash) })) setMessage("Paper account created.");
  }
  async function openPosition() {
    if (!selected) return;
    const payload = { ticker, symbol: selected.symbol, quantity: Number(quantity), price: Number(price), fee: Number(fee) };
    if (await post("/paper/positions", { request_id: requestId(openRequest, payload), ...payload })) {
      openRequest.current = null;
      setQuantity(""); setPrice(""); setFee(""); setMessage("Hypothetical position recorded.");
    }
  }
  async function closePosition(id: number) {
    const payload = { position_id: id, quantity: Number(closeQuantity), price: Number(closePrice), fee: Number(closeFee), method };
    if (await post(`/paper/positions/${id}/close`, { request_id: requestId(closeRequest, payload), quantity: payload.quantity, price: payload.price, fee: payload.fee, method })) {
      closeRequest.current = null;
      setClosing(null); setCloseQuantity(""); setClosePrice(""); setCloseFee(""); setMessage("Hypothetical close recorded.");
    }
  }
  async function saveValuation() {
    if (await post("/paper/valuations")) setMessage("Valuation snapshot saved.");
  }
  async function checkCoverage() {
    setCheckingCoverage(true); setCoverageError(""); setCoverage(null);
    try { setCoverage(await getJSON("/backtests/coverage-check", { method: "POST" })); }
    catch (e) { setCoverageError(e instanceof Error ? e.message : "Coverage check failed."); }
    finally { setCheckingCoverage(false); }
  }
  const canOpen = selected && quantity !== "" && price !== "" && fee !== "" && Number.isInteger(Number(quantity)) && Number(quantity) > 0 && Number(price) > 0 && Number(fee) >= 0;
  const canClose = closeQuantity !== "" && closePrice !== "" && closeFee !== "" && Number.isInteger(Number(closeQuantity)) && Number(closeQuantity) > 0 && Number(closePrice) >= 0 && Number(closeFee) >= 0;
  const setCash = initialCash !== "" && Number.isFinite(Number(initialCash)) && Number(initialCash) > 0;
  return <section id="paper" className="research-section">
    <div className="section-heading"><div><h2>Paper portfolio</h2><p>Hypothetical positions only. No broker orders are sent.</p></div></div>
    {error && <div className="notice error" role="alert">{error}</div>}{message && <div className="notice" role="status">{message}</div>}
    {!portfolio ? <div className="panel"><p className="research-muted">Loading paper portfolio...</p></div> : portfolio.initial_cash == null ? <div className="panel paper-panel"><p>Choose a starting amount of hypothetical cash. It cannot be edited after creation.</p><div className="assumption-fields"><label>Starting paper cash ($)<input type="number" min="1" step="any" value={initialCash} onChange={e => setInitialCash(e.target.value)}/></label><button className="primary" disabled={!setCash || busy} onClick={createAccount}>Create paper account</button></div></div> : <>
      <div className="metrics paper-metrics">
        <div className="metric"><span>PAPER CASH</span><strong>{money(portfolio.cash)}</strong></div>
        <div className="metric"><Term label="PAPER EQUITY" definition="Hypothetical cash plus the value of open positions, when every position has a usable quote. Indicative marks are not executable."/><strong>{money(portfolio.equity)}</strong><p>{portfolio.incomplete_marks ? `${portfolio.incomplete_marks} position(s) unvalued` : "Indicative marks may be used"}</p></div>
        <div className="metric"><Term label="REALIZED P&L" definition="Profit or loss from manually recorded paper closes, including the allocated entry fee and closing fee."/><strong>{money(portfolio.realized_profit)}</strong></div>
        <div className="metric"><span>TOTAL RETURN</span><strong>{pct(portfolio.total_return)}</strong><p>Unavailable if any position is unvalued</p></div>
      </div>
      <div className="panel paper-panel"><div className="panel-top"><strong>Record a paper position</strong><span className="tag">NO REAL TRADE</span></div>
        {selected ? <><p>Selected: {ticker} {selected.kind} {money(selected.strike)} · {selected.expiration}</p><p className="research-muted">Enter a hypothetical purchase price per share and total fees. Displayed indicative quotes are not executable.</p><div className="assumption-fields"><label>Contracts<input aria-label="Paper contracts" type="number" min="1" step="1" value={quantity} onChange={e => setQuantity(e.target.value)}/></label><label>Paper entry price per share ($)<input aria-label="Paper entry price per share" type="number" min="0" step="any" value={price} onChange={e => setPrice(e.target.value)}/></label><label>Total entry fees ($)<input aria-label="Paper entry fees" type="number" min="0" step="any" value={fee} onChange={e => setFee(e.target.value)}/></label><button className="primary" disabled={!canOpen || busy} onClick={openPosition}>Record paper position</button></div></> : <p className="research-muted">Select an option in the chain to record a paper position.</p>}
      </div>
      <div className="panel paper-panel"><div className="panel-top"><strong>Positions</strong><button className="verify-button" disabled={busy} onClick={saveValuation}>Save valuation snapshot</button></div>
        {!portfolio.positions.length ? <p className="research-muted">No paper positions.</p> : portfolio.positions.map(position => <div className="paper-position" key={position.id}>
          <div className="paper-position-head"><strong>{position.ticker} {position.kind} {money(position.strike)} · {position.expiration}</strong><span>{position.remaining_quantity} of {position.initial_quantity} open</span></div>
          <div className="paper-values"><span>Entry: {money(position.entry_price)} / share</span><span>Mark: {money(position.mark_per_share)} / share</span><span>Unrealized: {money(position.unrealized_profit)}</span><span>Realized: {money(position.realized_profit)}</span></div>
          {position.warnings.map(warning => <p className="research-muted" key={warning}>{warning}</p>)}
          {position.remaining_quantity > 0 && <button className="table-select" onClick={() => { setClosing(closing === position.id ? null : position.id); setCloseQuantity(""); setClosePrice(""); setCloseFee(""); setMethod("sale"); }}>Record paper close</button>}
          {closing === position.id && <div className="paper-close"><p className="research-muted">Enter a hypothetical sale or, on or after expiration, a settlement amount. Nothing is sent to a broker.</p><div className="assumption-fields"><label>Type<select aria-label="Paper close type" value={method} onChange={e => setMethod(e.target.value as "sale" | "settlement")}><option value="sale">Sale</option><option value="settlement">Settlement</option></select></label><label>Contracts<input aria-label="Paper close contracts" type="number" min="1" max={position.remaining_quantity} step="1" value={closeQuantity} onChange={e => setCloseQuantity(e.target.value)}/></label><label>Price per share ($)<input aria-label="Paper close price per share" type="number" min="0" step="any" value={closePrice} onChange={e => setClosePrice(e.target.value)}/></label><label>Total close fees ($)<input aria-label="Paper close fees" type="number" min="0" step="any" value={closeFee} onChange={e => setCloseFee(e.target.value)}/></label><button className="primary" disabled={!canClose || busy} onClick={() => closePosition(position.id)}>Save paper close</button></div></div>}
          <details><summary>Paper fills</summary>{position.fills.map((fill, index) => <p className="research-muted" key={index}>{new Date(fill.occurred_at).toLocaleString()} · {fill.side} · {fill.quantity} at {money(fill.price)} · fees {money(fill.fee)}</p>)}</details>
        </div>)}
      </div>
      <div className="panel paper-panel"><div className="panel-top"><strong>Paper performance</strong><span className="subtle">Based on saved manual activity</span></div>
        <div className="paper-values"><span>Closed positions: {portfolio.closed_positions}</span><span>Win rate: {pct(portfolio.win_rate)}</span><span>Average closed return: {pct(portfolio.average_closed_return)}</span><span><Term label="Sampled maximum drawdown" definition="The largest fall from a previous high among saved valuation snapshots. It can miss larger losses between snapshots."/>: {pct(portfolio.sampled_max_drawdown)}</span></div>
        <p className="research-muted">Drawdown uses up to {portfolio.sampled_valuation_count} manually saved snapshots and is unavailable if any is incomplete. It can miss movements between snapshots.</p><p className="research-muted">Benchmark comparison unavailable: {portfolio.benchmark?.reason}</p>
        <details className="history-details"><summary>Valuation snapshots ({valuations.length}, latest 100)</summary>{valuations.map(v => <div className="history-row" key={v.id}><span>{new Date(v.observed_at).toLocaleString()} · cash {money(v.cash)} · equity {v.equity == null ? "unavailable" : money(v.equity)}</span></div>)}</details>
      </div>
    </>}
    <div className="section-heading"><div><h2>Historical backtesting</h2></div></div><div className="panel paper-panel"><div className="panel-top"><strong>Status: {readiness?.status || "unavailable"}</strong><span className="subtle">{readiness?.saved_quote_count ?? 0} locally saved quotes</span></div>
      <p className="research-muted">The validated backtest is unavailable until the required data and replay checks are complete. A separate limited AAPL experiment appears below when imported data is available.</p>
      <button className="verify-button" disabled={checkingCoverage} onClick={checkCoverage}>{checkingCoverage ? "Checking historical data..." : "Check a historical data sample"}</button>
      <p className="research-muted">Requests one narrowly filtered AAPL option sample and may use provider credits. A sample cannot verify the full dataset.</p>
      {coverageError && <p className="research-muted" role="alert">{coverageError}</p>}
      {coverage && <div role="status"><p className="research-muted">{coverage.ticker} sample for {coverage.sample_date}: {coverage.contract_count} contract(s). {coverage.fields.bid && coverage.fields.ask ? "Bid and ask present." : "Bid or ask missing."} {coverage.fields.iv ? "Implied volatility present." : "Implied volatility missing; the current signal cannot be replayed directly."} Credits used: {coverage.credits_consumed ?? "not reported"}.</p><p className="research-muted">{coverage.note}</p></div>}
      {Array.isArray(readiness?.blockers) && <ul className="readiness-list">{readiness.blockers.map(blocker => <li key={blocker}>{blocker}</li>)}</ul>}
    </div>
    <OptionsDxResearch />
  </section>;
}
