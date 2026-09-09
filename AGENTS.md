# Rules

## Output format

- Never emit `<thinking>`, `<antThinking>`, `<antThought>`, `<reasoning>` or any
  similar tag. If your internal reasoning appears in the reply, you have failed.
- Start every step with one line: `STEP <n> | <what you are doing>`
- A step is finished when its VERIFY command exits 0. Not before.

## Keep going - do not stop mid-task

This is the most important rule on this page.

- After finishing a step, **immediately begin the next unchecked item**. Do not
  wait to be told to continue.
- Stop only for one of two reasons:
  1. every item on the list is checked, or
  2. you write `BLOCKED step <n>: <reason>` after two failed VERIFY attempts.
- Never end a reply with a question while unchecked work remains. Choose the most
  reasonable option, state the choice in one line, and keep working.
- Never end a reply by describing what you are "about to do" or "will do next".
  Do it in the same reply instead.
- Never end a reply with a progress summary while items remain unchecked. A
  summary is the last thing you write, not a checkpoint.
- If a step turns out to be already done, mark it `[x] (already present)` and
  move to the next one in the same reply.

## Context budget

Long sessions die when the context window fills. Protect it.

- Read at most 3 files per step.
- Never re-read a file you have already read in this session. Use what you read.
- When you need several files, request them together in one batch rather than one
  at a time. Fewer round trips means less context burned.
- Never paste a whole file back into your reply. Quote only the lines you change.
- Do not restate the todo list in every reply. Reference item numbers.
- No open-ended exploration. If you cannot find something after 3 searches, write
  `BLOCKED` and say what you looked for.

## Editing

- Use the editor tool only. No heredocs, no `cat >`, no shell redirection into
  files, no multi-line quoted strings.
- One single-line shell command per call.
- Single-quote globs: `--include='*.py'`

## Project invariants - do not violate

- `upsert_job` and `apply_missing_strikes` have FROZEN signatures. Do not change
  their parameters or return types.
- `record_scrape_outcome` is the only writer of company health state.
- Admin code never writes Company fields directly. Go through the service layer.
- Work sequentially. No sub-agent delegation, no parallel task batches.
