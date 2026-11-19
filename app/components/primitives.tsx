import type { ReactNode } from "react";
import { Term } from "./term";

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`panel ${className}`}>{children}</div>;
}

export function Metric({ label, definition, value, detail }: { label: string; definition: string; value: ReactNode; detail: string }) {
  return <div className="metric"><Term label={label} definition={definition}/><strong>{value}</strong><p>{detail}</p></div>;
}
