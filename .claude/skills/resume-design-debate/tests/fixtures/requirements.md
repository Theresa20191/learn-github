# Requirements snapshot (SYNTHETIC TEST FIXTURE)
Scope: full-system. Focus: balanced.

## Functional requirements
- FR-1 Generate a tailored resume from a master profile and a job description [source: docs/requirements.md:3 "generates a tailored resume from a master profile and a job description"]
- FR-2 Generate a cover letter for each job description [source: docs/requirements.md:4 "generates a cover letter for each job description"]
## Non-functional requirements
- NFR-1 A rerun with unchanged inputs produces identical artifacts [source: docs/requirements.md:5 "A rerun with unchanged inputs must produce identical artifacts"]
- NFR-2 Model usage under USD 0.50 per job description, as a target [source: docs/requirements.md:10 "Target cost: under USD 0.50 of model usage per job description"]
## Safety and privacy constraints
- SP-1 No claim may appear without a source in the master profile [source: docs/requirements.md:6 "No claim may appear in any output without a source in the master profile"]
## Operational constraints
- OP-1 Runs locally from the CLI [source: docs/requirements.md:7 "runs locally from the command line"]
## Acceptance tests
- AT-1 Every bullet maps to a profile evidence ID (covers SP-1) [source: docs/requirements.md:8 "every bullet maps to a profile evidence ID"]
## Optimisation priorities
- PR-1 Factual integrity over speed [source: docs/requirements.md:9 "Factual integrity takes priority over speed"]
## Gaps and conflicts
- Quality versus cost priority is open in the source (docs/requirements.md:11); not used by any requirement.
## Assumptions
None.
## User confirmations
- None required: every item is sourced.
## Sources
- docs/requirements.md  (synthetic)
