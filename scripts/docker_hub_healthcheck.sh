#!/usr/bin/env bash
set -euo pipefail

TIMEOUT="${TIMEOUT:-12}"
SKIP_PULL="${SKIP_PULL:-0}"

echo "[1/4] DNS resolve check"
for host in registry-1.docker.io auth.docker.io production.cloudflare.docker.com; do
  if ! getent hosts "$host" >/dev/null 2>&1; then
    echo "[FAIL] DNS resolve failed: $host"
    exit 10
  fi
  echo "[OK] $host"
done

echo "[2/4] Docker Hub registry HEAD"
code="$(curl -sS -o /tmp/docker_hub_registry_head.txt -w '%{http_code}' -m "$TIMEOUT" -I https://registry-1.docker.io/v2/ || true)"
if [[ "$code" != "401" && "$code" != "200" ]]; then
  echo "[FAIL] registry-1.docker.io/v2/ unexpected HTTP code: ${code:-N/A}"
  exit 20
fi
echo "[OK] registry head HTTP $code"

echo "[3/4] Docker auth endpoint"
if ! curl -sS -m "$TIMEOUT" "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/hello-world:pull" >/tmp/docker_hub_auth.json; then
  echo "[FAIL] auth.docker.io unreachable"
  exit 30
fi
if ! rg -q '"token"\s*:' /tmp/docker_hub_auth.json; then
  echo "[FAIL] auth endpoint response missing token"
  exit 31
fi
echo "[OK] auth token response"

if [[ "$SKIP_PULL" == "1" ]]; then
  echo "[4/4] skip docker pull (SKIP_PULL=1)"
  echo "PASS"
  exit 0
fi

echo "[4/4] docker pull smoke test"
if ! docker pull --quiet hello-world >/tmp/docker_hub_pull.log 2>&1; then
  echo "[FAIL] docker pull hello-world failed"
  tail -n 50 /tmp/docker_hub_pull.log || true
  exit 40
fi
echo "[OK] docker pull hello-world"

echo "PASS"
