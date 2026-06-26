#!/usr/bin/env python3
# Tier-2 ablation runner (epic shorts-dwt / shorts-xoq). Drives the picker ON vs OFF and
# applies the PRE-REGISTERED decision rule (PRE-REGISTRATION.md §3,§6,§7). NO LLM in the scorer.
#
#   ablation.py run --manifest runs.json [--k 5] [--out tools/eval/ablation_runs]
#       manifest = [{"source_id": "...", "transcript": "work/<id>/transcript.json",
#                    "goldset": "goldset/<id>.json", "n": 5, "dmin": 28, "dmax": 55}, ...]
#       For each source x arm(OFF,ON) x k repeats: runs pick-segments.sh with ADVICE_CORPUS
#       set, into out/<source>/<arm>/run_<i>.json. Idempotent (skips existing run files).
#   ablation.py aggregate [--out tools/eval/ablation_runs] [--tau 0.5] [--boot 10000]
#       Scores every run vs its goldset, k-averages, splits DEV/TEST by frozen sha1 bucket,
#       bootstraps mean(ON-OFF) weighted-overlap over TEST sources, prints the G1 ship-gate.
#   ablation.py selftest
import argparse, glob, hashlib, json, os, subprocess, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import score_selection as SS  # noqa: E402

PICK_SH = os.path.join(ROOT, ".claude/skills/pick-segments/pick-segments.sh")


def bucket(source_id):
    return int(hashlib.sha1(source_id.encode()).hexdigest(), 16) % 10


def split_of(source_id):
    return "TEST" if bucket(source_id) >= 7 else "DEV"


def freeze_splits(source_ids, out):
    p = os.path.join(out, "splits.json")
    if os.path.isfile(p):
        return json.load(open(p))
    sp = {sid: {"bucket": bucket(sid), "split": split_of(sid)} for sid in source_ids}
    os.makedirs(out, exist_ok=True)
    json.dump(sp, open(p, "w"), indent=2)
    return sp


def run(a):
    manifest = json.load(open(a.manifest))
    freeze_splits([m["source_id"] for m in manifest], a.out)
    for m in manifest:
        for arm, flag in (("OFF", "0"), ("ON", "1")):
            d = os.path.join(a.out, m["source_id"], arm)
            os.makedirs(d, exist_ok=True)
            for i in range(a.k):
                outp = os.path.join(d, f"run_{i}.json")
                if os.path.isfile(outp) and os.path.getsize(outp) > 2:
                    continue
                env = {**os.environ, "ADVICE_CORPUS": flag}
                cmd = ["bash", PICK_SH, m["transcript"], outp,
                       str(m.get("n", 5)), str(m.get("dmin", 28)), str(m.get("dmax", 55))]
                if m.get("topics"):
                    cmd.append(m["topics"])
                print(f"[{m['source_id']}] {arm} run {i}...", file=sys.stderr)
                r = subprocess.run(cmd, env=env)
                if r.returncode != 0:
                    print(f"  WARN: picker failed ({m['source_id']}/{arm}/{i})", file=sys.stderr)
    print("run complete; now: ablation.py aggregate")


def kavg(runs, goldset, tau):
    vals = {}
    for rp in runs:
        try:
            picks = json.load(open(rp)).get("shorts", [])
        except Exception:
            continue
        s = SS.score(goldset, picks, tau)
        for kk in ("weighted_overlap", "recall_at_n", "mean_iou", "rank_corr"):
            v = s.get(kk)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                vals.setdefault(kk, []).append(v)
    return {kk: float(np.mean(v)) for kk, v in vals.items() if v}


def boot_ci(deltas, B, seed):
    d = np.asarray(deltas, float)
    if len(d) < 2:
        return {"mean": float(d.mean()) if len(d) else float("nan"),
                "ci": [float("nan")] * 2, "frac_pos": float("nan"), "n": len(d)}
    rng = np.random.default_rng(seed)
    boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(B)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"mean": float(d.mean()), "ci": [float(lo), float(hi)],
            "frac_pos": float(np.mean(np.array(boots) > 0)), "n": len(d)}


def aggregate(a):
    splits = json.load(open(os.path.join(a.out, "splits.json")))
    persrc = {}
    for sid in splits:
        gp = None
        for cand in (os.path.join(ROOT, "goldset", f"{sid}.json"),):
            if os.path.isfile(cand):
                gp = cand
        if not gp:
            continue
        goldset = json.load(open(gp))
        arms = {}
        for arm in ("OFF", "ON"):
            runs = glob.glob(os.path.join(a.out, sid, arm, "run_*.json"))
            if runs:
                arms[arm] = kavg(runs, goldset, a.tau)
        if "OFF" in arms and "ON" in arms:
            persrc[sid] = {"split": splits[sid]["split"], "OFF": arms["OFF"], "ON": arms["ON"]}

    def deltas(metric, split):
        return [persrc[s]["ON"].get(metric, float("nan")) - persrc[s]["OFF"].get(metric, float("nan"))
                for s in persrc if persrc[s]["split"] == split
                and metric in persrc[s]["ON"] and metric in persrc[s]["OFF"]]

    report = {"n_sources_scored": len(persrc), "tau": a.tau, "bootstrap_B": a.boot,
              "primary_metric": "weighted_overlap", "per_source": persrc, "splits": {}}
    for split in ("TEST", "DEV"):
        block = {}
        for metric in ("weighted_overlap", "recall_at_n", "mean_iou", "rank_corr"):
            block[metric] = boot_ci(deltas(metric, split), a.boot, a.seed)
        report["splits"][split] = block

    # G1 ship gate: TEST weighted_overlap delta CI lower bound > 0
    test_wo = report["splits"]["TEST"]["weighted_overlap"]
    g1 = isinstance(test_wo["ci"][0], float) and test_wo["ci"][0] > 0
    report["G1_pass"] = bool(g1)
    report["verdict"] = (
        "SHIP-ELIGIBLE on Tier-2 (G1 met; primary CI excludes 0 positive on held-out TEST). "
        "Still requires G2 (Tier-1 non-contradiction) before shipping default."
        if g1 else
        "NULL/NEGATIVE on Tier-2 primary: do not ship the corpus on this evidence. "
        "(CI on TEST weighted-overlap delta straddles or excludes 0 negatively.)")
    os.makedirs(a.out, exist_ok=True)
    json.dump(report, open(os.path.join(a.out, "ablation_report.json"), "w"), indent=2)
    print(json.dumps({"n_sources": len(persrc),
                      "TEST_weighted_overlap_delta": test_wo,
                      "G1_pass": report["G1_pass"], "verdict": report["verdict"]}, indent=2))


def selftest():
    # Decision-rule logic: an all-positive, low-variance TEST delta must clear G1;
    # a delta straddling 0 must NOT.
    pos = boot_ci([0.10, 0.08, 0.12, 0.09, 0.11], 10000, 7)
    null = boot_ci([0.10, -0.09, 0.02, -0.05, 0.08], 10000, 7)
    fails = []
    if not (pos["ci"][0] > 0):
        fails.append(f"all-positive deltas failed G1: CI {pos['ci']}")
    if null["ci"][0] > 0:
        fails.append(f"straddling deltas wrongly passed G1: CI {null['ci']}")
    if split_of("aaaa") not in ("DEV", "TEST") or bucket("aaaa") != bucket("aaaa"):
        fails.append("split bucket not deterministic")
    # buckets 7,8,9 -> TEST; verify the partition is ~30% over many ids
    ntest = sum(split_of(f"src{i}") == "TEST" for i in range(1000))
    if not (200 <= ntest <= 400):
        fails.append(f"TEST fraction {ntest/1000:.2f} far from ~0.30")
    if fails:
        for f in fails:
            print("FAIL:", f, file=sys.stderr)
        return 1
    print(f"OK: G1 fires on CI-clean positive ({pos['ci']}), stays null on straddle ({null['ci']}); "
          f"DEV/TEST split deterministic (~{ntest/1000:.0%} TEST)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--manifest", required=True)
    r.add_argument("--k", type=int, default=5)
    r.add_argument("--out", default=os.path.join(HERE, "ablation_runs"))
    ag = sub.add_parser("aggregate")
    ag.add_argument("--out", default=os.path.join(HERE, "ablation_runs"))
    ag.add_argument("--tau", type=float, default=0.5)
    ag.add_argument("--boot", type=int, default=10000)
    ag.add_argument("--seed", type=int, default=20260626)
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "run":
        return run(a)
    if a.cmd == "aggregate":
        return aggregate(a)
    return selftest()


if __name__ == "__main__":
    sys.exit(main() or 0)
