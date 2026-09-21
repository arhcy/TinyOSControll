#!/usr/bin/env bash
# Generate the shared self-signed certificate used for mTLS between main and
# agents. One certificate serves as the server cert (main) and the client cert
# (agents); it is also its own CA, so it is the trust anchor for both sides.
#
# Usage: tools/gen-certs.sh <out_dir> <main_host>
#   <out_dir>    directory to write cert.key + cert.crt into (created if needed)
#   <main_host>  IP or hostname agents use to reach main (added to the SAN)
#
# Requires OpenSSL 1.1.1+ (for -addext).
set -euo pipefail

OUT_DIR="${1:?usage: gen-certs.sh <out_dir> <main_host>}"
MAIN_HOST="${2:?usage: gen-certs.sh <out_dir> <main_host>}"

# Build the SAN entry for main: IP: for addresses, DNS: for hostnames.
if [[ "$MAIN_HOST" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ || "$MAIN_HOST" =~ ^[0-9a-fA-F:]+$ ]]; then
  SAN_MAIN="IP:${MAIN_HOST}"
else
  SAN_MAIN="DNS:${MAIN_HOST}"
fi

mkdir -p "$OUT_DIR"
KEY="$OUT_DIR/cert.key"
CRT="$OUT_DIR/cert.crt"

# 10-year self-signed cert, valid as server AND client, trusted as its own CA.
openssl req -x509 -newkey rsa:3072 -sha256 -nodes \
  -keyout "$KEY" -out "$CRT" -days 3650 \
  -subj "/CN=TinyOSControll" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign" \
  -addext "extendedKeyUsage=serverAuth,clientAuth" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,${SAN_MAIN}"

chmod 600 "$KEY"
echo "wrote $KEY and $CRT (SAN includes $SAN_MAIN, localhost, 127.0.0.1)"
