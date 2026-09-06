#!/data/data/com.termux/files/usr/bin/bash
# Termux user-side transport and preflight. Does not install APKs or change Git configuration.
set -euo pipefail
stage=preflight
trap 'status=$?; if [ "$status" -ne 0 ]; then printf "[failed] stage=%s exit=%s\n" "$stage" "$status" >&2; fi' EXIT

proxy=${SELFFONT_PROXY:-http://127.0.0.1:7890}
export http_proxy="$proxy" https_proxy="$proxy" HTTP_PROXY="$proxy" HTTPS_PROXY="$proxy"
export no_proxy=localhost,127.0.0.1,::1 NO_PROXY=localhost,127.0.0.1,::1
for tool in curl gh sha256sum mktemp su; do
    command -v "$tool" >/dev/null || { echo "Missing command: $tool" >&2; exit 2; }
done

stage=network
printf '[1/5] Proxy and GitHub API\n'
code=$(curl --proxy "$proxy" --fail --silent --show-error \
    --connect-timeout 10 --max-time 30 --retry 2 --retry-delay 2 --retry-connrefused \
    -o /dev/null -w '%{http_code}' https://api.github.com)
printf 'GitHub API HTTP %s\n' "$code"
[ "$code" = 200 ] || { echo 'Network preflight failed; no root command was run.' >&2; exit 3; }

stage=authentication
printf '[2/5] Existing GitHub login\n'
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
    echo 'Login unavailable. Complete gh auth login -h github.com -p https -w, then rerun.' >&2
    exit 4
fi

work=$(mktemp -d "$HOME/selffont-metrics.XXXXXX")
stage=artifact
printf '[3/5] Pinned diagnostic container\n'
# Each attempt has a fresh directory, so an incomplete previous extraction cannot be reused.
artifact=
for attempt in 1 2; do
    dir="$work/download-$attempt"
    mkdir "$dir"
    if gh run download 34006028276 -R Sumicya/Selffont \
        -n selffont-phase1-debug-apk -D "$dir"; then
        artifact="$dir/app-debug.apk"
        [ -s "$artifact" ] && break
        artifact=
    fi
done
[ -n "$artifact" ] || { echo 'Artifact download failed; no root command was run.' >&2; exit 5; }

stage=launcher
printf '[4/5] Verify standalone launcher\n'
gh api -H 'Accept: application/vnd.github.raw+json' \
    'repos/Sumicya/Selffont/contents/tools/run_font_probe.sh?ref=09f145e2cdcf67ea60db8f20acdf6570cbda8bb9' \
    > "$work/run.sh"
printf '%s  %s\n' \
    '456f85204e0796124b2de71769692df7ad67c1eee27a4a847ab6285a70b22f7e' \
    "$work/run.sh" | sha256sum -c -

stage=measurement
printf '[5/5] Standalone Android font measurement (no installation)\n'
status=0
su -c "sh '$work/run.sh' '$artifact'" || status=$?
printf 'Probe exit=%s; diagnostics printed above.\n' "$status"
exit "$status"
