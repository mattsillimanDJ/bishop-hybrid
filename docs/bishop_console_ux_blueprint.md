# Bishop Console UX Blueprint

## Product Vision

Bishop Console should become Matt's private, richer workspace for serious work with Bishop. Slack should remain the quick-command surface. The Console should become the place where Matt can see what Bishop knows, what Bishop did, what sources support an answer, what tasks exist, what project is active, and what artifacts were produced.

The goal is not to replace Slack. The goal is to give Bishop a Claude-like workbench that is more transparent, project-aware, and useful for larger work sessions across:

- Bishop
- StemLab
- RTG / Work
- DJ
- Events
- Website
- Personal

The Console should feel private, calm, practical, and trustworthy. It should not feel like a public SaaS product, a marketing page, or a generic chatbot skin.

## Current Repo Baseline

The current app is a FastAPI service with Slack as the main interface.

Existing app entry points:

- `app/main.py` starts the FastAPI app.
- Existing routers are health, Slack events, memory, and conversations.
- Startup initializes memory, conversation logs, focus, modes, provider state, tasks, and working session context.

Existing reusable services:

- `memory_service.py`: SQLite-backed memories with `user_id`, `owner_user_id`, `category`, `content`, `lane`, `visibility`, and `created_at`.
- `task_service.py`: SQLite-backed tasks with lane, status, source message, assistant commitment, timestamps, and dedupe.
- `conversation_log_service.py`: saved user and assistant turns with platform, channel, session, mode, provider, model, metadata, and memory-used flag.
- `focus_service.py`: active focus by user and lane.
- `mode_service.py`: current mode by user.
- `lane_service.py`: maps Slack channels to lanes and default memory visibility.
- `provider_service.py` and `provider_state_service.py`: OpenAI/Claude provider support, provider override, default fallback, model reporting, and config checks.
- `research_service.py`: public-search research abstraction for Tavily, Brave, or Serper, including source parsing, source quality labels, access limits, and suggested next queries.
- `artifact_service.py`: DOCX and XLSX artifact creation for Slack upload.
- `session_context_service.py`: short working-session context scoped by user, lane, and focus.

Existing public-ish HTTP routes:

- `GET /`
- `GET /health`
- `POST /slack/events`
- `GET /memory`
- `POST /memory/add`
- `GET /conversations`

Existing Slack capabilities:

- Normal Bishop replies through configured OpenAI or Claude provider.
- Mode commands.
- Provider commands.
- Focus commands and natural focus switching.
- Lane-aware memory recall, save, and forget.
- Lane-aware task listing, save, complete, remove, and clear.
- Build status and next sprint commands.
- Research planning and live public-search research when configured.
- StemLab-specific product/research/memory commands.
- DOCX and XLSX export requests.
- Conversation logging and short working-session context.

Audit notes from this sprint:

- `app/main.py` initializes the current SQLite-backed state tables on startup and mounts only health, Slack, memory, and conversation routers.
- `app/routes/slack.py` is the main product surface today. It owns Slack event filtering, command parsing, focus/mode/provider/status commands, memory/task commands, StemLab command helpers, research command formatting, artifact export upload, conversation logging, and the normal Bishop reply path.
- `app/routes/memory.py` exposes a very small memory API today: list recent memory and add memory.
- `app/routes/conversations.py` exposes recent conversations only.
- There are no HTTP routes yet for tasks, focus, mode, provider state, research runs, artifacts, activity traces, project pages, or Console auth.
- Research results are produced on demand and returned to Slack, but research runs are not persisted as first-class records.
- Artifacts are created as files in a local artifact directory and uploaded to Slack, but artifact metadata is not persisted as a library.
- Current traceability is partial: conversation rows record provider, model, mode, metadata, and whether memory was used; tasks carry source message and assistant commitment; memory rows carry lane and visibility; research sources carry quality annotations. There is not yet one structured per-answer trace joining all of those together.

Useful existing tables and state:

| Area | Existing storage | Console readiness |
| --- | --- | --- |
| Memory | `memory_entries` | Good for read-only list/filter; source attribution needs later schema work. |
| Tasks | `tasks` | Good for read-only task center; priority/due date/project links need later schema work. |
| Conversations | `conversation_logs` | Good for history; per-answer traces need later schema work. |
| Focus | `active_focuses` | Good for current state display and project context hints. |
| Mode | `user_modes` | Good for current state display. |
| Provider | `provider_state` plus environment config | Good for status display without secrets. |
| Working context | `working_session_contexts` | Good for showing recent ephemeral context; must be labeled as non-durable memory. |
| Research | service result dict only | Good for config/status; needs persistence for history/detail pages. |
| Artifacts | generated files only | Good for export action today; needs metadata table for library/preview. |

Design principle from the audit: Phase 1 should read from existing state and add Console-specific read APIs without changing Slack route behavior, provider choice, prompt assembly, memory capture, task capture, or deployment.

## Why Slack Alone Is Not Enough

Slack is good for quick commands, but it is not a rich workbench.

Main gaps:

- Slack threads are poor for long-running project work.
- Sources are hard to inspect after the answer scrolls away.
- Memories are hidden unless Matt asks with exact commands.
- Tasks exist, but there is no dashboard for pending, done, lane, source, or commitment.
- Artifacts are created and uploaded, but there is no artifact library or preview panel.
- Research output is text-first, not source-first.
- Tool activity is not visible enough for trust.
- Project context is implied through lane, focus, mode, and memory, but Matt cannot easily see or adjust it.
- Slack does not provide a Claude/ChatGPT-style split view with chat, artifact, source, and activity panels.

Slack should stay fast. Bishop Console should make Bishop understandable.

## Slack vs Bishop Console Responsibilities

### Slack Should Keep Doing

- Quick questions and lightweight replies.
- Fast status checks.
- Focus switching.
- Mode switching.
- Provider checks.
- Quick memory saves and recalls.
- Quick task capture and completion.
- Simple research commands.
- Simple artifact export requests.
- Notifications and reminders when Bishop eventually has scheduled or async work.

### Bishop Console Should Take Over

- Serious work sessions.
- Project dashboards.
- Source inspection.
- Memory inspection and editing.
- Task triage.
- Research review.
- Artifact preview and library.
- Conversation history browsing.
- Transparent tool/activity logs.
- Admin/status visibility.
- Safer review flows before editing memory, tasks, or important project state.

## Left Navigation and Project Model

The left navigation should make project context explicit.

Primary nav:

- Home
- Bishop
- StemLab
- RTG / Work
- DJ
- Events
- Website
- Personal
- Tasks
- Memory
- Research
- Artifacts
- Activity
- Settings

Recommended internal model:

- `project`: user-facing workspace such as Bishop, StemLab, RTG / Work, DJ, Events, Website, Personal.
- `lane`: existing backend routing/storage concept, currently `matt`, `work`, `dj`, `creative`, `family`, etc.
- `focus`: current active subject inside a lane, currently `stemlab`, `work`, `dj`, `personal`, `bishop`, `website`, `events`.
- `mode`: thinking style, currently `default`, `work`, `personal`, `website`, `cmo`, `creative`, `stemlab`, `product`, `events`.

The Console should not erase the existing lane/focus/mode concepts. It should explain them visually.

Example project mapping:

| Console project | Likely lane | Likely focus | Useful modes |
| --- | --- | --- | --- |
| Bishop | matt | bishop | default, product |
| StemLab | matt or creative | stemlab | stemlab, product |
| RTG / Work | work | work | work, cmo, creative |
| DJ | dj | dj | creative, default |
| Events | work or matt | events | events, work |
| Website | matt or creative | website | website, product |
| Personal | matt | personal | personal, default |

## Core User Flows

### Start A Serious Work Session

1. Matt opens Bishop Console.
2. He selects a project, for example StemLab.
3. The main chat starts with visible current project, lane, focus, mode, provider, and recent context.
4. Bishop answers in the center.
5. Sources, memories used, tasks created, and tool activity appear in the right panel.

### Inspect Why Bishop Answered A Certain Way

1. Matt clicks an answer.
2. The right panel shows provider, model, mode, focus, lane, memories used, recent context used, tasks referenced, sources used, and tool calls.
3. Matt can confirm whether the answer came from memory, current chat, research sources, or model judgment.

### Review And Clean Memory

1. Matt opens Memory.
2. He filters by project, lane, category, visibility, and date.
3. He can inspect memory content and where it came from.
4. Later build phases can allow edit, hide, delete, merge, or convert to project note.

### Turn Research Into A Decision

1. Matt opens Research.
2. He starts a research run or opens a previous one.
3. Sources are listed with source type, quality score, snippet, and link.
4. Bishop summarizes findings, confidence, weak signals, and product implications.
5. Matt can save a source-backed memory only after review.

### Manage Tasks

1. Matt opens Task Center.
2. He sees pending and done tasks by project, lane, source, and age.
3. Each task shows the original source message and Bishop's assistant commitment.
4. Matt can mark done, remove, or later assign priority/date.

### Create And Reuse Artifacts

1. Matt asks Bishop to draft or export something.
2. The artifact appears in a right panel or artifact tab.
3. The artifact is saved into an artifact library.
4. Later, artifacts can be edited, versioned, downloaded, or attached to Slack.

## MVP Screen Map

Phase 1 MVP should be read-only first.

MVP screens:

- Home dashboard
- Project page
- Conversation history
- Memory inspector
- Task center
- Research status/history placeholder
- Artifact library placeholder
- Activity log
- Settings/status page

MVP should answer:

- What is Bishop's current state?
- What projects exist?
- What memories are saved?
- What tasks are pending?
- What has Bishop recently said?
- What provider/model/mode/focus/lane are active?
- What research capability is configured?

MVP interaction rules:

- Every screen must clearly label whether data is read-only.
- Filters can change what is shown, but should not mutate Bishop state.
- Empty states should say what exists today rather than promising background work.
- Status screens should show configured/not configured without exposing secrets.
- Project pages should tolerate incomplete project mapping because the current backend has lanes and focuses, not a dedicated project table.
- The Console should prefer "view source" and "inspect" language over "fix" or "optimize" language until write actions exist.

## Future Screen Map

Future screens:

- Full chat workspace
- Project-specific chat threads
- Artifact editor and preview
- Source review table
- Research run detail pages
- Memory edit/review queue
- Task detail drawer
- Workflow automation center
- Notifications and approvals
- Slack message bridge view
- Admin audit log
- User/access management
- Provider/model routing controls

Future interaction rules:

- Write actions should show a preview of what will change.
- Memory writes should show visibility, lane, and source before saving.
- Task writes should show source message and whether a duplicate may already exist.
- Research-to-memory flows should require source selection and Matt approval.
- Provider/model controls should be admin-only and should not silently alter Slack behavior.
- Slack handoff should be explicit: Console may draft or send to Slack only when Matt chooses that action.

## Main Workspace Wireframe

```text
+--------------------------------------------------------------------------------+
| Bishop Console                  Project: StemLab          Mode: product         |
+----------------------+------------------------------------+--------------------+
| Home                 | StemLab                             | Transparency       |
| Bishop               | Lane: matt                          |                    |
| StemLab              | Focus: stemlab                      | Sources            |
| RTG / Work           | Provider: claude / model            | - Source 1         |
| DJ                   |                                    | - Source 2         |
| Events               | User: What should we test next?     |                    |
| Website              |                                    | Memories Used      |
| Personal             | Bishop:                            | - Memory A         |
|                      | Start with a manual Ableton-ready   | - Memory B         |
| Tasks                | stem-pack test for 3 producers...   |                    |
| Memory               |                                    | Tasks              |
| Research             | [composer input area]               | - Created none     |
| Artifacts            |                                    |                    |
| Activity             |                                    | Tool Activity      |
| Settings             |                                    | - searched memory  |
+----------------------+------------------------------------+--------------------+
```

## Home Dashboard Wireframe

```text
+--------------------------------------------------------------------------------+
| Bishop Console                                                                  |
+--------------------------------------------------------------------------------+
| Current State                                                                   |
| Provider: openai/claude     Mode: default     Active focus: none or project     |
| Pending tasks: 8           Memories: 42       Recent conversations: 20          |
+--------------------------------------------------------------------------------+
| Projects                                                                        |
| Bishop      StemLab      RTG / Work      DJ      Events      Website      Personal|
+--------------------------------------------------------------------------------+
| Needs Attention                                                                 |
| - Pending tasks by age                                                          |
| - Recent commitments Bishop made                                                |
| - Research runs needing review                                                  |
+--------------------------------------------------------------------------------+
| Recent Activity                                                                 |
| - Slack reply                                                                   |
| - Memory saved                                                                  |
| - Task marked done                                                              |
+--------------------------------------------------------------------------------+
```

## Project Page Wireframe

```text
+--------------------------------------------------------------------------------+
| Project: RTG / Work                                                             |
+--------------------------------------------------------------------------------+
| Context                                                                         |
| Lane: work       Focus: work       Recommended modes: work, cmo, creative       |
+--------------------------------------------------------------------------------+
| Recent Conversations              | Tasks                  | Memory             |
| - Last Slack/Console turn          | - Pending              | - Work prefs       |
| - Recent campaign prompt           | - Done                 | - Client context   |
+--------------------------------------------------------------------------------+
| Research & Sources                                                              |
| - Recent source-backed findings                                                 |
| - Open questions                                                                |
+--------------------------------------------------------------------------------+
| Artifacts                                                                       |
| - Drafts, docs, sheets, exports                                                 |
+--------------------------------------------------------------------------------+
```

## Memory Inspector Wireframe

```text
+--------------------------------------------------------------------------------+
| Memory                                                                          |
+--------------------------------------------------------------------------------+
| Filters: Project [StemLab] Lane [matt] Category [All] Visibility [All] Search []|
+--------------------------------------------------------------------------------+
| ID   Category                  Visibility   Lane     Created      Content       |
| 42   StemLab Decision           private      matt     2026-...    StemLab...    |
| 41   preference                 private      matt     2026-...    Matt prefers...|
+--------------------------------------------------------------------------------+
| Detail Drawer                                                                   |
| Content                                                                         |
| Source conversation or command                                                  |
| Visibility explanation                                                          |
| Actions for later phases: edit, delete, merge, convert                          |
+--------------------------------------------------------------------------------+
```

## Task Center Wireframe

```text
+--------------------------------------------------------------------------------+
| Task Center                                                                     |
+--------------------------------------------------------------------------------+
| Tabs: Pending | Done | All       Filters: Project, Lane, Source, Search         |
+--------------------------------------------------------------------------------+
| Task                                  Lane    Status    Created     Source      |
| Prepare StemLab interview list         matt    pending   2026-...    Slack       |
| Review July 4 campaign spine           work    done      2026-...    Slack       |
+--------------------------------------------------------------------------------+
| Task Detail                                                                     |
| Task text                                                                       |
| Original source message                                                         |
| Bishop commitment                                                               |
| Conversation link                                                               |
| Actions for later phases: mark done, remove, priority, due date                 |
+--------------------------------------------------------------------------------+
```

## Research Center Wireframe

```text
+--------------------------------------------------------------------------------+
| Research Center                                                                 |
+--------------------------------------------------------------------------------+
| Status: provider configured/not configured     Access limits visible            |
+--------------------------------------------------------------------------------+
| Research Runs                                                                   |
| Query                         Project     Provider     Confidence     Date      |
| StemLab Ableton workflow       StemLab     brave        medium         ...       |
+--------------------------------------------------------------------------------+
| Source Review                                                                   |
| Source title             Type                  Quality score       Weak signal  |
| ableton.com/...          official docs/help    85                  no           |
| reddit.com/...           community discussion  40                  yes          |
+--------------------------------------------------------------------------------+
| Findings                                                                         |
| - Finding tied to sources                                                        |
| - Product implication                                                            |
| - Open question                                                                  |
| Save memory later only after Matt approves                                       |
+--------------------------------------------------------------------------------+
```

## Settings, Admin, And Status Wireframe

```text
+--------------------------------------------------------------------------------+
| Settings / Status                                                               |
+--------------------------------------------------------------------------------+
| App                                                                             |
| Environment: development/production                                             |
| Database path/status                                                            |
+--------------------------------------------------------------------------------+
| Providers                                                                       |
| Effective provider                                                              |
| Default provider                                                                |
| Override                                                                        |
| OpenAI config check                                                             |
| Claude config check                                                             |
+--------------------------------------------------------------------------------+
| Research                                                                         |
| Provider                                                                        |
| Config check                                                                    |
| Access limits                                                                   |
+--------------------------------------------------------------------------------+
| Slack                                                                            |
| Signing configured?                                                             |
| Bot token configured?                                                           |
| Auto-listen channels                                                            |
+--------------------------------------------------------------------------------+
```

## Main Chat And Work Area

The center of the Console should be a real work surface, not only a Slack transcript.

It should include:

- Project title and current context strip.
- Chat history.
- Composer.
- Thread or session title.
- Current mode selector.
- Project/focus selector.
- Optional "send to Slack" action later.
- Clear distinction between user text, Bishop answer, generated artifact, and system/tool event.

Important behavior rule:

- Do not change Bishop's answer style or prompt behavior during the first Console build. The Console should call existing services first, then add richer display around the result.

## Right-Side Artifact, Source, And Transparency Panel

The right panel is the main difference between Slack and Console.

Panel tabs:

- Sources
- Memories
- Tasks
- Artifacts
- Activity
- Context

For each Bishop answer, the panel should show:

- Provider and model.
- Mode.
- Lane.
- Focus.
- Memories found or used.
- Tasks referenced or created.
- Research sources and quality labels.
- Artifact files created.
- Tool/service steps.
- Any access limits or safety guardrails.

The right panel should make trust inspectable without making the main answer noisy.

## Memory Transparency Model

Memory should be visible and reviewable.

Each memory item should show:

- Content.
- Category.
- Lane.
- Visibility.
- Owner.
- Created date.
- Whether it is working memory or background profile.
- Source command or conversation when available.
- Whether it was manually saved, explicitly saved, or auto-captured by a narrow approved rule.

Rules:

- No random autosave.
- No hidden memory edits.
- Memory saves should remain explicit unless a future sprint approves a narrow capture rule.
- Memory deletion and editing should require a clear action.

## Task Transparency Model

Tasks should show why they exist.

Each task should show:

- Task text.
- Status.
- Lane.
- Source message.
- Assistant commitment.
- Created and updated dates.
- Channel/session if available.
- Whether it was deduped.

Rules:

- Do not create tasks unless Matt explicitly asks or existing approved task behavior captures the command.
- Do not add automatic task creation from normal conversation in the Console MVP.
- Make pending vs done clear.

## Source Transparency Model

Sources should be treated as evidence, not decoration.

For research and source-backed answers, show:

- Title.
- URL.
- Host.
- Snippet.
- Source type.
- Source quality label.
- Source quality reason.
- Source quality score.
- Weak signals.
- Which finding the source supports.

Access limits should always be visible:

- Public web/search results only.
- No login-only content accessed.
- No paywall bypass.
- No protected previews accessed.
- Snippets are snippets, not full article reads.
- No automatic memory save.

## Tool And Activity Transparency Model

The Console should show what Bishop did in plain English.

Examples:

- Searched memory.
- Loaded pending tasks.
- Checked current mode.
- Checked active focus.
- Ran web research.
- Created DOCX artifact.
- Logged conversation.

The MVP can start with coarse activity labels from existing service boundaries. Later phases can add structured tool events.

## Memory Inspector

The Memory Inspector should become the safest place to understand and clean Bishop's memory.

MVP:

- Read-only list.
- Filter by lane, visibility, category, and search text.
- Show created date.
- Explain visibility in plain English.

Later:

- Edit memory.
- Delete memory.
- Merge duplicates.
- Convert memory to project note.
- Show source conversation.
- Flag stale memory.
- Suggest cleanup, with Matt approval.

## Task Center

The Task Center should make Bishop's commitments visible.

MVP:

- Read-only pending/done/all views.
- Filter by lane/project.
- Show source message and assistant commitment.

Later:

- Mark done.
- Remove.
- Add task.
- Add priority.
- Add due date.
- Link to project page.
- Slack notification or reminder controls.

## Research Center

The Research Center should make research reviewable and source-backed.

MVP:

- Show research config status.
- Explain access limits.
- Show recent research-shaped outputs if stored later.
- Start with placeholder/history only if research runs are not persisted yet.

Later:

- Run research from Console.
- Save research runs.
- Compare sources.
- Attach findings to projects.
- Save source-backed memory after Matt approves.
- Track open questions.

## Project Pages

Each project page should answer:

- What is this project?
- What is the active focus?
- Which lane does it use?
- Which mode is recommended?
- What did Bishop recently discuss here?
- What tasks are pending?
- What memory exists?
- What artifacts exist?
- What research is active or needed?

Project pages should be the bridge between raw Bishop data and Matt's day-to-day work.

## Settings, Admin, And Status

Settings should be useful without exposing secrets.

Show:

- App environment.
- Provider status.
- Effective provider.
- Active model.
- Provider override.
- Research provider status.
- Slack configuration status as yes/no, not token values.
- Database status.
- Counts for conversations, memories, tasks, and artifacts.

Do not show:

- API keys.
- Slack token values.
- Signing secret values.
- Raw `.env` contents.

## Suggested Backend Endpoints Needed

Read-only Phase 1 endpoints:

- `GET /console/status`
- `GET /console/projects`
- `GET /console/projects/{project_id}`
- `GET /console/conversations`
- `GET /console/conversations/{conversation_id}`
- `GET /console/memory`
- `GET /console/tasks`
- `GET /console/research/status`
- `GET /console/artifacts`
- `GET /console/activity`

Phase 2 chat endpoints:

- `POST /console/chat`
- `GET /console/sessions`
- `GET /console/sessions/{session_id}`
- `POST /console/sessions`

Phase 3 editing endpoints:

- `PATCH /console/memory/{memory_id}`
- `DELETE /console/memory/{memory_id}`
- `POST /console/tasks`
- `PATCH /console/tasks/{task_id}`
- `DELETE /console/tasks/{task_id}`
- `POST /console/research/runs`
- `POST /console/artifacts`

Admin/status endpoints:

- `GET /console/provider/status`
- `GET /console/mode`
- `GET /console/focus`
- `GET /console/lane-map`
- `GET /console/database/status`

Suggested Phase 1 response shapes:

```text
GET /console/status
- app: name, environment, version/build label if available
- provider: effective provider, active model, default provider, override, config statuses
- slack: signing configured, bot token configured, auto-listen channel count
- research: configured, provider, access limits
- counts: memories, tasks pending/done, recent conversations, artifacts if indexed
- current_context: lane, focus by lane, mode
```

```text
GET /console/projects
- projects: id, name, lane, focus, recommended_modes, counts, last_activity_at
```

```text
GET /console/projects/{project_id}
- project metadata
- current lane/focus/mode/provider context
- recent conversations
- memory highlights
- pending tasks
- research status/recent runs if available
- artifacts if available
```

```text
GET /console/conversations
- filters: user_id, platform, project_id, lane, mode, provider, search, limit
- items: id, created_at, platform, channel_id, session_id, user_message,
  assistant_response, memory_used, mode, provider, model, metadata
```

```text
GET /console/memory
- filters: user_id, project_id, lane, category, visibility, search, limit
- items: id, content, category, lane, visibility, owner_user_id, created_at
```

```text
GET /console/tasks
- filters: user_id, project_id, lane, status, search, limit
- items: id, task_text, status, lane, source_message, assistant_commitment,
  channel_id, session_id, created_at, updated_at, dedupe indicators if available
```

Phase 2 `POST /console/chat` should return both answer and display metadata:

```text
- message: assistant text
- conversation_id
- provider/model/mode/lane/focus
- memory: retrieved/used summaries where safely available
- tasks: created/referenced summaries where safely available
- research: source summaries if a research path was used
- artifacts: generated artifact metadata if any
- activity: coarse steps suitable for the right panel
```

The first implementation can return coarse metadata and improve trace detail later. It should not pretend precision that the backend does not yet record.

## Current Existing Data And Services Bishop Can Reuse

The Console can reuse:

- SQLite memory table.
- SQLite tasks table.
- Conversation log table.
- Active focus table.
- User mode table.
- Provider state table.
- Working session context table.
- Existing provider resolution.
- Existing memory visibility rules.
- Existing lane mapping.
- Existing task status model.
- Existing research source quality model.
- Existing artifact generation functions.

This is enough for a read-only dashboard without changing Bishop runtime behavior.

Reuse guidance by feature:

| Console feature | Reuse first | Avoid in MVP |
| --- | --- | --- |
| Home dashboard | provider/mode/focus/task/memory/conversation services | New orchestration engine. |
| Project pages | lane/focus mapping plus filtered memory/tasks/conversations | New project database as a prerequisite. |
| Memory inspector | `get_memories`, `search_memories`, existing visibility rules | Editing/deleting until confirmation UI and audit trail exist. |
| Task center | `get_tasks` by lane/status | Due-date/priority model until schema sprint. |
| Conversation history | `get_recent_conversations` | Full transcript migration or Slack thread import. |
| Research center | `validate_research_config`, `RESEARCH_ACCESS_LIMITS`, source quality functions | Running and storing research until research-run persistence exists. |
| Artifact library | artifact service concepts and configured output directory | Assuming files on disk are a durable library without metadata. |
| Settings/status | provider resolution and config validators | Showing secret values or enabling risky writes. |

## New API Gaps To Fill Later

Gaps:

- No first-class project table.
- No Console auth/session model.
- No artifact metadata table.
- No persisted research run table.
- No structured tool/activity event table.
- No per-answer structured trace showing exact memories/sources/tasks used.
- No memory source-conversation foreign key.
- No task priority or due date.
- No project notes.
- No user-facing API for focus/mode/provider changes outside Slack.
- No frontend app shell.

These gaps should be filled in small build sprints after the blueprint is approved.

## Auth And Security Assumptions

Assumptions:

- Bishop Console is private, not public.
- It should require authentication before showing any memory, task, source, or conversation data.
- Secrets must never be shown in the UI.
- Admin controls should be separate from normal project work.
- Write actions should be phased in after read-only visibility is working.
- Any external exposure should use HTTPS.
- If deployed beyond localhost/private network, use a real auth provider or a tightly controlled reverse-proxy auth layer.

MVP security stance:

- Prefer local/private access for the first build.
- Read-only first.
- No secret display.
- No deploy changes during the first Console sprint unless Matt separately approves a deploy sprint.

## Safety And Access-Limit Model

The Console should keep Bishop's current safety shape:

- No commits, pushes, deploys, or destructive actions without Matt approval.
- No `.env` or secret editing.
- No automatic memory saving beyond existing approved behavior.
- No automatic task creation beyond existing approved behavior.
- No provider architecture changes from the UI in early phases.
- No Slack route behavior changes from the Console MVP.
- Public web/search research only unless a later sprint explicitly approves more.

Write actions should be staged:

1. Read-only visibility.
2. Explicit user action.
3. Confirmation for risky edits.
4. Audit log.
5. Undo or recovery where practical.

## MVP Build Phases

### Phase 0: Blueprint

Create this document. No app build. No runtime behavior changes.

Done when:

- The desired Console shape is documented.
- Current reusable backend pieces are identified.
- API gaps are clear.
- Future build phases are scoped.

### Phase 1: Read-Only Dashboard

Build a private, read-only Console.

Scope:

- App shell.
- Left nav.
- Home dashboard.
- Project pages.
- Memory list.
- Task list.
- Conversation history.
- Provider/mode/focus/status page.
- Research status page.

Do not include:

- Chat sending.
- Memory editing.
- Task editing.
- Research execution.
- Artifact editing.
- Provider changes.

### Phase 2: Chat + Project Workspace

Add Console chat while preserving existing Bishop behavior.

Scope:

- Chat composer.
- Session history.
- Project context selector.
- Mode/focus display.
- Right-side transparency panel.
- Conversation logging.
- Basic artifact display when generated.

Important:

- Reuse existing chat/provider/memory/task services.
- Do not rewrite prompts or Slack behavior.

### Phase 3: Artifact, Research, And Memory Editing

Add careful write actions.

Scope:

- Artifact library and preview.
- Persisted research runs.
- Research detail pages.
- Source-backed memory save review.
- Memory edit/delete with confirmation.
- Task mark done/remove/add.

Important:

- All edits should be explicit.
- Memory edits should show source and impact.

### Phase 4: Richer Workflow Automation

Add higher-leverage workflow features after the transparent base works.

Scope:

- Approval queues.
- Scheduled reminders.
- Project briefs.
- Workflow templates.
- Slack-to-Console handoff.
- Research-to-decision workflows.
- Artifact versioning.
- Notifications.
- More granular tool traces.

## What Not To Build Yet

Do not build these in the first Console sprint:

- A full frontend app before the read-only API shape is clear.
- Public multi-user SaaS auth.
- Agent frameworks.
- MCP framework changes.
- Browser automation.
- New provider architecture.
- Provider prompt rewrites.
- Slack routing changes.
- Deployment changes.
- Automatic task creation from normal conversation.
- Broad automatic memory capture.
- Full artifact editor.
- Complex workflow automation.
- Mobile-first advanced UI.

## Risks And Tradeoffs

Main risks:

- Building a pretty UI before the data model is clear.
- Accidentally changing Slack behavior while adding Console behavior.
- Making memory editing too easy without transparency.
- Treating search snippets as verified article reads.
- Exposing private memory/task/conversation data without strong enough access control.
- Creating a second source of truth for project state.
- Letting project, lane, focus, and mode become confusing.

Tradeoffs:

- Read-only first is slower, but safer.
- Reusing current services limits early UI polish, but protects existing behavior.
- A project model improves usability, but it must map cleanly to current lanes/focuses.
- Rich transparency adds UI complexity, but it is the main reason to build the Console.

## Definition Of Done For Future Build Sprint

A future Phase 1 build sprint is done when:

- A private Console shell exists.
- Left nav includes the planned project and system sections.
- Home dashboard shows real read-only Bishop state.
- Project pages show real read-only memory, tasks, recent conversations, and context.
- Memory Inspector reads from existing memory data without changing memory behavior.
- Task Center reads from existing task data without changing task behavior.
- Settings/status shows provider, model, mode, focus, research, and Slack config status without exposing secrets.
- No Slack behavior changed.
- No provider behavior changed.
- No memory/task/focus/mode behavior changed.
- Tests cover new read-only endpoints.
- Full test suite passes.
- Matt can run it locally and understand what Bishop knows and what Bishop has been doing.

## Matt-Friendly Operating Model

Use Slack when the job is quick.

Good Slack uses:

- "What should I focus on?"
- "Show tasks."
- "Remember this..."
- "Focus StemLab."
- "Mode creative."
- "Research status."
- "Give me three quick campaign ideas."

Use Bishop Console when the job needs a workspace.

Good Console uses:

- Review all StemLab tasks and memory.
- Work through a serious project chat.
- Check what source supported a research finding.
- Inspect why Bishop answered a certain way.
- Clean up memory.
- Review artifacts.
- See recent Bishop activity.
- Understand current provider, mode, focus, and status without memorizing Slack commands.

Simple daily rhythm:

1. Use Slack for quick capture and quick answers during the day.
2. Open Bishop Console when work gets deeper or messy.
3. Use project pages to see the state of Bishop, StemLab, RTG / Work, DJ, Events, Website, and Personal.
4. Use the right panel to check sources, memory, tasks, artifacts, and tool activity.
5. Keep commits, pushes, deploys, provider changes, and risky behavior changes outside the Console until Matt explicitly approves those workflows.
