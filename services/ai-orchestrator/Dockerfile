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

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
