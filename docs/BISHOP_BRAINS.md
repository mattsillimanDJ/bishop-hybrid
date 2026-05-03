# Bishop Brains

This document summarizes the current Bishop brain and provider setup from repo evidence. Treat this as existing architecture unless the repo clearly changes later.

## Short Version

Bishop already has OpenAI/Chat and Claude provider support wired into the app. Codex is the builder/developer agent used to inspect the repo, edit files, run tests, and summarize changes. Do not rebuild this setup unless Matt approves a provider or architecture sprint.

## What The Repo Shows

### Chat/OpenAI Brain

Evidence:

- `app/services/provider_service.py` imports `OpenAI`.
- `VALID_PROVIDERS` includes `openai`.
- `generate_text()` sends OpenAI requests through `client.chat.completions.create(...)`.
- `app/config.py` defines:
  - `LLM_PROVIDER`, default `openai`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`, default `gpt-5.4`
- Slack supports:
  - `provider openai`
  - `provider`
  - `show provider`
  - `model`
  - `status`

Known:

- OpenAI is a first-class Bishop provider.
- OpenAI can be the default provider.
- OpenAI provider config is checked before switching.

Unknown from safe repo inspection:

- Whether production OpenAI secrets are currently set. Do not inspect `.env` secret values.
- Which provider is active in production at this exact moment unless checked through Slack or approved ops.

### Claude Brain

Evidence:

- `app/services/provider_service.py` imports `Anthropic`.
- `VALID_PROVIDERS` includes `claude`.
- `generate_text()` sends Claude requests through `client.messages.create(...)`.
- `app/config.py` defines:
  - `ANTHROPIC_API_KEY`
  - `ANTHROPIC_MODEL`, default `claude-sonnet-4-6`
- Slack supports:
  - `provider claude`
  - `provider`
  - `show provider`
  - `model`
  - `status`

Known:

- Claude is a first-class Bishop provider.
- Claude can be selected by provider override.
- Claude provider config is checked before switching.

Unknown from safe repo inspection:

- Whether production Claude secrets are currently set. Do not inspect `.env` secret values.
- Which Claude model is actually used in production if environment variables override defaults.

### Provider State And Commands

Evidence:

- `app/services/provider_state_service.py` stores provider override in SQLite table `provider_state`.
- `get_effective_provider()` resolves provider in this order:
  - usable override
  - usable default provider
  - usable OpenAI fallback
  - usable Claude fallback
  - default provider as last resort
- `app/routes/slack.py` handles:
  - `provider`
  - `show provider`
  - `provider openai`
  - `provider claude`
  - `provider default`
  - `model`
  - `status`
- `build_provider_summary_text()` reports effective provider, active model, override, default provider, and resolution source.

Do not remove or simplify this without Matt approval.

## Mode Brains

Evidence:

- `app/services/mode_service.py` defines live modes:
  - `default`
  - `work`
  - `personal`
  - `website`
  - `cmo`
  - `stemlab`
  - `product`
- `app/services/chat_service.py` builds mode-specific system prompts.
- `app/data/mode_brains/cmo.md`, `stemlab.md`, and `product.md` add deeper brain context for those modes.
- Slack supports `mode <name>`, `show mode`, `modes`, `show modes`, and mode recommendations.

Do not change mode names, prompts, or answer shape during documentation sprints.

## Codex Builder Role

Codex is not one of Bishop's Slack answer providers. Codex is the builder/developer agent for the repo.

Codex should:

- Inspect the repo.
- Edit files inside the scoped sprint.
- Run tests.
- Review diffs.
- Explain changes in beginner-friendly language.
- Stop before commits, pushes, deploys, secrets, provider architecture changes, or large/risky changes.

## What Should Not Be Rebuilt Without Need

Do not rebuild:

- OpenAI provider setup.
- Claude provider setup.
- Provider override resolution.
- Slack provider commands.
- Mode brain files.
- Focus behavior.
- Lane-scoped memory.
- Lane-scoped tasks.
- Slack route command handling.

Matt has said Claude and Chat/OpenAI were already set up as Bishop brains weeks ago. Treat that as the working architecture unless repo evidence clearly proves otherwise.
