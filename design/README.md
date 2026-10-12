# Design debates

This folder holds the output of the `/resume-design-debate` workflow. Each debate is
saved in its own run directory and is never overwritten.

## Run it

In Claude Code, from the repository root:

```
/resume-design-debate
/resume-design-debate requirements=docs/resume_autopilot_requirements.md
/resume-design-debate scope=cover-letter focus=reliability
/resume-design-debate resume=<run_id>
```

| Argument | Values | Default |
|---|---|---|
| `scope` | `full-system` or a module name | `full-system` |
| `focus` | `balanced`, `reliability`, `quality`, `cost`, `automation` | `balanced` |
| `mode` | `design-only`, `implementation-after-approval` | `design-only` |
| `requirements` | path to the requirements or spec source | auto-discovered |
| `resume` | id of an earlier run to continue | (new run) |

Stage 1 asks any open requirement questions *before* freezing the snapshot. After that,
the snapshot is immutable. If you later change a requirement or an answer, the run is
superseded by a new linked run; it is never edited. The debate **stops at Stage 1** unless the repository (or `requirements=`) contains a
real description of Resume Auto-Pilot. It does not invent requirements.

In both modes the debate only writes under `design/`. Implementation starts only after
you explicitly approve the decision record.

## What gets written

```
design/runs/<run_id>/
  requirements_snapshot.md   frozen, sourced requirements (sha256 in the manifest)
  proposal_a.md              architect-reliability, written independently
  proposal_b.md              architect-efficiency, written independently
  risk_assessment_a.md       top five failure modes, written blind
  risk_assessment_b.md
  cross_exam_round_1.md      each architect critiques the other's proposal
  rebuttal_round_2.md        concessions, rebuttals and revisions
  comparison_matrix.md       hard gates, then weighted scoring
  final_decision.md          the decision record
  manifest.json              commit, hashes, agents, per-stage status, event log
  parts/                     per-agent parts, the judge's blind criteria,
                             failed attempts and superseded files
```

## Inspect a run without Claude

```
H="python3 .claude/skills/resume-design-debate/scripts/debate_run.py"
$H list                       # all runs and their status
$H status <run_id>            # per-stage status
$H next <run_id>              # resume point, interrupted or invalidated stages
$H check-independence <run_id>
$H guard <run_id>             # design-only check: nothing changed outside design/
$H supersede <run_id> --reason "..."   # requirements/answers changed after freezing: new linked run
```

## Tests

```
python3 -m unittest discover -s .claude/skills/resume-design-debate/tests -v
```
