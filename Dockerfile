FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV KRILL_BRAINDUMP_PATH=/app/data/braindump.db

WORKDIR /app

RUN useradd --create-home --shell /usr/sbin/nologin krill

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY static /app/static
COPY docker-entrypoint.sh /app/docker-entrypoint.sh

RUN mkdir -p /app/data

RUN chmod +x /app/docker-entrypoint.sh && chown -R krill:krill /app

USER krill

EXPOSE 8055

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8055/api/settings', timeout=4)"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8055"]
