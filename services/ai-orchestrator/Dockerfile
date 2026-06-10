# ⚠ NOTE: this Dockerfile was originally `FROM python:latest` — see Item 11
# in docs/brownfield-debt.md. It was hand-pinned to 3.11 in 2026-Q1 after
# numpy/pydantic-core wheels broke on python 3.14. The OTHER Dockerfiles
# (api-gateway, contract-modification-service, invoice-review-service, frontend) still
# carry the :latest debt. Cohort finds those in W4 Wed AI Security
# Engineering Day (OWASP LLM03 Supply Chain).
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download cross-encoder model at build time — never pull at runtime (ADR-0005 §5)
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY app ./app
# Finding 4: scripts/ MUST be in the image — the entrypoint runs
# `python -m scripts.create_indexes` to create the Atlas search indexes on
# startup. Without this COPY the indexes never exist and every POST /retrieve
# returns 502 'Both retrieval paths failed'.
COPY scripts ./scripts
RUN chmod +x ./scripts/entrypoint.sh

EXPOSE 8000
# Run index bootstrap (idempotent) before exec'ing uvicorn. The entrypoint
# fails loudly (non-zero exit) if index creation fails — §10 no-silent-failure.
ENTRYPOINT ["./scripts/entrypoint.sh"]
