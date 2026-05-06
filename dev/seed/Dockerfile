# Pin by tag for dev/test (digest pinning is for production per rules/coding.md §1).
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt /app/
RUN pip install -r requirements.txt

COPY seed_loader.py /app/

# Runs as root: the seeder is a transient dev/test data loader (not a runtime
# service), and named-volume permissions for the SQLite path are simpler when
# the loader owns its own writes. The production API + realtime services run
# as unprivileged users — that's where the non-root pattern is enforced.
ENTRYPOINT ["python", "/app/seed_loader.py"]
