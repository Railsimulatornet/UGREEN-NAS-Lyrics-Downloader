#!/usr/bin/env bash
# Promote one verified multi-platform artifact to both registries, without a rebuild.
set -Eeuo pipefail
umask 077
ARCHIVE="$(realpath "${1:?OCI archive required}")"
TAG="${2:?release or unique build tag required}"
[[ -s "$ARCHIVE" ]]
[[ "$TAG" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-build\.[0-9]{8}\.[0-9]+\.[0-9]+)?$ ]]
: "${GH_TOKEN:?GHCR token required}"
: "${REGISTRY_USER:?GHCR user required}"
: "${DOCKERHUB_USERNAME:?Docker Hub user required}"
: "${DOCKERHUB_TOKEN:?Docker Hub token required}"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
AUTH="$WORK/auth.json"
printf '%s' "$GH_TOKEN" | skopeo login --authfile "$AUTH" --username "$REGISTRY_USER" --password-stdin ghcr.io
printf '%s' "$DOCKERHUB_TOKEN" | skopeo login --authfile "$AUTH" --username "$DOCKERHUB_USERNAME" --password-stdin docker.io
skopeo inspect --raw "oci-archive:$ARCHIVE" > "$WORK/source.json"
EXPECTED="$(skopeo manifest-digest "$WORK/source.json")"
[[ "$EXPECTED" =~ ^sha256:[a-f0-9]{64}$ ]]
IMAGES=(ghcr.io/railsimulatornet/ugreen-nas-lyrics-downloader docker.io/railsimulatornet/ugreen-nas-lyrics-downloader)
# Preflight BOTH destinations before any write; never replace a version/build tag.
for image in "${IMAGES[@]}"; do
  if skopeo inspect --authfile "$AUTH" --raw "docker://$image:$TAG" > "$WORK/existing.json" 2> "$WORK/error"; then
    [[ "$(skopeo manifest-digest "$WORK/existing.json")" == "$EXPECTED" ]] || {
      echo "Refusing to overwrite existing image: $image:$TAG" >&2; exit 1;
    }
  elif ! grep -Eqi 'manifest unknown|MANIFEST_UNKNOWN' "$WORK/error"; then
    cat "$WORK/error" >&2; exit 1
  fi
done
for tag in "$TAG" latest; do
  for image in "${IMAGES[@]}"; do
    skopeo copy --authfile "$AUTH" --all --preserve-digests "oci-archive:$ARCHIVE" "docker://$image:$tag"
    skopeo inspect --authfile "$AUTH" --raw "docker://$image:$tag" > "$WORK/published.json"
    [[ "$(skopeo manifest-digest "$WORK/published.json")" == "$EXPECTED" ]]
    printf '%s:%s -> %s\n' "$image" "$tag" "$EXPECTED"
  done
done
