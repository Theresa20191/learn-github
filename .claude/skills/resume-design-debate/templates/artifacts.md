# Artifact templates

The orchestrator pastes the relevant template into each agent prompt. Headings are
validated mechanically by `scripts/debate_run.py`. Keep them word for word; numbering
prefixes such as `## 1.` are allowed. Tags used everywhere:
`[UNVERIFIED]`, `[ESTIMATE]`, `[MEASURED]`, `[JUDGEMENT]`. Requirement evidence tags are defined under T1.

---

## T1 requirements_snapshot.md (written by the orchestrator, Stage 1)

```markdown
# Requirements snapshot
Scope: <full-system | module name>. Focus: <focus>. Frozen at commit <sha>.

## Functional requirements
- FR-1 <requirement> [source: docs/spec.md:12 "exact words from line 12"]
## Non-functional requirements
- NFR-1 <requirement> [source: user, 2026-10-12, Q1]
## Safety and privacy constraints
- SP-1 ... [source: path:L-M "exact words spanning lines L to M"]
## Operational constraints
- OP-1 <derived requirement> [interpretation: path:L "exact words"; why this reading]
## Acceptance tests
- AT-1 <observable pass/fail check> (covers FR-1, SP-2) [source: ...]
## Optimisation priorities
- PR-1 <priority, ordered> [assumption: A-1]
## Gaps and conflicts
- <missing requirement or conflict between sources>. Any assumption made about it: see A-n.
## Assumptions
### A-1 <the assumed statement>
Basis: <why it is assumed; what evidence exists>
Impact: <requirements and decisions that depend on it>
Confirm by: <the question to ask the user, or the experiment>
Status: unconfirmed
(or "None.")
## User confirmations
- Q1: <question asked before freezing> A: <user's answer, verbatim> (<date>)
  (or "- None required: every item is sourced.")
## Sources
- path/to/file.md  (what it contributed)
```

Evidence tags (validated by `record`):

| Tag | Meaning | Mechanical checks |
|---|---|---|
| `[source: path:L "quote"]` or `path:L-M` (max 5 lines) | Stated in the source | File exists in repo and is listed under *Sources*; not `design/runs/`; lines exist; quote is ≥3 words and appears verbatim (case/whitespace-insensitive) in non-heading, non-blank cited lines; ≥2 shared content terms with the requirement; every number and bound qualifier (cap, target, limit, hard/soft, maximum, minimum, at most/least, mandatory, optional) in the requirement appears in the quote; quote is not ambiguous (undecided, TBD, open question, unclear, maybe, `?` …) |
| `[source: user, YYYY-MM-DD, Qn]` | Stated by the user | `Qn` is logged under *User confirmations* with an answer; numbers and qualifiers appear in the answer; answer is not ambiguous |
| `[interpretation: path:L "quote"; reason]` | Derived from a source, not stated | Same checks as a source citation (a number or qualifier the quote lacks needs an `A-n`); reported as a warning and classified `interpretation` |
| `[assumption: A-n]` | Not supported by evidence | `A-n` is registered under *Assumptions* with Basis, Impact, Confirm by and `Status: unconfirmed`; every registered A-n is referenced; numbers or qualifiers not in the other evidence are allowed but reported; classified `assumption`; the final decision must mention every A-n |
| `[unsourced: needs user confirmation]` | Draft only | `record` rejects it; ask the user first |

Prose anywhere in the requirement sections, *Gaps and conflicts* or *User confirmations* that states an
assumption (assume, presume, treat as, interpret as, default to, taken as …) must reference an `A-n`.
A confirmed assumption is never edited to `Status: confirmed`. Once the snapshot is frozen, confirming
it means `supersede`: the new run logs the answer as `Qn` and cites `[source: user, <date>, Qn]`.
Never add a priority silently.

**Limits:** these checks are lexical. They prove the quote exists at the cited place and shares terms,
numbers and qualifiers with the requirement. They do **not** prove the passage supports the meaning. A
requirement that negates or narrows its passage while reusing its words passes, and so does a paraphrase
that keeps the shared terms. A correct paraphrase with no shared terms can be rejected. Assumption detection
in prose is keyword-based and misses unmarked assumptions.

---

## T2 proposal_a.md / proposal_b.md (architects, Stage 2)

```markdown
# Proposal <A|B>: <one-line summary>
## 1. Architecture and module boundaries
## 2. End-to-end workflow
## 3. Data flow and artifact contracts
## 4. LLM versus deterministic code responsibilities
## 5. Error handling and recovery
## 6. Evidence and factual-integrity controls
## 7. Automation and human approval boundaries
## 8. Test strategy
## 9. Cost and complexity estimate
(model calls per application, tokens, implementation effort; all marked [ESTIMATE] with derivation)
## 10. Known weaknesses and unresolved assumptions
## Independence attestation
Files read: <list>. I did not read any other architect's artifact.
```

---

## T3 risk_assessment_a.md / risk_assessment_b.md (architects, Stage 3)

```markdown
# Risk assessment <A|B>
## Failure modes
### FM-1 <name>
Requirement: <IDs>. Likelihood: <low/med/high> [JUDGEMENT]. Impact: <...>.
Scenario: <concrete sequence of events>. Detection: <test or signal>.
### FM-2 ... ### FM-5
## Independence attestation
Files read: <list>.
```

Exactly five failure modes, ranked by risk. They assess the requirements, not a proposal.

---

## T4 parts/cross_exam_N_<a|b>.md (architects, Stage 4)

```markdown
# Cross-examination by <A|B> of Proposal <B|A>
## Strongest aspects
### S-1 <aspect>  (why it serves which requirement)
### S-2 ...
### S-3 ...
## Weaknesses
### W-1 <specific decision being criticised>
Requirement: <IDs / acceptance test affected>
Failure scenario: <concrete inputs → wrong outcome>
Severity: <critical | major | minor> [JUDGEMENT]
Repair or test: <change, or experiment that would settle it>
### W-2 ... (at least five; if fewer genuinely exist, write "Fewer than five material weaknesses found because ...")
## Disagreements to resolve
- <disagreement> → <test or experiment that would resolve it>
```

Criticise architectural decisions, not prose. Fewer, well-evidenced objections beat many weak ones.

---

## T5 parts/rebuttal_2_<a|b>.md (architects, Stage 5)

```markdown
# Rebuttal and revision by <A|B>
## Concessions
- W-n from <peer>: conceded because ...
## Rejected objections
- W-n: rejected because <evidence/reasoning>; what would change my mind: ...
## Revisions
### R-1 <title>
Original: <what the proposal said>
Objection: <W-n and who raised it>
Evidence: <reasoning, file path, or [UNVERIFIED]>
Revised design: <new decision>
Remaining trade-off: <what is still given up>
(or write "No revisions" with a reason)
## Revised proposal
<compact restatement of the full revised architecture: modules, flow, gates, call count>
```

---

## T6 parts/judge_criteria.md (judge, before seeing proposals)

```markdown
# Judge criteria (set blind, from requirements only)
## Hard rejection criteria
### HG-1 <gate> (requirement IDs). Fail if: <observable condition>. Critical: yes/no
### HG-2 ...
## Weights
| Dimension | Weight |
|---|---|
| Correctness and factual integrity | 25% |
| ... (must sum to 100%) |
## Weight changes
<None, or each change from the defaults/focus-adjusted weights and why>
```

---

## T7 comparison_matrix.md (judge, Stage 6)

```markdown
# Comparison matrix
## Hard rejection criteria
<copied from judge_criteria.md, unchanged>
## Hard-gate results
| Gate | Proposal A (revised) | Proposal B (revised) | Evidence |
| HG-1 | PASS | FAIL | ... [JUDGEMENT] |
## Weights
<same table as criteria; any change recorded with reason>
## Weighted comparison
| Dimension | Weight | A score (1-5) | B score (1-5) | Rationale and evidence class |
Weighted totals: A = x.xx, B = y.yy. Gate-failing proposals are listed but cannot be selected.
## Complementary and incompatible elements
```

---

## T8 final_decision.md (judge, Stage 7)

```markdown
# Decision record: <title>
Run: <run_id>. Requirements sha256: <hash>. Commit: <sha>.
## Chosen architecture
<A | B | hybrid | neither: third design required>, with a summary
## Requirements traceability
| Requirement | Component that satisfies it | Verified by (AT-n) |
## Weighted comparison and hard-gate results
## Adopted components
- From A: ...  - From B: ...
## Rejected alternatives
## Remaining risks
## Unresolved disagreements
## Experiments
- EXP-1 Hypothesis / method / metric / decision rule
## Implementation sequence
1. ... (small, independently testable steps)
## Rollback and recovery
## Implementation acceptance criteria
## Evidence classification
<which conclusions are [MEASURED], [ESTIMATE], [JUDGEMENT]; list [UNVERIFIED] claims>
## Additional round
Required: no   (or "Required: yes" plus the material issue that would change the decision)
```
