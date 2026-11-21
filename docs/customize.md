# Customize and scale

## Security model


- Every service sits on the private Docker network `in-house-net` and talks by service name.
- No port is published to the network. Remote access is outbound-only, so the firewall can
  keep every inbound port closed: either `tailscale` (joins your private tailnet) or
  `cloudflared` (connects out to Cloudflare). Both are optional Compose profiles chosen with
  `COMPOSE_PROFILES`.
- With Tailscale, only devices on your tailnet can reach the stack. With Cloudflare, Cloudflare
  Access checks identity before anyone even sees the login page.
- Open WebUI is also bound to `127.0.0.1:3000` for local access. Remove that binding if you
  only want access through the tunnel.
- Keep secrets only in `.env`; `.gitignore` excludes it. Verify with `git status` before
  sharing the repository, because ignore rules do not remove a file that was already tracked.
- Sign-ups are turned off after the first (admin) account, so only the admin adds users.

## Swap a component

One opinionated stack that works, with clear exits:

| Component | Default | Common alternative | What changes |
|---|---|---|---|
| Model server | Ollama | vLLM (big GPUs, many users) | Replace the service; point `litellm/config.yaml` at it |
| Chat model | `qwen3:4b-instruct` | `llama3.2:3b` (fits fully in 4 GB), `gemma3:4b`, `phi4-mini`, larger Qwen on big hardware | `CHAT_MODEL` in `.env` and `litellm/config.yaml` |
| Remote access | Tailscale and/or Cloudflare Tunnel + Access | Local only | Set `COMPOSE_PROFILES` in `.env` (`tailscale`, `cloudflare`, both, or empty) |
| Hardware | NVIDIA GPU | CPU only | Delete the `deploy:` block from `ollama` in `docker-compose.yaml` |
| Vector store | pgvector in Postgres | Qdrant, Chroma | Open WebUI's `VECTOR_DB` settings |

With the Tailscale profile, the URL is `https://in-house-ai.<your-tailnet>.ts.net`.

Trade-off to know: Cloudflare decrypts traffic at its edge; Tailscale only sees metadata.
For confidential data, decide which you're comfortable with.

## Scaling up: bigger GPUs and servers

1. Enable the bundled vLLM service (NVIDIA GPU required): add `vllm` to `COMPOSE_PROFILES` and
   set `VLLM_MODEL` (a Hugging Face model) in `.env`. The installer does this for you when you
   choose vLLM. The service is served as `local-chat`. Keep Ollama running: embeddings
   (`local-embed`) still use it.
2. In `litellm/config.yaml`, point the chat model at vLLM:

   ```yaml
   - model_name: local-chat
     litellm_params:
       model: hosted_vllm/local-chat
       api_base: http://vllm:8000/v1
   ```

   Open WebUI doesn't change at all. It still asks for `local-chat`. Tune the `vllm` service's
   flags (`--max-model-len`, `--gpu-memory-utilization`) for your GPU.
3. Pin every image to an exact version tag (no `latest` or `main`).
4. Remove the `127.0.0.1:3000` port binding from `open-webui`.
5. Check the target architecture before deploying. For example, the DGX Spark is ARM64;
   verify that any custom image you add supports the target system.
6. Benchmark with the method above, then load-test with `vllm bench serve` at increasing
   numbers of concurrent users.

Hardware tradeoffs vary by system. A laptop GPU has limited dedicated VRAM, and work that
doesn't fit may spill to CPU memory over PCIe. The DGX Spark is one example of a system with
128 GB of unified memory shared by CPU and GPU, allowing larger models to remain in memory
accessible to the accelerator. Multi-GPU servers offer another scaling path through
additional accelerator memory and parallel compute.

## Scope: what's deliberately not included

In-House AI is the core you need to run a private assistant. Tracing uses LiteLLM's built-in
logging, and a small answer check is an optional add-on. Personal-data masking is left out:
teams that self-host usually have their own preference, and every extra layer is more to
install, secure and maintain.

Good places to extend it, with your tools of choice:

- **Tracing:** the LiteLLM gateway already logs every call (model, tokens, latency, status,
  errors) to the Postgres database it uses, so no extra service is needed.
  - Query it from the host without opening any port:
    `docker compose exec litellm python -c "import urllib.request as u; r=u.Request('http://localhost:4000/spend/logs', headers={'Authorization':'Bearer '+__import__('os').environ['LITELLM_MASTER_KEY']}); print(u.urlopen(r).read().decode())"`
  - Or browse the LiteLLM admin UI (Logs and Usage pages). Port 4000 is not published by
    default; to reach it, add a `docker-compose.override.yaml` with
    `services: { litellm: { ports: ["127.0.0.1:4000:4000"] } }`, then open
    `http://127.0.0.1:4000/ui` (user `admin`, password is your `LITELLM_MASTER_KEY`).
  - Prompts and answers are not stored by default, which keeps conversations private. To
    record them for debugging, add `store_prompts_in_spend_logs: true` under
    `general_settings` in `litellm/config.yaml` and restart LiteLLM. Anyone with database
    or admin access can then read user conversations, so enable it only if that is
    acceptable.
  - GPU and host metrics are a separate choice (Prometheus and Grafana).
- **Answer-quality evaluation:** `benchmarks/eval_rag.py` scores a small handbook.
  A larger or messier corpus needs its own set.
- **PII masking:** guardrails in the gateway, for example with Presidio.

## Need help?

Want In-House AI deployed on your own hardware, adapted to your documents and tools, or
extended with monitoring and evaluation? Get in touch:
[LinkedIn](https://www.linkedin.com/in/raza-jahangir) ·
[Upwork](https://www.upwork.com/freelancers/developerraza)

## Third-party software

In-House AI combines independently licensed software and models. Each component remains under
its own licence; users must review and comply with the applicable licences and terms:

- [Open WebUI](https://github.com/open-webui/open-webui): Open WebUI License (includes
  conditions on altering or removing Open WebUI branding)
- [LiteLLM](https://github.com/BerriAI/litellm): MIT for core components; other components
  may have separate terms
- [Ollama](https://github.com/ollama/ollama): MIT
- [pgvector](https://github.com/pgvector/pgvector): PostgreSQL License
- [cloudflared](https://github.com/cloudflare/cloudflared): Apache License 2.0
- Default chat model, Qwen3 `qwen3:4b-instruct`: Apache License 2.0

These are the upstream projects' stated licences. Check the exact versions and model
artifacts you download; their licence notices govern your use.
