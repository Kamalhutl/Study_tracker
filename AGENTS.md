# Execution rules (opencode auto-loads this file)

These rules override anything in a prompt file that contradicts them.

## Output format

- NEVER emit `<antThinking>`, `<antThought>`, `<thinking>`, or any other XML-style
  reasoning tag in your response. Reason silently. If you catch yourself opening
  such a tag, stop and rewrite the message without it.
- No "Let me..." narration. No announcing what you are about to read.
- Before each tool call, one line only: `STEP <n> | <action>`.

## Sequencing (hard)

- ONE tool call per response. Never batch. Never say "in parallel".
- Never spawn sub-agents or task batches.
- Max 3 read/grep calls per step. If you still lack context after 3, write the
  code with what you have and let the tests tell you what is wrong.
- There is no exploration phase. Every file you need is listed in the prompt's
  FILE MANIFEST. Do not go looking for others.

## Step discipline

- Do exactly one numbered step per response, then immediately run that step's
  VERIFY command before moving on.
- Update the todo list after every single step. Mark it `[x]` only after VERIFY
  passes.
- If a step's target already exists in the codebase, mark it `[x] (already
  present)` and move to the next step. Do not rewrite working code.
- If VERIFY fails twice on the same step, stop and print:
  `BLOCKED step <n>: <one line reason>` then continue to the next independent step.

## Editing

- Editor tool only. No heredocs, no `cat >`, no shell redirection, no multi-line
  quoted strings. One single-line shell command per call.
- Single-quote all globs: `--include='*.py'`. An unmatched glob is fatal in zsh.
- `upsert_job` and `apply_missing_strikes` have FROZEN signatures. Do not touch.
- `record_scrape_outcome` is the only writer of company health state.
- Admins never write Company fields directly. Every mutation goes through
  `apps/companies/services.py`.

## Definition of done

A step is done when its VERIFY command exits 0. Not when you believe the code is
correct.
