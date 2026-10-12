---
name: resume-design-debate
description: Run a structured, persisted multi-agent architecture debate for Resume Auto-Pilot (two independent architects, cross-examination, rebuttal, independent judge, decision record). Design-only by default. Use when the user invokes /resume-design-debate or asks to run, resume or review the Resume Auto-Pilot design debate.
argument-hint: "[scope=full-system|<module>] [focus=balanced|reliability|quality|cost|automation] [mode=design-only|implementation-after-approval] [requirements=<path>] [resume=<run_id>]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Write, Agent, Bash(python3 .claude/skills/resume-design-debate/scripts/debate_run.py:*), Bash(git status:*), Bash(git rev-parse:*), Bash(git log:*), Bash(git diff:*)
---

# Resume Auto-Pilot design debate

Arguments: `$ARGUMENTS`

You are the **orchestrator**. You run the stages, write the artifacts, and call the helper
for all bookkeeping. You do not argue for either design. Three subagents do the reasoning:
`architect-reliability` (A), `architect-efficiency` (B) and `design-judge`. All three are
read-only. They return Markdown, and you save it verbatim to the artifact path the helper gives you.

```
H = python3 .claude/skills/resume-design-debate/scripts/debate_run.py
```

Artifact templates: `.claude/skills/resume-design-debate/templates/artifacts.md` (T1–T8).
Paste the relevant template into each agent prompt.

## 0. Parse arguments and set up the run

- Defaults: `scope=full-system`, `focus=balanced`, `mode=design-only`. Treat unknown keys as an error and show the argument hint.
- `resume=<run_id>`: skip `init` and go to **Resume**.
- Otherwise run `H init --scope … --focus … --mode …` and note `run_id` and `run_dir`.
- `H weights --focus …` gives the default weights for this focus. Pass them to the judge as defaults.

**DESIGN-ONLY contract** (every mode until the user approves implementation): write only
under `design/`. No edits to application code, tests, configuration or dependencies. No
installs, no destructive git commands, no commits unless the user asks.

## Stage 1: Freeze the requirements (orchestrator)

1. Discover the sources. If `requirements=<path>` was given, use it first. Then look at
   `CLAUDE.md`, `README*`, `docs/`, `design/` (excluding `design/runs/`), `requirements*`, `spec*`,
   any `*.txt` or `*.md` the user attached or named, source modules and tests. Use Glob and Grep, and read what is relevant.
2. **Hard stop.** If no source actually describes Resume Auto-Pilot (its inputs, outputs and
   constraints), do not invent requirements. Run `H block <run> --reason "no Resume Auto-Pilot requirements found in <places searched>"`,
   report what you searched, and ask the user for a requirements file or the correct repository. Then stop.
3. Write `<run_dir>/requirements_snapshot.md` using template T1. Every item must carry
   `[source: path:line]`. Anything you had to infer is `[unsourced: needs user confirmation]`.
   Record missing requirements and conflicts under *Gaps and conflicts*. For a named-module scope, keep the module's
   requirements plus **all** cross-cutting safety, privacy and factual-integrity constraints.
4. `H start <run> requirements`, then `H record <run> requirements`. If validation fails, fix the snapshot and record again.
5. If any optimisation priority is unsourced, or *Gaps and conflicts* contains a conflict that changes
   priorities, ask the user (one AskUserQuestion, at most 4 questions) before Stage 2. Record the answers in
   the snapshot as `[source: user, <date>]`. Note that this changes the hash, so record it again.

## Stages 2 and 3: Independent proposals and blind risk assessments (parallel)

Launch **five Agent calls in one message** so that no agent can see another's output:
`proposal_a` (A), `proposal_b` (B), `risk_a` (A), `risk_b` (B), `judge_criteria` (judge).
Run `H start <run> <stage>` for each one first.

Every prompt contains: the absolute path to `requirements_snapshot.md` (the only debate file the
agent may read), the scope and focus, the template (T2, T3 or T6), and this instruction:
*"Do not read any file under design/runs/ other than requirements_snapshot.md. Return only the Markdown artifact."*
The judge-criteria prompt also includes the focus-adjusted weights as defaults.

When each call returns, save its text to the stage's artifact path and run `H record <run> <stage>`.
- If the agent errored or returned nothing, run `H fail <run> <stage> --error "<what happened>"`.
- If validation failed, the helper archives the bad output under `parts/failed/`.
- Retry a failed stage at most **twice**. On retry, `start` warns when peer artifacts already exist. Keep the
  prohibition in the prompt; the manifest records independence as `weakened`. Mention this in the final report.

Then run `H check-independence <run>`. It must return `ok: true` before Stage 4.

## Stage 4: Cross-examination, round 1 (parallel)

`H start` `cross_exam_1_a` and `cross_exam_1_b`, then launch both in one message:
- A receives `proposal_b.md`, `risk_assessment_b.md`, its own proposal and the snapshot.
- B receives `proposal_a.md`, `risk_assessment_a.md`, its own proposal and the snapshot.

Use template T4. Require: the 3 strongest aspects; at least 5 weaknesses (only if they genuinely exist), each with
*Requirement*, *Failure scenario* and *Repair or test*; criticism of decisions, not writing; and uncertainty marked
`[UNVERIFIED]`. Save each result to `parts/cross_exam_1_<a|b>.md`, run `H record`, then `H assemble <run> cross_exam_1`.

## Stage 5: Rebuttal and revision, round 2 (parallel)

`H start` `rebuttal_2_a` and `rebuttal_2_b`. Each architect receives `cross_exam_round_1.md` and its own
proposal, and uses template T5. Each must concede valid points, rebut the rest with evidence, and give every
material revision the fields Original, Objection, Evidence, Revised design and Remaining trade-off. Do not push them to agree.
Save the results, `H record` each, then `H assemble <run> rebuttal_2`.

## Stage 6: Independent adjudication (judge)

1. `H judge-inputs <run>` must return `ok: true`. Pass the judge **every** path listed, plus a summary of the
   existing implementation and any test results you actually ran (say "none available" if there are none). Never pass your own opinion.
2. `H start <run> comparison_matrix`. Ask the judge for **both** T7 and T8 in one response, separated by a line
   `=== final_decision.md ===`. Save the part before that line to `comparison_matrix.md` and the part after it to `final_decision.md`.
   Run `H record` on `comparison_matrix`, then `H start` and `H record` on `final_decision`.
3. The judge must use the hard gates from `parts/judge_criteria.md`. Gates may not be loosened after the proposals are seen;
   any change to them is a weight change and must be justified in the artifact.

**Optional round 3.** If `final_decision.md` says `Required: yes` and no round 3 exists yet, run
`H add-round <run> --reason "<material issue>"`. This archives the decision under `parts/superseded/`. Then run
`cross_exam_3_a` and `cross_exam_3_b` (scoped to the named issue only, template T4), `H assemble <run> cross_exam_3`,
and repeat Stage 6. Never run a fourth round. If the issue is still open, it goes in *Experiments*.

## Stage 7: Decision record and acceptance checks

Run `H finalize <run>`. This checks that every stage is ok, independence holds, and the design-only guard is clean
(nothing changed outside `design/`). Read `final_decision.md` yourself and check that it distinguishes `[MEASURED]`,
`[ESTIMATE]` and `[JUDGEMENT]`. Never claim a stage succeeded unless the helper says `ok`.

### Report to the user (concise)
1. Where the artifacts were saved (`design/runs/<run_id>/`).
2. The main architectural decision.
3. The most consequential trade-off.
4. Remaining unresolved questions and experiments.
5. Acceptance-check results from `finalize`, including any `weakened` independence and guard violations.
6. The exact next command, for example `/resume-design-debate resume=<run_id>` to continue a partial run, or
   "reply *approve implementation of <run_id>*" to proceed.

## Stage 8: Implementation (only after explicit approval)

Even with `mode=implementation-after-approval`, stop after the report and ask (AskUserQuestion) whether to
implement. Only on an explicit yes: follow the decision's *Implementation sequence* in small steps. After each step,
run the relevant tests, inspect `git diff`, and report verified results. Commit only if the user asks. Append a
note to `design/runs/<run_id>/implementation_log.md`. Never edit the debate artifacts.

## Resume

Run `H status <run>` and then `H next <run>`.
- `recoverable` lists interrupted stages whose artifact was saved but never recorded. Run `H record` on each
  first. This resumes from the last valid artifact, and the stage keeps the independence status of its original
  launch. Rerun the stage only if `record` fails validation.
- Any other stage in `interrupted` was started but its output never arrived. Rerun it. `start` archives any stale
  file under `parts/failed/`, so a new attempt never inherits old output.
- `invalidated` lists stages whose artifact or prerequisite changed after recording. These, and everything after them, must be rerun.
  New output goes to a fresh file; the old one is never silently reused.
- Continue with the `runnable` stages. Never overwrite a stage that is `ok`; the helper refuses to.
If a run is `blocked`, start a new run once the blocker is resolved. Never edit the blocked run.

## Debate quality rules (apply them in every prompt)
- Both architects get the same frozen snapshot, and the hash is in the manifest.
- Every objection must link to a requirement ID, a failure scenario or a test. Volume and tone earn nothing.
- Claims without evidence are `[UNVERIFIED]`. Estimates show how they were derived.
- The judge may prefer an experiment to further debate, may reject both proposals, and must not treat consensus as correctness.
- Keep each artifact under about 1,500 words.
