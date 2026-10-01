# Deploying

One container on one VM. No orchestration, because there is one service: the
corpus is a sqlite file and the target repo is baked into the image.

Live at **https://ticket-to-pr-agent.exe.xyz** (exe.dev, `fra`) — **closed by
default**; see [Access](#access).

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

It is **private** today. It was public for one review — a tokenised link
needs a browser to complete its redirect, so a reviewer fetching the URL with
curl gets a 401, and public was what made it gradeable. Every page is served
`X-Robots-Tag: noindex, nofollow`, so public meant reachable, not indexed.

Open it for a review, close it after. `curl -o /dev/null -w '%{http_code}'` on
the root says which state it is in: 200 open, 307 closed.

## The kill switches

Four environment variables, in the order to reach for them. The rollout plan says when ([`SHADOW_ROLLOUT.md`](SHADOW_ROLLOUT.md)).

| Variable | Does | `/health` shows |
|---|---|---|
| `SHADOW_MODE=true` | every write tool becomes a receipt; the agent keeps running | `shadow_mode` |
| `AGENT_ENABLED=false` | `/v1/run` and `/v1/chat` answer 503 before anything else | `agent_enabled` |
| `DISABLED_TOOLS=open_pr,comment_on_ticket` | the named tools are refused, the rest work | `disabled_tools`, `disabled_tools_unknown` |
| `LLM_MODEL=<model>` | the model fallback | `model` |

Changing one needs the container recreated, not rebuilt, and none of it needs a deploy:

```bash
ssh ticket-to-pr-agent.exe.xyz 'set_switch() { f=~/app/.env; grep -q "^$1=" "$f" && sed -i.bak "s/^$1=.*/$1=$2/" "$f" || echo "$1=$2" >> "$f"; }
  set_switch AGENT_ENABLED false
  cd ~/app && docker compose --env-file .env -f deploy/docker-compose.yml up -d'
curl -s https://ticket-to-pr-agent.exe.xyz/health   # the field must read what you set
```

`/health` is how you check it actually applied, rather than assuming. Recreating the container ends any run in progress, since `/v1/run` is synchronous. The helper above has been tested on a copy of `.env` and has not yet been run on this VM. The compose file lists each variable by name: a variable it does not list never reaches the container. All of them fail toward the safe state on a typo: writes are enabled only by exactly `SHADOW_MODE=false`, and anything but `true` turns `AGENT_ENABLED` off. A misspelt tool name in `DISABLED_TOOLS` shows up under `disabled_tools_unknown`.

**This needs SSH access to the VM**, held by one person today, so it does not meet the bar of being usable by someone who is not the author. A platform with an environment-variable page would remove the requirement; the variables are the same.

## Running the rollback check on a schedule

`agent/rollout_check.py` reads the run traces and exits 1 when an unauthorized-write trigger trips ([`SHADOW_ROLLOUT.md`](SHADOW_ROLLOUT.md)). Nothing runs it unattended until this entry is installed on the VM, and it needs an alert URL the owner chooses (a Slack incoming webhook, an `ntfy` topic, anything that accepts a JSON `{"text": ...}` post):

```bash
# every 15 minutes: check the traces inside the container, post to the webhook on a trip
*/15 * * * * cd ~/app && docker compose --env-file .env -f deploy/docker-compose.yml exec -T agent \
  python -m agent.rollout_check /app/tmp/sessions --require-runs --notify-url "$ROLLOUT_ALERT_URL" \
  >> ~/rollout-check.log 2>&1
```

`--require-runs` makes a missing or empty trace directory exit 2 instead of reading as healthy, which also means a week with no runs at all will exit 2: drop the flag for a deployment that is expected to be idle. A dead webhook never hides a trip: the exit code stays 1 and the log says it could not notify. This has been tested against recorded traces and a stand-in webhook, and has not been installed here.

## The image goes stale on purpose

`TARGET_REF` pins the target repo's commit at build time rather than tracking
its default branch. That is what makes the image reproducible — the suite
`run_tests` runs is the suite this image was built against, not whatever
`main` moved to since.

**The cost is real and worth stating before anyone asks**: nothing refreshes
it. When the target repo moves, this image keeps working against the commit it
was built with, and a rebuild is the only thing that catches it up:

```bash
ssh ticket-to-pr-agent.exe.xyz "cd ~/app && git pull -q && \
  TARGET_REF=main docker compose --env-file .env -f deploy/docker-compose.yml up -d --build"
```

Production would put that on a schedule, or on the same webhook that triggers
a run. Neither is built. The alternative — building against a floating
`main` — trades the staleness for a worse problem: two runs of the same image
testing against different code, with no way to tell which.

## What costs money while this runs

The VM is persistent and bills until `exedev vm kill ticket-to-pr-agent` — it
does not sleep, which is why it was chosen over a free tier that cold-starts
for 30 seconds on the first click. The container itself spends nothing until
someone clicks: a knowledge-base question is $0.011-$0.047 on Haiku.
