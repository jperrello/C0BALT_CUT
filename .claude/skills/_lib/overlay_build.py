#!/usr/bin/env python3
# Build the ffmpeg input args + chained filtergraph for compose_overlays.
#
#   argv[1]      base.mp4 (ffmpeg input 0 — added by the bash caller, NOT here)
#   argv[2]      "audio" if the base has an audio stream, else ""
#   argv[3:]     N *.overlay.json spec files, applied in order
#
# Emits a NUL-delimited token stream the bash side reads into arrays:
#   <ffmpeg-input-arg>\0 …  then  "--FILTER--"\0  <video-filtergraph>\0
#   then  "--AUDIO--"\0  <audio-filter-or-empty>\0
#
# The base is ffmpeg input 0 (the caller prepends `-i base`); this script lays
# out every overlay LAYER input as inputs 1..k (with -loop/-framerate/-t as the
# spec asks), then any audio-mix wavs as the trailing inputs. The filtergraph
# chains each spec: spec0 reads [0:v] -> [s0]; spec1 reads [s0] -> [s1]; the
# last spec's output is renamed [v]. Each spec's {Ln} tokens map to its layer
# inputs' global indices; {IN}/{OUT} are the chain labels.
import json
import sys

base = sys.argv[1]
has_audio = sys.argv[2] == "audio"
specs = sys.argv[3:]

out = []


def emit(tok):
    out.append(tok)


# Input 0 is the base (added by the caller). Layer inputs start at index 1.
idx = 1
chain = []         # filter snippets, in order
audio_mixes = []   # (input_index, apad) for spec audio.mix wavs

prev_label = "0:v"
for si, path in enumerate(specs):
    with open(path) as f:
        spec = json.load(f)
    inputs = spec.get("inputs", [])
    layer_indices = []
    for inp in inputs:
        # -loop 1 -t DUR for a single looped still; -framerate for a PNG seq;
        # plain -i for a ProRes/mov asset.
        if inp.get("loop"):
            emit("-loop"); emit("1")
            if inp.get("t") is not None:
                emit("-t"); emit(str(inp["t"]))
        if inp.get("framerate") is not None:
            emit("-framerate"); emit(str(inp["framerate"]))
        emit("-i"); emit(inp["path"])
        layer_indices.append(idx)
        idx += 1

    out_label = "v" if si == len(specs) - 1 else f"s{si}"
    flt = spec.get("filter", "")
    flt = flt.replace("{IN}", prev_label).replace("{OUT}", out_label)
    for li, gi in enumerate(layer_indices):
        flt = flt.replace("{L%d}" % li, "%d:v" % gi)
    chain.append(flt)
    prev_label = out_label

    audio = spec.get("audio")
    if audio and audio.get("mix"):
        emit("-i"); emit(audio["mix"])
        audio_mixes.append((idx, bool(audio.get("apad"))))
        idx += 1

video_fg = ";".join(chain)

# Audio: if any spec folded a mix wav, amix base audio + every mix wav
# (normalize=0 keeps relative levels, then a limiter — same as sfx-beats /
# title-transition / bg-music do today). With no mixes, the bash side copies
# the base audio, so emit an empty audio filter.
audio_fg = ""
if audio_mixes and has_audio:
    parts = []
    labels = ["0:a"]
    for gi, apad in audio_mixes:
        if apad:
            parts.append("[%d:a]apad[am%d]" % (gi, gi))
            labels.append("[am%d]" % gi)
        else:
            labels.append("%d:a" % gi)
    n = len(labels)
    mix = "%samix=inputs=%d:duration=first:normalize=0,alimiter=limit=0.97[a]" % (
        "".join("[%s]" % l.strip("[]") for l in labels), n)
    if parts:
        audio_fg = ";".join(parts) + ";" + mix
    else:
        audio_fg = mix

for tok in out:
    sys.stdout.write(tok + "\0")
sys.stdout.write("--FILTER--\0")
sys.stdout.write(video_fg + "\0")
sys.stdout.write("--AUDIO--\0")
sys.stdout.write(audio_fg + "\0")
