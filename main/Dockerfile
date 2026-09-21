FROM python:3.12-slim

# ca-certificates so the self-signed mgmt/web certs resolve; aiohttp is the
# only runtime dependency (web + mTLS WS server + SSE).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/tinyos
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY main/main.py ./main.py
COPY main/web/ ./web/

# main holds no host access: it only serves the web UI/API, accepts agent
# mTLS connections, and sends WoL packets (see deploy/main/docker-compose.yml).
ENV WEB_ROOT=/opt/tinyos/web
ENTRYPOINT ["python3", "/opt/tinyos/main.py"]
