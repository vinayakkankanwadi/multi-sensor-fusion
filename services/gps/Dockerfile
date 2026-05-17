# syntax=docker/dockerfile:1.6
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/ /app/app/

EXPOSE 8090 8500/udp
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
