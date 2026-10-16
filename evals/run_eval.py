"""Run the golden set against a model and score the answers with an LLM judge.

Context mode is "oracle": each question gets the passages of its gold documents (or, for
no_answer questions, the near-miss documents in related_doc_ids). Retrieval is deliberately
left out so that runs compare answer generation only; retrieval gets its own metrics later.

Usage:
  python evals/run_eval.py --backend ollama --model qwen3:8b
  python evals/run_eval.py --backend openai --model gpt-5-mini --price-in 0.25 --price-out 2.0
  python evals/run_eval.py ... --limit 3            # quick smoke test
  python evals/run_eval.py --rejudge evals/results/<run>.jsonl   # re-score saved answers

Results: evals/results/<timestamp>_<model>.jsonl (one row per question) and a
<same name>.summary.json with the aggregate numbers.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from openai import OpenAI

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RESULTS_DIR = ROOT / "evals" / "results"
DEFAULT_GOLDEN = ROOT / "evals" / "golden_v1.jsonl"

MAX_DOC_CHARS = 6000   # documents up to this size are passed whole
WINDOW_CHARS = 2000    # otherwise: this much context on each side of every evidence quote
NO_ANSWER_TEXT = "Dokümanlarda bu bilgi yok."

SYSTEM_PROMPTS = {
    # v1: first version. Qwen3 8B said "no answer" on 5/24 answerable questions with it.
    "v1": (
        "Sen Türkçe finans dokümanlarına dayanarak soru cevaplayan bir asistansın. "
        "Yalnızca verilen dokümanlardaki bilgiyi kullan, kendi bilgini ekleme. "
        f"Cevap dokümanlarda yoksa sadece \"{NO_ANSWER_TEXT}\" yaz. "
        "Cevabı kısa ve net ver; sayıları ve tarihleri dokümandaki gibi yaz."
    ),
    # v2: explicitly allows answers derived from the documents (sums, dates to periods,
    # combining two documents) and asks for a one-sentence justification.
    "v2": (
        "Sen Türkçe finans dokümanlarına dayanarak soru cevaplayan bir asistansın. "
        "Yalnızca verilen dokümanlardaki bilgiyi kullan, kendi bilgini ekleme. "
        "Cevap dokümanlardaki bilgilerden hesaplanabiliyor ya da çıkarılabiliyorsa "
        "(toplama, tarihten dönem çıkarma, iki dokümanı birleştirme), cevabı ver ve nasıl bulduğunu bir cümleyle yaz. "
        f"Cevap dokümanlarda yoksa ve onlardan çıkarılamıyorsa sadece \"{NO_ANSWER_TEXT}\" yaz. "
        "Cevabı kısa ve net ver; sayıları ve tarihleri dokümandaki gibi yaz."
    ),
}
SYSTEM_PROMPT = SYSTEM_PROMPTS["v1"]

# gpt-5-mini agreed with hand labels on 21/21 test gradings, gpt-5-nano on 18/21
# (nano missed rating notches such as "BB-" vs "BB"); see evals/README.md.
DEFAULT_JUDGE = "gpt-5-mini"

JUDGE_PROMPT = """You grade one answer from a question-answering system over Turkish finance documents.

Question: {question}
Reference answer: {gold}
System answer: {answer}

Grade only the facts the QUESTION asks for. The reference may contain extra context (e.g. outlook, capacity, legal article numbers); missing extra context is fine.
1. Write down the value(s) the question asks for, copied exactly from the reference (e.g. "BB-" and "BB" are different ratings).
2. Copy what the system answer gives for each of them, exactly.
3. Verdict:
- "correct": every asked-for value matches.
- "partial": some asked-for values match, others are missing; none is wrong.
- "incorrect": any asked-for value is wrong or contradicted, or the system says the information is not available.

Return JSON: {{"asked": [{{"reference": "...", "system": "...", "status": "match|missing|wrong"}}], "verdict": "correct|partial|incorrect", "reason": "<one short sentence>"}}"""

NO_ANSWER_JUDGE_PROMPT = """The documents given to a question-answering system do NOT contain the answer to this question.

Question: {question}
Why there is no answer: {gold}
System answer: {answer}

Verdict:
- "correct": the system says the information is not available in the documents (it may add related facts that are true).
- "incorrect": the system presents a specific answer to the question (a number, name, date, yes/no) as fact.

Return JSON: {{"verdict": "correct|incorrect", "reason": "<one short sentence>"}}"""

SCORES = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

# USD per 1M tokens (input, output), standard tier, checked 2026-10-16.
JUDGE_PRICES = {"gpt-5-mini": (0.25, 2.00), "gpt-5-nano": (0.05, 0.40)}


def risk_points(row: dict) -> float:
    """Risk-adjusted points: in finance a wrong answer is worse than no answer.

    correct +1, partial +0.5, saying "no answer" when there is one 0, any wrong or made-up answer -1.
    """
    if row["verdict"] == "correct":
        return 1.0
    if row["verdict"] == "partial":
        return 0.5
    if row["category"] != "no_answer" and abstains(row["answer"]):
        return 0.0
    return -1.0


# ---------------------------------------------------------------- helpers

def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"'))


def load_doc(doc_id: str) -> dict:
    source = doc_id.split("-", 1)[0]
    return json.loads((RAW_DIR / source / f"{doc_id}.json").read_text(encoding="utf-8"))


def passages(doc: dict, quotes: list[str]) -> str:
    """Whole text for short documents; merged windows around the evidence quotes for long ones."""
    text = doc["text"]
    if len(text) <= MAX_DOC_CHARS:
        return text
    spans = []
    flat = re.sub(r"\s+", " ", text)
    for quote in quotes:
        i = flat.find(re.sub(r"\s+", " ", quote).strip())
        if i >= 0:
            spans.append((max(0, i - WINDOW_CHARS), min(len(flat), i + len(quote) + WINDOW_CHARS)))
    if not spans:
        return text[:MAX_DOC_CHARS]
    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return "\n[...]\n".join(flat[s:e] for s, e in merged)


def build_context(q: dict) -> str:
    doc_ids = q["doc_ids"] or q["related_doc_ids"]
    blocks = []
    for doc_id in doc_ids:
        doc = load_doc(doc_id)
        quotes = [e["quote"] for e in q["evidence"] if e["doc_id"] == doc_id]
        blocks.append(f"### Doküman {doc_id}: {doc['title']} ({doc['date']})\n{passages(doc, quotes)}")
    return "\n\n".join(blocks) if blocks else "(Bu soru için doküman bulunamadı.)"


def user_prompt(q: dict) -> str:
    return f"Dokümanlar:\n\n{build_context(q)}\n\nSoru: {q['question']}"


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "unknown"


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


# ---------------------------------------------------------------- backends

def ask_ollama(args, messages: list[dict]) -> dict:
    """Native Ollama API: lets us set num_ctx and think, and returns exact token counts."""
    body = {
        "model": args.model, "messages": messages, "stream": False, "think": args.think,
        "options": {"num_ctx": args.num_ctx, "temperature": 0},
    }
    start = time.perf_counter()
    r = requests.post(f"{args.ollama_url}/api/chat", json=body, timeout=600)
    r.raise_for_status()
    latency = time.perf_counter() - start
    data = r.json()
    return {
        "answer": data["message"]["content"].strip(),
        "thinking": data["message"].get("thinking") or None,
        "latency_s": latency,
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "completion_tokens": data.get("eval_count", 0),
        "gen_tok_per_s": data["eval_count"] / (data["eval_duration"] / 1e9) if data.get("eval_duration") else None,
    }


def ask_openai(args, client: OpenAI, messages: list[dict]) -> dict:
    kwargs = {"model": args.model, "messages": messages}
    if args.reasoning_effort:
        kwargs["reasoning_effort"] = args.reasoning_effort
    start = time.perf_counter()
    resp = client.chat.completions.create(**kwargs)
    latency = time.perf_counter() - start
    details = resp.usage.completion_tokens_details
    return {
        "answer": (resp.choices[0].message.content or "").strip(),
        "thinking": None,  # OpenAI does not return reasoning text, only its token count
        "reasoning_tokens": getattr(details, "reasoning_tokens", None) if details else None,
        "latency_s": latency,
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
        "gen_tok_per_s": None,
    }


def abstains(answer: str) -> bool:
    return NO_ANSWER_TEXT.lower().rstrip(".") in answer.lower()


def judge(client: OpenAI, judge_model: str, q: dict, answer: str) -> dict:
    # Exact abstentions are graded by rule: right for no_answer questions, wrong otherwise.
    if abstains(answer):
        verdict = "correct" if q["category"] == "no_answer" else "incorrect"
        return {"verdict": verdict, "reason": "abstained (rule)", "judge_details": None,
                "judge_prompt_tokens": 0, "judge_completion_tokens": 0}
    template = NO_ANSWER_JUDGE_PROMPT if q["category"] == "no_answer" else JUDGE_PROMPT
    resp = client.chat.completions.create(
        model=judge_model,
        messages=[{"role": "user", "content": template.format(question=q["question"], gold=q["answer"], answer=answer)}],
        response_format={"type": "json_object"},
        reasoning_effort="low",
    )
    try:
        out = json.loads(resp.choices[0].message.content)
        verdict = out.get("verdict") if out.get("verdict") in SCORES else "incorrect"
        reason, details = out.get("reason", ""), out.get("asked")
    except json.JSONDecodeError:
        verdict, reason, details = "incorrect", "judge returned invalid JSON", None
    return {"verdict": verdict, "reason": reason, "judge_details": details,
            "judge_prompt_tokens": resp.usage.prompt_tokens,
            "judge_completion_tokens": resp.usage.completion_tokens}


# ---------------------------------------------------------------- summary

def summarize(rows: list[dict], meta: dict) -> dict:
    def block(rs: list[dict]) -> dict:
        lat = [r["latency_s"] for r in rs]
        return {
            "n": len(rs),
            "score": round(sum(SCORES[r["verdict"]] for r in rs) / len(rs), 3) if rs else None,
            "risk_score": round(sum(risk_points(r) for r in rs) / len(rs), 3) if rs else None,
            "correct": sum(r["verdict"] == "correct" for r in rs),
            "partial": sum(r["verdict"] == "partial" for r in rs),
            "incorrect": sum(r["verdict"] == "incorrect" for r in rs),
            "latency_p50_s": round(pct(lat, 0.5), 2),
            "latency_p95_s": round(pct(lat, 0.95), 2),
        }
    cost = [r["cost_usd"] for r in rows]
    answerable = [r for r in rows if r["category"] != "no_answer"]
    unanswerable = [r for r in rows if r["category"] == "no_answer"]
    summary = {
        **meta,
        "overall": block(rows),
        # The two error types of abstention, reported together: saying "no answer" when the
        # documents contain it, and answering when they do not.
        "false_abstentions": f"{sum(abstains(r['answer']) for r in answerable)}/{len(answerable)}",
        "hallucinated_answers": f"{sum(r['verdict'] != 'correct' for r in unanswerable)}/{len(unanswerable)}",
        "by_category": {c: block([r for r in rows if r["category"] == c]) for c in ("easy", "multi_hop", "no_answer")},
        "prompt_tokens_mean": round(statistics.mean(r["prompt_tokens"] for r in rows)),
        "completion_tokens_mean": round(statistics.mean(r["completion_tokens"] for r in rows)),
        "cost_usd_per_question": round(statistics.mean(cost), 6) if None not in cost else None,
        "cost_usd_total": round(sum(cost), 4) if None not in cost else None,
    }
    judge_price = JUDGE_PRICES.get(meta.get("judge"))
    if judge_price:
        summary["judge_cost_usd_total"] = round(sum(
            r.get("judge_prompt_tokens", 0) * judge_price[0] + r.get("judge_completion_tokens", 0) * judge_price[1]
            for r in rows) / 1e6, 4)
    tps = [r["gen_tok_per_s"] for r in rows if r.get("gen_tok_per_s")]
    if tps:
        summary["gen_tok_per_s_mean"] = round(statistics.mean(tps), 1)
    return summary


def print_summary(s: dict) -> None:
    print(f"\n{s['model']} ({s['backend']})  score {s['overall']['score']}  risk score {s['overall']['risk_score']}  "
          f"p50 {s['overall']['latency_p50_s']}s  p95 {s['overall']['latency_p95_s']}s  "
          f"cost/q {s['cost_usd_per_question']}")
    print(f"false abstentions {s['false_abstentions']}  hallucinated answers {s['hallucinated_answers']}")
    print(f"{'category':<10} {'n':>3} {'score':>6} {'risk':>6} {'ok':>3} {'part':>4} {'bad':>3}")
    for cat, b in s["by_category"].items():
        if b["n"]:
            print(f"{cat:<10} {b['n']:>3} {b['score']:>6} {b['risk_score']:>6} "
                  f"{b['correct']:>3} {b['partial']:>4} {b['incorrect']:>3}")


# ---------------------------------------------------------------- main

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--backend", choices=["ollama", "openai"], default="ollama")
    p.add_argument("--model", help="e.g. qwen3:8b or gpt-5-mini")
    p.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    p.add_argument("--limit", type=int, help="only the first N questions")
    p.add_argument("--ollama-url", default="http://localhost:11434")
    p.add_argument("--num-ctx", type=int, default=16384, help="Ollama context window (default 4096 would truncate)")
    p.add_argument("--think", action="store_true", help="enable thinking for reasoning-capable local models")
    p.add_argument("--reasoning-effort", help="OpenAI reasoning_effort, e.g. minimal/low")
    p.add_argument("--price-in", type=float, help="USD per 1M input tokens (API models)")
    p.add_argument("--price-out", type=float, help="USD per 1M output tokens (API models)")
    p.add_argument("--hardware", default="MacBook Air M4, 16 GB, fanless", help="recorded for local runs")
    p.add_argument("--rejudge", type=Path, help="re-score an existing results file instead of asking the model")
    p.add_argument("--judge-model", default=DEFAULT_JUDGE)
    p.add_argument("--prompt-version", choices=sorted(SYSTEM_PROMPTS), default="v1")
    p.add_argument("--tag", default="", help="suffix for the results file name, e.g. e1-prompt-v2")
    p.add_argument("--resummarize", type=Path, help="recompute the summary of a results file (no model or judge calls)")
    args = p.parse_args()

    if args.resummarize:
        rows = [json.loads(l) for l in args.resummarize.read_text(encoding="utf-8").splitlines() if l.strip()]
        summary_path = args.resummarize.with_suffix(".summary.json")
        old = json.loads(summary_path.read_text(encoding="utf-8"))
        meta = {k: v for k, v in old.items() if not isinstance(v, dict) and k not in
                ("false_abstentions", "hallucinated_answers", "prompt_tokens_mean", "completion_tokens_mean",
                 "cost_usd_per_question", "cost_usd_total", "judge_cost_usd_total", "gen_tok_per_s_mean")}
        meta.setdefault("prompt_version", "v1")
        summary = summarize(rows, meta)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print_summary(summary)
        return

    load_env()
    judge_client = OpenAI()  # reads OPENAI_API_KEY

    if args.rejudge:
        rows = [json.loads(l) for l in args.rejudge.read_text(encoding="utf-8").splitlines() if l.strip()]
        meta = json.loads(args.rejudge.with_suffix(".summary.json").read_text(encoding="utf-8"))
        questions = {json.loads(l)["id"]: json.loads(l) for l in args.golden.read_text(encoding="utf-8").splitlines() if l.strip()}
        for row in rows:
            row.update(judge(judge_client, args.judge_model, questions[row["id"]], row["answer"]))
        meta["judge"] = args.judge_model
        out_path = args.rejudge
    else:
        if not args.model:
            p.error("--model is required")
        if args.backend == "openai" and (args.price_in is None or args.price_out is None):
            p.error("--price-in and --price-out are required for API models (USD per 1M tokens)")
        golden_text = args.golden.read_text(encoding="utf-8")
        questions = [json.loads(l) for l in golden_text.splitlines() if l.strip()][: args.limit]
        model_client = OpenAI() if args.backend == "openai" else None

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        name = re.sub(r"[^A-Za-z0-9.-]+", "-", args.model) + (f"_{args.tag}" if args.tag else "")
        out_path = RESULTS_DIR / f"{stamp}_{name}.jsonl"
        meta = {
            "model": args.model, "backend": args.backend, "context_mode": "oracle",
            "prompt_version": args.prompt_version, "tag": args.tag,
            "golden": args.golden.name, "golden_sha256": hashlib.sha256(golden_text.encode()).hexdigest()[:12],
            "judge": args.judge_model, "git_commit": git_commit(), "started_at": stamp,
            "hardware": args.hardware if args.backend == "ollama" else "api",
            "num_ctx": args.num_ctx if args.backend == "ollama" else None,
            "think": args.think if args.backend == "ollama" else None,
            "reasoning_effort": args.reasoning_effort,
            "price_usd_per_1m": [args.price_in, args.price_out] if args.backend == "openai" else [0, 0],
            "python": platform.python_version(),
        }

        rows = []
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        partial_path = out_path.with_suffix(".partial.jsonl")  # progress, visible while running
        partial_path.unlink(missing_ok=True)
        for i, q in enumerate(questions, 1):
            messages = [{"role": "system", "content": SYSTEM_PROMPTS[args.prompt_version]},
                        {"role": "user", "content": user_prompt(q)}]
            res = ask_ollama(args, messages) if args.backend == "ollama" else ask_openai(args, model_client, messages)
            if args.backend == "ollama" and res["prompt_tokens"] >= args.num_ctx - 64:
                print(f"  warning: {q['id']} prompt may be truncated ({res['prompt_tokens']} tokens)")
            price_in, price_out = meta["price_usd_per_1m"]
            cost = (res["prompt_tokens"] * price_in + res["completion_tokens"] * price_out) / 1e6
            row = {"id": q["id"], "category": q["category"], "question": q["question"],
                   "gold": q["answer"], **res, "cost_usd": cost}
            row.update(judge(judge_client, args.judge_model, q, res["answer"]))
            rows.append(row)
            with partial_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(questions)}] {q['id']} {q['category']:<9} {row['verdict']:<9} "
                  f"{res['latency_s']:.1f}s {res['prompt_tokens']}+{res['completion_tokens']} tok")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if not args.rejudge:
        partial_path.unlink(missing_ok=True)
    out_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    summary = summarize(rows, meta)
    out_path.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print_summary(summary)
    print(f"\nsaved {out_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
