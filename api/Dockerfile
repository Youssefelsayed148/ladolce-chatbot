FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies are declared in requirements.txt and installed with pip.
# Generous timeout/retries so a transient PyPI/CDN hiccup doesn't fail the build.
COPY requirements.txt .
RUN pip install --timeout 120 --retries 10 -r requirements.txt

COPY . .

EXPOSE 8000

# --proxy-headers: trust X-Forwarded-For from nginx so rate limiting sees real client
# IPs. Safe because port 8000 is only exposed to the compose network, not the host.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
