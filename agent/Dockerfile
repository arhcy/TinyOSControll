FROM python:3.12-slim

# bash + docker CLI (to drive the host daemon via the mounted socket) +
# procps for host metrics + systemd (provides `systemctl`, which reaches the
# host's systemd over the mounted /run/systemd/private socket, see
# deploy/agent/docker-compose.yml). amd-smi is AMD-specific and is provided at
# deploy time (see docs/SPEC.md "Telemetry").
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash ca-certificates procps docker.io systemd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/tinyos
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY agent/agent.py ./agent.py
COPY agent/hostcmd.sh ./hostcmd.sh
COPY agent/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./hostcmd.sh ./entrypoint.sh

# Host-management agent: runs as root with host PID/network and the docker
# socket mounted (see deploy/agent/docker-compose.yml). Only the fixed
# hostcmd.sh operations are reachable.
ENTRYPOINT ["bash", "/opt/tinyos/entrypoint.sh"]
