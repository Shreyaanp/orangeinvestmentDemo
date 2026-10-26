---
name: pre-commit-gate
description: Run the full quality gate before proposing a commit. Use whenever work is done and the user may want to commit.
---

# Pre-commit gate

1. Run `python src/scripts/gate.py` (add `--strict` before submission: every requirement in the matrix must have a test tagged `# covers: R<n>`).
2. Fix failures at the cause. Do not weaken limits, ignore rules, or edit truth files.
3. Update `docs/DECISIONS.md` if a decision changed.
4. Show the user the diff summary and ask. Never commit or push unasked. A hook also blocks `git commit` while the gate fails.
