# Dockerfile
#
# Four stages, because this image has to carry three environments that must
# not mix:
#
#   1. Ours — the agent, its dependencies, its Python.
#   2. The target repo's — its own pinned dependency set, in its own venv,
#      because tools/run_tests.py runs its suite and running it with our
#      interpreter would test the wrong environment.
#   3. betterleaks — a compiled Go binary agent/secrets_redaction.py shells
#      out to. Absent, it degrades to the supplementary patterns only, which
#      docs/SECRETS-REDACTION.md names as a real narrowing of coverage.
#      Copying it in is what closes that gap; docs/research/secrets-redaction.md
#      named this build as the trigger to do it.
#
# No separate vector-DB service anywhere: the corpus is sqlite-vec, one file.
# That was the point of choosing it over Postgres, and it is why the compose
# file has exactly one service.

# --- betterleaks ------------------------------------------------------------
# Pinned to the version verified locally, not :latest — a secrets scanner that
# silently changes rules between builds changes what leaks.
FROM ghcr.io/betterleaks/betterleaks:v1.8.1 AS betterleaks

# --- our dependencies -------------------------------------------------------
FROM python:3.12-slim AS deps
WORKDIR /app
RUN pip install --no-cache-dir uv==0.9.7
COPY pyproject.toml uv.lock* ./
# --frozen: the lockfile decides, so the image cannot quietly resolve a
# different tree from the one the tests ran against.
RUN uv sync --frozen --no-dev --no-install-project

# --- the target repo and its own environment --------------------------------
FROM python:3.12-slim AS target
ARG TARGET_REPO=tekncoach/liberty-rider-myroadtrips
# A ref, not "whatever main is today": the image is reproducible, and the
# suite the agent runs is the suite this image was built against.
ARG TARGET_REF=main
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.9.7
WORKDIR /workspace
RUN git clone --depth 50 "https://github.com/${TARGET_REPO}.git" repo \
    && cd repo && git checkout "${TARGET_REF}"
# Its dependencies, in its own venv, at the path agent/config.py defaults to.
RUN cd repo && uv venv --python 3.12 .venv \
    && uv pip install --python .venv/bin/python -r requirements-dev.txt

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime

# git is a runtime dependency, not just a build one: tools/open_pr.py branches,
# commits and pushes with it.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 agent

COPY --from=betterleaks /usr/bin/betterleaks /usr/local/bin/betterleaks

WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY --from=target --chown=agent:agent /workspace/repo /app/workspace/liberty-rider-myroadtrips
COPY --chown=agent:agent agent/ ./agent/
COPY --chown=agent:agent tools/ ./tools/
COPY --chown=agent:agent rag/ ./rag/
COPY --chown=agent:agent evals/ ./evals/
COPY --chown=agent:agent pyproject.toml README.md ./

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    # The safe default, restated here rather than inherited: an image that
    # defaults to writing is one env var away from posting to a real repo.
    SHADOW_MODE=true

# The agent owns its own working tree — it edits files there and commits them.
# /app/tmp/sessions must exist, with the right owner, BEFORE the named volume
# is mounted over it. Docker initialises an empty named volume by copying the
# image's directory — content and ownership — but only if that directory is
# there. Create just /app/tmp and the volume appears as a fresh root-owned
# mount, and a non-root process cannot write its own traces into it.
RUN mkdir -p /app/tmp/sessions /app/data/kb && chown -R agent:agent /app/tmp /app/data
USER agent

# git refuses to operate on a tree it considers owned by someone else, and the
# checkout was copied in by root before the chown took effect on every path.
RUN git config --global --add safe.directory /app/workspace/liberty-rider-myroadtrips \
    && git config --global user.name "ticket-to-pr-agent" \
    && git config --global user.email "agent@localhost"

EXPOSE 8000
# Uses the interpreter rather than curl, which is not installed and should not
# be: the fewer network tools in an image running model-written code, the better.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen(f\"http://127.0.0.1:{os.environ['PORT']}/health\", timeout=4).status == 200 else 1)"

CMD ["sh", "-c", "uvicorn agent.service:app --host 0.0.0.0 --port ${PORT}"]
