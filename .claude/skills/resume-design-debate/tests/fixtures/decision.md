# Decision record (synthetic)
## Chosen architecture
Hybrid.
## Requirements traceability
| FR-1 | generator | AT-1 |
## Weighted comparison and hard-gate results
Both pass HG-1 [JUDGEMENT].
## Adopted components
- From A: verifier. - From B: caching.
## Rejected alternatives
None.
## Remaining risks
Verifier recall [UNVERIFIED].
## Unresolved disagreements
Cache key scope.
## Experiments
- EXP-1 measure verifier recall on 20 fixtures.
## Implementation sequence
1. Verifier.
## Rollback and recovery
Revert per step.
## Implementation acceptance criteria
AT-1 passes.
## Evidence classification
Cost figures are [ESTIMATE]; ranking is [JUDGEMENT]; nothing [MEASURED].
## Additional round
Required: no
