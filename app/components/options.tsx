"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Term } from "./term";
import { definitions } from "../lib/financial-terms";
import { money, pct, type Option } from "../lib/market";

const PAGE_SIZE = 25;

export function OptionsChain({ ticker, chain, selected, onSelect }: {
  ticker: string; chain: Option[]; selected: Option | null; onSelect: (option: Option) => void;
}) {
  const [expiration, setExpiration] = useState("");
  const [kind, setKind] = useState("");
  const [minStrike, setMinStrike] = useState("");
  const [maxStrike, setMaxStrike] = useState("");
  const [page, setPage] = useState(0);
  const expirations = useMemo(() => [...new Set(chain.map(row => row.expiration))].sort(), [chain]);
  const visible = useMemo(() => chain.filter(row =>
    (!expiration || row.expiration === expiration) &&
    (!kind || row.kind === kind) &&
    (minStrike === "" || row.strike >= Number(minStrike)) &&
    (maxStrike === "" || row.strike <= Number(maxStrike))
  ), [chain, expiration, kind, minStrike, maxStrike]);
  const lastPage = Math.max(0, Math.ceil(visible.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  const chartExpiry = expiration || expirations[0];
  const ivData = useMemo(() => {
    const byStrike = new Map<number, { strike: number; call?: number; put?: number }>();
    for (const row of chain) {
      if (row.expiration !== chartExpiry || row.iv == null || !Number.isFinite(row.iv) || !["call", "put"].includes(row.kind)) continue;
      const point = byStrike.get(row.strike) || { strike: row.strike };
      point[row.kind as "call" | "put"] = row.iv * 100;
      byStrike.set(row.strike, point);
    }
    return [...byStrike.values()].sort((a, b) => a.strike - b.strike);
  }, [chain, chartExpiry]);
  function change(set: (value: string) => void, value: string) { set(value); setPage(0); }
  return <div className="panel table-panel">
    <div className="panel-top"><Term label={`${ticker} options chain`} definition={definitions.chain}/><span className="subtle">{visible.length} of {chain.length} contracts</span></div>
    <div className="chain-filters">
      <label>Expiration<select aria-label="Filter expiration" value={expiration} onChange={e => change(setExpiration, e.target.value)}><option value="">All dates</option>{expirations.map(date => <option key={date} value={date}>{date}</option>)}</select></label>
      <label>Type<select aria-label="Filter option type" value={kind} onChange={e => change(setKind, e.target.value)}><option value="">Calls and puts</option><option value="call">Call</option><option value="put">Put</option></select></label>
      <label>Min strike<input aria-label="Minimum strike" type="number" min="0" value={minStrike} onChange={e => change(setMinStrike, e.target.value)}/></label>
      <label>Max strike<input aria-label="Maximum strike" type="number" min="0" value={maxStrike} onChange={e => change(setMaxStrike, e.target.value)}/></label>
    </div>
    <div className="table-wrap chain"><table><thead><tr><th><Term label="EXPIRY" definition={definitions.expiration}/></th><th><Term label="TYPE" definition={definitions.type}/></th><th><Term label="STRIKE" definition={definitions.strike}/></th><th><Term label="BID" definition={definitions.bid}/></th><th><Term label="ASK" definition={definitions.ask}/></th><th><Term label="IV" definition={definitions.iv}/></th><th>QUOTE TIME</th></tr></thead><tbody>{visible.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE).map(row => <tr key={row.symbol} className={selected?.symbol === row.symbol ? "selected" : ""}><td>{row.expiration}</td><td><button className="table-select" onClick={() => onSelect(row)}>{row.kind}</button></td><td>{money(row.strike)}</td><td>{money(row.bid)}</td><td>{money(row.ask)}</td><td>{pct(row.iv)}</td><td>{row.quote_timestamp ? new Date(row.quote_timestamp).toLocaleString() : row.date || "Unknown"}{row.stale ? " - STALE" : ""}</td></tr>)}</tbody></table>{!visible.length && <div className="empty compact">No options match these filters.</div>}</div>
    <div className="pagination"><button disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button><span>Page {currentPage + 1} of {lastPage + 1}</span><button disabled={currentPage >= lastPage} onClick={() => setPage(currentPage + 1)}>Next</button></div>
    <div className="panel-top"><div><Term label="Implied volatility by strike" definition={definitions.iv}/><p className="subtle">Expiration: {chartExpiry || "Unavailable"} · provider estimates, not forecasts</p></div></div>
    {ivData.length ? <div className="chart small-chart" aria-label="Implied volatility by strike"><ResponsiveContainer width="100%" height="100%"><LineChart data={ivData}><CartesianGrid stroke="#edf0ec"/><XAxis dataKey="strike" type="number" domain={["dataMin", "dataMax"]} tick={{fontSize:10}}/><YAxis unit="%" tick={{fontSize:10}} width={50}/><Tooltip formatter={value => typeof value === "number" ? `${value.toFixed(1)}%` : "-"} labelFormatter={value => `Strike $${value}`}/><Line dataKey="call" name="Call IV" stroke="#197b63" dot={false} connectNulls={false}/><Line dataKey="put" name="Put IV" stroke="#b57a36" dot={false} connectNulls={false}/></LineChart></ResponsiveContainer></div> : <div className="chart-empty">No implied volatility available for this expiration.</div>}
  </div>;
}

export function PayoffChart({ option, target }: { option: Option; target: number }) {
  if (option.ask == null || !Number.isFinite(option.ask) || option.ask <= 0) return <p className="micro chart-message">A positive ask is needed for the payoff chart.</p>;
  const premium = option.ask;
  const maxPrice = Math.max(option.strike * 2, target * 1.2, 1);
  const data = Array.from({ length: 51 }, (_, i) => {
    const price = maxPrice * i / 50;
    const intrinsic = Math.max(option.kind === "call" ? price - option.strike : option.strike - price, 0);
    return { price: Math.round(price * 100) / 100, profit: (intrinsic - premium) * 100 };
  });
  return <div className="payoff-chart"><p className="subtle">Hypothetical expiration profit/loss · one contract</p><div className="small-chart" aria-label="Hypothetical expiration payoff chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={data}><CartesianGrid stroke="#edf0ec"/><XAxis dataKey="price" type="number" domain={["dataMin","dataMax"]} tick={{fontSize:10}}/><YAxis tick={{fontSize:10}} width={55}/><Tooltip formatter={value => typeof value === "number" ? money(value) : "-"} labelFormatter={value => `Underlying: $${value}`}/><ReferenceLine y={0} stroke="#a1ada5"/><Line dataKey="profit" name="Profit/loss" stroke="#197b63" dot={false}/></LineChart></ResponsiveContainer></div></div>;
}
