# Customize and scale

## Security model


- Every service sits on the private Docker network `in-house-net` and talks by service name.
- No port is published to the network. `cloudflared` makes an outbound connection to
  Cloudflare, so the firewall can keep every inbound port closed.
- Cloudflare Access checks identity before anyone even sees the login page.
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
| Remote access | Cloudflare Tunnel + Access | Tailscale (end-to-end encrypted, private network only) | Remove `cloudflared`; run `tailscale serve` on the host |
| Hardware | NVIDIA GPU | CPU only | Remove the `deploy:` block from `ollama` |
| Vector store | pgvector in Postgres | Qdrant, Chroma | Open WebUI's `VECTOR_DB` settings |

When using Tailscale Serve, the URL is `https://in-house-ai.<your-tailnet>.ts.net`.

Trade-off to know: Cloudflare decrypts traffic at its edge; Tailscale only sees metadata.
For confidential data, decide which you're comfortable with.

## Scaling up: bigger GPUs and servers

1. On a larger GPU server, replace the `ollama` and `ollama-init` services with a vLLM
   container supported by that server, with accelerator access and model storage mounted
   read-only from the host. A workstation, multi-GPU server, or NVIDIA DGX Spark are all
   possible targets; select a backend and configuration suited to the hardware.
2. In `litellm/config.yaml`, change the model entry:

   ```yaml
   - model_name: local-chat
     litellm_params:
       model: hosted_vllm/<model-name>
       api_base: http://vllm:8000/v1
   ```

   Open WebUI doesn't change at all. It still asks for `local-chat`.
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

In-House AI is the core you need to run a private assistant, and nothing more. Observability,
evaluation and data-protection layers are left out on purpose: teams that self-host usually
have their own preferences, and every extra layer is more to install, secure and maintain.

Good places to extend it, with your tools of choice:

- **Tracing and monitoring:** LiteLLM supports callbacks to tools such as Langfuse; the
  model server and GPU can be monitored with Prometheus and Grafana.
- **Answer-quality evaluation:** a test set of questions scored with a framework such as
  Ragas or DeepEval.
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
