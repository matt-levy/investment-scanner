"""Transparent screening indicators; not a valuation or forecast."""
from math import isfinite

def screen_factors(quote: dict, realized_volatility: float) -> dict:
    iv, spread = quote.get("iv"), quote.get("spread")
    gap = max(0.0, min(1.0, (realized_volatility - iv) / realized_volatility)) * 100 if realized_volatility > 0 and iv is not None and isfinite(iv) else None
    spread_quality = max(0.0, min(1.0, 1 - spread / 0.5)) * 100 if spread is not None and isfinite(spread) else None
    fields = ("bid", "ask", "iv", "quote_timestamp", "volume", "open_interest")
    known = sum(quote.get(key) is not None for key in fields)
    completeness = 100 * (known + (not quote.get("stale", True))) / 7
    score = round(0.4 * gap + 0.4 * spread_quality + 0.2 * completeness, 1) if gap is not None and spread_quality is not None else None
    return {
        "score": score,
        "volatility_factor": round(gap, 1) if gap is not None else None,
        "spread_factor": round(spread_quality, 1) if spread_quality is not None else None,
        "completeness_factor": round(completeness, 1),
        "weights": {"volatility": 0.4, "spread": 0.4, "completeness": 0.2},
        "research_evidence": "not assessed",
        "catalyst_relevance": "not assessed",
        "expected_value": "not assessed",
        "note": "Heuristic screening priority, not evidence of mispricing or investment quality. Indicative quotes are not executable.",
    }

def watchlist_priority(quantitative: float | None, expected_value: float | None, capital_at_risk: float | None, catalyst: str, evidence: str, fresh: bool) -> dict:
    """Only rank complete, current assessments; user judgments are not verified."""
    labels = {"low": 0, "medium": 50, "high": 100}
    quality = {"weak": 0, "mixed": 50, "strong": 100}
    ev_factor = None if expected_value is None or not capital_at_risk or capital_at_risk <= 0 else max(0.0, min(100.0, 50.0 + 50.0 * expected_value / capital_at_risk))
    catalyst_factor = labels.get(catalyst)
    evidence_factor = quality.get(evidence)
    components = (quantitative, ev_factor, catalyst_factor, evidence_factor)
    complete = all(value is not None for value in components)
    score = round(.5 * quantitative + .2 * ev_factor + .15 * catalyst_factor + .15 * evidence_factor, 1) if complete and fresh else None
    return {"score": score, "quantitative": quantitative, "expected_value_factor": round(ev_factor, 1) if ev_factor is not None else None,
            "catalyst_factor": catalyst_factor, "evidence_factor": evidence_factor, "fresh": fresh,
            "weights": {"quantitative": .5, "expected_value": .2, "catalyst": .15, "evidence": .15},
            "note": "User-supplied assumptions and judgments; neither expected value nor a score establishes mispricing."}
