# Bishop Autonomous Build Protocol

Autonomous does not mean unlimited. For Bishop, autonomous means ChatGPT and Codex can work independently inside a clearly scoped sprint, then stop before risky actions.

## Roles

### ChatGPT

ChatGPT helps Matt plan the sprint.

ChatGPT should:

- Turn Matt's goal into a small sprint prompt.
- Explain risks in plain English.
- Suggest what Codex should inspect.
- Suggest tests to run.
- Review Codex summaries.
- Help Matt decide whether to approve commit, push, deploy, or a larger follow-up.

ChatGPT should not pretend the repo is unknown when Matt says an architecture already exists. For Bishop brains, treat Claude and Chat/OpenAI as existing architecture unless repo evidence clearly says otherwise.

### Codex

Codex does the repo work.

Codex should:

- Start in `~/bishop_hybrid`.
- Inspect before editing.
- Keep the change scoped.
- Preserve runtime behavior unless the sprint specifically asks for a behavior change.
- Run tests.
- Review `git diff`.
- Summarize files changed, tests, diff stat, behavior impact, and uncertainty.
- Stop before commit, push, deploy, secrets, destructive git commands, or large/risky changes.

### Matt

Matt is the owner and approver.

Matt approves:

- Commits.
- Pushes.
- Deploys.
- Provider changes.
- Slack behavior changes.
- Memory/task/focus behavior changes.
- Big architecture changes.
- Any sprint that feels risky, broad, or unclear.

Matt does not need to read code to approve next steps. Codex and ChatGPT should explain in plain English what changed and what the risk is.

## Permission Levels

### Green: Codex Can Usually Proceed

These are safe inside a scoped sprint:

- Create or update docs.
- Add runbooks.
- Add repo instructions.
- Fix typos in docs.
- Add small tests that preserve existing behavior.
- Improve comments only when they clarify existing behavior.

### Yellow: Codex Should Pause And Explain First

These may be okay, but need a clear note before continuing:

- Any code edit.
- Any dependency edit.
- Any test expectation change.
- Any file touching provider, mode, lane, task, memory, focus, Slack route, prompt, or deploy behavior.
- Any change larger than the sprint.
- Any uncertainty about whether the change affects runtime behavior.

### Red: Matt Approval Required First

Do not do these without Matt approval:

- Commit.
- Push.
- Deploy.
- Edit `.env` or secrets.
- Delete files.
- Reset or rewrite git history.
- Change provider architecture.
- Rebuild OpenAI/Chat or Claude setup.
- Add a new provider.
- Change Slack routing.
- Change prompt behavior or answer shape.
- Change mode, lane, task, memory, or focus behavior.
- Add automatic task creation.
- Add random answer autosave to memory.

## Stop-And-Ask Triggers

Codex must stop and ask Matt before continuing when:

- The requested work requires runtime behavior changes.
- Tests fail in a way unrelated to the docs change.
- The repo has unrelated dirty files that would be touched.
- The change would need secrets or `.env`.
- The change would need a commit, push, deploy, or destructive git command.
- The sprint grows beyond the original request.
- The provider setup appears inconsistent with Matt's stated architecture.
- The safe path is unclear.

## Required Codex Start

At the start of a Bishop sprint, Codex should run:

```bash
cd ~/bishop_hybrid
git status --short --branch
git log --oneline -5
pytest -q
```

If tests are already failing, Codex should report that before editing.

## Required Codex Final Summary

Codex should end with this format:

```text
Files changed:
- path/to/file

Created or updated:
- Plain-English summary.

Evidence found:
- Existing provider/brain/mode/lane/task/memory/focus evidence, if relevant.

Tests:
- pytest -q: pass/fail summary.

Diff stat:
- Paste git diff --stat output.

Behavior:
- Say whether runtime behavior changed.

Uncertainty:
- Say what remains unknown, or "None."

Commit:
- No commit was made.
```

## What Autonomous Means For Bishop

Autonomous means:

- Codex can inspect the repo without waiting for Matt to point at every file.
- Codex can make small scoped edits.
- Codex can run tests and review diffs.
- Codex can normalize Matt's typos.
- Codex can choose conservative wording and repo-consistent documentation.

Autonomous does not mean:

- Codex can commit or push.
- Codex can deploy.
- Codex can touch secrets.
- Codex can change Bishop's runtime behavior during a docs sprint.
- Codex can rebuild provider brains because it forgot they already exist.
- Codex can create tasks or save memories unless the sprint specifically asks for that behavior.
