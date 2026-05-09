FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV KRILL_BRAINDUMP_PATH=/app/data/braindump.db
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV KRILL_ENABLE_XVFB=1
ENV DISPLAY=:99

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin krill

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        chromium \
        xvfb \
        git \
        openssh-client \
        gh \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY pi-sidecar /app/pi-sidecar
COPY app /app/app
COPY static /app/static
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

RUN npm --prefix /app/pi-sidecar install --omit=dev
RUN npm --prefix /app/app/integrations/whatsapp/sidecar install --omit=dev

RUN mkdir -p /app/data

RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh && chown -R krill:krill /app

USER krill

EXPOSE 8055

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8055/api/auth/status', timeout=4)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8055", "--proxy-headers", "--forwarded-allow-ips", "*"]
