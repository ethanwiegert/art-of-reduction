# Guided review

This checklist is for a reviewer who did not write the change. Answer every line with evidence: a command run, a `file:line`, or a scorecard number. The verdict at the end is **ship**, **fix first** (list the fixes), or **kill**.

## 1. Moat

- Which claim in `ROADMAP.md` does this serve, and which scorecard number did it move? A change that moves none of them is a kill.
- Is this item the top of **Next**, or is it scope creep?

## 2. Evidence

- `python3 -m unittest discover tests` is green. Paste the last line.
- The `evals/run.py` scorecard is committed. Compare it with the previous file in `evals/results/`: turns saved has not dropped, harnesses folded is still 6/6, and leaks is 0.
- Behavior changed in redaction, mapping or folding has a test with the exact shape it covers.

## 3. House rules (AGENTS.md)

- It uses the standard library only and runs with a bare `python3`.
- It is agent-agnostic. No field, column or doc makes sense for one harness only.
- Hooks fail open: `record.py` still exits 0 and prints `{}` on any input.
- Redaction happens before anything reaches disk, on both `record.py` and `serve.py`.
- `report.py` and `query.py` stay read-only, and `install.sh` still writes no harness config.

## 4. First-time creator

Pretend you have never seen this repo.

- Follow the README from a clean clone into a temp `AOR_HOME`. Does the change work without reading the code?
- Is the new command or output understandable from its `--help` and the `SKILL.md` alone?
- Are the README and `AGENTS.md` updated where commands changed?

## 5. Reduction

- Did the change remove a concept or add one? If it added one, could an existing script have taken it on instead?
- Is anything an agent would re-derive written as prose when it should be a script?
