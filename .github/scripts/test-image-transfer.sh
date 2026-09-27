#!/usr/bin/env bash
# Round-trip all platforms and attestations through a loopback-only test registry.
set -Eeuo pipefail
ARCHIVE="$(realpath "${1:?OCI archive required}")"
[[ -s "$ARCHIVE" ]]
WORK="$(mktemp -d)"
CID=''
cleanup() {
  if [[ -n "$CID" ]]; then docker rm -fv "$CID" >/dev/null 2>&1 || true; fi
  rm -rf -- "$WORK"
}
trap cleanup EXIT
CID="$(docker run --rm -d --publish 127.0.0.1::5000 --env OTEL_TRACES_EXPORTER=none registry:3)"
ENDPOINT="$(docker port "$CID" 5000/tcp)"
[[ "$ENDPOINT" =~ ^127\.0\.0\.1:[0-9]+$ ]]
READY=0
for ((i=0; i<30; i++)); do
  if curl --fail --silent --show-error --max-time 2 "http://$ENDPOINT/v2/" >/dev/null 2>&1; then READY=1; break; fi
  sleep 1
done
[[ "$READY" == 1 ]]
skopeo inspect --raw "oci-archive:$ARCHIVE" > "$WORK/source.json"
TARGET="$ENDPOINT/lyrics-fixture:verified"
skopeo copy --all --preserve-digests --dest-tls-verify=false "oci-archive:$ARCHIVE" "docker://$TARGET"
skopeo inspect --raw --tls-verify=false "docker://$TARGET" > "$WORK/published.json"
cmp "$WORK/source.json" "$WORK/published.json"
skopeo copy --all --preserve-digests --src-tls-verify=false "docker://$TARGET" "oci:$WORK/roundtrip"
skopeo inspect --raw "oci:$WORK/roundtrip" > "$WORK/roundtrip.json"
cmp "$WORK/source.json" "$WORK/roundtrip.json"
echo 'Image and attestation round trip: OK'
