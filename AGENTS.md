# Bishop Agent Instructions

This repo is Bishop's config and control-plane repo. Start every Codex session here:

```bash
cd ~/bishop_hybrid
```

Matt is not a coder. Final answers should be beginner-friendly, exact, and clear about what changed and what did not change. Matt is also a bad speller, so normalize obvious typos and keep moving.

## Start Every Session

Run these commands before editing:

```bash
git status --short --branch
git log --oneline -5
pytest -q
```

If tests fail before you edit, tell Matt that the repo was already failing and show the failing test names.

## Hard Rules

- Do not commit or push until Matt explicitly approves.
- Do not touch `.env` or secret values.
- You may inspect `.env.example`.
- Keep sprints small.
- Do not change runtime behavior during documentation/control-plane sprints.
- Preserve existing mode behavior.
- Preserve existing lane behavior.
- Preserve existing provider behavior.
- Preserve existing task behavior.
- Preserve existing memory behavior.
- Preserve existing focus behavior.
- Preserve existing Slack routing behavior.
- Preserve exact focus commands, natural focus switching, active focus context, and focused Slack answer shape.
- Preserve the existing Claude/OpenAI/Chat provider brain setup.
- Preserve Codex as the builder/developer agent.
- Do not autosave random answers to memory.
- Do not create tasks unless Matt explicitly requests task behavior.
- Do not add automatic task creation.
- Do not rebuild provider behavior unless Matt approves a provider sprint.
- Do not change prompts, answer shape, deploy behavior, or Slack routing unless the sprint specifically asks for it.

## Approval Rules

Green changes can usually be done inside the sprint:

- Small docs updates.
- Small tests for existing behavior.
- Small wording fixes that do not change runtime behavior.
- Repo instructions, runbooks, and checklists.

Yellow changes require a clear note to Matt before continuing:

- Any code change outside docs.
- Any test rewrite that changes expected behavior.
- Any dependency change.
- Any provider, mode, lane, task, memory, focus, Slack, prompt, or deploy file touch.
- Any change that is bigger than the current sprint.

Red changes require Matt approval first:

- Commit.
- Push.
- Deploy.
- Edit `.env` or secrets.
- Remove files.
- Reset or rewrite git history.
- Change provider architecture.
- Change Slack route behavior.
- Change memory saving rules.
- Change task creation behavior.
- Change focus behavior.
- Change prompts or answer shape.

## Required Workflow

1. Inspect the relevant files first.
2. Make the smallest useful change.
3. Run targeted tests if code changed.
4. Run the full suite:

```bash
pytest -q
```

5. Review the diff:

```bash
git diff --stat
git diff
git status --short --branch
```

6. Do not commit.

## Required Final Summary

End every Codex sprint with:

- Files changed.
- What was created or updated.
- Tests run and result.
- `git diff --stat`.
- Behavior summary, including whether runtime behavior changed.
- Any uncertainty or follow-up needed.
- Confirmation that no commit was made.

Keep this summary clear enough that Matt can paste it into ChatGPT and understand the state of the repo.
