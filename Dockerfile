FROM python:3.12-slim AS base

# libjpeg/zlib for Pillow's JPEG/PNG codecs; tini for correct signal
# forwarding so SIGTERM reaches uvicorn (and its graceful-shutdown handler)
# instead of being swallowed by PID 1.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo zlib1g tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY fonts ./fonts
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

RUN mkdir -p /app/cache

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

ENTRYPOINT ["tini", "--"]
CMD ["./entrypoint.sh"]
