#!/bin/sh
# Container start: migrate, bootstrap the catalog, then serve. Idempotent, so a
# plain `docker compose up -d --build` is the whole deployment.
set -e
(cd /db && alembic upgrade head)
python scripts/bootstrap.py
# --proxy-headers: trust X-Forwarded-For from the reverse proxy (port 8000 is only
# reachable on the compose network) so rate limiting sees real client IPs.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"
