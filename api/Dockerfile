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

RUN useradd --system --no-create-home app
USER app

EXPOSE 8000

CMD ["sh", "/app/entrypoint.sh"]
