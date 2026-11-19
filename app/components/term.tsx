"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import "./term.css";

type TermProps = {
  label: string;
  definition: string;
  accessibleLabel?: string;
};

export function Term({ label, definition, accessibleLabel }: TermProps) {
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0, above: false });

  const positionTooltip = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const rect = trigger.getBoundingClientRect();
    const width = Math.min(280, window.innerWidth - 24);
    const height = tooltipRef.current?.offsetHeight ?? 120;
    const above = rect.top >= height + 12;
    setPosition({
      left: Math.max(12, Math.min(rect.left + rect.width / 2 - width / 2, window.innerWidth - width - 12)),
      top: above ? rect.top - 8 : rect.bottom + 8,
      above,
    });
  }, []);

  useEffect(() => {
    if (!open) return;
    const reposition = () => positionTooltip();
    const dismiss = (event: PointerEvent) => {
      if (!triggerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("resize", reposition);
      window.removeEventListener("scroll", reposition, true);
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", escape);
    };
  }, [open, positionTooltip]);

  function show() {
    positionTooltip();
    setOpen(true);
  }

  return <span className="term" onMouseEnter={show} onMouseLeave={() => {
    if (document.activeElement !== triggerRef.current) setOpen(false);
  }}>
    {label}
    <button
      ref={triggerRef}
      type="button"
      className="term-trigger"
      aria-label={`About ${accessibleLabel || label}`}
      aria-describedby={open ? id : undefined}
      onFocus={show}
      onBlur={() => setOpen(false)}
      onClick={event => { event.stopPropagation(); show(); }}
    >?</button>
    {open && createPortal(
      <span ref={tooltipRef} id={id} role="tooltip" className="term-tooltip"
        style={{ left: position.left, top: position.top, transform: position.above ? "translateY(-100%)" : undefined }}>
        {definition}
      </span>, document.body
    )}
  </span>;
}
