# 운영 game-server·front-a 와 같은 OS·Python·패키지(Ubuntu 24.04, Python 3.12.3, requirements-prod.txt·requirements-front.txt)
FROM ubuntu:24.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev build-essential pkg-config default-libmysqlclient-dev iproute2 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-prod.txt requirements-front.txt /tmp/
RUN python3.12 -m venv /venv && /venv/bin/pip install --no-cache-dir -r /tmp/requirements-prod.txt -r /tmp/requirements-front.txt
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
