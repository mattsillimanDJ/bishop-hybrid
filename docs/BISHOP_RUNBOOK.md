# Bishop Runbook

This is the beginner-friendly checklist for working on Bishop from the Mac mini.

## Current Bishop v1 Completed Capabilities

Bishop v1 currently has these working capabilities documented in the repo and covered by tests:

- Exact Slack focus commands:
  - `focus stemlab`
  - `switch focus to stemlab`
  - `set focus stemlab`
  - `current focus`
  - `show focus`
  - `clear focus`
- Natural Slack focus switching:
  - `let's work on StemLab for a bit`
  - `back to Bishop`
  - `switch us over to DJ stuff`
  - `let's talk website`
  - `clear the focus for now`
- Active focus context for:
  - StemLab
  - Bishop
  - DJ
  - Website
- Shorter focused Slack answer shape:
  - Starts with one direct recommendation.
  - Uses at most 2 or 3 short bullets.
  - Ends with one concrete next move.
  - Avoids nested bullets unless Matt asks for detail.
- Autonomous builder docs:
  - ChatGPT helps Matt plan small sprints.
  - Codex edits, tests, and summarizes.
  - Matt approves commits, pushes, and deploys.
- Build/project status command:
  - `build status`
  - `project status`
  - `bishop status`
  - `bishop build status`
  - `what is the build status`
  - `where are we with bishop`
  - `what did we just finish`
- Next sprint command:
  - `next sprint`
  - `what should we build next`
  - `what should we work on next`
  - `recommend next sprint`
  - `bishop next sprint`
- Existing system/provider status is preserved:
  - `status` still shows the normal Bishop system status.
  - `provider` and `show provider` still show provider status.
  - `model` still shows the active model.
- OpenAI and Claude provider checks are visible in Slack status/provider output.

## Bishop v1 Wrap Checklist

Use this checklist before treating Bishop v1 as wrapped:

- Repo is clean.
- Tests are passing.
- Slack focus works.
- Build status works.
- Next sprint works.
- System status works.
- No random memory autosave.
- No accidental task creation.
- Matt approves commits and pushes.
- No Slack shell, git, deploy, or file mutation commands.

## Daily Operating Flow

This is the normal beginner-friendly loop for using ChatGPT, Codex, Terminal, and Slack together:

1. Ask Bishop in Slack:

```text
@Bishop Hybrid build status
```

2. Ask Bishop in Slack:

```text
@Bishop Hybrid next sprint
```

3. Open Terminal.

4. SSH to the Bishop Mac mini:

```bash
ssh bishop@YOUR_MAC_MINI_ADDRESS
```

5. Go to the repo:

```bash
cd ~/bishop_hybrid
```

6. Activate the virtual environment:

```bash
source .venv/bin/activate
```

7. Check the repo state:

```bash
git status --short --branch
```

8. Run the tests:

```bash
pytest -q
```

9. Start Codex:

```bash
codex
```

10. Paste a small sprint prompt into Codex. Keep it narrow, and include:

```text
Do not commit. Do not push. Keep this small. Preserve Bishop runtime behavior.
```

11. When Codex finishes, paste the Codex summary back into ChatGPT.

12. Commit and push only after Matt approves.

13. Live-test the result in Slack.

## Stop Adding Features

When the Bishop v1 wrap checklist passes, stop polishing for a few days.

Use Bishop live in Slack. Collect rough edges as they appear in real use. Do not keep adding features or cleanup sprints unless a real issue appears.

## 1. SSH Into The Bishop Mac Mini

From your own computer, open Terminal and run the SSH command you normally use for the Bishop Mac mini.

It will look something like this:

```bash
ssh bishop@YOUR_MAC_MINI_ADDRESS
```

Use the real Mac mini address or saved SSH shortcut. Do not paste secrets into ChatGPT or Codex.

## 2. Go To The Repo

```bash
cd ~/bishop_hybrid
```

Confirm you are in the right place:

```bash
pwd
```

Expected result:

```text
/Users/bishop/bishop_hybrid
```

## 3. Activate The Virtual Environment

```bash
source .venv/bin/activate
```

After this, your terminal prompt may show `(.venv)`.

## 4. Check Git Status

```bash
git status --short --branch
```

Clean expected result:

```text
## main...origin/main
```

If you see file names under that line, there are local changes.

## 5. Check Recent History

```bash
git log --oneline -5
```

This shows the last 5 commits. Copy this into ChatGPT if you want help understanding the current repo state.

## 6. Run Tests

```bash
pytest -q
```

Passing tests end with something like:

```text
... passed in ...s
```

If tests fail, do not commit. Paste the failing test names back into ChatGPT or Codex.

## 7. Start Codex

From the repo folder:

```bash
codex
```

When Codex opens, paste the sprint prompt from ChatGPT. Tell Codex:

```text
Do not commit. Do not push. Keep this small. Preserve Bishop runtime behavior.
```

## 8. Inspect What Changed

After Codex finishes, run:

```bash
git status --short --branch
git diff --stat
git diff
```

What these mean:

- `git status --short --branch` shows which files changed.
- `git diff --stat` shows a short summary of changed files.
- `git diff` shows the actual text changes.

If the diff is too long or confusing, paste `git diff --stat` and the Codex final summary into ChatGPT.

## 9. Commit Only After Approval

Do not commit until Matt approves.

When approved, stage the specific files:

```bash
git add AGENTS.md docs/BISHOP_BRAINS.md docs/BISHOP_AUTONOMOUS_BUILD_PROTOCOL.md docs/BISHOP_RUNBOOK.md
```

Commit:

```bash
git commit -m "Add Bishop autonomous build docs"
```

## 10. Push

Only after the commit is approved:

```bash
git push
```

## 11. Verify Slack Behavior

For documentation-only changes, Slack runtime behavior should not change.

To smoke test Slack, mention Bishop in Slack with:

```text
@Bishop Hybrid status
@Bishop Hybrid provider
@Bishop Hybrid show mode
@Bishop Hybrid show lane
@Bishop Hybrid current focus
@Bishop Hybrid show pending
```

Expected result:

- Bishop replies in Slack.
- Provider/status commands still work.
- Mode still reports normally.
- Lane still reports normally.
- Focus still reports normally.
- Pending tasks still report normally.

Do not test memory writes or task creation unless you actually want to save a memory or create a task.

## 12. What To Paste Back Into ChatGPT

Paste this:

```text
Codex summary:
[paste Codex final summary]

Git status:
[paste git status --short --branch]

Diff stat:
[paste git diff --stat]

Tests:
[paste pytest -q result]

Question:
Should I approve commit and push?
```

ChatGPT can then help decide whether the change is safe to approve.

## Safety Reminders

- Do not edit `.env`.
- Do not paste secrets into ChatGPT or Codex.
- Do not commit failing tests unless Matt explicitly decides to.
- Do not push until the commit is approved.
- For Bishop docs sprints, runtime behavior should stay unchanged.
