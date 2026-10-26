#!/usr/bin/env bash
# The issue bridge between drmoyassine/ams and drmoyassine/ai-native-bi (the same file in both repositories).
#  - An issue here labelled OUT_LABEL is copied to OTHER_REPO as a new issue labelled COPY_LABEL, linked both ways (once).
#  - When a copy that came from OTHER_REPO (labelled IN_LABEL) is closed here, the original gets the outcome and the last
#    comment, and is closed the same way.
# Inputs (env): GH_TOKEN (a token with Issues: read and write on both repositories), THIS_REPO, OTHER_REPO, OUT_LABEL, IN_LABEL, COPY_LABEL,
# ACTION, NUMBER, plus the event's issue fields. Titles and bodies arrive only through env, never inlined into the script.
set -euo pipefail

ensure_label() { # repo name color description
  gh label create "$2" --repo "$1" --color "$3" --description "$4" --force >/dev/null
}

if [[ "$ACTION" == "opened" || "$ACTION" == "labeled" ]]; then
  jq -e --arg l "$OUT_LABEL" 'index($l)' <<<"$LABELS" >/dev/null || { echo "not labelled $OUT_LABEL"; exit 0; }
  if gh api "repos/$THIS_REPO/issues/$NUMBER/comments" --paginate --jq '.[].body' | grep -q '<!-- bridge:sent-to '; then
    echo "already sent"; exit 0
  fi
  ensure_label "$OTHER_REPO" "$COPY_LABEL" 0e8a16 "A request copied from $THIS_REPO by the issue bridge"
  body=$(printf '%s\n\n---\nFrom %s#%s by @%s: %s\n<!-- bridge:from %s#%s -->' \
    "${BODY:-}" "$THIS_REPO" "$NUMBER" "$AUTHOR" "$URL" "$THIS_REPO" "$NUMBER")
  new_url=$(gh issue create --repo "$OTHER_REPO" --title "$TITLE" --body "$body" --label "$COPY_LABEL")
  gh issue comment "$NUMBER" --repo "$THIS_REPO" \
    --body "$(printf 'Sent to %s: %s\n<!-- bridge:sent-to %s -->' "$OTHER_REPO" "$new_url" "$new_url")"
  echo "sent to $new_url"
  exit 0
fi

if [[ "$ACTION" == "closed" ]]; then
  jq -e --arg l "$IN_LABEL" 'index($l)' <<<"$LABELS" >/dev/null || { echo "not labelled $IN_LABEL"; exit 0; }
  origin=$(grep -oE '<!-- bridge:from [^ ]+#[0-9]+ -->' <<<"${BODY:-}" | tail -1 | sed -E 's/<!-- bridge:from ([^ ]+) -->/\1/') || true
  [[ -n "$origin" ]] || { echo "no origin marker"; exit 0; }
  origin_repo=${origin%#*}; origin_number=${origin##*#}
  [[ "$origin_repo" == "$OTHER_REPO" ]] || { echo "origin $origin_repo is not $OTHER_REPO"; exit 0; }
  last=$(gh api "repos/$THIS_REPO/issues/$NUMBER/comments" --paginate --jq '[.[] | select(.body | contains("<!-- bridge:") | not)] | last | .body // ""')
  reason=${STATE_REASON:-completed}
  msg=$(printf 'Closed in %s (%s): %s' "$THIS_REPO" "$reason" "$URL")
  [[ -n "$last" ]] && msg=$(printf '%s\n\nLast comment there:\n\n%s' "$msg" "$(sed 's/^/> /' <<<"$last")")
  gh issue comment "$origin_number" --repo "$origin_repo" --body "$(printf '%s\n<!-- bridge:closed -->' "$msg")"
  if [[ "$reason" == "not_planned" ]]; then
    gh issue close "$origin_number" --repo "$origin_repo" --reason "not planned"
  else
    gh issue close "$origin_number" --repo "$origin_repo" --reason completed
  fi
  echo "closed $origin"
fi
