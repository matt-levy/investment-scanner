"use client";

import { useCallback, useEffect, useState } from "react";
import { API } from "../lib/market";

type Source = { id: number; title: string; url: string; kind: string; published_on: string | null };
type Inputs = { catalyst_relevance: "unknown" | "low" | "medium" | "high"; evidence_quality: "unknown" | "weak" | "mixed" | "strong"; notes: string; source_ids: number[] };
type Assessment = { id: number; created_at: string; inputs: Inputs };

export function AssessmentEditor({ itemId, ticker, onUpdated }: { itemId: number; ticker: string; onUpdated: () => Promise<void> }) {
  const [sources, setSources] = useState<Source[]>([]);
  const [history, setHistory] = useState<Assessment[]>([]);
  const [inputs, setInputs] = useState<Inputs>({ catalyst_relevance: "unknown", evidence_quality: "unknown", notes: "", source_ids: [] });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    const responses = await Promise.all([fetch(`${API}/research/${ticker}/sources`, { signal }), fetch(`${API}/watchlist/${itemId}/assessments`, { signal })]);
    if (responses.some(response => !response.ok)) throw new Error("Research sources or assessment history unavailable.");
    const [docs, saved] = await Promise.all(responses.map(response => response.json()));
    if (!signal?.aborted) {
      setSources(docs); setHistory(saved);
      if (saved.length) setInputs(saved[0].inputs);
    }
  }, [itemId, ticker]);
  useEffect(() => {
    const controller = new AbortController();
    const timer = setTimeout(() => { load(controller.signal).catch(() => { if (!controller.signal.aborted) setMessage("Research sources or assessment history unavailable."); }); }, 0);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [load]);
  async function save() {
    setBusy(true); setMessage("");
    try {
      const response = await fetch(`${API}/watchlist/${itemId}/assessments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(inputs) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Select at least one source for an assessed factor.");
      await Promise.all([load(), onUpdated()]);
      setMessage("Assessment saved.");
    } catch (e) { setMessage(e instanceof Error ? e.message : "Assessment could not be saved."); }
    finally { setBusy(false); }
  }
  return <details className="history-details"><summary>Research assessment · your judgment</summary>
    <p className="research-muted">Choose your own ratings and the sources you reviewed. These ratings are subjective and do not verify a thesis. Select at least one source for a rating.</p>
    <div className="assumption-fields"><label>Catalyst relevance<select aria-label="Catalyst relevance" value={inputs.catalyst_relevance} onChange={e => setInputs(x => ({ ...x, catalyst_relevance: e.target.value as Inputs["catalyst_relevance"] }))}><option value="unknown">Unknown</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label><label>Evidence quality<select aria-label="Evidence quality" value={inputs.evidence_quality} onChange={e => setInputs(x => ({ ...x, evidence_quality: e.target.value as Inputs["evidence_quality"] }))}><option value="unknown">Unknown</option><option value="weak">Weak</option><option value="mixed">Mixed</option><option value="strong">Strong</option></select></label></div>
    <label className="assessment-notes">Your notes<textarea aria-label="Assessment notes" maxLength={2000} value={inputs.notes} onChange={e => setInputs(x => ({ ...x, notes: e.target.value }))}/></label>
    <p>Sources reviewed:</p>{sources.length ? <div className="assessment-sources">{sources.slice(0, 100).map(source => <label key={source.id}><input type="checkbox" checked={inputs.source_ids.includes(source.id)} disabled={!inputs.source_ids.includes(source.id) && inputs.source_ids.length >= 20} onChange={e => setInputs(x => ({ ...x, source_ids: e.target.checked ? [...x.source_ids, source.id] : x.source_ids.filter(id => id !== source.id) }))}/> {source.kind} · {source.published_on || "Date unknown"} · <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></label>)}</div> : <p className="research-muted">Retrieve sources in the research section first.</p>}
    <button type="button" className="verify-button" onClick={save} disabled={busy}>{busy ? "Saving..." : "Save assessment"}</button>{message && <p role="status" className="research-muted">{message}</p>}
    <details><summary>Earlier assessments ({history.length})</summary>{history.map(record => <p className="research-muted" key={record.id}>{new Date(record.created_at).toLocaleString()} · Catalyst: {record.inputs.catalyst_relevance} · Evidence: {record.inputs.evidence_quality} · Sources: {record.inputs.source_ids.join(", ") || "none"}{record.inputs.notes && <> · {record.inputs.notes}</>}</p>)}</details>
  </details>;
}
