"""Tests for debate_run.py using synthetic artifacts in a throwaway git repo.

Run:  python3 -m unittest discover -s .claude/skills/resume-design-debate/tests -v
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
REPO = SKILL.parents[2]
SCRIPT = SKILL / "scripts" / "debate_run.py"
FIX = HERE / "fixtures"


def run(root, *args):
    p = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                       capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def fixture(name):
    return (FIX / name).read_text()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        g = lambda *a: subprocess.run(["git", "-C", str(self.root), *a], check=True, capture_output=True)
        g("init", "-q")
        g("config", "user.email", "t@example.com")
        g("config", "user.name", "t")
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('resume')\n")
        (self.root / "docs").mkdir()
        (self.root / "docs" / "requirements.md").write_text("# Resume Auto-Pilot requirements\n")
        g("add", ".")
        g("commit", "-qm", "init")
        code, out = run(self.root, "init")
        self.assertEqual(code, 0, out)
        self.run_id, self.dir = out["run_id"], Path(out["run_dir"])

    def tearDown(self):
        self.tmp.cleanup()

    def write_and_record(self, stage, rel, text, expect_ok=True, start=True):
        if start:
            self.assertEqual(run(self.root, "start", self.run_id, stage)[0], 0)
        (self.dir / rel).write_text(text)
        code, out = run(self.root, "record", self.run_id, stage)
        self.assertEqual(out["ok"], expect_ok, out)
        return out

    def independent_stages(self):
        self.write_and_record("requirements", "requirements_snapshot.md", fixture("requirements.md"))
        stages = [("proposal_a", "proposal_a.md", fixture("proposal.md").replace("<X>", "A")),
                  ("proposal_b", "proposal_b.md", fixture("proposal.md").replace("<X>", "B")),
                  ("risk_a", "risk_assessment_a.md", fixture("risk.md")),
                  ("risk_b", "risk_assessment_b.md", fixture("risk.md")),
                  ("judge_criteria", "parts/judge_criteria.md", fixture("criteria.md"))]
        for stage, _rel, _text in stages:  # parallel launch, as the skill requires
            self.assertEqual(run(self.root, "start", self.run_id, stage)[0], 0)
        for stage, rel, text in stages:
            self.write_and_record(stage, rel, text, start=False)

    def debate_stages(self):
        for s in ("a", "b"):
            self.write_and_record(f"cross_exam_1_{s}", f"parts/cross_exam_1_{s}.md", fixture("cross.md"))
        self.assertEqual(run(self.root, "assemble", self.run_id, "cross_exam_1")[0], 0)
        for s in ("a", "b"):
            self.write_and_record(f"rebuttal_2_{s}", f"parts/rebuttal_2_{s}.md", fixture("rebuttal.md"))
        self.assertEqual(run(self.root, "assemble", self.run_id, "rebuttal_2")[0], 0)

    def judge_stages(self, decision=None):
        self.write_and_record("comparison_matrix", "comparison_matrix.md", fixture("matrix.md"))
        self.write_and_record("final_decision", "final_decision.md", decision or fixture("decision.md"))


class FullRun(Base):
    def test_synthetic_end_to_end(self):
        self.independent_stages()
        code, ind = run(self.root, "check-independence", self.run_id)
        self.assertTrue(ind["ok"], ind)
        self.assertEqual(ind["weakened"], [])
        # judge inputs must NOT be ready before cross-exam/rebuttal exist
        code, ji = run(self.root, "judge-inputs", self.run_id)
        self.assertFalse(ji["ok"])
        self.assertTrue(any("cross_exam_round_1.md" in p for p in ji["problems"]))
        self.debate_stages()
        code, ji = run(self.root, "judge-inputs", self.run_id)
        self.assertTrue(ji["ok"], ji)
        self.assertEqual(len(ji["inputs"]), 8)
        self.judge_stages()
        code, fin = run(self.root, "finalize", self.run_id)
        self.assertEqual(code, 0, fin)
        self.assertEqual(fin["status"], "completed")
        m = json.loads((self.dir / "manifest.json").read_text())
        self.assertRegex(m["requirements_sha256"], r"^[0-9a-f]{64}$")
        self.assertIsNotNone(m["repo_commit"])
        self.assertEqual(m["agents"]["judge"], "design-judge")
        self.assertEqual(m["requirements_sources"][0]["path"], "docs/requirements.md")
        self.assertIsNotNone(m["requirements_sources"][0]["sha256"])
        for f in ("requirements_snapshot.md", "proposal_a.md", "proposal_b.md", "risk_assessment_a.md",
                  "risk_assessment_b.md", "cross_exam_round_1.md", "rebuttal_round_2.md",
                  "comparison_matrix.md", "final_decision.md", "manifest.json"):
            self.assertTrue((self.dir / f).is_file(), f)
        assembled = (self.dir / "cross_exam_round_1.md").read_text()
        self.assertIn("Architect A (architect-reliability) on Proposal B", assembled)
        self.assertIn("Architect B (architect-efficiency) on Proposal A", assembled)

    def test_cross_exam_blocked_until_both_proposals_persisted(self):
        self.write_and_record("requirements", "requirements_snapshot.md", fixture("requirements.md"))
        self.write_and_record("proposal_a", "proposal_a.md", fixture("proposal.md"))
        code, out = run(self.root, "start", self.run_id, "cross_exam_1_a")
        self.assertEqual(code, 2)
        self.assertIn("proposal_b", out["error"])
        code, nxt = run(self.root, "next", self.run_id)
        self.assertNotIn("cross_exam_1_a", [r["stage"] for r in nxt["runnable"]])

    def test_runs_never_overwrite(self):
        code, out2 = run(self.root, "init")
        self.assertNotEqual(out2["run_id"], self.run_id)
        self.independent_stages()
        code, out = run(self.root, "start", self.run_id, "proposal_a")
        self.assertEqual(code, 2)
        self.assertIn("never overwritten", out["error"])
        code, out = run(self.root, "record", self.run_id, "proposal_a")
        self.assertEqual(code, 2)


class Validation(Base):
    def test_unsourced_requirement_rejected(self):
        bad = fixture("requirements.md").replace(" [source: docs/requirements.md:3]", "", 1)
        out = self.write_and_record("requirements", "requirements_snapshot.md", bad, expect_ok=False)
        self.assertTrue(any("FR-1" in e for e in out["errors"]))

    def test_unsourced_tag_is_warning(self):
        txt = fixture("requirements.md").replace("[source: docs/requirements.md:9]",
                                                 "[unsourced: needs user confirmation]")
        out = self.write_and_record("requirements", "requirements_snapshot.md", txt)
        self.assertTrue(out["warnings"])

    def test_proposal_missing_section(self):
        self.write_and_record("requirements", "requirements_snapshot.md", fixture("requirements.md"))
        bad = fixture("proposal.md").replace("## 8. Test strategy", "## 8. Tests")
        out = self.write_and_record("proposal_a", "proposal_a.md", bad, expect_ok=False)
        self.assertIn("missing section '## Test strategy'", out["errors"])

    def test_independence_violation_detected(self):
        self.write_and_record("requirements", "requirements_snapshot.md", fixture("requirements.md"))
        bad = fixture("proposal.md").replace("Files read:", "Files read: design/runs/x/proposal_b.md,")
        out = self.write_and_record("proposal_a", "proposal_a.md", bad, expect_ok=False)
        self.assertTrue(any("independence violated" in e for e in out["errors"]))

    def test_cross_exam_needs_linked_objections(self):
        self.independent_stages()
        bad = re.sub(r"Failure scenario:.*\n", "", fixture("cross.md"), count=1)
        out = self.write_and_record("cross_exam_1_a", "parts/cross_exam_1_a.md", bad, expect_ok=False)
        self.assertIn("W-1 lacks 'Failure scenario:'", out["errors"])

    def test_weights_must_sum_to_100(self):
        self.write_and_record("requirements", "requirements_snapshot.md", fixture("requirements.md"))
        bad = fixture("criteria.md").replace("| 25% |", "| 30% |")
        out = self.write_and_record("judge_criteria", "parts/judge_criteria.md", bad, expect_ok=False)
        self.assertTrue(any("sum to 105%" in e for e in out["errors"]))

    def test_focus_weights(self):
        for focus in ("balanced", "reliability", "quality", "cost", "automation"):
            code, out = run(self.root, "weights", "--focus", focus)
            self.assertEqual(sum(out["weights"].values()), 100)
            self.assertGreaterEqual(out["weights"]["Correctness and factual integrity"], 25)
            self.assertGreaterEqual(out["weights"]["Privacy and security"], 10)


class Recovery(Base):
    def test_missing_agent_output_then_retry(self):
        self.write_and_record("requirements", "requirements_snapshot.md", fixture("requirements.md"))
        out = self.write_and_record("proposal_b", "proposal_b.md", "", expect_ok=False)
        self.assertIn("missing agent output", out["errors"][0])
        # agent crash with partial output
        run(self.root, "start", self.run_id, "proposal_b")
        (self.dir / "proposal_b.md").write_text("# partial")
        code, out = run(self.root, "fail", self.run_id, "proposal_b", "--error", "agent timeout")
        self.assertEqual(out["archived"], "parts/failed/proposal_b.attempt2.md")
        self.assertFalse((self.dir / "proposal_b.md").exists())
        code, nxt = run(self.root, "next", self.run_id)
        self.assertIn("proposal_b", [r["stage"] for r in nxt["runnable"]])
        self.write_and_record("proposal_b", "proposal_b.md", fixture("proposal.md"))
        m = json.loads((self.dir / "manifest.json").read_text())
        self.assertEqual(m["stages"]["proposal_b"]["attempts"], 3)
        self.assertEqual(m["stages"]["proposal_b"]["status"], "ok")
        self.assertTrue(any(e["event"] == "agent_failed" for e in m["events"]))

    def test_retry_after_peer_persisted_marks_weakened(self):
        self.write_and_record("requirements", "requirements_snapshot.md", fixture("requirements.md"))
        self.write_and_record("proposal_a", "proposal_a.md", fixture("proposal.md"))
        code, out = run(self.root, "start", self.run_id, "proposal_b")
        self.assertIn("warning", out)
        (self.dir / "proposal_b.md").write_text(fixture("proposal.md"))
        run(self.root, "record", self.run_id, "proposal_b")
        for st, rel in (("risk_a", "risk_assessment_a.md"), ("risk_b", "risk_assessment_b.md")):
            self.write_and_record(st, rel, fixture("risk.md"))
        self.write_and_record("judge_criteria", "parts/judge_criteria.md", fixture("criteria.md"))
        code, ind = run(self.root, "check-independence", self.run_id)
        self.assertIn("proposal_b", ind["weakened"])

    def test_interrupted_run_resumes(self):
        self.independent_stages()
        run(self.root, "start", self.run_id, "cross_exam_1_a")  # process dies here
        code, nxt = run(self.root, "next", self.run_id)
        self.assertEqual(nxt["interrupted"], ["cross_exam_1_a"])
        self.assertEqual({r["stage"] for r in nxt["runnable"]}, {"cross_exam_1_a", "cross_exam_1_b"})
        self.write_and_record("cross_exam_1_a", "parts/cross_exam_1_a.md", fixture("cross.md"))
        m = json.loads((self.dir / "manifest.json").read_text())
        self.assertTrue(any(e["event"] == "interrupted_attempt_detected" for e in m["events"]))

    def test_tampered_artifact_invalidates_downstream(self):
        self.independent_stages()
        self.debate_stages()
        with open(self.dir / "proposal_a.md", "a") as f:
            f.write("\nedited after the fact\n")
        code, nxt = run(self.root, "next", self.run_id)
        self.assertIn("proposal_a", nxt["invalidated"])
        self.assertIn("cross_exam_1", nxt["invalidated"])
        self.assertIn("rebuttal_2", nxt["invalidated"])
        self.assertNotIn("proposal_b", nxt["invalidated"])
        code, ji = run(self.root, "judge-inputs", self.run_id)
        self.assertFalse(ji["ok"])

    def test_additional_round_once(self):
        self.independent_stages()
        self.debate_stages()
        self.judge_stages(fixture("decision.md").replace("Required: no", "Required: yes (gate HG-1 disputed)"))
        code, fin = run(self.root, "finalize", self.run_id)
        self.assertFalse(fin["ok"])
        self.assertIn("judge requested an additional round; run add-round", fin["checks"]["problems"])
        code, out = run(self.root, "add-round", self.run_id, "--reason", "HG-1 disputed")
        self.assertEqual(code, 0)
        self.assertTrue((self.dir / "parts/superseded/final_decision.before_round3.md").is_file())
        code, out = run(self.root, "add-round", self.run_id, "--reason", "again")
        self.assertEqual(code, 2)
        for s in ("a", "b"):
            self.write_and_record(f"cross_exam_3_{s}", f"parts/cross_exam_3_{s}.md", fixture("cross.md"))
        run(self.root, "assemble", self.run_id, "cross_exam_3")
        code, ji = run(self.root, "judge-inputs", self.run_id)
        self.assertTrue(any(i.endswith("cross_exam_round_3.md") for i in ji["inputs"]))
        self.judge_stages()
        code, fin = run(self.root, "finalize", self.run_id)
        self.assertEqual(fin["status"], "completed", fin)

    def test_blocked_without_requirements(self):
        code, out = run(self.root, "block", self.run_id, "--reason", "no requirements found")
        self.assertEqual(out["status"], "blocked")
        code, fin = run(self.root, "finalize", self.run_id)
        self.assertEqual(fin["status"], "blocked")


class Guard(Base):
    def test_design_only_allows_design_dir(self):
        self.independent_stages()
        code, g = run(self.root, "guard", self.run_id)
        self.assertTrue(g["ok"], g)

    def test_design_only_detects_production_edit(self):
        (self.root / "src" / "app.py").write_text("print('changed')\n")
        (self.root / "requirements.txt").write_text("requests\n")
        code, g = run(self.root, "guard", self.run_id)
        self.assertEqual(code, 1)
        self.assertEqual(g["violations"], ["requirements.txt", "src/app.py"])

    def test_design_only_detects_commit(self):
        (self.root / "src" / "app.py").write_text("print('changed')\n")
        subprocess.run(["git", "-C", str(self.root), "commit", "-qam", "sneaky"], check=True)
        code, g = run(self.root, "guard", self.run_id)
        self.assertIn("src/app.py", g["violations"])

    def test_preexisting_dirty_file_tolerated_if_unchanged(self):
        (self.root / "src" / "app.py").write_text("print('wip')\n")
        code, out = run(self.root, "init")
        rid = out["run_id"]
        self.assertTrue(run(self.root, "guard", rid)[1]["ok"])
        (self.root / "src" / "app.py").write_text("print('wip2')\n")
        self.assertEqual(run(self.root, "guard", rid)[1]["violations"], ["src/app.py"])


class Conventions(unittest.TestCase):
    """Validate the real agent and skill files in this repository."""

    def frontmatter(self, path):
        import yaml
        text = path.read_text()
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        self.assertIsNotNone(m, f"{path} has no YAML frontmatter")
        return yaml.safe_load(m.group(1)), text[m.end():]

    def test_agents(self):
        for name in ("architect-reliability", "architect-efficiency", "design-judge"):
            path = REPO / ".claude" / "agents" / f"{name}.md"
            fm, body = self.frontmatter(path)
            self.assertEqual(fm["name"], name)
            self.assertTrue(fm["description"].strip())
            tools = [t.strip() for t in fm["tools"].split(",")]
            self.assertEqual(sorted(tools), ["Glob", "Grep", "Read"], "agents must be read-only")
            self.assertIn("Read-only", body)

    def test_skill(self):
        fm, body = self.frontmatter(SKILL / "SKILL.md")
        self.assertEqual(fm["name"], "resume-design-debate")
        self.assertEqual(SKILL.name, fm["name"])
        for key in ("description", "argument-hint", "allowed-tools"):
            self.assertIn(key, fm)
        self.assertIn("$ARGUMENTS", body)
        for agent in ("architect-reliability", "architect-efficiency", "design-judge"):
            self.assertIn(agent, body)
        self.assertNotRegex(fm["allowed-tools"], r"\bEdit\b|Bash\(\*|Bash,|Bash$")
        # every stage named by the helper is referenced in the skill
        sys.path.insert(0, str(SKILL / "scripts"))
        import debate_run
        for stage in list(debate_run.BASE_STAGES) + list(debate_run.ROUND3_STAGES):
            if stage.endswith(("_a", "_b")):
                stage = stage[:-2]
            self.assertIn(stage, body, stage)

    def test_templates_match_validator(self):
        sys.path.insert(0, str(SKILL / "scripts"))
        import debate_run
        tpl = (SKILL / "templates" / "artifacts.md").read_text()
        for h in (debate_run.PROPOSAL_HEADINGS + debate_run.REQUIREMENTS_HEADINGS + debate_run.CROSS_HEADINGS
                  + debate_run.REBUTTAL_HEADINGS + debate_run.MATRIX_HEADINGS + debate_run.DECISION_HEADINGS
                  + debate_run.CRITERIA_HEADINGS):
            self.assertIn(h, tpl, h)


if __name__ == "__main__":
    unittest.main()
