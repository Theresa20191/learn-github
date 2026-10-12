#!/usr/bin/env python3
"""Deterministic state manager for the resume-design-debate skill.

The LLM orchestrator does the reasoning; this script does the bookkeeping that
must not depend on an LLM: unique run directories, hashes, stage validation,
resume points, independence checks, judge-input checks and the design-only
guard. Standard library only.

Usage (run from the repository root, or pass --root):
  debate_run.py init [--scope S] [--focus F] [--mode M]
  debate_run.py start  RUN STAGE [--agent NAME]
  debate_run.py record RUN STAGE [--agent NAME]
  debate_run.py fail   RUN STAGE --error MSG [--agent NAME]
  debate_run.py next   RUN
  debate_run.py assemble RUN STAGE
  debate_run.py judge-inputs RUN
  debate_run.py check-independence RUN
  debate_run.py add-round RUN --reason MSG
  debate_run.py guard  RUN
  debate_run.py block  RUN --reason MSG
  debate_run.py supersede RUN --reason MSG   (requirements/answers changed after freezing)
  debate_run.py finalize RUN
  debate_run.py status RUN
  debate_run.py list
  debate_run.py weights [--focus F]

RUN is a run id or a path to a run directory. Every command prints JSON.
Exit codes: 0 ok, 1 validation/guard failure, 2 usage or state error.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

AGENT_A = "architect-reliability"
AGENT_B = "architect-efficiency"
JUDGE = "design-judge"

SCOPES_DEFAULT = "full-system"
FOCI = ("balanced", "reliability", "quality", "cost", "automation")
MODES = ("design-only", "implementation-after-approval")

DEFAULT_WEIGHTS = {
    "Correctness and factual integrity": 25,
    "Reliability and recoverability": 20,
    "Output quality and requirement coverage": 20,
    "Operational simplicity and maintainability": 15,
    "Runtime and model-call efficiency": 10,
    "Privacy and security": 10,
}
# Focus shifts 5 points between two dimensions. Correctness and privacy are
# never reduced by a focus setting.
FOCUS_SHIFTS = {
    "balanced": None,
    "reliability": ("Reliability and recoverability", "Runtime and model-call efficiency"),
    "quality": ("Output quality and requirement coverage", "Operational simplicity and maintainability"),
    "cost": ("Runtime and model-call efficiency", "Output quality and requirement coverage"),
    "automation": ("Operational simplicity and maintainability", "Reliability and recoverability"),
}

PROPOSAL_HEADINGS = [
    "Architecture and module boundaries",
    "End-to-end workflow",
    "Data flow and artifact contracts",
    "LLM versus deterministic code responsibilities",
    "Error handling and recovery",
    "Evidence and factual-integrity controls",
    "Automation and human approval boundaries",
    "Test strategy",
    "Cost and complexity estimate",
    "Known weaknesses and unresolved assumptions",
    "Independence attestation",
]
REQUIREMENTS_HEADINGS = [
    "Functional requirements",
    "Non-functional requirements",
    "Safety and privacy constraints",
    "Operational constraints",
    "Acceptance tests",
    "Optimisation priorities",
    "Gaps and conflicts",
    "User confirmations",
    "Sources",
]
# Run states in which stages may still be started or recorded.
ACTIVE_STATUSES = ("in_progress", "incomplete")
RISK_HEADINGS = ["Failure modes", "Independence attestation"]
CROSS_HEADINGS = ["Strongest aspects", "Weaknesses", "Disagreements to resolve"]
REBUTTAL_HEADINGS = ["Concessions", "Rejected objections", "Revisions", "Revised proposal"]
CRITERIA_HEADINGS = ["Hard rejection criteria", "Weights", "Weight changes"]
MATRIX_HEADINGS = [
    "Hard rejection criteria",
    "Hard-gate results",
    "Weights",
    "Weighted comparison",
    "Complementary and incompatible elements",
]
DECISION_HEADINGS = [
    "Chosen architecture",
    "Requirements traceability",
    "Weighted comparison and hard-gate results",
    "Adopted components",
    "Rejected alternatives",
    "Remaining risks",
    "Unresolved disagreements",
    "Experiments",
    "Implementation sequence",
    "Rollback and recovery",
    "Implementation acceptance criteria",
    "Evidence classification",
    "Additional round",
]

# stage id -> (artifact path relative to run dir, agent or None, deps, kind)
BASE_STAGES: dict[str, tuple[str, str | None, list[str], str]] = {
    "requirements": ("requirements_snapshot.md", None, [], "requirements"),
    "proposal_a": ("proposal_a.md", AGENT_A, ["requirements"], "proposal"),
    "proposal_b": ("proposal_b.md", AGENT_B, ["requirements"], "proposal"),
    "risk_a": ("risk_assessment_a.md", AGENT_A, ["requirements"], "risk"),
    "risk_b": ("risk_assessment_b.md", AGENT_B, ["requirements"], "risk"),
    "judge_criteria": ("parts/judge_criteria.md", JUDGE, ["requirements"], "criteria"),
    "cross_exam_1_a": ("parts/cross_exam_1_a.md", AGENT_A,
                       ["proposal_a", "proposal_b", "risk_a", "risk_b"], "cross"),
    "cross_exam_1_b": ("parts/cross_exam_1_b.md", AGENT_B,
                       ["proposal_a", "proposal_b", "risk_a", "risk_b"], "cross"),
    "cross_exam_1": ("cross_exam_round_1.md", None, ["cross_exam_1_a", "cross_exam_1_b"], "assembled"),
    "rebuttal_2_a": ("parts/rebuttal_2_a.md", AGENT_A, ["cross_exam_1"], "rebuttal"),
    "rebuttal_2_b": ("parts/rebuttal_2_b.md", AGENT_B, ["cross_exam_1"], "rebuttal"),
    "rebuttal_2": ("rebuttal_round_2.md", None, ["rebuttal_2_a", "rebuttal_2_b"], "assembled"),
    "comparison_matrix": ("comparison_matrix.md", JUDGE, ["judge_criteria", "rebuttal_2"], "matrix"),
    "final_decision": ("final_decision.md", JUDGE, ["comparison_matrix"], "decision"),
}
ROUND3_STAGES: dict[str, tuple[str, str | None, list[str], str]] = {
    "cross_exam_3_a": ("parts/cross_exam_3_a.md", AGENT_A, ["rebuttal_2"], "cross"),
    "cross_exam_3_b": ("parts/cross_exam_3_b.md", AGENT_B, ["rebuttal_2"], "cross"),
    "cross_exam_3": ("cross_exam_round_3.md", None, ["cross_exam_3_a", "cross_exam_3_b"], "assembled"),
}
ASSEMBLED_FROM = {
    "cross_exam_1": ("Cross-examination, round 1", ["cross_exam_1_a", "cross_exam_1_b"]),
    "rebuttal_2": ("Rebuttal and revision, round 2", ["rebuttal_2_a", "rebuttal_2_b"]),
    "cross_exam_3": ("Cross-examination, round 3 (judge-requested)", ["cross_exam_3_a", "cross_exam_3_b"]),
}
# Artifacts an independent stage must not have seen.
PEER_ARTIFACTS = {
    "proposal_a": ["proposal_b.md", "risk_assessment_b.md"],
    "risk_a": ["proposal_b.md", "risk_assessment_b.md"],
    "proposal_b": ["proposal_a.md", "risk_assessment_a.md"],
    "risk_b": ["proposal_a.md", "risk_assessment_a.md"],
    "judge_criteria": ["proposal_a.md", "proposal_b.md", "risk_assessment_a.md", "risk_assessment_b.md"],
}
JUDGE_INPUTS = [
    "requirements_snapshot.md", "proposal_a.md", "proposal_b.md",
    "risk_assessment_a.md", "risk_assessment_b.md", "parts/judge_criteria.md",
    "cross_exam_round_1.md", "rebuttal_round_2.md",
]

# Only these sections define requirements; IDs mentioned elsewhere (gaps, Q/A) are references.
REQUIREMENT_SECTIONS = REQUIREMENTS_HEADINGS[:6]
REQ_ID = re.compile(r"^\s*[-*]\s*\**((?:FR|NFR|SP|OP|AT|PR)-\d+)\b")


class StateError(Exception):
    pass


# ---------------------------------------------------------------- utilities

def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.decode("utf-8", "replace")


def repo_root(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    top = git(Path.cwd(), "rev-parse", "--show-toplevel")
    return Path(top.strip()) if top else Path.cwd()


def runs_dir(root: Path) -> Path:
    return root / "design" / "runs"


def resolve_run(root: Path, run: str) -> Path:
    p = Path(run)
    if not p.is_absolute():
        p = runs_dir(root) / run if not (root / run).is_dir() else root / run
    if not (p / "manifest.json").is_file():
        raise StateError(f"no manifest.json in {p}")
    return p


def load(run_dir: Path) -> dict:
    return json.loads((run_dir / "manifest.json").read_text())


def save(run_dir: Path, manifest: dict) -> None:
    tmp = run_dir / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    os.replace(tmp, run_dir / "manifest.json")


def event(manifest: dict, msg: str, **kw) -> None:
    manifest.setdefault("events", []).append({"at": now(), "event": msg, **kw})


def stage_table(manifest: dict) -> dict:
    table = dict(BASE_STAGES)
    if manifest.get("round3"):
        table.update(ROUND3_STAGES)
        path, agent, deps, kind = table["comparison_matrix"]
        table["comparison_matrix"] = (path, agent, deps + ["cross_exam_3"], kind)
    return table


def git_changes(root: Path) -> dict[str, str]:
    """Map of changed/untracked path -> content hash ('deleted' if absent)."""
    out = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if out is None:
        return {}
    changes: dict[str, str] = {}
    entries = out.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1  # skip the rename source
        fp = root / path
        changes[path] = sha256_file(fp) if fp.is_file() else "deleted"
    return changes


def in_design_dir(path: str) -> bool:
    return path == "design" or path.startswith("design/")


# --------------------------------------------------------------- validation

def sections(text: str) -> dict[str, str]:
    """Split Markdown into {level-2 heading (lower-case): body}."""
    out: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(?!#)(.+?)\s*$", line)
        if m:
            if current is not None:
                out[current] = "\n".join(buf)
            current = re.sub(r"^\d+[.)]\s*", "", m.group(1)).strip().lower()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf)
    return out


def blocks(body: str, prefix: str) -> list[str]:
    parts = re.split(rf"(?m)^###\s+{prefix}-\d+", body)
    return parts[1:]


def require_headings(secs: dict[str, str], headings: list[str]) -> list[str]:
    return [f"missing section '## {h}'" for h in headings if h.lower() not in secs]


def percents(body: str) -> list[int]:
    """Percentages in a weights section, ignoring any 'Total' row."""
    return [int(x) for line in body.splitlines() if "total" not in line.lower()
            for x in re.findall(r"\b(\d{1,3})\s*%", line)]


def validate(kind: str, text: str, stage: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for an artifact of the given kind."""
    errors: list[str] = []
    warnings: list[str] = []
    if not text.strip():
        return ["artifact is empty (missing agent output)"], warnings
    secs = sections(text)

    if kind == "requirements":
        errors += require_headings(secs, REQUIREMENTS_HEADINGS)
        ids = []
        req_lines = [ln for h in REQUIREMENT_SECTIONS for ln in secs.get(h.lower(), "").splitlines()]
        for line in req_lines:
            m = REQ_ID.match(line)
            if not m:
                continue
            ids.append(m.group(1))
            low = line.lower()
            if "[unsourced" in low:
                # Questions are asked BEFORE the snapshot is frozen; a frozen snapshot
                # can never be amended with the answers (supersede instead).
                errors.append(f"{m.group(1)} is still [unsourced]; ask the user and tag it "
                              "[source: user, <date>] or [unconfirmed: <reason>] before recording")
            elif "[unconfirmed" in low:
                warnings.append(f"{m.group(1)} is an unconfirmed assumption")
            elif "[source:" not in low:
                errors.append(f"{m.group(1)} has no [source: ...] or [unconfirmed: ...] tag")
        if not ids:
            errors.append("no requirement IDs (FR-/NFR-/SP-/OP-/AT-/PR-) found")
        if not any(i.startswith("AT-") for i in ids):
            errors.append("no acceptance tests (AT-n) found")
        if len(ids) != len(set(ids)):
            errors.append("duplicate requirement IDs")
        src = secs.get("sources", "")
        if not re.search(r"\S", src):
            errors.append("'## Sources' is empty")
        if "[source: user" in text.lower() and not re.search(r"(?im)^\s*[-*]\s*Q:", secs.get("user confirmations", "")):
            errors.append("items cite [source: user, ...] but '## User confirmations' records no '- Q: ... A: ...' entries")

    elif kind == "proposal":
        errors += require_headings(secs, PROPOSAL_HEADINGS)

    elif kind == "risk":
        errors += require_headings(secs, RISK_HEADINGS)
        fms = set(re.findall(r"(?m)^###\s+FM-(\d+)", secs.get("failure modes", "")))
        missing = [n for n in "12345" if n not in fms]
        if missing:
            errors.append(f"failure modes FM-{', FM-'.join(missing)} missing (exactly five required)")

    elif kind == "cross":
        errors += require_headings(secs, CROSS_HEADINGS)
        strong = blocks(secs.get("strongest aspects", ""), "S")
        if len(strong) < 3:
            errors.append(f"needs 3 strongest aspects (### S-n), found {len(strong)}")
        weak_body = secs.get("weaknesses", "")
        weak = blocks(weak_body, "W")
        if len(weak) < 5 and "fewer than five" not in weak_body.lower():
            errors.append(f"needs >=5 weaknesses (### W-n) or an explicit 'fewer than five' justification, found {len(weak)}")
        for n, b in enumerate(weak, 1):
            for field in ("Requirement:", "Failure scenario:", "Repair or test:"):
                if field.lower() not in b.lower():
                    errors.append(f"W-{n} lacks '{field}'")

    elif kind == "rebuttal":
        errors += require_headings(secs, REBUTTAL_HEADINGS)
        revs = blocks(secs.get("revisions", ""), "R")
        for n, b in enumerate(revs, 1):
            for field in ("Original:", "Objection:", "Evidence:", "Revised design:", "Remaining trade-off:"):
                if field.lower() not in b.lower():
                    errors.append(f"R-{n} lacks '{field}'")
        if not revs and "no revisions" not in secs.get("revisions", "").lower():
            errors.append("'## Revisions' has no ### R-n entries and does not state 'No revisions'")

    elif kind == "criteria":
        errors += require_headings(secs, CRITERIA_HEADINGS)
        if not re.search(r"(?m)^###\s+HG-\d+", secs.get("hard rejection criteria", "")):
            errors.append("no hard gates (### HG-n) defined")
        w = percents(secs.get("weights", ""))
        if sum(w) != 100:
            errors.append(f"weights sum to {sum(w)}%, expected 100%")

    elif kind == "matrix":
        errors += require_headings(secs, MATRIX_HEADINGS)
        w = percents(secs.get("weights", ""))
        if sum(w) != 100:
            errors.append(f"weights sum to {sum(w)}%, expected 100%")
        if not re.search(r"(?i)\b(pass|fail)\b", secs.get("hard-gate results", "")):
            errors.append("'## Hard-gate results' has no PASS/FAIL entries")

    elif kind == "decision":
        errors += require_headings(secs, DECISION_HEADINGS)
        add = secs.get("additional round", "")
        if not re.search(r"(?i)required:\s*(yes|no)\b", add):
            errors.append("'## Additional round' must state 'Required: yes' or 'Required: no'")
        tags = set(re.findall(r"\[(MEASURED|ESTIMATE|JUDGEMENT|UNVERIFIED)\]", text))
        if not ({"ESTIMATE", "JUDGEMENT"} & tags):
            errors.append("decision does not classify evidence ([MEASURED]/[ESTIMATE]/[JUDGEMENT])")

    elif kind == "assembled":
        pass

    # Independence attestation must not mention peer artifacts.
    if stage in PEER_ARTIFACTS:
        att = secs.get("independence attestation", "")
        if kind == "criteria":
            att = text  # judge criteria must not reference proposals at all
        for peer in PEER_ARTIFACTS[stage]:
            if peer in att:
                errors.append(f"independence violated: artifact references peer file {peer}")
    return errors, warnings


# ----------------------------------------------------------------- commands

def cmd_init(root: Path, a) -> dict:
    if a.focus not in FOCI:
        raise StateError(f"focus must be one of {FOCI}")
    if a.mode not in MODES:
        raise StateError(f"mode must be one of {MODES}")
    base = runs_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(5):
        run_id = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3)
        run_dir = base / run_id
        try:
            run_dir.mkdir()  # exclusive: never reuse an existing run
            break
        except FileExistsError:
            continue
    else:
        raise StateError("could not allocate a unique run id")
    (run_dir / "parts").mkdir()
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    baseline = git_changes(root)
    manifest = {
        "schema": 1,
        "run_id": run_id,
        "created_at": now(),
        "repo_commit": head.strip() if head else None,
        "repo_branch": branch.strip() if branch else None,
        "repo_dirty_at_start": bool(baseline),
        "args": {"scope": a.scope, "focus": a.focus, "mode": a.mode},
        "agents": {"A": AGENT_A, "B": AGENT_B, "judge": JUDGE},
        "weights": weights_for(a.focus),
        "requirements_sha256": None,
        "requirements_sources": [],
        "round3": False,
        "status": "in_progress",
        "guard_baseline": {"head": head.strip() if head else None, "changes": baseline},
        "stages": {k: {"status": "pending", "attempts": 0} for k in BASE_STAGES},
        "events": [],
    }
    event(manifest, "init")
    save(run_dir, manifest)
    return {"ok": True, "run_id": run_id, "run_dir": str(run_dir)}


def require_active(m: dict, stage: str | None = None) -> None:
    if m["status"] not in ACTIVE_STATUSES:
        extra = f" (superseded by {m['superseded_by']})" if m.get("superseded_by") else ""
        raise StateError(f"run is {m['status']}{extra}; it is immutable. Start or use a new run")
    if stage == "requirements" and m.get("requirements_sha256"):
        raise StateError("requirements are frozen for this run (sha256 recorded). A changed requirement or "
                          "answer needs a new run: debate_run.py supersede RUN --reason ...")


def check_deps(manifest: dict, stage: str) -> list[str]:
    table = stage_table(manifest)
    return [d for d in table[stage][2] if manifest["stages"][d]["status"] != "ok"]


def cmd_start(run_dir: Path, a) -> dict:
    m = load(run_dir)
    table = stage_table(m)
    if a.stage not in table:
        raise StateError(f"unknown stage {a.stage}")
    st = m["stages"][a.stage]
    if st["status"] == "ok":
        raise StateError(f"stage {a.stage} already ok; earlier debate artifacts are never overwritten")
    require_active(m, a.stage)
    missing = check_deps(m, a.stage)
    if missing:
        raise StateError(f"stage {a.stage} blocked; prerequisites not ok: {missing}")
    if st["status"] == "in_progress":
        event(m, "interrupted_attempt_detected", stage=a.stage)
    # A retry never inherits output from an interrupted or invalidated attempt. After a
    # *failed* attempt the bad output was already archived by record/fail, so a file present
    # now is the new attempt's output (e.g. a corrected draft or the judge's two-file reply).
    if st["status"] in ("in_progress", "invalidated"):
        stale = archive_failed(run_dir, table[a.stage][0], a.stage, st["attempts"], suffix="stale")
        if stale:
            event(m, "archived_stale_output", stage=a.stage, path=stale,
                  sha256=sha256_file(run_dir / stale))
    peers_present = [p for p in PEER_ARTIFACTS.get(a.stage, []) if (run_dir / p).exists()]
    st.update(status="in_progress", started_at=now(), agent=a.agent or table[a.stage][1])
    st["attempts"] = st.get("attempts", 0) + 1
    if a.stage in PEER_ARTIFACTS:
        st["peer_artifacts_present_at_start"] = peers_present
    event(m, "start", stage=a.stage, attempt=st["attempts"])
    save(run_dir, m)
    out = {"ok": True, "stage": a.stage, "artifact": str(run_dir / table[a.stage][0]), "attempt": st["attempts"]}
    if peers_present:
        out["warning"] = ("peer artifacts already exist on disk: "
                          f"{peers_present}; prompt must forbid reading them and independence is recorded as weakened")
    return out


def archive_failed(run_dir: Path, rel: str, stage: str, attempt: int, suffix: str = "") -> str | None:
    src = run_dir / rel
    if not src.exists():
        return None
    dest_dir = run_dir / "parts" / "failed"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{stage}.attempt{attempt}{'.' + suffix if suffix else ''}.md"
    n = 1
    while dest.exists():  # never overwrite an earlier archive
        n += 1
        dest = dest.with_name(f"{stage}.attempt{attempt}.{suffix or 'dup'}{n}.md")
    shutil.move(str(src), dest)
    return str(dest.relative_to(run_dir))


def cmd_record(run_dir: Path, a) -> dict:
    m = load(run_dir)
    table = stage_table(m)
    if a.stage not in table:
        raise StateError(f"unknown stage {a.stage}")
    rel, agent, _deps, kind = table[a.stage]
    st = m["stages"][a.stage]
    if st["status"] == "ok":
        raise StateError(f"stage {a.stage} already ok")
    require_active(m, a.stage)
    missing = check_deps(m, a.stage)
    if missing:
        raise StateError(f"stage {a.stage} blocked; prerequisites not ok: {missing}")
    path = run_dir / rel
    text = path.read_text() if path.is_file() else ""
    errors, warnings = validate(kind, text, a.stage)
    if not path.is_file():
        errors = ["artifact file not written (missing agent output)"]
    attempt = st.get("attempts", 0) or 1
    if errors:
        archived = archive_failed(run_dir, rel, a.stage, attempt)
        st.update(status="failed", failed_at=now(), errors=errors, archived=archived)
        event(m, "validation_failed", stage=a.stage, errors=errors, archived=archived,
              sha256=sha256_file(run_dir / archived) if archived else None)
        save(run_dir, m)
        return {"ok": False, "stage": a.stage, "errors": errors, "archived": archived}
    st.update(status="ok", completed_at=now(), sha256=sha256_file(path), warnings=warnings,
              agent=a.agent or agent, errors=[])
    if st.get("peer_artifacts_present_at_start"):
        st["independence"] = "weakened"
    elif a.stage in PEER_ARTIFACTS:
        st["independence"] = "clean"
    if a.stage == "requirements":
        m["requirements_sha256"] = st["sha256"]
        m["requirements_sources"] = hash_sources(run_dir, text)
    event(m, "record_ok", stage=a.stage)
    save(run_dir, m)
    return {"ok": True, "stage": a.stage, "sha256": st["sha256"], "warnings": warnings}


def hash_sources(run_dir: Path, text: str) -> list[dict]:
    root = run_dir.parents[2]
    out = []
    for line in sections(text).get("sources", "").splitlines():
        m = re.match(r"^\s*[-*]\s*`?([^`\s:]+)", line)
        if not m:
            continue
        p = root / m.group(1)
        out.append({"path": m.group(1), "sha256": sha256_file(p) if p.is_file() else None})
    return out


def cmd_fail(run_dir: Path, a) -> dict:
    m = load(run_dir)
    table = stage_table(m)
    if a.stage not in table:
        raise StateError(f"unknown stage {a.stage}")
    st = m["stages"][a.stage]
    if st["status"] == "ok":
        raise StateError(f"stage {a.stage} already ok")
    require_active(m)
    archived = archive_failed(run_dir, table[a.stage][0], a.stage, st.get("attempts", 0) or 1)
    st.update(status="failed", failed_at=now(), errors=[a.error], archived=archived)
    event(m, "agent_failed", stage=a.stage, error=a.error, archived=archived,
          sha256=sha256_file(run_dir / archived) if archived else None)
    save(run_dir, m)
    return {"ok": True, "stage": a.stage, "status": "failed", "archived": archived}


def verify_integrity(run_dir: Path, m: dict) -> list[str]:
    """Invalidate ok stages whose artifact changed or vanished, and dependants."""
    table = stage_table(m)
    invalid: list[str] = []
    for stage in table:
        st = m["stages"][stage]
        if st["status"] != "ok":
            continue
        p = run_dir / table[stage][0]
        if not p.is_file() or sha256_file(p) != st.get("sha256"):
            invalid.append(stage)
    changed = True
    while changed:
        changed = False
        for stage, (_r, _a, deps, _k) in table.items():
            if stage not in invalid and m["stages"][stage]["status"] == "ok" and set(deps) & set(invalid):
                invalid.append(stage)
                changed = True
    for stage in invalid:
        m["stages"][stage].update(status="invalidated", errors=["artifact or prerequisite changed after recording"])
        event(m, "invalidated", stage=stage)
    if "requirements" in invalid and m["status"] in ACTIVE_STATUSES:
        p = run_dir / table["requirements"][0]
        m["status"] = "requirements_changed"
        event(m, "requirements_changed_after_freeze", recorded_sha256=m["requirements_sha256"],
              current_sha256=sha256_file(p) if p.is_file() else None)
    return invalid


def cmd_next(run_dir: Path, _a) -> dict:
    m = load(run_dir)
    invalid = verify_integrity(run_dir, m)
    if invalid:
        save(run_dir, m)
    table = stage_table(m)
    runnable, interrupted, recoverable = [], [], []
    for stage in table:
        st = m["stages"][stage]
        if st["status"] == "ok":
            continue
        if st["status"] == "in_progress":
            interrupted.append(stage)
            if (run_dir / table[stage][0]).is_file():
                recoverable.append(stage)  # output saved, never recorded: try `record` first
        if not check_deps(m, stage):
            runnable.append({"stage": stage, "agent": table[stage][1], "artifact": table[stage][0],
                             "previous_status": st["status"], "attempts": st.get("attempts", 0)})
    done = all(m["stages"][s]["status"] == "ok" for s in table)
    action = None
    if m["status"] not in ACTIVE_STATUSES:
        runnable = []  # an inactive run never advances
        action = ("supersede" if m["status"] == "requirements_changed"
                  else f"run is {m['status']}; nothing to resume")
    return {"ok": True, "action": action, "run_id": m["run_id"], "run_status": m["status"], "all_stages_ok": done,
            "runnable": runnable, "interrupted": interrupted, "recoverable": recoverable,
            "invalidated": invalid}


def cmd_assemble(run_dir: Path, a) -> dict:
    m = load(run_dir)
    if a.stage not in ASSEMBLED_FROM:
        raise StateError(f"{a.stage} is not an assembled stage")
    if m["stages"].get(a.stage, {}).get("status") == "ok":
        raise StateError(f"{a.stage} already ok; not overwriting")
    require_active(m)
    title, parts = ASSEMBLED_FROM[a.stage]
    missing = check_deps(m, a.stage)
    if missing:
        raise StateError(f"cannot assemble; parts not ok: {missing}")
    table = stage_table(m)
    labels = {"_a": f"Architect A ({AGENT_A}) on Proposal B", "_b": f"Architect B ({AGENT_B}) on Proposal A"}
    if a.stage.startswith("rebuttal"):
        labels = {"_a": f"Architect A ({AGENT_A}) rebuttal and revision", "_b": f"Architect B ({AGENT_B}) rebuttal and revision"}
    chunks = [f"# {title}\n", f"Run: `{m['run_id']}`. Assembled verbatim from the per-agent parts.\n"]
    for part in parts:
        body = (run_dir / table[part][0]).read_text()
        body = re.sub(r"(?m)^(#{1,5})\s", lambda x: "#" + x.group(1) + " ", body)  # demote headings
        chunks.append(f"\n## {labels[part[-2:]]}\n\nSource part: `{table[part][0]}` (sha256 `{m['stages'][part]['sha256'][:12]}`)\n\n{body.strip()}\n")
    (run_dir / table[a.stage][0]).write_text("\n".join(chunks))
    st = m["stages"][a.stage]
    st["attempts"] = st.get("attempts", 0) + 1
    save(run_dir, m)
    return cmd_record(run_dir, argparse.Namespace(stage=a.stage, agent=None))


def cmd_judge_inputs(run_dir: Path, _a) -> dict:
    m = load(run_dir)
    verify_integrity(run_dir, m)
    inputs = list(JUDGE_INPUTS) + (["cross_exam_round_3.md"] if m.get("round3") else [])
    table = stage_table(m)
    by_path = {v[0]: k for k, v in table.items()}
    problems = []
    for rel in inputs:
        stage = by_path[rel]
        if m["stages"][stage]["status"] != "ok":
            problems.append(f"{rel}: stage {stage} is {m['stages'][stage]['status']}")
    return {"ok": not problems, "inputs": [str(run_dir / r) for r in inputs], "problems": problems,
            "also_provide": ["repository implementation and test results (if any)"]}


def cmd_check_independence(run_dir: Path, _a) -> dict:
    m = load(run_dir)
    report, problems = {}, []
    for stage in ("proposal_a", "proposal_b", "risk_a", "risk_b", "judge_criteria"):
        st = m["stages"][stage]
        report[stage] = {"status": st["status"], "independence": st.get("independence"),
                         "peer_artifacts_present_at_start": st.get("peer_artifacts_present_at_start")}
        if st["status"] != "ok":
            problems.append(f"{stage} not persisted (status {st['status']})")
    for cross in ("cross_exam_1_a", "cross_exam_1_b"):
        st = m["stages"][cross]
        if st.get("started_at"):
            for stage in ("proposal_a", "proposal_b", "risk_a", "risk_b"):
                done = m["stages"][stage].get("completed_at")
                if not done or done > st["started_at"]:
                    problems.append(f"{cross} started before {stage} was persisted")
    weakened = [s for s, r in report.items() if r["independence"] == "weakened"]
    return {"ok": not problems, "stages": report, "problems": problems, "weakened": weakened}


def cmd_add_round(run_dir: Path, a) -> dict:
    m = load(run_dir)
    require_active(m)
    if m.get("round3"):
        raise StateError("an additional round was already added; only one is permitted")
    if m["stages"]["rebuttal_2"]["status"] != "ok":
        raise StateError("additional round requires rebuttal_2 to be ok")
    m["round3"] = True
    m["round3_reason"] = a.reason
    for k in ROUND3_STAGES:
        m["stages"][k] = {"status": "pending", "attempts": 0}
    sup = run_dir / "parts" / "superseded"
    sup.mkdir(parents=True, exist_ok=True)
    for stage in ("comparison_matrix", "final_decision"):
        rel = BASE_STAGES[stage][0]
        src = run_dir / rel
        if src.exists():
            shutil.move(str(src), sup / f"{Path(rel).stem}.before_round3.md")
        m["stages"][stage] = {"status": "pending", "attempts": 0, "superseded_before_round3": True}
    event(m, "add_round", reason=a.reason)
    save(run_dir, m)
    return {"ok": True, "added": list(ROUND3_STAGES), "reset": ["comparison_matrix", "final_decision"]}


def cmd_guard(run_dir: Path, _a) -> dict:
    m = load(run_dir)
    root = run_dir.parents[2]
    base = m["guard_baseline"]
    violations = []
    cur = git_changes(root)
    for path, digest in cur.items():
        if in_design_dir(path):
            continue
        if base["changes"].get(path) != digest:
            violations.append(path)
    for path in base["changes"]:
        if not in_design_dir(path) and path not in cur:
            violations.append(path)  # reverted or committed away a pre-existing change
    head = git(root, "rev-parse", "HEAD")
    head = head.strip() if head else None
    if base.get("head") and head and head != base["head"]:
        diff = git(root, "diff", "--name-only", base["head"], head) or ""
        violations += [p for p in diff.splitlines() if p and not in_design_dir(p)]
    violations = sorted(set(violations))
    return {"ok": not violations, "mode": m["args"]["mode"], "violations": violations}


def cmd_block(run_dir: Path, a) -> dict:
    m = load(run_dir)
    require_active(m)
    m["status"] = "blocked"
    m["blocked_reason"] = a.reason
    event(m, "blocked", reason=a.reason)
    save(run_dir, m)
    return {"ok": True, "status": "blocked", "reason": a.reason}


def cmd_supersede(run_dir: Path, a) -> dict:
    """Close a run whose requirements or answers changed and open a fresh linked run.

    The old run's artifacts are left byte-for-byte untouched; only its manifest
    gains the new status, link and event.
    """
    m = load(run_dir)
    if m.get("superseded_by"):
        raise StateError(f"run already superseded by {m['superseded_by']}")
    root = run_dir.parents[2]
    new = cmd_init(root, argparse.Namespace(scope=m["args"]["scope"], focus=m["args"]["focus"],
                                            mode=m["args"]["mode"]))
    new_dir = Path(new["run_dir"])
    nm = load(new_dir)
    nm["supersedes"] = m["run_id"]
    nm["supersede_reason"] = a.reason
    event(nm, "supersedes", run=m["run_id"], reason=a.reason)
    save(new_dir, nm)
    prev = m["status"]
    m["status"] = "superseded"
    m["superseded_by"] = nm["run_id"]
    m["superseded_reason"] = a.reason
    event(m, "superseded", by=nm["run_id"], reason=a.reason, previous_status=prev)
    save(run_dir, m)
    return {"ok": True, "old_run": m["run_id"], "old_status": "superseded", "new_run_id": nm["run_id"],
            "new_run_dir": str(new_dir)}


def cmd_finalize(run_dir: Path, a) -> dict:
    nxt = cmd_next(run_dir, a)
    guard = cmd_guard(run_dir, a)
    ind = cmd_check_independence(run_dir, a)
    m = load(run_dir)
    problems = []
    if not nxt["all_stages_ok"]:
        problems.append("not all stages ok")
    if m["args"]["mode"] == "design-only" and not guard["ok"]:
        problems.append(f"design-only guard violated: {guard['violations']}")
    if not ind["ok"]:
        problems += ind["problems"]
    if m["stages"]["final_decision"]["status"] == "ok":
        dec = sections((run_dir / "final_decision.md").read_text()).get("additional round", "")
        if re.search(r"(?i)required:\s*yes", dec) and not m.get("round3"):
            problems.append("judge requested an additional round; run add-round")
    if m["status"] not in ACTIVE_STATUSES + ("completed",):
        problems.append(f"run is {m['status']}")
        new_status = m["status"]  # blocked / superseded / requirements_changed stay as they are
    else:
        new_status = "completed" if not problems else "incomplete"
    m["status"] = new_status
    m["finalized_at"] = now()
    m["acceptance_checks"] = {"all_stages_ok": nxt["all_stages_ok"], "guard_ok": guard["ok"],
                              "independence_ok": ind["ok"], "independence_weakened": ind["weakened"],
                              "unconfirmed_requirements": m["stages"]["requirements"].get("warnings", []),
                              "problems": problems}
    event(m, "finalize", status=m["status"])
    save(run_dir, m)
    return {"ok": not problems, "status": m["status"], "checks": m["acceptance_checks"]}


def cmd_status(run_dir: Path, _a) -> dict:
    m = load(run_dir)
    return {"ok": True, "run_id": m["run_id"], "status": m["status"], "args": m["args"],
            "requirements_sha256": m["requirements_sha256"], "repo_commit": m["repo_commit"],
            "stages": {k: v["status"] for k, v in m["stages"].items()}}


def cmd_list(root: Path, _a) -> dict:
    base = runs_dir(root)
    runs = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if (d / "manifest.json").is_file():
                m = load(d)
                runs.append({"run_id": m["run_id"], "status": m["status"], "created_at": m["created_at"],
                             "args": m["args"]})
    return {"ok": True, "runs": runs}


def weights_for(focus: str) -> dict:
    w = dict(DEFAULT_WEIGHTS)
    shift = FOCUS_SHIFTS[focus]
    if shift:
        up, down = shift
        w[up] += 5
        w[down] -= 5
    assert sum(w.values()) == 100
    return w


def cmd_weights(_root: Path, a) -> dict:
    if a.focus not in FOCI:
        raise StateError(f"focus must be one of {FOCI}")
    return {"ok": True, "focus": a.focus, "weights": weights_for(a.focus)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", help="repository root (default: git toplevel of cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.add_argument("--scope", default=SCOPES_DEFAULT)
    s.add_argument("--focus", default="balanced")
    s.add_argument("--mode", default="design-only")
    for name in ("start", "record"):
        s = sub.add_parser(name)
        s.add_argument("run")
        s.add_argument("stage")
        s.add_argument("--agent")
    s = sub.add_parser("fail")
    s.add_argument("run")
    s.add_argument("stage")
    s.add_argument("--error", required=True)
    s.add_argument("--agent")
    s = sub.add_parser("assemble")
    s.add_argument("run")
    s.add_argument("stage")
    for name in ("next", "judge-inputs", "check-independence", "guard", "finalize", "status"):
        s = sub.add_parser(name)
        s.add_argument("run")
    for name in ("add-round", "block", "supersede"):
        s = sub.add_parser(name)
        s.add_argument("run")
        s.add_argument("--reason", required=True)
    sub.add_parser("list")
    s = sub.add_parser("weights")
    s.add_argument("--focus", default="balanced")
    a = p.parse_args(argv)
    root = repo_root(a.root)
    run_cmds = {
        "start": cmd_start, "record": cmd_record, "fail": cmd_fail, "next": cmd_next,
        "assemble": cmd_assemble, "judge-inputs": cmd_judge_inputs,
        "check-independence": cmd_check_independence, "add-round": cmd_add_round,
        "guard": cmd_guard, "block": cmd_block, "supersede": cmd_supersede, "finalize": cmd_finalize, "status": cmd_status,
    }
    try:
        if a.cmd in run_cmds:
            result = run_cmds[a.cmd](resolve_run(root, a.run), a)
        else:
            result = {"init": cmd_init, "list": cmd_list, "weights": cmd_weights}[a.cmd](root, a)
    except StateError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
