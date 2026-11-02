#!/usr/bin/env python3
"""Inhouse AI benchmark: repeatable speed numbers for an Ollama model.

Runs every prompt in prompts/*.txt against Ollama's API, discards a warm-up run,
then averages N measured runs. Each run starts with a unique ID so Ollama's
prompt cache can't skip work, and no chat history is carried between runs.

Measures per prompt:
  - prompt tokens, prompt eval rate (tok/s)  -> how fast the model reads input (matters for RAG)
  - time to first token (s)                  -> what the user actually waits
  - generation rate (tok/s)                  -> how fast the answer streams
  - total time (s)

Stdlib only. Ollama has no published port in this stack, so run it on the Docker network:

  docker run --rm --network inhouse-net \
    -v "$PWD/benchmarks:/bench" -w /bench python:3.12-slim \
    python bench.py --model qwen3:4b-instruct

Watch GPU/VRAM in another terminal meanwhile:  watch -n 1 nvidia-smi
And check CPU/GPU placement after:              docker compose exec ollama ollama ps
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

NS = 1e9


@dataclass
class RunResult:
    prompt_tokens: int
    prompt_eval_rate: float
    ttft_s: float
    gen_tokens: int
    gen_rate: float
    total_s: float


def run_once(base_url: str, model: str, prompt: str, num_ctx: int, max_tokens: int, timeout: float) -> RunResult:
    body = {
        "model": model,
        # Unique prefix defeats prompt caching, so prompt eval is measured honestly.
        "prompt": f"[run {uuid.uuid4().hex[:8]}]\n{prompt}",
        "stream": True,
        "keep_alive": "30m",
        "options": {"num_ctx": num_ctx, "num_predict": max_tokens, "temperature": 0, "seed": 42},
    }
    req = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    start = time.perf_counter()
    ttft: float | None = None
    final: dict | None = None
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for line in resp:
            if not line.strip():
                continue
            chunk = json.loads(line)
            if "error" in chunk:
                raise RuntimeError(chunk["error"])
            if ttft is None and chunk.get("response"):
                ttft = time.perf_counter() - start
            if chunk.get("done"):
                final = chunk
    if final is None:
        raise RuntimeError("stream ended without a final 'done' chunk")

    p_count = final.get("prompt_eval_count", 0)
    p_dur = final.get("prompt_eval_duration", 0) / NS
    e_count = final.get("eval_count", 0)
    e_dur = final.get("eval_duration", 0) / NS
    return RunResult(
        prompt_tokens=p_count,
        prompt_eval_rate=p_count / p_dur if p_dur else 0.0,
        ttft_s=ttft if ttft is not None else time.perf_counter() - start,
        gen_tokens=e_count,
        gen_rate=e_count / e_dur if e_dur else 0.0,
        total_s=final.get("total_duration", 0) / NS,
    )


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=os.getenv("CHAT_MODEL", "qwen3:4b-instruct"))
    ap.add_argument("--url", default=os.getenv("OLLAMA_URL", "http://ollama:11434"))
    ap.add_argument("--prompts", default="prompts", help="folder of .txt prompts")
    ap.add_argument("--runs", type=int, default=5, help="measured runs per prompt (after 1 warm-up)")
    ap.add_argument("--num-ctx", type=int, default=8192, help="context length; keep equal to OLLAMA_CONTEXT_LENGTH")
    ap.add_argument("--max-tokens", type=int, default=300, help="cap on generated tokens, for comparable runs")
    ap.add_argument("--timeout", type=float, default=600)
    ap.add_argument("--out", default="results", help="folder for the JSON results")
    args = ap.parse_args()

    files = sorted(Path(args.prompts).glob("*.txt"))
    if not files:
        print(f"No prompts found in {args.prompts}/*.txt", file=sys.stderr)
        return 1

    summary: dict[str, dict] = {}
    try:
        for f in files:
            prompt = f.read_text(encoding="utf-8").strip()
            print(f"\n== {f.name}: warm-up run (discarded) ...", flush=True)
            run_once(args.url, args.model, prompt, args.num_ctx, args.max_tokens, args.timeout)
            runs: list[RunResult] = []
            for i in range(1, args.runs + 1):
                r = run_once(args.url, args.model, prompt, args.num_ctx, args.max_tokens, args.timeout)
                runs.append(r)
                print(
                    f"   run {i}: prompt {r.prompt_tokens} tok @ {r.prompt_eval_rate:.1f} tok/s | "
                    f"TTFT {r.ttft_s:.2f}s | gen {r.gen_tokens} tok @ {r.gen_rate:.1f} tok/s",
                    flush=True,
                )
            summary[f.stem] = {
                "prompt_tokens": round(mean([r.prompt_tokens for r in runs])),
                "prompt_eval_rate": round(mean([r.prompt_eval_rate for r in runs]), 1),
                "ttft_s": round(mean([r.ttft_s for r in runs]), 2),
                "gen_tokens": round(mean([r.gen_tokens for r in runs])),
                "gen_rate": round(mean([r.gen_rate for r in runs]), 1),
                "gen_rate_stdev": round(statistics.stdev([r.gen_rate for r in runs]), 1) if len(runs) > 1 else 0.0,
                "total_s": round(mean([r.total_s for r in runs]), 2),
                "runs": [asdict(r) for r in runs],
            }
    except urllib.error.URLError as e:
        print(f"\nCan't reach Ollama at {args.url}: {e}. Is the container on the same Docker network?", file=sys.stderr)
        return 2
    except (RuntimeError, TimeoutError) as e:
        print(f"\nBenchmark failed: {e}", file=sys.stderr)
        return 3

    print(f"\n### {args.model} (num_ctx {args.num_ctx}, {args.runs} runs averaged, warm-up discarded)\n")
    print("| Prompt | Prompt tokens | Prompt eval (tok/s) | Time to first token (s) | Generation (tok/s) | Total (s) |")
    print("|---|---|---|---|---|---|")
    for name, s in summary.items():
        print(
            f"| {name} | {s['prompt_tokens']} | {s['prompt_eval_rate']} | {s['ttft_s']} | "
            f"{s['gen_rate']} ± {s['gen_rate_stdev']} | {s['total_s']} |"
        )

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.model.replace(':', '_').replace('/', '_')}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"model": args.model, "num_ctx": args.num_ctx, "results": summary}, indent=2))
    print(f"\nSaved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())