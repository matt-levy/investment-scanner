export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export type Option = { symbol: string; expiration: string; kind: string; strike: number; date: string; bid: number | null; ask: number | null; iv: number | null; volume: number | null; open_interest: number | null; spread: number | null; ticker?: string; iv_minus_rv?: number; source?: string; feed?: string; quote_timestamp?: string | null; retrieved_at?: string; stale?: boolean; warning?: string | null; delta?: number | null; gamma?: number | null; theta?: number | null; vega?: number | null; screen_factors?: { score: number | null; volatility_factor: number | null; spread_factor: number | null; completeness_factor: number; note: string } };
export type Detail = { ticker: string; prices: { date: string; close: number }[]; realized_volatility: number | null; last_ingestion: { status: string; message: string; started_at: string } | null };
export type Health = { status: string; provider_configured: boolean; provider: string };
export type Verification = { primary: Option; secondary: Option; timestamp_difference_seconds: number | null; differences_secondary_minus_primary: Record<string, number | null>; significant_discrepancy: boolean; warnings: string[] };
export const pct = (x: number | null | undefined) => x == null ? "—" : `${(x * 100).toFixed(1)}%`;
export const money = (x: number | null | undefined) => x == null ? "—" : `$${x.toFixed(2)}`;

