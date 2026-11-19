"""Offline evaluation of the chatbot with the real LLMs against golden questions.

Pemakaian (dari folder backend, butuh kredensial AICORE_* dan DB berisi seed demo):
    python -m scripts.seed --reset --demo-schedules
    python -m scripts.eval_chatbot [--golden tests/chatbot_eval/golden.yaml] [--out report.json]
"""
import argparse
import json
import statistics
import uuid
from pathlib import Path

import yaml

from app.chatbot.service import get_chat_service

METRICS = ("faithfulness", "answer_relevance", "numeric_grounding", "completeness")


def answer_text(final: dict) -> str:
    """All text and table cells of an answer, lower-cased, for fact matching."""
    parts = []
    for b in final.get("blocks", []):
        parts.append(b.get("text") or "")
        for row in b.get("rows", []):
            parts.extend(str(c) for c in row)
    return " ".join(parts).lower()


def evaluate_case(svc, case: dict) -> dict:
    """Runs one golden question in a fresh thread and checks intent, facts and the quality gate."""
    final = svc.run(case["question"], f"eval-{uuid.uuid4().hex[:16]}")
    if final.get("type") != "final":
        return {"question": case["question"], "ok": False, "error": final.get("detail")}
    meta = final["meta"]
    text = answer_text(final)
    missing = [f for f in case.get("expect_contains", []) if f.lower() not in text]
    intent_ok = meta["intent"] == case.get("expect_intent", "mrp_query")
    gate_ok = meta["passed"] is not False
    return {"question": case["question"], "intent": meta["intent"], "score": meta["score"],
            "passed_gate": meta["passed"], "metrics": meta["metrics"], "missing_facts": missing,
            "attempts": meta["attempts"], "tools": [s["tool"] for s in meta["sources"]],
            "ok": intent_ok and gate_ok and not missing}


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluasi chatbot MRP terhadap golden questions")
    ap.add_argument("--golden", default=str(Path(__file__).resolve().parents[1] / "tests/chatbot_eval/golden.yaml"))
    ap.add_argument("--out", default=None, help="tulis laporan JSON ke file ini")
    args = ap.parse_args()

    cases = yaml.safe_load(Path(args.golden).read_text(encoding="utf-8"))
    svc = get_chat_service()
    results = []
    for case in cases:
        r = evaluate_case(svc, case)
        results.append(r)
        flag = "PASS" if r["ok"] else "FAIL"
        score = f"{r['score']:.2f}" if r.get("score") is not None else "  - "
        print(f"[{flag}] {score}  {r['question']}" + (f"  missing={r['missing_facts']}" if r.get("missing_facts") else ""))

    scored = [r for r in results if r.get("metrics")]
    summary = {
        "cases": len(results),
        "ok": sum(r["ok"] for r in results),
        "gate_pass_rate": round(sum(bool(r["passed_gate"]) for r in scored) / len(scored), 3) if scored else None,
        "mean_score": round(statistics.mean(r["score"] for r in scored), 3) if scored else None,
        "mean_metrics": {m: round(statistics.mean(r["metrics"][m] for r in scored), 3) for m in METRICS} if scored else {},
    }
    print(json.dumps(summary, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
