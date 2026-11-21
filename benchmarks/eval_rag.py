#!/usr/bin/env python3
"""Retrieval and answer-quality check for the local In-House AI models.

Uses the same models as the stack (nomic-embed-text and qwen3:4b-instruct) and
stores passages in Postgres with pgvector. It does not go through Open WebUI.
Each paragraph is one passage, and search returns the top 3 by cosine distance.
Open WebUI's own splitter can cut a file differently.

Scores, all automatic:
  - hit@3 and MRR against the labeled passage
  - fact recall: every required phrase appears in the answer
  - abstention: unanswerable questions are refused
  - number faithfulness: every number in the answer also appears in the top 3

Run on the private Docker network after postgres and ollama are up:

  docker run --rm --network in-house-net \
    -v "$PWD/benchmarks:/bench" -w /bench \
    -e OLLAMA_HOST=http://ollama:11434 \
    -e DATABASE_URL \
    python:3.12-slim bash -c "pip install -q 'psycopg[binary]' && python eval_rag.py"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from pathlib import Path

import psycopg

TOP_K = 3
OLLAMA = os.environ.get("OLLAMA_HOST", "http://ollama:11434").rstrip("/")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "qwen3:4b-instruct")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "eval" / "corpus.json"
OUT = ROOT / "results" / "rag-eval.json"

ABSTAIN = re.compile(
    r"do not (say|contain|include|mention|specify|state)|"
    r"does not (say|contain|include|mention|specify|state)|"
    r"not (in|stated|specified|mentioned|found)|"
    r"no information|cannot (find|answer|determine)|"
    r"not (covered|addressed)|documents do not",
    re.I,
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")
NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
    "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
    "fifteen": "15", "sixteen": "16", "seventeen": "17", "eighteen": "18",
    "nineteen": "19", "twenty": "20",
}


def post(path: str, payload: dict, timeout: int = 600) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        OLLAMA + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def embed(text: str, kind: str) -> list[float]:
    body = post("/api/embed", {"model": EMBED_MODEL, "input": f"search_{kind}: {text}"})
    vectors = body.get("embeddings") or [body["embedding"]]
    return vectors[0]


def chat(question: str, passages: list[dict]) -> str:
    blocks = [f"[{i}] {p['title']}\n{p['text']}" for i, p in enumerate(passages, 1)]
    prompt = (
        "Answer the question using only the passages. "
        "If the passages do not contain the answer, say that the documents do not say. "
        "Do not use outside knowledge. Keep the answer to one or two sentences.\n\n"
        "Passages:\n"
        + "\n\n".join(blocks)
        + f"\n\nQuestion: {question}"
    )
    body = post(
        "/api/chat",
        {
            "model": CHAT_MODEL,
            "think": False,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "num_predict": 180},
        },
    )
    return body["message"]["content"].strip()


def norm(text: str) -> str:
    text = text.lower().replace("usd", "dollars").replace("$", "")
    text = re.sub(
        r"\b(" + "|".join(NUMBER_WORDS) + r")\b",
        lambda m: NUMBER_WORDS[m.group(0)],
        text,
    )
    return re.sub(r"\s+", " ", text)


def facts_hit(answer: str, facts: list[str]) -> list[bool]:
    hay = norm(answer)
    return [norm(fact) in hay for fact in facts]


def numbers_supported(answer: str, passages: list[dict]) -> bool:
    allowed = set(NUMBER.findall(" ".join(p["text"] for p in passages)))
    return set(NUMBER.findall(answer)).issubset(allowed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text())
    chunks = []
    for doc in corpus["documents"]:
        for i, paragraph in enumerate(doc["paragraphs"]):
            chunks.append(
                {
                    "id": f"{doc['id']}:{i}",
                    "doc": doc["id"],
                    "title": doc["title"],
                    "paragraph": i,
                    "text": paragraph,
                }
            )

    print(f"Embedding {len(chunks)} passages with {EMBED_MODEL}", flush=True)
    t0 = time.time()
    for chunk in chunks:
        chunk["embedding"] = embed(chunk["text"], "document")
    embed_s = time.time() - t0
    dim = len(chunks[0]["embedding"])
    print(f"Embedded in {embed_s:.1f}s, dim {dim}", flush=True)

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute("DROP TABLE IF EXISTS eval_chunks")
        conn.execute(
            f"CREATE TABLE eval_chunks ("
            f"id text PRIMARY KEY, doc text, title text, paragraph int, body text, "
            f"embedding vector({dim}))"
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO eval_chunks (id, doc, title, paragraph, body, embedding) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (c["id"], c["doc"], c["title"], c["paragraph"], c["text"], str(c["embedding"]))
                    for c in chunks
                ],
            )
        conn.commit()

        rows = []
        hits = 0
        rr_sum = 0.0
        fact_hits = 0
        fact_total = 0
        answer_ok = 0
        abstain_ok = 0
        abstain_total = 0
        faithful = 0

        for q in corpus["questions"]:
            print(f"Question {q['id']}: {q['question']}", flush=True)
            qvec = embed(q["question"], "query")
            ranked = conn.execute(
                "SELECT id, title, body FROM eval_chunks "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                (str(qvec), TOP_K),
            ).fetchall()
            passages = [{"id": r[0], "title": r[1], "text": r[2]} for r in ranked]
            gold = None if q["unanswerable"] else f"{q['gold_doc']}:{q['gold_paragraph']}"
            rank = next((i for i, p in enumerate(passages, 1) if p["id"] == gold), None)
            hit = rank is not None
            if hit:
                hits += 1
                rr_sum += 1 / rank
            t1 = time.time()
            answer = chat(q["question"], passages)
            gen_s = time.time() - t1
            got = facts_hit(answer, q["facts"])
            fact_hits += sum(got)
            fact_total += len(q["facts"])
            supported = numbers_supported(answer, passages)
            if supported:
                faithful += 1
            abstained = bool(ABSTAIN.search(answer))
            if q["unanswerable"]:
                abstain_total += 1
                correct = abstained and supported
            else:
                correct = all(got) and supported
            if correct:
                answer_ok += 1
                if q["unanswerable"]:
                    abstain_ok += 1
            print(f"  hit={hit} rank={rank} answer_ok={correct} ({gen_s:.1f}s)", flush=True)
            print(f"  {answer.replace(chr(10), ' ')[:280]}", flush=True)
            rows.append(
                {
                    "id": q["id"],
                    "question": q["question"],
                    "unanswerable": q["unanswerable"],
                    "gold": gold,
                    "retrieved": [p["id"] for p in passages],
                    "hit_at_3": hit,
                    "rank": rank,
                    "facts": q["facts"],
                    "facts_found": got,
                    "numbers_supported": supported,
                    "abstained": abstained,
                    "answer_correct": correct,
                    "generation_s": round(gen_s, 2),
                    "answer": answer,
                }
            )

    n = len(corpus["questions"])
    n_answerable = n - abstain_total
    summary = {
        "chat_model": CHAT_MODEL,
        "embed_model": EMBED_MODEL,
        "top_k": TOP_K,
        "passages": len(chunks),
        "questions": n,
        "embed_seconds": round(embed_s, 1),
        "corpus": str(args.corpus.name),
        "hit_at_1": sum(1 for row in rows if row["rank"] == 1),
        "hit_at_3": hits,
        "hit_at_3_of": n_answerable,
        "hit_at_3_rate": round(hits / n_answerable, 3) if n_answerable else None,
        "mrr": round(rr_sum / n_answerable, 3) if n_answerable else None,
        "fact_recall": round(fact_hits / fact_total, 3) if fact_total else None,
        "answer_correct": answer_ok,
        "answer_correct_of": n,
        "answer_correct_rate": round(answer_ok / n, 3),
        "number_faithfulness": faithful,
        "number_faithfulness_of": n,
        "number_faithfulness_rate": round(faithful / n, 3),
        "abstention_correct": abstain_ok,
        "abstention_total": abstain_total,
        "items": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "items"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
