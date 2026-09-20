# OSControl build stage: runs INSIDE a container and produces the install
# bundle (TLS keys, packaged daemons, configs, target installer) in /out —
# a mounted docker volume ("osagent-build"). The host needs only Docker:
# no Go, no Python, no openssl on the host.
FROM python:3.12-slim

# openssl CLI for key generation (libssl is present in the base image, the
# binary is not)
RUN apt-get update \
 && apt-get install -y --no-install-recommends openssl \
 && rm -rf /var/lib/apt/lists/*

# Sources copied from the repository (build context = repo root)
COPY daemons/ /src/daemons/
COPY deploy/target/units/ /src/units/
COPY deploy/target/sudoers.d-osagent /src/sudoers.d-osagent
COPY deploy/scripts/install.sh /src/install.sh
COPY deploy/build/build.sh /build.sh
RUN chmod +x /build.sh /src/install.sh

CMD ["/build.sh"]
