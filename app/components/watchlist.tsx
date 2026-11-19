"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { API, money, pct, type Option } from "../lib/market";
import { Term } from "./term";
import { AssessmentEditor } from "./assessment";
import { europeanOptionValue } from "../lib/option-model";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

type Item = { id: number; ticker: string; symbol: string; kind: "call" | "put"; strike: number; expiration: string; current_quote: Option | null; priority?: { score: number | null; quantitative: number | null; expected_value_factor: number | null; catalyst_factor: number | null; evidence_factor: number | null; fresh: boolean; bars_fresh: boolean; scenario_current: boolean; scenario_created_at: string | null; assessment_created_at: string | null }; research_assessment?: { catalyst_relevance: string; evidence_quality: string } | null };
type Scenario = { name: string; price: string; probability: string; volatility: string };
type Assumptions = { premium: number; transaction_cost: number; valuation_date?: string | null; risk_free_rate?: number | null; dividend_yield?: number | null; scenarios: { name: string; price: number; probability: number; volatility?: number | null }[] };
type Result = { outcomes: { name: string; price: number; probability: number; net_profit: number }[]; expected_value: number; break_even_probability: number | null };
type Snapshot = { id: number; created_at: string; assumptions: Assumptions; results: Result; quote_snapshot: Option | null };

const blank = (): Scenario[] => [{ name: "Bullish", price: "", probability: "", volatility: "" }, { name: "Neutral", price: "", probability: "", volatility: "" }, { name: "Bearish", price: "", probability: "", volatility: "" }];

function ScenarioEditor({ item, onUpdated }: { item: Item; onUpdated: () => Promise<void> }) {
  const [premium, setPremium] = useState("");
  const [cost, setCost] = useState("");
  const [mode, setMode] = useState<"expiration" | "before">("expiration");
  const [valuationDate, setValuationDate] = useState("");
  const [rate, setRate] = useState("");
  const [dividend, setDividend] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>(blank);
  const [history, setHistory] = useState<Snapshot[]>([]);
  const [quotes, setQuotes] = useState<Option[]>([]);
  const [quoteSource, setQuoteSource] = useState("alpaca");
  const [quotePage, setQuotePage] = useState(0);
  const [quoteFeed, setQuoteFeed] = useState("indicative");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    const responses = await Promise.all([fetch(`${API}/watchlist/${item.id}/scenarios`, { signal }), fetch(`${API}/watchlist/${item.id}/quotes?source=${quoteSource}&offset=${quotePage * 100}${quoteSource === "alpaca" ? `&feed=${quoteFeed}` : ""}`, { signal })]);
    if (responses.some(r => !r.ok)) throw new Error("Saved history could not be loaded.");
    const [saved, observations] = await Promise.all(responses.map(r => r.json()));
    if (!signal?.aborted) { setHistory(saved); setQuotes(observations); }
  }, [item.id, quoteSource, quotePage, quoteFeed]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => { load(controller.signal).catch(() => { if (!controller.signal.aborted) setError("Saved history could not be loaded."); }); }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [load]);

  const inputs = useMemo(() => {
    if (premium.trim() === "" || cost.trim() === "" || scenarios.some(s => s.price.trim() === "" || s.probability.trim() === "")) return null;
    const p = Number(premium), c = Number(cost);
    const rows = scenarios.map(s => ({ name: s.name, price: Number(s.price), probability: Number(s.probability) / 100 }));
    if (!Number.isFinite(p) || p <= 0 || !Number.isFinite(c) || c < 0 || rows.some(s => !Number.isFinite(s.price) || s.price < 0 || !Number.isFinite(s.probability) || s.probability < 0 || s.probability > 1) || Math.abs(rows.reduce((sum, s) => sum + s.probability, 0) - 1) > 0.000001) return null;
    if (mode === "before") {
      if (!valuationDate || valuationDate >= item.expiration || !rate.trim() || !dividend.trim() || scenarios.some(s => !s.volatility.trim())) return null;
      const r = Number(rate) / 100, d = Number(dividend) / 100;
      const withVol = rows.map((row, i) => ({ ...row, volatility: Number(scenarios[i].volatility) / 100 }));
      if (!Number.isFinite(r) || r < -.2 || r > 1 || !Number.isFinite(d) || d < 0 || d > 1 || withVol.some(s => !Number.isFinite(s.volatility) || s.volatility < 0 || s.volatility > 5)) return null;
      return { premium: p, transaction_cost: c, valuation_date: valuationDate, risk_free_rate: r, dividend_yield: d, scenarios: withVol };
    }
    return { premium: p, transaction_cost: c, valuation_date: null, risk_free_rate: null, dividend_yield: null, scenarios: rows };
  }, [premium, cost, scenarios, mode, valuationDate, rate, dividend, item.expiration]);
  const results = useMemo(() => {
    if (!inputs) return null;
    const years = inputs.valuation_date ? (Date.parse(item.expiration + "T00:00:00Z") - Date.parse(inputs.valuation_date + "T00:00:00Z")) / 86400000 / 365 : 0;
    const rows = inputs.scenarios.map(s => {
      const value = years > 0 && "volatility" in s ? europeanOptionValue(item.kind, s.price, item.strike, years, s.volatility, inputs.risk_free_rate!, inputs.dividend_yield!) : Math.max(item.kind === "call" ? s.price - item.strike : item.strike - s.price, 0);
      return { ...s, value, profit: (value - inputs.premium) * 100 - inputs.transaction_cost };
    });
    const neutral = rows[1].probability;
    const denominator = rows[0].profit - rows[2].profit;
    const base = neutral * rows[1].profit + (1 - neutral) * rows[2].profit;
    const threshold = Math.abs(denominator) > 1e-9 ? -base / denominator : null;
    const breakEvenBull = threshold != null && threshold >= 0 && threshold <= 1 - neutral ? threshold : null;
    const everySplitBreaksEven = Math.abs(denominator) <= 1e-9 && Math.abs(base) <= 1e-9;
    return { rows, expected: rows.reduce((sum, s) => sum + s.probability * s.profit, 0), breakEvenBull, everySplitBreaksEven };
  }, [inputs, item.kind, item.strike, item.expiration]);

  async function save() {
    if (!inputs) return;
    setSaving(true); setError(""); setMessage("");
    try {
      const response = await fetch(`${API}/watchlist/${item.id}/scenarios`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(inputs) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Check the scenario values.");
      await Promise.all([load(), onUpdated()]);
      setMessage("Assumptions saved.");
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to save."); }
    finally { setSaving(false); }
  }
  function restore(snapshot: Snapshot) {
    const saved = snapshot.assumptions;
    if (saved.scenarios.length !== 3 || !["Bullish", "Neutral", "Bearish"].every((name, index) => saved.scenarios[index].name === name)) {
      setMessage("This saved version uses a different scenario layout and cannot be edited here.");
      return;
    }
    setPremium(String(saved.premium)); setCost(String(saved.transaction_cost));
    setMode(saved.valuation_date && saved.valuation_date < item.expiration ? "before" : "expiration");
    setValuationDate(saved.valuation_date || ""); setRate(saved.risk_free_rate == null ? "" : String(saved.risk_free_rate * 100)); setDividend(saved.dividend_yield == null ? "" : String(saved.dividend_yield * 100));
    setScenarios(saved.scenarios.map(s => ({ name: s.name, price: String(s.price), probability: String(s.probability * 100), volatility: s.volatility == null ? "" : String(s.volatility * 100) })));
    setMessage("Saved assumptions loaded; edit and save to create a new version.");
  }
  function change(index: number, field: "price" | "probability" | "volatility", value: string) {
    setScenarios(current => current.map((s, i) => i === index ? { ...s, [field]: value } : s));
  }
  return <div className="scenario-editor">
    <h3>Expiration scenarios · {item.ticker} {item.kind} {money(item.strike)}</h3>
    <p className="research-muted">Hypothetical only. Enter your own prices and probabilities; they must total 100%. One long standard contract.</p>
    <div className="priority-detail"><strong>Watchlist research priority: {item.priority?.score ?? "Not ranked"}</strong><div>Quantitative {item.priority?.quantitative ?? "unknown"} x 50% | Expected value {item.priority?.expected_value_factor ?? "unknown"} x 20% | Your catalyst rating {item.priority?.catalyst_factor ?? "unknown"} x 15% | Your evidence rating {item.priority?.evidence_factor ?? "unknown"} x 15%.</div><div>Requires a fresh quote, a price bar from the past seven days, a current saved scenario, and both source-linked ratings. Expected value uses your saved entry price and scenarios, not the current ask. Inputs are subjective and do not establish mispricing.</div>{item.priority?.scenario_created_at && <div>Scenario saved {new Date(item.priority.scenario_created_at).toLocaleString()}{!item.priority.scenario_current ? " - past valuation or expiration" : ""}.</div>}{item.priority?.assessment_created_at && <div>Assessment saved {new Date(item.priority.assessment_created_at).toLocaleString()}.</div>}</div>
    <div className="assumption-fields"><label>Valuation timing<select aria-label="Valuation timing" value={mode} onChange={e => setMode(e.target.value as "expiration" | "before")}><option value="expiration">At expiration</option><option value="before">Before expiration</option></select></label>{mode === "before" && <><label>Sale date<input aria-label="Sale date" type="date" max={item.expiration} value={valuationDate} onChange={e => setValuationDate(e.target.value)}/></label><label>Annual risk-free rate (%)<input aria-label="Annual risk-free rate" type="number" step="any" value={rate} onChange={e => setRate(e.target.value)}/></label><label>Annual dividend yield (%)<input aria-label="Annual dividend yield" type="number" min="0" step="any" value={dividend} onChange={e => setDividend(e.target.value)}/></label></>}</div>
    {mode === "before" && <p className="research-muted">European Black-Scholes-Merton estimate, using calendar days and a continuous dividend yield. American early exercise, discrete dividends, spreads and future market prices are not modeled.</p>}
    <div className="assumption-fields"><label>Option purchase price per share<input aria-label="Option purchase price per share" type="number" min="0" step="any" value={premium} onChange={e => setPremium(e.target.value)}/></label><label>Transaction costs per contract ($)<input aria-label="Transaction costs per contract" type="number" min="0" step="any" value={cost} onChange={e => setCost(e.target.value)}/></label></div>
    <div className="table-wrap"><table><thead><tr><th>SCENARIO</th><th>UNDERLYING PRICE AT VALUATION</th><th>YOUR PROBABILITY (%)</th>{mode === "before" && <th>ASSUMED IV (%)</th>}<th>OPTION VALUE / SHARE</th><th>NET PROFIT / LOSS</th></tr></thead><tbody>{scenarios.map((s, i) => <tr key={s.name}><td>{s.name}</td><td><input aria-label={`${s.name} price`} type="number" min="0" step="any" value={s.price} onChange={e => change(i, "price", e.target.value)}/></td><td><input aria-label={`${s.name} probability`} type="number" min="0" max="100" step="any" value={s.probability} onChange={e => change(i, "probability", e.target.value)}/></td>{mode === "before" && <td><input aria-label={`${s.name} volatility`} type="number" min="0" max="500" step="any" value={s.volatility} onChange={e => change(i, "volatility", e.target.value)}/></td>}<td>{results ? money(results.rows[i].value) : "-"}</td><td>{results ? money(results.rows[i].profit) : "—"}</td></tr>)}</tbody></table></div>
    {results && inputs ? <><p><Term label="Expected value" definition="The average outcome implied by the prices and probabilities you enter. It is not a forecast or a guarantee."/>: <strong>{money(results.expected)}</strong></p><p className="research-muted">Sensitivity: holding the neutral probability at {pct(inputs.scenarios[1].probability)}, the remainder is split between bullish and bearish outcomes.</p><div className="sensitivity">{[0, .25, .5, .75, 1].map(fraction => {
      const neutral = inputs.scenarios[1].probability, bull = (1 - neutral) * fraction, bear = 1 - neutral - bull;
      const expected = bull * results.rows[0].profit + neutral * results.rows[1].profit + bear * results.rows[2].profit;
      return <div key={fraction}><span>Bull {pct(bull)} · Bear {pct(bear)}</span><strong>{money(expected)}</strong></div>;
    })}</div><p className="research-muted">Break-even bullish probability (neutral fixed at {pct(inputs.scenarios[1].probability)}): {results.everySplitBreaksEven ? "Every probability in this range." : results.breakEvenBull == null ? "No break-even within this range." : pct(results.breakEvenBull)}.</p></> : <p className="research-muted">Enter valid values for every field. Probabilities must total 100%, and a sale date must be before expiration.</p>}
    <button className="verify-button" type="button" disabled={!inputs || saving} onClick={save}>{saving ? "Saving..." : "Save assumptions"}</button>
    {message && <p className="research-muted" role="status">{message}</p>}{error && <p className="notice error" role="alert">{error}</p>}
    <details className="history-details"><summary>Saved assumptions ({history.length})</summary>{history.length === 0 ? <p className="research-muted">No saved versions.</p> : history.map(s => <div className="history-row" key={s.id}><span>{new Date(s.created_at).toLocaleString()} · expected {money(s.results.expected_value)} · entry {money(s.assumptions.premium)} · saved quote {s.quote_snapshot?.quote_timestamp ? new Date(s.quote_snapshot.quote_timestamp).toLocaleString() : "unavailable"}</span><button type="button" className="table-select" onClick={() => restore(s)}>Load</button></div>)}</details>
    <AssessmentEditor itemId={item.id} ticker={item.ticker} onUpdated={onUpdated}/>
    <details className="history-details"><summary>Saved quote history</summary><p className="research-muted">Locally saved observations, not complete market history. Quotes from different feeds or times are not directly comparable; indicative quotes are not executable.</p><label>Source <select aria-label="Quote history source" value={quoteSource} onChange={e => { setQuoteSource(e.target.value); setQuotePage(0); }}><option value="alpaca">Alpaca</option><option value="marketdata">MarketData.app</option></select></label>{quoteSource === "alpaca" && <label> Feed <select aria-label="Quote history feed" value={quoteFeed} onChange={e => { setQuoteFeed(e.target.value); setQuotePage(0); }}><option value="indicative">Indicative</option><option value="opra">OPRA</option></select></label>}
      {quotes.some(q => q.quote_timestamp && (q.bid != null || q.ask != null)) && <div className="small-chart" aria-label="Saved bid and ask history"><ResponsiveContainer width="100%" height="100%"><LineChart data={[...quotes].filter(q => q.quote_timestamp).reverse()}><CartesianGrid stroke="#edf0ec"/><XAxis dataKey="quote_timestamp" tickFormatter={value => new Date(value).toLocaleDateString()} tick={{fontSize:10}} minTickGap={40}/><YAxis domain={["auto","auto"]} tick={{fontSize:10}} width={55}/><Tooltip labelFormatter={value => new Date(String(value)).toLocaleString()}/><Line dataKey="bid" name="Bid" stroke="#197b63" dot={false}/><Line dataKey="ask" name="Ask" stroke="#b57a36" dot={false}/></LineChart></ResponsiveContainer></div>}
      {quotes.length === 0 && <p className="research-muted">No saved observations on this page.</p>}
      {quotes.map((q, i) => <div className="history-row" key={i}><span>{q.quote_timestamp ? new Date(q.quote_timestamp).toLocaleString() : "Time unavailable"} - {q.source} / {q.feed} - bid {money(q.bid)} - ask {money(q.ask)} - IV {pct(q.iv)}{q.stale ? " - stale" : ""}</span></div>)}
      <div className="pagination"><button disabled={quotePage === 0} onClick={() => setQuotePage(value => value - 1)}>Previous</button><span>Page {quotePage + 1}</span><button disabled={quotes.length < 100} onClick={() => setQuotePage(value => value + 1)}>Next</button></div>
    </details>
  </div>;
}

export function Watchlist({ revision }: { revision: number }) {
  const [items, setItems] = useState<Item[]>([]);
  const [active, setActive] = useState<number | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    const response = await fetch(`${API}/watchlist`, { signal });
    if (!response.ok) throw new Error("Watchlist unavailable.");
    const data: Item[] = await response.json();
    if (!signal?.aborted) { setItems(data); setActive(current => data.some(i => i.id === current) ? current : null); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => { load(controller.signal).catch(() => { if (!controller.signal.aborted) setError("Watchlist unavailable."); }); }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [load, revision]);
  async function remove(id: number) {
    try {
      const response = await fetch(`${API}/watchlist/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error("Could not remove watchlist item.");
      await load(); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not remove item."); }
  }
  const selected = items.find(item => item.id === active);
  return <section id="watchlist" className="research-section"><div className="section-heading"><h2>Watchlist &amp; scenarios</h2></div><div className="panel research-panel">
    {error && <div className="notice error" role="alert">{error}</div>}
    {!items.length ? <p className="research-muted">Select an option above and add it to your watchlist.</p> : <div className="table-wrap"><table><thead><tr><th>CONTRACT</th><th>EXPIRATION</th><th>LATEST BID / ASK</th><th>QUOTE TIME</th><th>RESEARCH PRIORITY</th><th></th></tr></thead><tbody>{items.map(item => <tr key={item.id}><td><button className="table-select" onClick={() => setActive(item.id)}>{item.ticker} {item.kind} {money(item.strike)}</button></td><td>{item.expiration}</td><td>{item.current_quote ? `${money(item.current_quote.bid)} / ${money(item.current_quote.ask)}` : "Unavailable"}</td><td>{item.current_quote?.quote_timestamp ? new Date(item.current_quote.quote_timestamp).toLocaleString() : "Unavailable"}{item.current_quote?.stale ? " · stale" : ""}</td><td><button className="table-select" onClick={() => remove(item.id)}>Remove</button></td></tr>)}</tbody></table></div>}
    {selected && <ScenarioEditor key={selected.id} item={selected} onUpdated={() => load()}/>}
  </div></section>;
}
