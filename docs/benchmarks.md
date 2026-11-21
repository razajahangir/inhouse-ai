# Benchmarks



The numbers that decide how the stack feels are the model's speed on your hardware. This
section measures exactly that, with nothing else in the way: no Open WebUI, no LiteLLM, no
retrieval. Run it on any supported host, from a CPU-only laptop or small GPU to a workstation,
DGX Spark, or multi-GPU server.

## What is measured

Ollama's `--verbose` output prints these after every answer:

| Ollama output | Meaning | Why it matters |
|---|---|---|
| `prompt eval count` | Tokens the model had to read (your text + chat template + any history) | RAG adds retrieved chunks here, so it can reach thousands |
| `prompt eval cached` | Tokens reused from Ollama's cache instead of read again | ~3 is normal (the chat template). A big number means the run is invalid |
| `prompt eval duration` | Time spent reading the prompt | Roughly the **wait before the first word** |
| `prompt eval rate` | Reading speed, tokens/s | Decides the wait on long (RAG) prompts |
| `eval count` / `eval rate` | Tokens written / writing speed, tokens/s | How fast the answer streams |
| `load duration` | Time to load the model | Should be milliseconds once warm; seconds means a cold start |

## Method

1. **Record your setup:** on NVIDIA systems, capture `nvidia-smi` (driver, CUDA); on CPU-only
   systems, record the CPU model. Also record `docker compose exec ollama ollama --version`,
   `docker compose exec ollama ollama show <model>` (parameters, quantization), and the context
   length (`grep CONTEXT docker-compose.yaml`).
2. **Fix the conditions:** close competing workloads and avoid thermal throttling. On a
   laptop, keep it plugged in and on a hard surface. For NVIDIA GPUs, monitor with
   `watch -n 1 nvidia-smi`.
3. **Start a session and lock the settings** (they last only for this session):

   ```bash
   docker compose exec ollama ollama run qwen3:4b-instruct --verbose
   ```
   ```
   /set parameter temperature 0
   /set parameter num_predict 300
   ```

4. **Warm up:** send `hi` and ignore the numbers.
5. **Make every run fresh:**
   - Type `/clear` before each run, so no chat history is re-sent.
   - Start each prompt with a different first word (`Apple:`, `Banana:`, `Cherry:` …), so
     Ollama's prompt cache can't skip the reading.
   - Check `prompt eval cached` stays around 3. If it's larger, discard and repeat the run.
6. **Run three prompt sizes**, three to five times each (starter prompts are in `benchmarks/prompts/`):
   - **Short:** `What is Docker in one sentence?`
   - **Medium:** `Explain how a reverse proxy works and when you'd use one, in about 200 words.`
   - **Long (RAG-sized):** the ~2,150-word document in `benchmarks/prompts/long.txt`
     (~3,500 tokens), wrapped in `"""` so Ollama accepts multiple lines. It starts with
     `Summarise the main points of this document.`
7. **Watch the hardware** during a long run (VRAM, GPU-Util, temperature, power), then after
   `/bye` run `docker compose exec ollama ollama ps` for the CPU/GPU split.
8. **Average** each prompt's runs. If runs differ by more than a few percent, something else
   is competing for the machine; fix that and repeat.

**Prefer it automated?** `benchmarks/bench.py` benchmarks through Ollama's API, prints a
Markdown results table, and saves a JSON results file under `benchmarks/results/`. It uses
only the Python standard library and connects over the private Docker network:

```bash
docker run --rm --network in-house-net \
  -v "$PWD/benchmarks:/bench" -w /bench python:3.12-slim \
  python bench.py --model qwen3:4b-instruct --runs 3
```

The table below shows example results. Follow [CONTRIBUTING.md](./CONTRIBUTING.md) to add a
benchmark row for your hardware.

## Tested on

| | |
|---|---|
| Machine | HP Victus laptop, Ubuntu |
| GPU | NVIDIA GeForce GTX 1650, 4 GB VRAM (driver 595.99.02, CUDA 13.2) |
| RAM | 24 GB |
| Chat model | `qwen3:4b-instruct` (4.0B, Q4_K_M, Apache 2.0) |
| Embedding model | `nomic-embed-text` |
| Runtime | Ollama (llama.cpp), context 8,192 tokens |

The stack also runs on CPU only; results from a second machine are below.

## Example results: HP Victus (GTX 1650, 4 GB)

Settings: `qwen3:4b-instruct`, Q4_K_M, context 8,192, temperature 0, max 300 output tokens,
warm model, no chat history. 3.4 GB loaded, 22% CPU / 78% GPU (2.6 GB in VRAM).

| Prompt | Prompt tokens | Time to first token | Reading speed | Writing speed | Total time |
|---|---|---|---|---|---|
| Short | 26 | 0.30 s | n/a* | 28.5 ± 0.4 tok/s | 1.1 s |
| Medium | 41 | 0.42 s | 103 tok/s | 26.7 ± 0.9 tok/s | 9.2 s |
| Long (RAG-sized) | 3,576 | 30.7 s | 118 tok/s | 11.9 ± 0.3 tok/s | 56 s |

Measured with `benchmarks/bench.py`: two separate sessions of 3 runs each (6 runs per prompt),
warm-up discarded. Manual runs with `ollama run --verbose` agreed within ~5%.

\*Too few tokens to time reliably.

GPU at 99–100% utilisation, 48–49 °C, 28 W of 50 W, no throttling.

**What it shows:** short chats feel instant, but a RAG-sized prompt of ~3,500 tokens means a
~30-second wait before the first word, and generation slows from ~28 to ~12 tok/s (and to ~10
on very long answers, because each new token looks back over everything before it). On small
hardware, **reading long prompts is the bottleneck**, which is why Top K matters for RAG and
why bigger GPUs, workstations or unified-memory machines change the experience.

Ran it on your hardware? Open a pull request adding a row: machine, GPU/VRAM, RAM, model,
quantization, context length, and the five numbers above.

## Example results: ThinkPad T14s (CPU only)

| | |
|---|---|
| Machine | ThinkPad T14s Gen 2a, Ubuntu 26.04, on AC power, performance power profile |
| CPU | AMD Ryzen 5 PRO 5650U (6 cores, 12 threads), about 2.0 GHz sustained, up to 71 °C |
| RAM | 16 GB (about 14 GiB usable), no GPU |
| Runtime | Ollama 0.40.13 (llama.cpp), 100% CPU, same `qwen3:4b-instruct` model |

Settings: `qwen3:4b-instruct`, Q4_K_M, context 8,192, temperature 0, max 300 output tokens,
warm model, no chat history. Only the Ollama service was running, other applications were
closed, and Ollama was started fresh for each session so it began with a clean memory state.

| Prompt | Prompt tokens | Time to first token | Reading speed | Writing speed | Total time |
|---|---|---|---|---|---|
| Short | 26 | 0.56 s | n/a* | 14.0 tok/s | 2.2 s |
| Medium | 41 | 0.92 s | 46.4 tok/s | 12.9 ± 0.2 tok/s | 19.9 s |
| Long (RAG-sized) | 3,583 | 106 s | 34.0 tok/s | 6.9 ± 0.2 tok/s | 149 s |

Measured with `benchmarks/bench.py`: three separate sessions of 3 runs each (9 runs per prompt),
warm-up discarded, averaged together. Short and medium prompts agreed across sessions within
about 3%. Long prompts took 103.3–103.7 s to the first token in two sessions and 106–120 s in
the third (its first run was the slowest, and free memory dipped to about 3.6 GB), so expect
roughly 103–110 s; the median is 103 s. Swap held at about 2 GB (left over from before the
runs) with no swap writes in any session.

\*Too few tokens to time reliably.

**What it shows:** on CPU, short chats still feel quick (about half a second to the first
word, then ~14 tok/s), but a RAG-sized prompt of ~3,600 tokens means waiting **about
1 minute 45 seconds** before the first word, and writing slows to ~7 tok/s. That is
roughly 3.4 times the wait of the GTX 1650 above. If you run on CPU, keep Top K low and the
context short. The first message after the stack starts also loads the model into memory, so
allow extra time for it.

**Memory matters on a 16 GB machine.** In an earlier, longer session of five long prompts in a
row, the Ollama runner grew to about 8.7 GB and free memory fell below 2.5 GB; the last two
long runs were about 7% slower (114 s to the first token instead of 106 s). Another early
run, made while apps were open and about 4 GB of swap was in use, was slower still. For
repeatable numbers, close other applications and restart Ollama between sessions
(`docker compose restart ollama`).

## Baseline vs end-to-end

These numbers are the **model-on-hardware baseline**. A real RAG question in Open WebUI adds
embedding the question, a pgvector search and the gateway hop, so the wait a user sees is a
little longer. LiteLLM itself adds only milliseconds.
