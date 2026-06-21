#!/usr/bin/env bash
# fix-cold-open: deterministic, grade.json-routed repair of a short's cold open.
# NON-FATAL by construction — any error leaves the input untouched and exits 0,
# never corrupts a clip. Two modes:
#   preventive (in-chain): the 16:9 source + .vert.fillplan.json + .broll_plan.json
#     all live in work/<id>/; every op is clean (truncate cold-open b-roll, re-punch
#     the speaker on shot 0, re-fire credit/title).
#   curative (standalone backlog): a finished output/<src>/x.mp4 with the defect
#     BAKED into pixels and no co-located source -> emit rerun_recommended, never
#     fabricate a degraded re-crop.
set -uo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
[[ -f "$root/.env" ]] && { set -a; . "$root/.env"; set +a; }

clip="${1:-}"
grade_arg="${2:-}"

if [[ -z "$clip" ]]; then
  echo "usage: fix-cold-open.sh <clip.mp4> [grade.json]" >&2
  exit 2
fi
if [[ ! -f "$clip" ]]; then
  # non-fatal: nothing to repair, nothing to corrupt
  echo "fix-cold-open: input not found: $clip (passthrough)" >&2
  exit 0
fi

guard="${FIXCO_OPEN_GUARD_SEC:-2.2}"
stem="${clip%.*}"
grade="${grade_arg:-$stem.grade.json}"
# in-chain clips share a clip_NN stem; the grade may also be at clip_NN.final.grade.json
clipdir="$(cd "$(dirname "$clip")" && pwd)"
base="$(basename "$clip")"
ccore=""
if [[ "$base" =~ ^(clip_[0-9]+)\. ]]; then
  ccore="${BASH_REMATCH[1]}"
fi
report="$stem.fix.json"

# ---- non-fatal passthrough: report nothing changed, exit 0 -----------------
emit() {
  # $1 ran-json-array  $2 skipped-json-array  $3 output  $4 rerun_recommended(bool)
  python3 - "$report" "$1" "$2" "$3" "$4" "$mode" <<'PY' 2>/dev/null || true
import json, sys
report, ran, skipped, output, rerun, mode = sys.argv[1:7]
doc = {
    "mode": mode,
    "ran": json.loads(ran or "[]"),
    "skipped": json.loads(skipped or "[]"),
    "output": output,
    "rerun_recommended": rerun == "1",
}
json.dump(doc, open(report, "w"), indent=2)
print(json.dumps(doc))
PY
}

# ---- locate the grade -------------------------------------------------------
if [[ ! -f "$grade" && -n "$ccore" ]]; then
  for g in "$clipdir/$ccore.final.grade.json" "$clipdir/$ccore.grade.json"; do
    [[ -f "$g" ]] && { grade="$g"; break; }
  done
fi
if [[ ! -f "$grade" ]]; then
  echo "fix-cold-open: no grade.json for $clip (passthrough)" >&2
  mode="${FIXCO_MODE:-auto}"
  emit '[]' '[{"route":"all","reason":"no_grade_json"}]' "$clip" 0
  exit 0
fi

# ---- read routes + tier -----------------------------------------------------
tier="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("tier",""))' "$grade" 2>/dev/null || echo "")"
FR=()
while IFS= read -r line; do [[ -n "$line" ]] && FR+=("$line"); done < <(python3 "$here/plan.py" routes "$grade" 2>/dev/null || true)

if [[ "$tier" == "GOLD" || "${#FR[@]}" -eq 0 ]]; then
  echo "fix-cold-open: nothing to fix (tier=$tier routes=${#FR[@]}) — passthrough" >&2
  mode="${FIXCO_MODE:-auto}"
  emit '[]' '[]' "$clip" 0
  exit 0
fi

has_route() { local r; for r in "${FR[@]}"; do [[ "$r" == "$1" ]] && return 0; done; return 1; }

# ---- resolve sidecars (in-chain) -------------------------------------------
fill=""; broll=""; src16=""; preclean=""; ingest=""; title=""
if [[ -n "$ccore" ]]; then
  for f in "$clipdir/$ccore.vert.fillplan.json" "$clipdir/$ccore.fillplan.json"; do
    [[ -f "$f" ]] && { fill="$f"; break; }
  done
  [[ -f "$clipdir/$ccore.broll_plan.json" ]] && broll="$clipdir/$ccore.broll_plan.json"
  if [[ -f "$clipdir/$ccore.src16.path" ]]; then
    s="$(cat "$clipdir/$ccore.src16.path" 2>/dev/null || true)"
    [[ -n "$s" && -f "$s" ]] && src16="$s"
  fi
  # the clean vertical BEFORE broll-composite (so a re-composite starts clean).
  # search the chain in reverse precedence: switch-faces -> zoom -> jump-cut -> vert.
  for p in "$clipdir/$ccore.sw.mp4" "$clipdir/$ccore.zoom.mp4" "$clipdir/$ccore.jc.mp4" "$clipdir/$ccore.vert.mp4"; do
    [[ -f "$p" ]] && { preclean="$p"; break; }
  done
  [[ -f "$clipdir/ingest.json" ]] && ingest="$clipdir/ingest.json"
  [[ -f "$clipdir/$ccore.title.txt" ]] && title="$clipdir/$ccore.title.txt"
fi

# ---- mode detection ---------------------------------------------------------
# preventive needs the in-chain source artifacts; curative is everything else.
mode="${FIXCO_MODE:-auto}"
if [[ "$mode" == "auto" ]]; then
  if [[ -n "$broll" || ( -n "$fill" && -n "$src16" ) ]]; then
    mode="preventive"
  else
    mode="curative"
  fi
fi
echo "fix-cold-open: mode=$mode tier=$tier routes=${FR[*]}" >&2

ran="[]"; skipped="[]"
push_ran()     { ran="$(python3 -c 'import json,sys;a=json.loads(sys.argv[1]);a.append(sys.argv[2]);print(json.dumps(a))' "$ran" "$1")"; }
push_skip()    { skipped="$(python3 -c 'import json,sys;a=json.loads(sys.argv[1]);a.append({"route":sys.argv[2],"reason":sys.argv[3]});print(json.dumps(a))' "$skipped" "$1" "$2")"; }

# rerun_recommended is structural (letterbox = old render) — never repairable in
# place. If present we make NO pixel change and flag it.
rerun=0
if has_route "rerun_recommended"; then
  rerun=1
  push_skip "rerun_recommended" "structural (letterbox / old render) — re-run pipeline"
fi

# ---- CURATIVE honesty gate --------------------------------------------------
# In curative mode the defect is baked into pixels and we usually have NO 16:9
# source. shot0_repunch / broll_open_truncate are ONLY clean with the source +
# plans. Without them, recover NOTHING (a re-crop toward a face that isn't there
# zooms into the b-roll — a regression). Flag rerun_recommended and stop.
if [[ "$mode" == "curative" ]]; then
  if [[ -z "$src16" && -z "$broll" ]]; then
    if has_route "shot0_repunch"; then push_skip "shot0_repunch" "no recoverable 16:9 source — face is baked into pixels"; fi
    if has_route "broll_open_truncate"; then push_skip "broll_open_truncate" "no broll_plan/clean-vertical co-located — cannot re-composite"; fi
    if has_route "credit_rerender"; then push_skip "credit_rerender" "no co-located source artifacts"; fi
    if has_route "card_rerender"; then push_skip "card_rerender" "no co-located source artifacts"; fi
    echo "fix-cold-open: curative w/o recoverable source — rerun_recommended (no degradation)" >&2
    emit "$ran" "$skipped" "$clip" 1
    exit 0
  fi
  echo "fix-cold-open: curative WITH co-located work artifacts — repairing in place" >&2
fi

# ---- idempotency signature --------------------------------------------------
mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1"; }
sig="$(mtime "$clip")|$(mtime "$grade")|guard=$guard|mode=$mode|routes=${FR[*]}|v1"
out="$stem.fixed.mp4"
[[ "$mode" == "preventive" ]] && out="$clipdir/$ccore.fixed.mp4"
meta="$out.fixmeta"
if [[ -f "$out" && -f "$meta" && "$(cat "$meta")" == "$sig" ]]; then
  echo "fix-cold-open: cache hit at $out" >&2
  cat "$report" 2>/dev/null || emit "$ran" "$skipped" "$out" "$rerun"
  exit 0
fi

mkdir -p "$(dirname "$out")"
work="$clip"        # the current best clip we keep repairing
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# ============================================================================
# (b) shot0_repunch — force a fill-vertical speaker re-punch on shot 0.
# fillplan shot0.kind != face => the speaker's face was withheld at the open.
# This RE-RUNS face detection (identity clusters are not persisted) — a real
# per-clip cost; flagged in logs. Needs the 16:9 source.
# ============================================================================
repunched=0
if has_route "shot0_repunch"; then
  if [[ -z "$src16" ]]; then
    push_skip "shot0_repunch" "no 16:9 source (src16.path) — cannot re-detect the speaker"
  else
    k0="$(python3 "$here/plan.py" shot0 "$fill" 2>/dev/null || true)"
    echo "fix-cold-open: shot0_repunch — RE-RUNNING fill-vertical face detection on $src16 (shot0.kind=$k0) [per-clip cost]" >&2
    newvert="$tmp/repunch.vert.mp4"
    # tighter face_frac bias would over-zoom; use the skill default. The skill
    # writes <out_stem>.fillplan.json beside newvert.
    if bash "$(cd "$here/../fill-vertical" && pwd)/fill-vertical.sh" "$src16" "$newvert" >/dev/null 2>&1 && [[ -f "$newvert" ]]; then
      k0new="$(python3 "$here/plan.py" shot0 "${newvert%.*}.fillplan.json" 2>/dev/null || true)"
      if [[ "$k0new" == "face" ]]; then
        # adopt the re-punched vertical as the new clean base; downstream b-roll
        # (below) re-composites onto it so the open shows the speaker.
        preclean="$newvert"
        # if no broll to re-composite, the re-punched vertical IS the repair
        # (but it has no captions/title/brand — only safe in-chain where the
        # caller re-runs the rest of the chain). Keep it as the working clip ONLY
        # when there's a broll step to follow; otherwise we must NOT ship a
        # caption-less clip, so we record the new fillplan + flag rerun of the
        # downstream chain.
        repunched=1
        push_ran "shot0_repunch"
        echo "fix-cold-open: shot0_repunch OK — new shot0.kind=$k0new" >&2
      else
        push_skip "shot0_repunch" "re-detection still kind=$k0new (no clear speaker on shot 0)"
      fi
    else
      push_skip "shot0_repunch" "fill-vertical re-run failed"
    fi
  fi
fi

# ============================================================================
# (a) broll_open_truncate — drop any broll_plan picks window overlapping
# [0, guard] and re-composite onto the clean vertical so frame 1 is the speaker.
# Also the carrier for a shot0_repunch result (re-composite onto the new vert).
# ============================================================================
composited=0
if has_route "broll_open_truncate" || [[ "$repunched" -eq 1 ]]; then
  if [[ -z "$broll" ]]; then
    has_route "broll_open_truncate" && push_skip "broll_open_truncate" "no broll_plan.json co-located"
  elif [[ -z "$preclean" ]]; then
    has_route "broll_open_truncate" && push_skip "broll_open_truncate" "no clean pre-broll vertical to re-composite onto"
  else
    newplan="$tmp/broll_plan.truncated.json"
    dropped="$(python3 "$here/plan.py" truncate "$broll" "$newplan" "$guard" 2>/dev/null || echo '[]')"
    ndrop="$(python3 -c 'import json,sys;print(len(json.loads(sys.argv[1])))' "$dropped" 2>/dev/null || echo 0)"
    if has_route "broll_open_truncate" && [[ "$ndrop" -eq 0 && "$repunched" -eq 0 ]]; then
      push_skip "broll_open_truncate" "no broll pick overlaps [0,$guard]"
    else
      echo "fix-cold-open: broll re-composite — dropped $ndrop cold-open cutaway(s) over [0,$guard]; base=$(basename "$preclean")" >&2
      recomp="$tmp/recomp.mp4"
      if bash "$(cd "$here/../broll-composite" && pwd)/broll-composite.sh" "$preclean" "$newplan" "$recomp" >/dev/null 2>&1 && [[ -f "$recomp" ]]; then
        work="$recomp"
        composited=1
        has_route "broll_open_truncate" && [[ "$ndrop" -gt 0 ]] && push_ran "broll_open_truncate"
        echo "fix-cold-open: re-composite OK -> $(basename "$recomp")" >&2
      else
        has_route "broll_open_truncate" && push_skip "broll_open_truncate" "broll-composite re-run failed"
      fi
    fi
  fi
fi

# ============================================================================
# (c) credit_rerender / card_rerender — re-fire brand-overlays / title-transition.
# These act on the CURRENT working clip (post b-roll/repunch) so the fix stacks.
# ============================================================================
if has_route "credit_rerender"; then
  if [[ -z "$ingest" ]]; then
    push_skip "credit_rerender" "no ingest.json co-located for brand-overlays"
  else
    creout="$tmp/credited.mp4"
    if bash "$(cd "$here/../brand-overlays" && pwd)/brand-overlays.sh" "$work" "$ingest" "$creout" >/dev/null 2>&1 && [[ -f "$creout" ]]; then
      work="$creout"; push_ran "credit_rerender"
      echo "fix-cold-open: credit_rerender OK (brand-overlays re-fired)" >&2
    else
      push_skip "credit_rerender" "brand-overlays re-run failed"
    fi
  fi
fi

if has_route "card_rerender"; then
  if [[ -z "$title" ]]; then
    push_skip "card_rerender" "no title.txt co-located for title-transition"
  else
    ttxt="$(cat "$title" 2>/dev/null || true)"
    if [[ -z "$ttxt" ]]; then
      push_skip "card_rerender" "title.txt empty"
    else
      ttout="$tmp/titled.mp4"
      if bash "$(cd "$here/../title-transition" && pwd)/title-transition.sh" "$work" "$ttxt" "$ttout" >/dev/null 2>&1 && [[ -f "$ttout" ]]; then
        work="$ttout"; push_ran "card_rerender"
        echo "fix-cold-open: card_rerender OK (title-transition re-fired)" >&2
      else
        push_skip "card_rerender" "title-transition re-run failed"
      fi
    fi
  fi
fi

# ---- finalize ---------------------------------------------------------------
nran="$(python3 -c 'import json,sys;print(len(json.loads(sys.argv[1])))' "$ran" 2>/dev/null || echo 0)"
if [[ "$nran" -eq 0 ]]; then
  # nothing actually repaired — do NOT emit a fixed.mp4 (would just be a copy).
  echo "fix-cold-open: no op applied — input untouched" >&2
  emit "$ran" "$skipped" "$clip" "$rerun"
  exit 0
fi

if [[ "$work" == "$clip" ]]; then
  # repunch produced a new fillplan but no carrier (no b-roll) — the repaired
  # vertical exists but lacks the downstream chain; surface it without faking a
  # finished clip.
  echo "fix-cold-open: repaired the source framing but downstream chain (captions/title/brand) must be re-run — surfacing rerun_recommended" >&2
  rerun=1
  emit "$ran" "$skipped" "$clip" 1
  exit 0
fi

cp "$work" "$out"
printf '%s' "$sig" > "$meta"
echo "fix-cold-open: wrote $out (ran: $ran)" >&2
emit "$ran" "$skipped" "$out" "$rerun"
exit 0
