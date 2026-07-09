#!/usr/bin/env python3
# shorts-sgpa: idea-based assembly + spoken-hook floor in parse_reply.py.
import json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PARSE = os.path.join(HERE, "parse_reply.py")

TRANSCRIPT = {
    "source": "test",
    "segments": [
        {"t0": float(i * 10), "t1": float(i * 10 + 10),
         "text": "The quick brown fox jumps over the lazy dog again"}
        for i in range(60)
    ],
}
TOPICS = {"topics": [
    {"t0": 0.0, "t1": 300.0, "title": "Topic A", "summary": "a"},
    {"t0": 300.0, "t1": 600.0, "title": "Topic B", "summary": "b"},
]}

def pick(t0, t1, cuts=None, **kw):
    p = {"t0": t0, "t1": t1, "cuts": cuts or [[t0, t1]],
         "idea": kw.pop("idea", "one throughline"),
         "rationale": "r", "title_suggestion": "t",
         "opening_line": "The quick brown fox", "hook_type": "question",
         "hook_score": 8, "context_score": 8, "structure_score": 8,
         "hook_payoff_coherence": 8, "payoff_offset_sec": 1.0, "theme_fit": 5,
         "overall_score": 8}
    p.update(kw)
    return p

def run(shorts, env=None, n=5, dmin=28, dmax=55):
    d = tempfile.mkdtemp()
    reply = os.path.join(d, "reply.txt")
    tx = os.path.join(d, "transcript.json")
    tp = os.path.join(d, "topics.json")
    json.dump({"shorts": shorts}, open(reply, "w"))
    json.dump(TRANSCRIPT, open(tx, "w"))
    json.dump(TOPICS, open(tp, "w"))
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(
        [sys.executable, PARSE, reply, str(n), str(dmin), str(dmax), tx, tp],
        capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)["shorts"], r.stderr


class Assembly(unittest.TestCase):
    def test_multicut_cross_topic_kept(self):
        out, _ = run([pick(10, 595, cuts=[[10, 25], [580, 595]])])
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["cuts"]), 2)
        self.assertEqual(out[0]["idea"], "one throughline")
        self.assertEqual(out[0]["topic"], "one throughline")

    def test_singlecut_cross_topic_dropped(self):
        out, err = run([pick(280, 320)])
        self.assertEqual(out, [])
        self.assertIn("single-cut slice crosses topic boundary", err)

    def test_rollback_flag_restores_thread_gate(self):
        env = {"ASSEMBLE_CROSS_TOPIC": "0"}
        out, err = run([pick(10, 595, cuts=[[10, 25], [580, 595]])], env=env)
        self.assertEqual(out, [])
        self.assertIn("ASSEMBLE_CROSS_TOPIC=0", err)
        out, _ = run([pick(10, 595, cuts=[[10, 25], [580, 595]], thread=True)], env=env)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["thread"])

    def test_idea_carried_on_single_topic_pick(self):
        out, _ = run([pick(10, 45, idea="a named idea")])
        self.assertEqual(out[0]["idea"], "a named idea")
        self.assertEqual(out[0]["topic"], "Topic A")


class HookFloor(unittest.TestCase):
    def test_below_floor_dropped(self):
        out, err = run([pick(10, 45, hook_score=2), pick(60, 95, hook_score=8)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["hook_score"], 8)
        self.assertIn("< floor", err)

    def test_floor_never_empties(self):
        out, err = run([pick(10, 45, hook_score=2), pick(60, 95, hook_score=3)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["hook_score"], 3)
        self.assertIn("WARN all picks below hook floor", err)

    def test_floor_disabled(self):
        out, _ = run([pick(10, 45, hook_score=2)], env={"PICK_HOOK_FLOOR": "0"})
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()
