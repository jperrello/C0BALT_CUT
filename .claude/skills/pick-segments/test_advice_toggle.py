#!/usr/bin/env python3
# Golden test for the ADVICE_CORPUS toggle (shorts-874). Locks two invariants so a future
# edit can never silently corrupt the A/B:
#   1. OFF (unset) == OFF (=0) == today's prompt, byte-for-byte.
#   2. ON (=1) == OFF + the advice.md corpus block, and NOTHING else differs.
# Run: python3 .claude/skills/pick-segments/test_advice_toggle.py
import glob, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def find_inputs():
    for tx in glob.glob(os.path.join(HERE, "..", "..", "..", "work", "*", "transcript.json")):
        wd = os.path.dirname(tx)
        tp = os.path.join(wd, "topics.json")
        return tx, (tp if os.path.isfile(tp) else "")
    return None, None


def run(env_extra, args):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run([sys.executable, os.path.join(HERE, "build_prompt.py"), *args],
                          capture_output=True, text=True, env=env, check=True).stdout


def main():
    tx, topics = find_inputs()
    if not tx:
        print("SKIP: no work/*/transcript.json to drive the prompt builder", file=sys.stderr)
        return 0
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"rms": [0.1 + (i % 7) * 0.05 for i in range(120)], "seconds": 600}, f)
        rms = f.name
    args = [tx, rms, "5", "28", "55", topics, "", ""]

    off_unset = run({"ADVICE_CORPUS": ""}, args)
    off_zero = run({"ADVICE_CORPUS": "0"}, args)
    on = run({"ADVICE_CORPUS": "1"}, args)
    os.unlink(rms)

    corpus = open(os.path.join(HERE, "advice.md")).read().strip()
    expected_block = corpus + "\n\n---\n\n"
    sig = "veteran short-form clip editor"

    fails = []
    if off_unset != off_zero:
        fails.append("ADVICE_CORPUS unset differs from =0 (OFF must be deterministic)")
    if sig in off_zero:
        fails.append("OFF prompt leaked the corpus (must be today's prompt verbatim)")
    if on != expected_block + off_zero:
        fails.append("ON != advice.md block + OFF — the corpus is not the ONLY difference")
    if sig not in on:
        fails.append("ON prompt is missing the corpus")

    if fails:
        for m in fails:
            print("FAIL:", m, file=sys.stderr)
        return 1
    print(f"OK: OFF byte-for-byte deterministic; ON == OFF + advice.md "
          f"(+{len(expected_block)} chars). corpus signature present only in ON.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
