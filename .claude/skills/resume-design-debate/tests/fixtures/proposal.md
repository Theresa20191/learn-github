# Proposal <X>: synthetic pipeline
## 1. Architecture and module boundaries
Parser, matcher, generator, verifier.
## 2. End-to-end workflow
Parse, match, generate, verify, export.
## 3. Data flow and artifact contracts
profile.json -> evidence.json -> draft.md.
## 4. LLM versus deterministic code responsibilities
LLM drafts; Python validates evidence IDs.
## 5. Error handling and recovery
Checkpoint each step.
## 6. Evidence and factual-integrity controls
Each bullet cites an evidence ID (SP-1, AT-1).
## 7. Automation and human approval boundaries
One approval before submission.
## 8. Test strategy
Golden-file tests.
## 9. Cost and complexity estimate
3 calls per job [ESTIMATE: draft+letter+verify].
## 10. Known weaknesses and unresolved assumptions
Verifier recall [UNVERIFIED].
## Independence attestation
Files read: requirements_snapshot.md.
