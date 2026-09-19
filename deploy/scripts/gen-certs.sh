#!/usr/bin/env bash
# Usage: gen-certs.sh <out_dir> <controller_hostname> <controller_ip>
set -euo pipefail
OUT="${1:?out dir}"; CHOST="${2:?controller hostname}"; CIP="${3:?controller IP}"
mkdir -p "$OUT"; cd "$OUT"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out ca.key 2>/dev/null
openssl req -new -x509 -key ca.key -sha256 -days 3650 -subj "/CN=OSAgent CA" -out ca.crt
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out controller.key 2>/dev/null
openssl req -new -key controller.key -subj "/CN=$CHOST" -out controller.csr
printf "subjectAltName=DNS:%s,DNS:localhost,IP:%s,IP:127.0.0.1
" "$CHOST" "$CIP" > controller.ext
openssl x509 -req -in controller.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 825 -sha256 -extfile controller.ext -out controller.crt 2>/dev/null
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out agent.key 2>/dev/null
openssl req -new -key agent.key -subj "/CN=osagent-agent" -out agent.csr
openssl x509 -req -in agent.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 825 -sha256 -out agent.crt 2>/dev/null
rm -f *.csr *.ext *.srl
chmod 600 *.key
echo "OK: certificates in $OUT"
