# Setup guide

Fastest path: `curl -fsSL https://inhouse-ai.razajahangir.dev/install.sh | bash` asks two questions (access and model server), writes `.env` with fresh secrets and starts the stack. [Read the script](https://inhouse-ai.razajahangir.dev/install.sh) first if you like. The steps below do the same by hand.

Ten steps from a fresh Ubuntu machine to a private assistant. The [website](https://inhouse-ai.razajahangir.dev) has the same guide in a friendlier layout.

## Step 1: Install Docker Engine (Ubuntu)

Use Docker's official apt repository, not the Snap package or Docker Desktop.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
```

Log out and back in, then check:

```bash
docker run --rm hello-world
docker compose version
```

### GPU access (NVIDIA only, optional)

Skip this on a CPU-only machine, and delete the `deploy:` block from the `ollama` service in `docker-compose.yaml`. Compose refuses to start a service that reserves a GPU the host doesn't have.

1. Install the NVIDIA driver and check it works: `nvidia-smi`.
2. Install the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
   then register it with Docker:

   ```bash
   sudo nvidia-ctk runtime configure --runtime=docker
   sudo systemctl restart docker
   ```

3. The `ollama` service requests the GPU with:

   ```yaml
   deploy:
     resources:
       reservations:
         devices:
           - driver: nvidia
             count: all
             capabilities: [gpu]
   ```

   This is a reservation: if the GPU isn't available, Compose refuses to start the container
   rather than silently falling back to the CPU.

## Step 2: Get the project

```bash
git clone https://github.com/razajahangir/inhouse-ai.git in-house-ai
cd in-house-ai
```

The layout:

```
in-house-ai/
├── docker-compose.yaml     # all services, network and volumes
├── .env.example            # safe template; copy to .env
├── .gitignore              # excludes .env and models/
├── README.md
├── litellm/
│   └── config.yaml         # maps model names to backends
├── benchmarks/
│   ├── bench.py            # optional automated benchmark
│   └── prompts/            # the benchmark prompts
└── models/                 # downloaded model weights (created on first run, not in Git)
```

## Step 3: Fill in the secrets

```bash
cp .env.example .env
openssl rand -hex 32   # run once for each secret below
```

Edit `.env`:

- `WEBUI_SECRET_KEY`: a random value.
- `POSTGRES_USER`, `POSTGRES_DB`: names with underscores, not hyphens (e.g. `inhouse_ai_user`, `inhouse_ai_db`).
- `POSTGRES_PASSWORD`: a random value.
- `LITELLM_MASTER_KEY`: a random value **starting with `sk-`**, e.g. `sk-<random>`.
- `CHAT_MODEL` / `EMBED_MODEL`: e.g. `qwen3:4b-instruct` / `nomic-embed-text`. The chat model
  name must match the one in `litellm/config.yaml`.
- `COMPOSE_PROFILES`: which optional services to start (empty by default). `tailscale` (private, recommended
  for sensitive data), `cloudflare`, both, or empty for local-only access.
- `TS_AUTHKEY`: a Tailscale auth key (only with the `tailscale` profile; see Step 4).
- `CLOUDFLARE_TUNNEL_TOKEN`: only with the `cloudflare` profile; filled in during Step 4.

Check the file is ignored by Git:

```bash
git status   # .env must NOT appear
```

## Step 4: Choose how to reach it

Pick one or both, then list them in `COMPOSE_PROFILES` in `.env`. For local-only use, leave it
empty and skip to Step 6.

### Option A: Tailscale (private, end-to-end encrypted)

Best for sensitive data: Tailscale only sees metadata, and nothing is public.

1. In the Tailscale admin console, create a reusable **auth key** and put it in `TS_AUTHKEY`.
2. Set `COMPOSE_PROFILES=tailscale`.
3. After Step 6, open `https://in-house-ai.<your-tailnet>.ts.net` from any device on your
   tailnet. The hostname comes from `TS_HOSTNAME`. Enable HTTPS in the admin console's DNS
   settings if prompted.

### Option B: Cloudflare Tunnel (public hostname)

Set `COMPOSE_PROFILES=cloudflare` (or `tailscale,cloudflare`). Cloudflare decrypts traffic at
its edge. You need a domain whose DNS is managed by Cloudflare.

1. Cloudflare dashboard → **Zero Trust → Networks → Tunnels → Create a tunnel**.
2. Choose **Cloudflared**, name it `in-house-ai`, and pick **Docker** as the environment.
3. Cloudflare shows a `docker run ... --token <long-token>` command. Copy **only the token**
   (it starts with `eyJ`) into `CLOUDFLARE_TUNNEL_TOKEN` in `.env`. Don't run that command.
4. Add a **public hostname**:
   - Subdomain: `chat` / Domain: `yourdomain.com`
   - Service type: `HTTP`, URL: `open-webui:8080`

   Use the container name, not `localhost`. Inside the tunnel container, `localhost` is the
   tunnel itself.

## Step 5: Protect it with Cloudflare Access (Option B only)

Without this step, the login page is public to anyone who finds the URL.

1. **Zero Trust → Access → Applications → Add an application → Self-hosted**.
2. Application domain: `chat.yourdomain.com`.
3. Add a policy: **Action** Allow, **Include** Emails → your email (or your team's email domain).
4. Login method: One-time PIN is enough to start.

## Step 6: Start the stack

```bash
docker compose up -d
docker compose logs -f ollama-init
```

Wait until both models have downloaded (about 3 GB) and `ollama-init` exits. Then:

```bash
docker compose ps
```

Everything should show `running` (and `healthy` where a healthcheck exists), except
`ollama-init`, which shows `exited (0)`.

## Step 7: Verify each layer

**Tunnel (Cloudflare only):**

```bash
docker compose logs cloudflared | grep -i "registered"
```

You should see four registered tunnel connections.

**Gateway sees the models:**

```bash
KEY=$(grep '^LITELLM_MASTER_KEY=' .env | cut -d= -f2)
docker compose exec open-webui curl -s http://litellm:4000/v1/models -H "Authorization: Bearer $KEY"
```

You should see `local-chat` and `local-embed`.

**A model answers through the gateway:**

```bash
docker compose exec open-webui curl -s http://litellm:4000/v1/chat/completions \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model":"local-chat","messages":[{"role":"user","content":"Say hello in five words."}]}'
```

The first call can take a minute on CPU while the model loads.

**The model is on the GPU (if you have one):**

```bash
docker compose exec ollama ollama ps
```

The `PROCESSOR` column shows the CPU/GPU split, e.g. `22%/78% CPU/GPU` when the model doesn't
quite fit in VRAM, or `100% GPU` when it does.

**Nothing is exposed:**

```bash
sudo ss -tlnp | grep -E '3000|4000|5432|11434'
```

Only `127.0.0.1:3000` should appear. Nothing should listen on `0.0.0.0`.

## Step 8: First login and lock down sign-ups

1. Open `https://chat.yourdomain.com`, or `http://localhost:3000` locally.
2. Create the first account. It becomes the **admin**.
3. In `docker-compose.yaml`, set `ENABLE_SIGNUP: "false"`, then:

   ```bash
   docker compose up -d
   ```

From now on, only the admin adds users (**Admin Panel → Users**).

## Step 9: Set up RAG

1. **Workspace → Knowledge → Create**, e.g. "Company Policies".
2. Upload a few real PDFs or Word documents.
3. In a chat, type `#` and pick the knowledge base, then ask a question about the documents.
4. The answer should include clickable citations pointing back to the source.

On small GPUs, keep **Top K** at 3 (Admin Panel → Settings → Documents). Every retrieved chunk
makes the prompt longer, and long prompts are the slow part on modest hardware.

**Data isolation check:** create a second user who isn't in the knowledge base's group, log in
as them, and confirm they can't see or query it.

## Step 10: Walk through it end to end

A good order for showing the stack to someone (about 10 minutes):

1. Architecture: `docker compose ps` and this README's diagram.
2. Security: closed ports (`ss -tlnp`), the Cloudflare Access login, `.env` not in Git.
3. Chat with a local model through the tunnel.
4. RAG: upload a document, ask a question, show the citations.
5. Data isolation: switch to the second user.
6. The upgrade path: show the vLLM swap below and explain that only the gateway config changes.
7. Reproducibility: `docker compose down && docker compose up -d` (volumes keep the data).

Send one prompt first to warm up the model, and close heavy apps to free RAM.

---

## Useful commands

```bash
docker compose ps                              # status
docker compose logs -f <service>               # follow logs
docker compose restart <service>               # restart one service (e.g. after editing litellm/config.yaml)
docker compose up -d                           # apply changes to .env or docker-compose.yaml
docker compose exec ollama ollama ps           # is the model on GPU or CPU?
docker compose exec ollama ollama list         # downloaded models
watch -n 1 nvidia-smi                          # live GPU use
docker compose down                            # stop (data kept in volumes)
docker compose down -v                         # stop AND delete all data — careful
docker compose pull && docker compose up -d    # update images
```

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `permission denied` on the Docker socket | You're not in the `docker` group yet: `sudo usermod -aG docker $USER`, then log out and in. |
| Open WebUI says **"Backend Required"** or **"frontend only"** | Confirm `docker compose ps open-webui` shows the service running, then check `curl -i http://127.0.0.1:3000/api/config` returns `200`. Open `http://localhost:3000` locally, or make sure the Cloudflare hostname routes to `http://open-webui:8080`. If the API check returns `200` but the page still shows this message, hard-reload the page or clear site data for that hostname and try a private window; the browser may be using stale frontend assets or session data. If the check fails, inspect `docker compose logs --tail=100 open-webui`. |
| No models in the Open WebUI picker | `ollama-init` still running, or the LiteLLM key in `.env` doesn't start with `sk-`. Check `docker compose logs litellm`. |
| `model not found` | The model wasn't pulled, or `CHAT_MODEL` and `litellm/config.yaml` don't match. |
| Tunnel URL shows a 502 error | Hostname service URL isn't `http://open-webui:8080`, or Open WebUI is still starting. |
| `cloudflared` keeps restarting / "token is not valid" | Wrong or empty `CLOUDFLARE_TUNNEL_TOKEN`. Copy only the token (starts with `eyJ`), then `docker compose up -d --force-recreate cloudflared`. |
| Document upload fails | Embedding model not downloaded. Run `docker compose logs ollama-init`. |
| "prompt is too long" / context error with RAG | Raise `OLLAMA_CONTEXT_LENGTH` (e.g. 8192), lower Top K to 3, and turn off tools you don't need. |
| Replies show long "thinking" text | Use an instruct (non-thinking) model such as `qwen3:4b-instruct`. |
| Replies very slow | Check `ollama ps`: if mostly CPU, use a smaller model (`llama3.2:3b`, `qwen3:1.7b`) in both `.env` and `litellm/config.yaml`. Warm the model up first. |
