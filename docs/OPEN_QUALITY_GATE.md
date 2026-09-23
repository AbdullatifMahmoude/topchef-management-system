# Open quality gate

Last verified: 2026-09-22

## Current status

The Python test suite and configured Ruff gate both pass.

### Confirmed evidence

- 202 tests passed.
- `ruff check app tests` passed with zero findings.
- Intentional FastAPI dependency factories are configured as immutable calls for `B008`.
- Broad catches retained at external-service and background-task boundaries have local `BLE001` justifications.
- Previously silent cache and file-logging failures now emit warnings.
- Naive UTC persistence remains compatible with the existing database columns while avoiding deprecated `utcnow()` calls.

### Applied remediation

1. Applied behavior-preserving import, typing, annotation, and simplification fixes.
2. Corrected the public `AppExceptions` export and invalid `any` annotations.
3. Replaced deprecated naive UTC construction with explicit UTC conversion compatible with existing naive database fields.
4. Annotated intentionally broad external-boundary catches locally and added logging where exceptions were previously silent.
5. Re-ran the complete test suite and Ruff gate.

### Guardrails

- Do not run `ruff --fix` across the whole repository as the first action.
- Do not enable `--unsafe-fixes` without reviewing each affected category.
- Do not replace broad exception handling mechanically where it is part of a retry, WebSocket, Redis, logging, or shutdown boundary; define the intended failure behavior first.
- Keep formatting-only changes separate from behavioral fixes where practical.

### Closure criteria

- Every Ruff finding is fixed or narrowly justified: satisfied.
- The complete 202-test baseline remains green: satisfied.
- Ruff reports zero findings: satisfied.

### Commands

```powershell
.\env\Scripts\python.exe -m pytest -q -p no:cacheprovider
.\env\Scripts\ruff.exe check app tests --statistics
```
