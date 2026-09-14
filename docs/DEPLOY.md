# Deploying

One container on one VM. No orchestration, because there is one service: the
corpus is a sqlite file and the target repo is baked into the image.

Live at **https://ticket-to-pr-agent.exe.xyz** (exe.dev, `fra`).

## What has to be carried across, and why

The repository is public, so the VM clones it. Two things are not in it and
have to be moved by hand — which is the point of them not being in it:

| | Why it is not in git |
|---|---|
| `data/kb/` | the corpus cites sources that are not ours to redistribute |
| the three secrets | `LLM_API_KEY`, `GITHUB_TOKEN`, `HF_TOKEN` |

## The sequence

```bash
CLI=.claude/skills/sandbox-exe-dev/exedev_cli   # not committed; vendored skill

# 1. A VM. The name becomes the URL, and the proxy already fronts port 8000.
(cd $CLI && uv run exedev init --name ticket-to-pr-agent --cpu 2 --memory 4GB --disk 20GB)

# 2. Docker, and the login user in its group.
(cd $CLI && uv run exedev exec ticket-to-pr-agent --root \
  "apt-get update -qq && apt-get install -y -qq docker.io docker-compose-v2 git && sudo usermod -aG docker exedev")

# 3. The code, from GitHub rather than rsync — the VM pulls a known commit.
ssh ticket-to-pr-agent.exe.xyz "git clone -q https://github.com/tekncoach/ticket-to-pr-agent.git ~/app"

# 4. The two things git does not carry.
ssh ticket-to-pr-agent.exe.xyz "mkdir -p ~/app/data/kb"
scp data/kb/kb.sqlite3 data/kb/manifest.json ticket-to-pr-agent.exe.xyz:app/data/kb/
grep -E "^(LLM_API_KEY|GITHUB_TOKEN|HF_TOKEN)=" .env | \
  ssh ticket-to-pr-agent.exe.xyz "cat > ~/app/.env.secrets && chmod 600 ~/app/.env.secrets"

# 5. Compose reads one .env: the secrets plus the deployment's own settings.
ssh ticket-to-pr-agent.exe.xyz "cd ~/app && cat .env.secrets > .env && \
  printf 'SHADOW_MODE=true\nLLM_MODEL=claude-haiku-4-5\nMAX_TURNS=12\n' >> .env && \
  docker compose --env-file .env -f deploy/docker-compose.yml up -d --build"
```

`--env-file .env` is not optional: compose looks for `.env` beside the compose
file, which is `deploy/`, not the repo root. Without it every secret
interpolates to an empty string and the container comes up with no key.

## Access

Private by default — an unauthenticated request redirects to exe.dev login.
Three states, from tightest:

```bash
(cd $CLI && uv run exedev share add-link ticket-to-pr-agent)   # tokenised URL
(cd $CLI && uv run exedev share set-public ticket-to-pr-agent) # anyone with the link
(cd $CLI && uv run exedev share set-private ticket-to-pr-agent)
```

It is **public** today, because a tokenised link needs a browser to complete
its redirect and a reviewer fetching the URL with curl gets a 401. Every page
is served `X-Robots-Tag: noindex, nofollow`, so public means reachable, not
indexed. Set it private again when the review is done.

## The kill switch

`SHADOW_MODE` is read on every tool call, so stopping writes does not need a
rebuild:

```bash
ssh ticket-to-pr-agent.exe.xyz "cd ~/app && sed -i s/SHADOW_MODE=false/SHADOW_MODE=true/ .env && \
  docker compose --env-file .env -f deploy/docker-compose.yml up -d"
curl -s https://ticket-to-pr-agent.exe.xyz/health   # shadow_mode confirms it took
```

`/health` is how you check it actually applied, rather than assuming.

## What costs money while this runs

The VM is persistent and bills until `exedev vm kill ticket-to-pr-agent` — it
does not sleep, which is why it was chosen over a free tier that cold-starts
for 30 seconds on the first click. The container itself spends nothing until
someone clicks: a knowledge-base question is $0.011-$0.047 on Haiku.
