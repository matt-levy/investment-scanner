"use client";

import { useCallback, useEffect, useState } from "react";
import { API } from "../lib/market";

type Source = { id: number; provider: string; kind: string; title: string; url: string; published_on: string | null; retrieved_at: string; coverage: string; content: string };
type Citation = { source_id: number; quote: string };
type Statement = { text: string; citations: Citation[] };
type Scenario = { outcome: Statement; evidence_against: Statement[] };
type ReportBody = { market_view: Statement[]; catalysts: Statement[]; bullish: Scenario | null; neutral: Scenario | null; bearish: Scenario | null; reasons_correctly_priced: Statement[]; open_questions: string[] };
type Report = { id: number; created_at: string; model: string; report: ReportBody };
type Status = { sec_configured: boolean; news_configured: boolean; llm_configured: boolean };

function Statements({ items, sources }: { items: Statement[]; sources: Source[] }) {
  if (!items.length) return <p className="research-muted">Insufficient cited evidence.</p>;
  return <ul>{items.map((item, index) => <li key={index}><span>{item.text}</span>{item.citations.map((citation, i) => {
    const source = sources.find(s => s.id === citation.source_id);
    return <details key={i} className="citation"><summary>Source {citation.source_id}</summary>{source ? <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a> : <span>Source details unavailable</span>}<blockquote>{citation.quote}</blockquote></details>;
  })}</li>)}</ul>;
}

function ScenarioView({ name, scenario, sources }: { name: string; scenario: Scenario | null; sources: Source[] }) {
  return <div><h4>{name}</h4>{scenario ? <><Statements items={[scenario.outcome]} sources={sources}/>{scenario.evidence_against.length > 0 && <><h5>Evidence against</h5><Statements items={scenario.evidence_against} sources={sources}/></>}</> : <p className="research-muted">Insufficient cited evidence.</p>}</div>;
}

export function Research({ ticker }: { ticker: string }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [reports, setReports] = useState<Report[]>([]);
  const [status, setStatus] = useState<Status | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    const responses = await Promise.all([
      fetch(`${API}/research/${ticker}/sources`, { signal }),
      fetch(`${API}/research/${ticker}/reports`, { signal }),
      fetch(`${API}/research/status`, { signal }),
    ]);
    if (responses.some(r => !r.ok)) throw new Error("Research data could not be loaded.");
    const [sourceData, reportData, statusData] = await Promise.all(responses.map(r => r.json()));
    if (signal?.aborted) return;
    setSources(sourceData); setReports(reportData); setStatus(statusData);
    setSelected(previous => previous.filter(id => sourceData.some((source: Source) => source.id === id)));
  }, [ticker]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => {
      load(controller.signal).catch(() => { if (!controller.signal.aborted) setError("Research data could not be loaded."); });
    }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [load]);

  async function refresh() {
    setBusy("sources"); setError(""); setMessage("");
    try {
      const response = await fetch(`${API}/research/${ticker}/sources/refresh`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Source retrieval failed.");
      await load();
      const errors = Object.entries(data.errors as Record<string, string>).map(([provider, text]) => `${provider}: ${text}`);
      setMessage([`Added ${data.new_sources} sources.`, ...errors].join(" "));
    } catch (e) { setError(e instanceof Error ? e.message : "Source retrieval failed."); }
    finally { setBusy(""); }
  }

  async function generate() {
    setBusy("report"); setError(""); setMessage("");
    try {
      const response = await fetch(`${API}/research/${ticker}/reports`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_ids: selected }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Report generation failed.");
      await load();
      setMessage("Report saved.");
    } catch (e) { setError(e instanceof Error ? e.message : "Report generation failed."); }
    finally { setBusy(""); }
  }

  const latest = reports[0];
  const allSelected = sources.length > 0 && sources.every(source => selected.includes(source.id));
  return <section id="research" className="research-section">
    <div className="section-heading"><div><h2>Research sources · {ticker}</h2></div><button type="button" className="primary" onClick={refresh} disabled={!!busy}>{busy === "sources" ? "Retrieving..." : "Retrieve sources"}</button></div>
    {message && <div className="notice" role="status">{message}</div>}
    {error && <div className="notice error" role="alert">{error}</div>}
    <div className="panel research-panel">
      <div className="panel-top"><strong>Sources</strong><div className="source-controls"><span className="subtle">{sources.length} saved</span><button type="button" className="verify-button select-sources" disabled={!sources.length} onClick={() => setSelected(allSelected ? [] : sources.map(source => source.id))}>{allSelected ? "Deselect all" : "Select all"}</button></div></div>
      {status && !status.sec_configured && <p className="research-muted">SEC filings: configure SEC_USER_AGENT with a name and contact email.</p>}
      {status && !status.news_configured && <p className="research-muted">News: configure Alpaca credentials.</p>}
      {sources.length === 0 ? <p className="research-muted">No sources retrieved.</p> : <div className="source-list">{sources.map(source => <div className="source-item" key={source.id}>
        <label><input type="checkbox" checked={selected.includes(source.id)} onChange={e => setSelected(current => e.target.checked ? [...current, source.id] : current.filter(id => id !== source.id))}/> <span>{source.kind} · {source.published_on || "Date unknown"}</span></label>
        <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a>
        <span className="subtle">{source.provider} · {source.coverage.replaceAll("_", " ")} · retrieved {new Date(source.retrieved_at).toLocaleString()}</span>
        <details><summary>View saved text</summary><p className="source-text">{source.content}</p></details>
      </div>)}</div>}
      <div className="research-actions"><button className="primary" type="button" disabled={!!busy || !selected.length || selected.length > 8 || !status?.llm_configured} onClick={generate}>{busy === "report" ? "Generating..." : "Generate research report"}</button><span className="subtle">{selected.length} sources selected</span></div>
      {selected.length > 8 && status?.llm_configured && <p className="research-muted">Select up to 8 sources to generate an AI report.</p>}
      {status && !status.llm_configured && <p className="research-muted">Report generation: configure an LLM endpoint and model. Selected excerpts will be sent to that provider.</p>}
    </div>
    <div className="panel research-panel"><div className="panel-top"><strong>AI research report</strong><span className="subtle">{latest ? `${new Date(latest.created_at).toLocaleString()} · ${latest.model}` : "No reports"}</span></div>
      {latest && <div className="report-body"><p className="research-muted">AI-generated interpretations and hypotheses. Source quotes are checked; conclusions require review. No event probabilities are estimated.</p>
        <h3>Apparent market view</h3><Statements items={latest.report.market_view} sources={sources}/>
        <h3>Possible catalysts</h3><Statements items={latest.report.catalysts} sources={sources}/>
        <h3>Scenarios</h3><div className="scenario-grid"><ScenarioView name="Bullish" scenario={latest.report.bullish} sources={sources}/><ScenarioView name="Neutral" scenario={latest.report.neutral} sources={sources}/><ScenarioView name="Bearish" scenario={latest.report.bearish} sources={sources}/></div>
        <h3>Reasons it could be correctly priced</h3><Statements items={latest.report.reasons_correctly_priced} sources={sources}/>
        <h3>Open questions</h3><ul>{latest.report.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul>
      </div>}
    </div>
  </section>;
}
