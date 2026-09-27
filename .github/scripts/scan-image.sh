#!/usr/bin/env bash
# Scan each platform of the verified OCI artifact without mounting a Docker socket.
set -Eeuo pipefail
INPUT="$(realpath "${1:?usage: scan-image.sh OCI_LAYOUT PLATFORM REPORT_DIR}")"
PLATFORM="${2:?platform required}"
OUT="${3:?report directory required}"
case "$PLATFORM" in linux/amd64|linux/arm64) ;; *) exit 2 ;; esac
[[ -s "$INPUT/index.json" && -s "$INPUT/oci-layout" ]]
CACHE="${TRIVY_CACHE_DIR:-${RUNNER_TEMP:-/tmp}/lyrics-trivy-cache}"
mkdir -p "$OUT" "$CACHE"
OUT="$(realpath "$OUT")"
CACHE="$(realpath "$CACHE")"
TRIVY_IMAGE="${TRIVY_IMAGE:-ghcr.io/aquasecurity/trivy:latest}"
trivy() {
  docker run --rm \
    --mount "type=bind,src=$INPUT,dst=/image,readonly" \
    --mount "type=bind,src=$OUT,dst=/out" \
    --mount "type=bind,src=$CACHE,dst=/root/.cache/trivy" \
    "$TRIVY_IMAGE" "$@"
}
# Keep all findings in the report, including vulnerabilities without fixes.
trivy image --input /image --platform "$PLATFORM" --scanners vuln \
  --pkg-types os,library --no-progress --format json --output /out/trivy.json
[[ -s "$OUT/trivy.json" ]]
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("Metadata",{}).get("OS",{}).get("Family")=="debian"; assert any(r.get("Type")=="debian" for r in d.get("Results",[])); assert any(r.get("Type")=="python-pkg" for r in d.get("Results",[]))' "$OUT/trivy.json"
trivy convert --format sarif --severity HIGH,CRITICAL --output /out/trivy.sarif /out/trivy.json
trivy convert --format table --scanners vuln --severity HIGH,CRITICAL --output /out/all-high-critical.txt /out/trivy.json
# 42 = fixable HIGH/CRITICAL; 43 = detected OS EOL. Tool failures also block.
if trivy image --input /image --platform "$PLATFORM" --scanners vuln \
  --pkg-types os,library --no-progress --skip-db-update \
  --ignore-unfixed --severity HIGH,CRITICAL --exit-code 42 --exit-on-eol 43 \
  --format table --output /out/fixable.txt; then
  [[ -s "$OUT/fixable.txt" ]]
  cat "$OUT/fixable.txt"
else
  rc=$?
  if [[ -f "$OUT/fixable.txt" ]]; then cat "$OUT/fixable.txt"; fi
  printf 'Security gate blocked %s (exit %s).\n' "$PLATFORM" "$rc" >&2
  exit "$rc"
fi
