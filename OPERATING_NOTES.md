# Bishop Operating Notes

## Lanes (Slack)

- Each Slack channel maps to a lane
- Tasks are lane-scoped
- Memory is lane-scoped by default (private)
- Shared memory can appear across lanes
- Use "show lane" or "what lane am i in" to inspect

## Repo and environment

Source of truth repo:
~/bishop_hybrid

Activate the virtual environment:
cd ~/bishop_hybrid
source .venv/bin/activate

## Current status

Bishop is ready for daily internal Slack use.

As of April 10, 2026, the following has been verified:

- Slack task lifecycle works end to end
- Pending task capture works
- Reminder-style task capture works
- Task dedupe works
- Task completion works
- Task removal works
- Completed task viewing works
- Show all tasks works
- Clear completed tasks works
- Provider and status commands work
- Full automated test suite passes
- Live Slack regression test passed
- Git remote now uses SSH and no longer depends on HTTPS keychain auth

## Important repo state

Current repo:
~/bishop_hybrid

Main branch is the working branch currently in use.

Remote is configured for SSH.

Check remote:
git remote -v

Expected format:
origin  git@github.com:mattsillimanDJ/bishop-hybrid.git (fetch)
origin  git@github.com:mattsillimanDJ/bishop-hybrid.git (push)

## Start working checklist

Whenever starting a new Bishop work session:
cd ~/bishop_hybrid
source .venv/bin/activate
git status
pytest -q

Expected result:
- working tree clean
- tests passing

## Basic development workflow

1. Go to repo
2. Activate venv
3. Open one file at a time with nano
4. Use full-file replacement
5. Save and exit
6. Run targeted tests if appropriate
7. Run full test suite
8. Commit
9. Push

## Editing workflow

Preferred workflow:
- full-file replacement only
- no patch snippets
- use nano
- one file at a time
- test after each meaningful change

Open a file:
nano /full/path/to/file

Save:
Control + O
press Return

Exit:
Control + X

## Core commands

Run all tests:
pytest -q

Run Slack route tests only:
pytest -q tests/test_slack_route.py

Run service tests only:
pytest -q tests/test_services.py

## Git workflow

Check status:
git status

Stage files:
git add path/to/file

Commit:
git commit -m "Your commit message"

Push:
git push

Because the repo now uses SSH, pushes should no longer throw the old macOS keychain credential errors.

## Slack commands currently supported

Help and status:
- help
- provider
- show provider
- model
- status
- show mode
- mode default
- mode work
- mode personal
- provider openai
- provider claude
- provider default

Memory:
- remember ...
- recall ...
- forget ...
- show memory

Conversation history:
- show recent conversations
- show last 5 conversations

Tasks:
- show tasks
- show pending
- show pending tasks
- show done
- show done tasks
- show completed
- show completed tasks
- show all
- show all tasks
- clear tasks
- clear pending
- clear pending tasks
- clear done
- clear done tasks
- clear completed
- clear completed tasks
- add task ...
- save task ...
- remind me ...
- done ...
- complete task ...
- complete ...
- mark done ...
- mark task done ...
- remove task ...
- delete task ...
- drop task ...
- remove done task ...
- remove completed task ...
- delete done task ...
- delete completed task ...
- drop done task ...
- drop completed task ...

## Live Slack smoke test

Use this when you want to verify Bishop quickly in production Slack:

@Bishop Hybrid help
@Bishop Hybrid show pending
@Bishop Hybrid add task send the invoice
@Bishop Hybrid show pending
@Bishop Hybrid done send the invoice
@Bishop Hybrid show pending
@Bishop Hybrid add task review the deck
@Bishop Hybrid remove task review the deck
@Bishop Hybrid show pending
@Bishop Hybrid add task call the vendor
@Bishop Hybrid done call the vendor
@Bishop Hybrid show completed
@Bishop Hybrid show done
@Bishop Hybrid show all
@Bishop Hybrid remove completed task call the vendor
@Bishop Hybrid show completed
@Bishop Hybrid clear completed
@Bishop Hybrid provider
@Bishop Hybrid status

## Latest verified outcomes

The following are verified:
- help shows the updated command list
- show pending works when empty
- adding a task works
- marking a task done works
- removing a pending task works
- showing completed tasks works
- showing done tasks works
- showing all tasks works
- removing a completed task works
- clearing completed tasks works
- provider and status work correctly

## Recent project milestones

Recent completed work includes:
- explicit task capture
- reminder-style task detection
- pending task display
- task dedupe
- done and remove task flows
- completed task support
- clear completed support
- show all task support
- completed task removal support
- Slack route coverage for task lifecycle behavior
- service-level coverage for task lifecycle behavior
- SSH Git remote setup on the Mac mini

## Recommended workflow before any new feature work

Before building anything new:
1. run git status
2. run pytest -q
3. read app/routes/slack.py
4. read the relevant existing tests first
5. edit one file at a time
6. run targeted tests
7. run full tests
8. commit and push

## Likely next improvements

These are optional polish items, not blockers:
1. Improve formatting for show all so it reads more cleanly when one section is empty
2. Improve task list display formatting in Slack
3. Add a short internal release checklist
4. Add more tests around edge cases and text variants
5. Add more graceful wording for task-not-found responses if desired

## If something breaks

Start here:
cd ~/bishop_hybrid
source .venv/bin/activate
git status
pytest -q

Then inspect:
- app/routes/slack.py
- app/services/task_service.py
- tests/test_slack_route.py
- tests/test_services.py

## Key reminder

This repo should be worked in using:
- nano
- full-file replacement
- exact terminal steps
- one file at a time

Avoid partial patch workflows.
