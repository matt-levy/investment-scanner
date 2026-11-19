"use client";

import { useEffect, useState } from "react";
import { API, money, pct, type Option } from "../lib/market";
import { Term } from "./term";
import { definitions } from "../lib/financial-terms";

type Source = { id: number; title: string; url: string; kind: string; published_on: string | null; retrieved_at: string };

export function CandidateExplanation({ option, ticker, referencePrice, priceDate }: { option: Option; ticker: string; referencePrice: number | null; priceDate: string | null }) {
  const [fee, setFee] = useState("");
  const [sources, setSources] = useState<Source[] | null>(null);
  const [sourceRevision, setSourceRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API}/research/${encodeURIComponent(ticker)}/sources`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error(); return response.json(); })
      .then(data => { if (!controller.signal.aborted) setSources(Array.isArray(data) ? data : null); })
      .catch(() => { if (!controller.signal.aborted) setSources(null); });
    return () => controller.abort();
  }, [ticker, sourceRevision]);
  const ask = option.ask != null && Number.isFinite(option.ask) && option.ask > 0 ? option.ask : null;
  const bid = option.bid != null && Number.isFinite(option.bid) && option.bid >= 0 && ask != null && option.bid <= ask ? option.bid : null;
  const spot = referencePrice != null && Number.isFinite(referencePrice) && referencePrice > 0 ? referencePrice : null;
  const validFee = fee.trim() !== "" && Number.isFinite(Number(fee)) && Number(fee) >= 0;
  const fees = validFee ? Number(fee) : null;
  const breakEven = ask == null || fees == null ? null : option.strike + (option.kind === "call" ? 1 : -1) * (ask + fees / 100);
  const priceMove = breakEven != null && spot != null ? breakEven / spot - 1 : null;
  const scenarios = spot == null ? [] : [{label:"10% lower", price:spot * .9}, {label:"Unchanged", price:spot}, {label:"10% higher", price:spot * 1.1}];
  const gap = option.iv_minus_rv;
  return <section className="panel candidate-panel" aria-label="Selected candidate explanation">
    <div className="panel-top"><strong>Understand this candidate</strong><span className="subtle">{ticker} {option.kind} · {option.expiration}</span></div>
    <div className="candidate-body">
      <p>This {option.kind} {option.kind === "call" ? "gains expiration value if the stock finishes above" : "gains expiration value if the stock finishes below"} the {money(option.strike)} <Term label="strike price" definition={definitions.strike}/>. Profit also depends on what you pay.</p>
      <div className="candidate-grid">
        <div><strong>What needs to happen?</strong><p>Reference stock close: {money(spot)} {priceDate ? `on ${priceDate}` : "(date unavailable)"}. This is a prior close and may not match the option quote time.</p><p>Assumed purchase: {ask == null ? "unavailable: no positive ask" : `${money(ask * 100)} for one standard contract`}. {fees == null ? "Enter fees to calculate the expiration break-even and total risk." : <>At expiration, break-even is {breakEven != null && breakEven < 0 ? "not reachable at a nonnegative stock price" : money(breakEven)}{breakEven != null && breakEven >= 0 && priceMove != null ? ` (${priceMove >= 0 ? "+" : ""}${pct(priceMove)} from the reference close)` : ""}; maximum assumed loss is {money(ask == null ? null : ask * 100 + fees)}.</>}</p></div>
        <div><strong>Trading costs and data</strong><p><Term label="Bid" definition={definitions.bid}/> {money(bid)} / <Term label="ask" definition={definitions.ask}/> {money(ask)} · spread {pct(option.spread)}{bid != null && ask != null ? `, or ${money((ask - bid) * 100)} per contract` : " (unavailable)"}. This is the immediate quoted spread, not an additional fee.</p><p>Volume: {option.volume ?? "unavailable"} · <Term label="open interest" definition={definitions.interest}/> {option.open_interest ?? "unavailable"}. Activity does not guarantee a fill.</p><p>Option quote: {option.quote_timestamp ? new Date(option.quote_timestamp).toLocaleString() : "time unavailable"}{option.stale ? " · stale" : ""}. Feed: {option.feed || "not specified"}. {option.feed === "indicative" ? "Indicative prices are estimates and may not be executable." : "Displayed prices are not guaranteed fills."}</p></div>
        <div><strong>Why is it on the screen?</strong><p>{gap == null || !Number.isFinite(gap) ? "The implied-versus-recent volatility comparison is unavailable." : <>Implied volatility is {pct(Math.abs(gap))} {gap < 0 ? "below" : gap > 0 ? "above" : "equal to"} recent realized volatility, expressed as a difference in percentage points.</>} This compares an expectation reflected in option prices with past stock movement; it does not establish mispricing or predict direction.</p><p>Screen score: {option.screen_factors?.score ?? "not available"}. Company outlook, catalysts, and expected return are not included in this score.</p></div>
      </div>
      <div className="candidate-scenarios"><strong>Illustrative expiration outcomes</strong><p>These are examples, not forecasts or probabilities. They assume one standard contract bought at the displayed ask and held to expiration; early sale, exercise and taxes are excluded.</p><label>Total assumed fees per contract ($) <input aria-label="Total assumed fees per contract" type="number" min="0" step="any" value={fee} onChange={e => setFee(e.target.value)}/></label>
        {ask == null || spot == null || fees == null ? <p>Enter nonnegative total fees and select an option with a positive ask and an available stock close to see outcomes.</p> : <div className="table-wrap"><table><thead><tr><th>Example stock price at expiration</th><th>Estimated profit / loss</th></tr></thead><tbody>{scenarios.map(s => <tr key={s.label}><td>{s.label}: {money(s.price)}</td><td>{money((Math.max(option.kind === "call" ? s.price - option.strike : option.strike - s.price, 0) - ask) * 100 - fees)}</td></tr>)}</tbody></table></div>}
        <p>Before expiration, time passing and changes in implied volatility can change the option’s value even if the stock moves as expected. The expiration examples do not model those effects. For a pre-expiration model, add the contract to the watchlist and enter your own assumptions.</p>
      </div>
      <div className="candidate-sources"><strong>Company research · {ticker}</strong><p>Saved sources are documents to review, not automatically identified catalysts or evidence that a price will move.</p>{sources === null ? <p>Research source status unavailable.</p> : sources.length === 0 ? <p>No saved sources. Use “Retrieve sources” in the research section.</p> : <ul>{sources.slice(0, 5).map(source => <li key={source.id}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a> · {source.kind} · published {source.published_on || "date unknown"}</li>)}</ul>}<a href="#research">View research sources</a> <button type="button" className="verify-button" onClick={() => setSourceRevision(value => value + 1)}>Refresh saved sources</button></div>
    </div>
  </section>;
}
