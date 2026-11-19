"""Deterministic grounding checks and the weighted quality gate."""
import re
from collections import Counter
from dataclasses import dataclass

from app.chatbot.evidence import Evidence

_IGNORED_TOKENS = [
    r"\b[A-Z]{2,}(?:-[A-Z0-9]+)+\b",          # SKUs / codes: RM-PDL-01, PO-2026-0001, BATCH-...
    r"\b\d{4}-\d{2}-\d{2}(?:[T ][\d:.]+)?\b",  # ISO dates / timestamps
    r"\bE\d+\b",                               # evidence ids
]
_NUMBER = re.compile(r"(?<![\w.,])[-−]?\d[\d.,]*(?![\w])")
_TOL = 1e-6


def _candidates(token: str) -> set[float]:
    """All plausible values of a number written in Indonesian or English notation."""
    token = token.replace("−", "-").rstrip(".,")
    out = set()
    variants = {token.replace(",", ""), token.replace(".", "").replace(",", ".")}
    if re.fullmatch(r"-?\d+", token):
        variants.add(token)
    for v in variants:
        try:
            out.add(float(v))
        except ValueError:
            continue
    return out


def extract_numbers(text: str) -> list[str]:
    """Numeric tokens in prose, ignoring codes, dates and evidence ids."""
    for pattern in _IGNORED_TOKENS:
        text = re.sub(pattern, " ", text)
    return [m.group(0) for m in _NUMBER.finditer(text)]


def evidence_numbers(evidence: list[Evidence]) -> set[float]:
    """Numbers an answer may legitimately state: cell values, row counts, column sums,
    category counts, distinct counts, and numeric metadata."""
    values: set[float] = set()

    def add(v):
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            values.add(float(v))
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
        elif isinstance(v, list):
            for x in v:
                add(x)

    for ev in evidence:
        values.add(float(ev["row_count"]))
        values.add(float(len(ev["rows"])))
        add(ev["meta"])
        for col in ev["columns"]:
            col_vals = [r.get(col) for r in ev["rows"]]
            nums = [v for v in col_vals if isinstance(v, (int, float)) and not isinstance(v, bool)]
            for v in nums:
                values.add(float(v))
            if nums:
                values.add(float(sum(nums)))
            hashable = [v for v in col_vals if isinstance(v, (str, bool)) or v is None]
            for count in Counter(hashable).values():
                values.add(float(count))
            values.add(float(len({str(v) for v in col_vals})))
    return values


def numeric_grounding(text: str, evidence: list[Evidence], question: str = "") -> tuple[float, list[str]]:
    """Fraction of numbers in `text` that match evidence (or the question). Returns (score, ungrounded)."""
    tokens = extract_numbers(text)
    if not tokens:
        return 1.0, []
    allowed = evidence_numbers(evidence)
    for tok in extract_numbers(question):
        allowed |= _candidates(tok)
    ungrounded = []
    for tok in tokens:
        cands = _candidates(tok)
        if not any(abs(c - a) <= _TOL * max(1.0, abs(a)) for c in cands for a in allowed):
            ungrounded.append(tok)
    return 1 - len(ungrounded) / len(tokens), ungrounded


@dataclass(frozen=True)
class GateResult:
    """Outcome of the weighted quality gate."""
    score: float
    passed: bool
    metrics: dict[str, float]


def apply_gate(metrics: dict[str, float], weights: dict[str, float], threshold: float,
               faithfulness_floor: float) -> GateResult:
    """Weighted mean of metrics; passes only if >= threshold AND faithfulness >= floor."""
    total = sum(weights.values())
    score = sum(metrics[k] * w for k, w in weights.items()) / total
    # The floor stops a fluent, relevant answer from passing while still hallucinating.
    passed = score >= threshold and metrics["faithfulness"] >= faithfulness_floor
    return GateResult(score=round(score, 4), passed=passed,
                      metrics={k: round(v, 4) for k, v in metrics.items()})
