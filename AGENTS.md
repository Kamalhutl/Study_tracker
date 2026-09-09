# Rules

## Never call the todo tool

This provider serialises array arguments incorrectly. Calling the todo tool
produces `"todos": expected array, got string (not valid JSON)` and the run dies.

- Do not call `todowrite`, `todoread`, or any todo tool. Ever.
- Track progress in plain text instead. Open every step with:
  `STEP <n> | <what you are doing>`
- When a step is done, write one line: `STEP <n> DONE`
- Keep a plain-text checklist in your reply if you need one. Never a tool call.

## Output format

- Never emit `<thinking>`, `<antThinking>`, `<antThought>`, `<reasoning>` or any
  similar tag. If your internal reasoning appears in the reply, you have failed.
- A step is finished when its VERIFY command exits 0. Not before.

## Keep going - do not stop mid-task

- After finishing a step, immediately begin the next one. Do not wait to be told
  to continue.
- Stop only for one of two reasons:
  1. every step is done, or
  2. you write `BLOCKED step <n>: <reason>` after two failed VERIFY attempts.
- If a tool call fails, do not stop. Retry it once differently, and if it still
  fails, write `BLOCKED step <n>: <tool> failed` and move to the next step.
- Never end a reply with a question while work remains. Choose the most
  reasonable option, state the choice in one line, and keep working.
- Never end a reply describing what you are about to do. Do it instead.
- If a step turns out to be already done, mark it `STEP <n> DONE (already
  present)` and move on in the same reply.

## Context budget - this endpoint has a size ceiling

Large requests fail on this proxy. Keeping the conversation small is not a
preference, it is a requirement.

- Read at most 3 files per step.
- Never re-read a file you have already read in this session.
- Never paste a whole file into your reply. Quote only the lines you change.
- Never print directory listings into the reply.
- Do not restate your checklist every turn. Reference step numbers.
- No open-ended exploration. If you cannot find something after 3 searches,
  write `BLOCKED` and say what you looked for.

## Editing

- Use the editor tool only. No heredocs, no `cat >`, no shell redirection into
  files, no multi-line quoted strings.
- One single-line shell command per call.
- Single-quote globs: `--include='*.py'`

## Project invariants - do not violate

- `upsert_job` and `apply_missing_strikes` have FROZEN signatures. Do not change
  their parameters or return types.
- `record_scrape_outcome` is the only writer of company health state.
- Admin code never writes Company fields directly. Every mutation goes through
  `apps/companies/services.py`.
- Work sequentially. No sub-agents, no parallel batches.
