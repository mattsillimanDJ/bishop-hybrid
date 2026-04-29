import random
import re
import time
from typing import Optional

from fastapi import APIRouter, Request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from app.config import settings
from app.services.chat_service import generate_reply, response_contains_commitment
from app.services.conversation_log_service import (
    get_recent_conversations_for_user,
    log_conversation,
)
from app.services.lane_service import get_default_visibility_for_lane, get_lane_from_channel
from app.services.memory_service import (
    add_memory,
    delete_memory_by_exact_content,
    delete_memory_by_query,
    get_memories,
    infer_memory_category,
    search_memories,
)
from app.services.mode_service import VALID_MODES, get_mode, set_mode
from app.services.profile_service import (
    get_display_name_for_bishop_user_id,
    resolve_bishop_user_id,
)
from app.services.provider_service import get_provider_model, validate_provider_config
from app.services.provider_state_service import (
    clear_provider_override,
    get_effective_provider,
    get_provider_override,
    get_provider_resolution,
    set_provider_override,
)
from app.services.research_service import (
    is_live_research_available,
    run_web_research,
    validate_research_config,
)
from app.services.task_service import (
    add_task,
    build_task_text_from_user_message,
    clear_tasks,
    get_tasks,
    mark_task_done,
    remove_task,
    should_capture_task_from_user_message,
)

router = APIRouter()
slack_client = WebClient(token=settings.SLACK_BOT_TOKEN)

processed_event_ids = set()
recent_message_fingerprints: dict[str, float] = {}

MAX_PROCESSED_EVENT_IDS = 1000
MESSAGE_DEDUPE_WINDOW_SECONDS = 8
MESSAGE_DEDUPE_CACHE_LIMIT = 1000

SHORT_FOLLOWUP_MESSAGES = {
    "yes",
    "yes please",
    "yes please!",
    "yep",
    "yeah",
    "sure",
    "sure!",
    "go ahead",
    "please do",
    "do it",
    "more",
    "3 more",
    "three more",
    "ok",
    "okay",
}

MODE_QUERY_MESSAGES = {
    "show mode",
    "what mode are you in",
    "what mode",
    "current mode",
}

MODE_GUIDE_MESSAGES = {
    "modes",
    "show modes",
}

MODE_RECOMMENDATION_MESSAGES = {
    "what mode should i use",
    "which mode should i use",
    "recommend mode",
    "help me choose a mode",
}

STEMLAB_PROJECT_MESSAGES = {
    "stemlab",
    "stemlab plan",
    "stemlab next",
    "stemlab mvp",
    "stemlab founder",
    "stemlab product",
    "stemlab positioning",
    "stemlab customer",
    "stemlab validation",
    "stemlab assumptions",
    "stemlab research",
    "stemlab ableton research",
    "stemlab reddit research",
    "stemlab competitor research",
    "stemlab technical research",
    "stemlab what not to build",
    "stemlab research questions",
    "stemlab web research",
    "stemlab reddit search plan",
    "stemlab source backed finding",
}

RESEARCH_MESSAGES = {
    "research",
    "research status",
}

STEMLAB_MEMORY_LANE = "stemlab"

STEMLAB_MEMORY_CATEGORIES = {
    "StemLab Product Direction",
    "StemLab Decision",
    "StemLab Open Question",
    "StemLab Research Finding",
    "StemLab Risk",
    "StemLab Next Action",
}

STEMLAB_MEMORY_QUERY_MESSAGES = {
    "show stemlab memory": None,
    "stemlab memory": None,
    "stemlab decisions": "StemLab Decision",
    "stemlab open questions": "StemLab Open Question",
    "stemlab risks": "StemLab Risk",
}

STEMLAB_EXPLICIT_MEMORY_CATEGORIES = {
    "product direction": "StemLab Product Direction",
    "decision": "StemLab Decision",
    "open question": "StemLab Open Question",
    "research finding": "StemLab Research Finding",
    "risk": "StemLab Risk",
    "next action": "StemLab Next Action",
}

LANE_QUERY_MESSAGES = {
    "show lane",
    "what lane am i in",
    "what lane are we in",
    "current lane",
}

TASK_QUERY_MESSAGES = {
    "show tasks",
    "show pending",
    "show pending tasks",
}

DONE_TASK_QUERY_MESSAGES = {
    "show done",
    "show done tasks",
    "show completed",
    "show completed tasks",
}

ALL_TASK_QUERY_MESSAGES = {
    "show all",
    "show all tasks",
}

CLEAR_TASK_MESSAGES = {
    "clear tasks",
    "clear pending",
    "clear pending tasks",
}

CLEAR_DONE_TASK_MESSAGES = {
    "clear done",
    "clear done tasks",
    "clear completed",
    "clear completed tasks",
}

COMPLETE_TASK_PATTERNS = [
    r"^\s*done\s+",
    r"^\s*complete task\s+",
    r"^\s*complete\s+",
    r"^\s*completed\s+",
    r"^\s*mark done\s+",
    r"^\s*mark task done\s+",
    r"^\s*finished\s+",
    r"^\s*finish\s+",
    r"^\s*i finished\s+",
    r"^\s*i completed\s+",
    r"^\s*i did\s+",
    r"^\s*wrapped\s+",
    r"^\s*wrapped up\s+",
    r"^\s*that's done\s+",
    r"^\s*thats done\s+",
]

REMOVE_DONE_TASK_PATTERNS = [
    r"^\s*remove done task\s+",
    r"^\s*remove completed task\s+",
    r"^\s*delete done task\s+",
    r"^\s*delete completed task\s+",
    r"^\s*drop done task\s+",
    r"^\s*drop completed task\s+",
]

REMOVE_TASK_PATTERNS = [
    r"^\s*remove task\s+",
    r"^\s*delete task\s+",
    r"^\s*drop task\s+",
    r"^\s*forget task\s+",
    r"^\s*remove\s+",
    r"^\s*delete\s+",
    r"^\s*drop\s+",
]

REMEMBER_PATTERNS = [
    r"^\s*can you remember this(?:\s*[:,-]\s*|\s+)",
    r"^\s*please remember this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember that(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember(?:\s*[:,-]\s*|\s+)",
]

REMEMBER_SHARED_PATTERNS = [
    r"^\s*remember shared that(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember shared this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember shared(?:\s*[:,-]\s*|\s+)",
]

REMEMBER_PRIVATE_PATTERNS = [
    r"^\s*remember private that(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember private this(?:\s*[:,-]\s*|\s+)",
    r"^\s*remember private(?:\s*[:,-]\s*|\s+)",
]

RECALL_PATTERNS = [
    r"^\s*recall(?:\s*[:,-]\s*|\s+)",
    r"^\s*what do you remember about(?:\s*[:,-]\s*|\s+)",
    r"^\s*what do you remember of(?:\s*[:,-]\s*|\s+)",
    r"^\s*what do you know about(?:\s*[:,-]\s*|\s+)",
]

FORGET_MEMORY_PATTERNS = [
    r"^\s*please forget this(?:\s*[:,-]\s*|\s+)",
    r"^\s*forget this(?:\s*[:,-]\s*|\s+)",
    r"^\s*forget that(?:\s*[:,-]\s*|\s+)",
    r"^\s*forget(?:\s*[:,-]\s*|\s+)",
    r"^\s*stop remembering(?:\s*[:,-]\s*|\s+)",
]

EXACT_FORGET_MEMORY_PATTERNS = [
    r"^\s*forget exact memory(?:\s*[:,-]\s*|\s+)",
]


def post_message(channel: str, text: str):
    if not settings.SLACK_BOT_TOKEN:
        print("Missing SLACK_BOT_TOKEN")
        return {"ok": False, "error": "Missing SLACK_BOT_TOKEN"}

    try:
        response = slack_client.chat_postMessage(channel=channel, text=text)
        return {"ok": True, "ts": response.get("ts")}
    except SlackApiError as e:
        print(f"Slack API error: {e.response['error']}")
        return {"ok": False, "error": e.response["error"]}


def resolve_slack_channel_name(channel_id: str) -> Optional[str]:
    if not settings.SLACK_BOT_TOKEN:
        return None

    try:
        response = slack_client.conversations_info(channel=channel_id)
        channel = response.get("channel", {})
        return channel.get("name")
    except SlackApiError as e:
        print(f"Slack channel lookup error: {e.response['error']}")
        return None
    except Exception as e:
        print(f"Slack channel lookup unexpected error: {str(e)}")
        return None


def strip_app_mention(text: str) -> str:
    return re.sub(r"<@[^>]+>", "", text).strip()


def normalize_message_for_dedupe(text: str) -> str:
    normalized = (text or "").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[!?.。、，,;:]+$", "", normalized)
    return normalized.strip()


def prune_recent_message_fingerprints(now: float):
    expired_keys = [
        key
        for key, timestamp in recent_message_fingerprints.items()
        if now - timestamp > MESSAGE_DEDUPE_WINDOW_SECONDS
    ]
    for key in expired_keys:
        recent_message_fingerprints.pop(key, None)

    if len(recent_message_fingerprints) > MESSAGE_DEDUPE_CACHE_LIMIT:
        oldest_items = sorted(
            recent_message_fingerprints.items(),
            key=lambda item: item[1],
        )[: len(recent_message_fingerprints) - MESSAGE_DEDUPE_CACHE_LIMIT]
        for key, _ in oldest_items:
            recent_message_fingerprints.pop(key, None)


def is_duplicate_recent_message(user_id: str, channel_id: str, user_text: str) -> bool:
    normalized_text = normalize_message_for_dedupe(user_text)
    if not normalized_text:
        return False

    now = time.time()
    prune_recent_message_fingerprints(now)

    fingerprint = f"{user_id}:{channel_id}:{normalized_text}"
    last_seen = recent_message_fingerprints.get(fingerprint)

    if last_seen and now - last_seen <= MESSAGE_DEDUPE_WINDOW_SECONDS:
        print(f"Skipping near-duplicate Slack message: {fingerprint}")
        return True

    recent_message_fingerprints[fingerprint] = now
    return False


def should_send_working_message(user_text: str) -> bool:
    normalized = normalize_message_for_dedupe(user_text)
    if not normalized:
        return False

    if normalized in SHORT_FOLLOWUP_MESSAGES:
        return False

    if len(normalized) < 25:
        return False

    return True


def help_text() -> str:
    return (
        "Here are the commands I understand:\n\n"
        "Memory:\n"
        "* remember ...\n"
        "* remember that ...\n"
        "* remember this ...\n"
        "* can you remember this ...\n"
        "* remember shared ...\n"
        "* remember shared that ...\n"
        "* remember private ...\n"
        "* remember private that ...\n"
        "* recall ...\n"
        "* what do you remember\n"
        "* what do you remember about ...\n"
        "* forget ...\n"
        "* forget that ...\n"
        "* forget this ...\n"
        "* please forget this ...\n"
        "* stop remembering ...\n"
        "* forget exact memory ...\n"
        "* show memory\n"
        "* show all memory\n"
        "* show working memory\n"
        "* show background profile\n"
        "* what do you remember in full\n"
        "* show recent conversations\n"
        "* show last 5 conversations\n\n"
        "Tasks:\n"
        "* show tasks\n"
        "* show pending\n"
        "* show done\n"
        "* show completed\n"
        "* show all\n"
        "* show all tasks\n"
        "* clear tasks\n"
        "* clear done\n"
        "* clear completed\n"
        "* add task ...\n"
        "* save task ...\n"
        "* remind me ...\n"
        "* done ...\n"
        "* complete task ...\n"
        "* finished ...\n"
        "* i finished ...\n"
        "* that's done ...\n"
        "* delete ...\n"
        "* remove task ...\n"
        "* delete task ...\n"
        "* drop task ...\n"
        "* remove done task ...\n"
        "* remove completed task ...\n\n"
        "Modes:\n"
        "* mode default\n"
        "* mode work\n"
        "* mode personal\n"
        "* mode website\n"
        "* mode cmo\n"
        "* mode stemlab\n"
        "* mode product\n"
        "* show mode\n"
        "* modes\n"
        "* show modes\n"
        "* what mode should I use\n"
        "* recommend mode\n\n"
        "StemLab:\n"
        "* stemlab\n"
        "* stemlab plan\n"
        "* stemlab next\n"
        "* stemlab mvp\n\n"
        "* stemlab founder\n"
        "* stemlab product\n"
        "* stemlab positioning\n"
        "* stemlab customer\n"
        "* stemlab validation\n"
        "* stemlab assumptions\n\n"
        "* stemlab research\n"
        "* stemlab ableton research\n"
        "* stemlab reddit research\n"
        "* stemlab competitor research\n"
        "* stemlab technical research\n"
        "* stemlab what not to build\n"
        "* stemlab research questions\n\n"
        "Research:\n"
        "* research\n"
        "* research status\n"
        "* web research ...\n"
        "* stemlab web research\n"
        "* stemlab live web research ...\n"
        "* stemlab reddit search plan\n"
        "* stemlab source backed finding\n\n"
        "* show stemlab memory\n"
        "* stemlab memory\n"
        "* stemlab decisions\n"
        "* stemlab open questions\n"
        "* stemlab risks\n\n"
        "System:\n"
        "* show lane\n"
        "* what lane am i in\n"
        "* provider\n"
        "* show provider\n"
        "* provider openai\n"
        "* provider claude\n"
        "* provider default\n"
        "* model\n"
        "* status\n"
        "* help\n\n"
        "Or just mention me normally and I'll reply."
    )


def mode_guide_text() -> str:
    return (
        "Live modes:\n"
        "* default - General assistant mode for normal mixed requests.\n"
        "* work - Work-focused mode for professional priorities, decisions, and execution.\n"
        "* personal - Personal mode for life admin, private planning, and non-work context.\n"
        "* website - Website mode for site copy, structure, UX, and web launch work.\n"
        "* cmo - Marketing leadership mode for positioning, audience, channels, creative, and measurement.\n"
        "* stemlab - Music-tech and EDM stem workflow mode for product, production, and DJ-ready output.\n"
        "* product - Product strategy mode for MVP scope, users, workflows, monetization, and tradeoffs.\n\n"
        "Use `mode <name>` to switch modes. Use `show mode` to see the current mode."
    )


def mode_recommendation_text() -> str:
    return (
        "Choose a mode based on what you are trying to do:\n"
        "* default: use for normal mixed questions\n"
        "* work: use for client, production, vendor, and execution decisions\n"
        "* personal: use for family, relationship, life admin, and personal planning\n"
        "* website: use for site structure, copy, UX, SEO, and launch planning\n"
        "* cmo: use for marketing strategy, positioning, channels, creative, budget, and measurement\n"
        "* stemlab: use for EDM product, stems, Ableton, music workflow, and DJ/producer output\n"
        "* product: use for product ideas, MVP scope, workflows, monetization, and tradeoffs\n\n"
        "Tell me what you are working on and I can suggest the best mode."
    )


def stemlab_overview_text() -> str:
    return (
        "StemLab is Matt's AI product idea for DJs, EDM producers, remixers, and creators. "
        "It is not just Suno for EDM. The wedge is useful, producer-ready stems and workflows: "
        "drums, bass, vocals, hooks, synths, FX, MIDI when possible, dry/wet versions, loop points, "
        "arrangement sections, and drag-and-drop Ableton-ready material.\n\n"
        "I can help with product strategy, user workflows, MVP scope, competitive wedge, "
        "build-vs-buy decisions, technical unknowns, pricing, and next actions. "
        "If something needs research, I should call out what needs to be researched instead of pretending certainty."
    )


def stemlab_plan_text() -> str:
    return (
        "StemLab product plan:\n"
        "* User: DJs, EDM producers, remixers, and creators who need usable building blocks for real production workflows.\n"
        "* Problem: AI music tools can generate impressive full songs and ideas, but producers still need clean stems, loops, sections, and DAW-ready material they can actually use.\n"
        "* Wedge: Producer-ready stems and workflows, not just full-song generation. Focus on BPM, key, warping, clips, Session View, Arrangement View, clean audio, stems, loops, scenes, and exportable material.\n"
        "* MVP: Let a user describe a track idea or upload audio, create or separate useful stems, detect BPM and key, label stems clearly, suggest arrangement sections, and export an Ableton-ready stem pack.\n"
        "* What not to build yet: Do not start with a giant custom model, full DAW replacement, broad social platform, licensing marketplace, or every genre at once.\n"
        "* Next decisions: Pick the first user type, choose create-versus-separate for v0, define the export pack, list technical unknowns, and test whether producers would use the workflow."
    )


def stemlab_next_text() -> str:
    return (
        "Next 5 StemLab actions:\n"
        "1. Define the first user: DJ, EDM producer, remixer, or creator, and choose one primary workflow.\n"
        "2. Write the v0 promise in one sentence: what useful Ableton-ready output does StemLab create?\n"
        "3. Map the export pack: stems, loops, BPM, key, labels, arrangement sections, dry/wet versions, and MIDI where possible.\n"
        "4. Identify build-vs-buy options for generation, separation, BPM/key detection, labeling, and export packaging.\n"
        "5. Test the workflow with 3-5 producers using a mocked or manual stem pack before training anything large."
    )


def stemlab_mvp_text() -> str:
    return (
        "Smallest useful StemLab MVP workflow:\n"
        "1. User describes a track idea or uploads audio.\n"
        "2. StemLab creates or separates useful stems.\n"
        "3. It detects BPM and key.\n"
        "4. It labels stems clearly: drums, bass, vocals, hooks, synths, FX, and loops.\n"
        "5. It suggests arrangement sections for intro, build, drop, breakdown, and outro.\n"
        "6. It exports an Ableton-ready stem pack with clean audio, loop points, dry/wet versions where useful, and drag-and-drop organization.\n\n"
        "Validate workflow quality before trying to train a giant model."
    )


def stemlab_founder_text() -> str:
    return (
        "StemLab founder lens:\n"
        "* Wedge: producer-ready stems and Ableton workflows, not generic AI songs.\n"
        "* First market: EDM producers and remixers who already work from stems, loops, and reference tracks.\n"
        "* Unfair advantage: practical taste in dance music workflows plus fast manual validation before model work.\n"
        "* Fastest validation: deliver manual Ableton-ready stem packs to 3-5 producers and watch whether they use them.\n"
        "* Biggest risk: the output is impressive but not clean or controllable enough for real production.\n"
        "* Next founder move: pick one user segment and sell the workflow before building a broad platform."
    )


def stemlab_product_text() -> str:
    return (
        "StemLab product lens:\n"
        "* Primary user: an EDM producer or remixer trying to turn ideas or source audio into usable production parts.\n"
        "* Core workflow: prompt or upload audio, create or separate stems, label them, and export a DAW-ready pack.\n"
        "* MVP boundary: one genre lane, one export target, and one excellent stem-pack workflow.\n"
        "* Must-have output: cleanly named stems with BPM, key, loop points, sections, and Ableton-ready organization.\n"
        "* What to avoid: a full DAW, social feed, licensing marketplace, or giant custom model before demand is proven.\n"
        "* Next product move: define the exact v0 export pack and test it with real producer sessions."
    )


def stemlab_positioning_text() -> str:
    return (
        "StemLab positioning lens:\n"
        "* Category: AI stem workflow tool for EDM production.\n"
        "* Audience: DJs, remixers, and producers who need usable building blocks, not finished novelty tracks.\n"
        "* Promise: turn ideas or audio into organized stems producers can drag into Ableton and keep working on.\n"
        "* Proof: quality of separated or generated stems, labeling, BPM/key accuracy, and DAW-ready export structure.\n"
        "* Claims to avoid: replacing producers, instant finished hits, or perfect rights-safe commercial output.\n"
        "* One-sentence positioning: StemLab turns track ideas or audio into producer-ready stem packs for Ableton workflows."
    )


def stemlab_customer_text() -> str:
    return (
        "StemLab customer lens:\n"
        "* First users: EDM producers, remixers, sample-pack buyers, and DJs who already edit tracks in Ableton.\n"
        "* Pain points: hard-to-use AI output, messy stems, weak labels, missing BPM/key data, and slow remix prep.\n"
        "* Interview targets: working producers, remix contest entrants, DJ edit makers, and sample-pack power users.\n"
        "* Buying/use signals: they request exports, reuse stems in sessions, ask for more packs, or pay for faster prep.\n"
        "* Disqualifying users: people who only want a finished AI song and never open a DAW.\n"
        "* Next customer move: interview 5 producers with a sample stem pack and observe their actual workflow."
    )


def stemlab_validation_text() -> str:
    return (
        "StemLab validation lens:\n"
        "* Concierge MVP: manually prepare a few Ableton-ready stem packs from prompts or uploads.\n"
        "* Fake-door test: show the export promise and collect producer requests before automating the pipeline.\n"
        "* Producer test: give users stems during a real session and watch whether they keep, edit, or discard them.\n"
        "* Success metric: producers import the pack, use at least one stem, and ask for another workflow pass.\n"
        "* Failure signal: they say it is interesting but do not use the stems in a project.\n"
        "* Next validation move: run 3 observed sessions with a manual pack and record what blocks adoption."
    )


def stemlab_assumptions_text() -> str:
    return (
        "StemLab assumption stack:\n"
        "* Demand assumption: producers want AI-assisted stem workflows enough to change their current process.\n"
        "* Workflow assumption: Ableton-ready packs are more valuable than finished generated tracks for this audience.\n"
        "* Quality assumption: stems can be clean, labeled, and controlled enough for real production use.\n"
        "* Export assumption: BPM, key, sections, loop points, and file organization create meaningful workflow value.\n"
        "* Willingness-to-pay assumption: users will pay for faster usable stems, not just experiment with free demos.\n"
        "* Next assumption to test: whether producers reuse a manual StemLab pack inside an actual session."
    )


def stemlab_research_text() -> str:
    return (
        "StemLab research plan:\n"
        "* Core question: determine which producer workflow problem is painful enough to justify StemLab.\n"
        "* Evidence sources: interviews, observed sessions, search results, forums, product pages, docs, and reviews.\n"
        "* User workflow research: study how producers move from idea, sample, or track to Ableton-ready material.\n"
        "* Competitor research: compare what existing tools promise, where users complain, and what they omit.\n"
        "* Technical research: test feasibility for separation, BPM/key, sections, loop points, MIDI, and packaging.\n"
        "* Decision output: summarize evidence, unknowns, risks, and the next validation step before building."
    )


def stemlab_ableton_research_text() -> str:
    return (
        "StemLab Ableton research plan:\n"
        "* Session View workflow: learn how producers audition stems, loops, scenes, and clips.\n"
        "* Arrangement View workflow: map how stems become intros, builds, drops, breakdowns, and outros.\n"
        "* Warping and BPM: identify what makes imported audio align quickly and reliably.\n"
        "* Key and labeling: define naming, key, and metadata expectations for fast reuse.\n"
        "* Stem/clip organization: inspect folder, track, scene, and clip conventions producers prefer.\n"
        "* What Ableton-ready must mean: convert findings into an export checklist, not a vague claim."
    )


def stemlab_reddit_research_text() -> str:
    return (
        "StemLab Reddit/forum research plan:\n"
        "* Communities to search: r/ableton, r/edmproduction, r/musicproduction, r/DJs, r/Beatmatch, and r/WeAreTheMusicMakers.\n"
        "* Pain-point queries: find complaints about stems, remix prep, sample cleanup, labeling, BPM, and key.\n"
        "* Competitor complaint queries: search for Moises, LALAL.AI, RipX, Serato Stems, rekordbox stems, and DJ.Studio issues.\n"
        "* Ableton workflow queries: look for import, warping, Session View, Arrangement View, racks, clips, and scenes.\n"
        "* Quality/artifact queries: collect language users use for bleed, artifacts, phasing, timing, and unusable stems.\n"
        "* Synthesis method: tag posts by pain, workflow, tool, severity, workaround, and evidence quality."
    )


def stemlab_competitor_research_text() -> str:
    return (
        "StemLab competitor research plan:\n"
        "* Stem separation tools: compare Moises, LALAL.AI, and RipX on output quality, controls, and export workflow.\n"
        "* AI music generators: review Suno and Udio for creation strengths and DAW-readiness gaps.\n"
        "* Sample-pack workflows: study Splice and Loopcloud for browsing, metadata, key, BPM, and reuse patterns.\n"
        "* DJ stem tools: inspect Serato Stems, rekordbox stems, and DJ.Studio for performance and remix prep use cases.\n"
        "* Ableton ecosystem: look at packs, templates, Max devices, naming conventions, and import expectations.\n"
        "* Gap to look for: a focused Ableton-ready stem workflow that existing tools do not solve end to end."
    )


def stemlab_technical_research_text() -> str:
    return (
        "StemLab technical research plan:\n"
        "* Source separation: compare available APIs/models and test artifacts on dense EDM, vocals, drums, bass, and synths.\n"
        "* BPM/key detection: check accuracy, confidence scoring, edge cases, and correction workflows.\n"
        "* Section detection: evaluate whether intro, build, drop, breakdown, and outro labels can be useful enough.\n"
        "* Loop point detection: test bar alignment, transient handling, tails, and seamless loop exports.\n"
        "* MIDI extraction: assess where MIDI is useful, unreliable, or should be omitted from v0.\n"
        "* Export packaging: define folder structure, filenames, metadata, previews, dry/wet versions, and Ableton import behavior."
    )


def stemlab_what_not_to_build_text() -> str:
    return (
        "StemLab what-not-to-build list:\n"
        "* Generic Suno clone: broad full-song generation is not the wedge.\n"
        "* Full DAW replacement: producers already have Ableton and need better input material.\n"
        "* Full Ableton project export too early: validate organized stems before promising complete projects.\n"
        "* Broad social platform: sharing and feeds distract from workflow proof.\n"
        "* Too many genres: start with one production lane where quality expectations are clear.\n"
        "* Perfect-stems-from-any-song promise: dense mixes and rights issues make this unsafe as a v0 claim.\n"
        "* Model training before validation: prove the workflow manually or with existing tools first."
    )


def stemlab_research_questions_text() -> str:
    return (
        "StemLab research questions:\n"
        "* User questions: who has the pain often enough to pay or switch behavior?\n"
        "* Workflow questions: where do producers lose time between idea, audio, stems, and Ableton session?\n"
        "* Quality questions: what artifacts, labels, timing, or missing metadata make output unusable?\n"
        "* Market questions: which alternatives are used today, and why are they insufficient?\n"
        "* Technical questions: which parts can be reliable with existing tools, and which need invention?\n"
        "* Legal/licensing questions: what uploads, outputs, and commercial uses create risk?\n"
        "* Validation questions: what observed behavior proves users would reuse StemLab output?"
    )


def live_research_tools_available() -> bool:
    return is_live_research_available()


def research_text() -> str:
    return (
        "Bishop research layer:\n"
        "Bishop can plan research, structure source review, and save source-backed findings, "
        "but live browsing depends on connected tools.\n"
        "* plan: turn the question into a deterministic research plan.\n"
        "* search: define source targets and query patterns before looking anything up.\n"
        "* verify: separate claims, evidence, credibility, and open questions.\n"
        "* synthesize: turn reviewed sources into product or decision implications.\n"
        "* cite: keep findings tied to the sources that support them.\n"
        "* save: save only source-backed findings, not unsupported guesses."
    )


def research_status_text() -> str:
    available, message, provider = validate_research_config()
    if available:
        live_status = f"Live web research is configured through {provider}."
    else:
        if provider in {"", "none", "off", "disabled"}:
            live_status = "Live web/MCP execution is not wired yet."
        else:
            live_status = "Live web research provider is not configured."

    return (
        "Bishop research status:\n"
        f"* Live capability: {live_status}\n"
        f"* Configuration: {message}\n"
        "* Deterministic research plans are available.\n"
        "* Persistent memory is available.\n"
        "* Source-backed findings can be structured for saving when a real source is available."
    )


def research_command_text(command: str) -> str:
    if command == "research status":
        return research_status_text()
    return research_text()


def stemlab_web_research_text() -> str:
    return (
        "StemLab web research workflow:\n"
        "* question: define the decision the research must inform.\n"
        "* source targets: identify primary sources, docs, product pages, forums, reviews, and credible comparisons.\n"
        "* search queries: write focused queries for user pain, workflow behavior, competitors, and technical feasibility.\n"
        "* credibility checks: separate official claims, user reports, repeated complaints, and unsupported opinions.\n"
        "* synthesis: group evidence by workflow, quality, technical risk, market signal, and product implication.\n"
        "* decision output: summarize what to do next, what not to claim, and what remains unknown.\n\n"
        "This is a workflow unless live search tools are wired."
    )


def stemlab_reddit_search_plan_text() -> str:
    return (
        "StemLab Reddit search plan:\n"
        "* communities: r/ableton, r/edmproduction, r/musicproduction, r/DJs, r/Beatmatch, r/WeAreTheMusicMakers.\n"
        "* query patterns: stems, remix prep, Ableton import, warping, BPM, key, sample cleanup, AI music, stem separation.\n"
        "* complaints to look for: artifacts, bleed, bad timing, weak labels, unusable stems, missing metadata, slow prep, poor export flow.\n"
        "* quality/artifact language: phasing, smearing, watery vocals, transient loss, timing drift, muddy bass, noisy highs.\n"
        "* Ableton workflow signals: Session View, Arrangement View, clips, scenes, racks, warp markers, loop points, dry/wet versions.\n"
        "* synthesis tags: pain, workflow, tool, artifact, severity, workaround, willingness-to-pay, product implication."
    )


def stemlab_source_backed_finding_text() -> str:
    return (
        "StemLab source-backed finding format:\n"
        "* Finding:\n"
        "* Source:\n"
        "* Evidence:\n"
        "* Confidence:\n"
        "* Product implication:\n"
        "* Memory category:\n"
        "* Open question:\n\n"
        "Findings should only be saved when a source is available."
    )


def extract_web_research_query(user_text: str) -> str | None:
    match = re.match(r"^\s*web\s+research(?:\s*[:,-]\s*|\s+)(.+)$", user_text or "", re.IGNORECASE)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip() or None


def extract_stemlab_live_web_research_query(user_text: str) -> str | None:
    match = re.match(
        r"^\s*stemlab\s+live\s+web\s+research(?:\s*[:,-]\s*|\s+)(.+)$",
        user_text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip() or None


def format_sources_for_slack(sources: list[dict]) -> list[str]:
    if not sources:
        return ["* none"]

    lines = []
    for source in sources:
        title = clean_string(source.get("title"), "Untitled source")
        url = clean_string(source.get("url"))
        if url:
            lines.append(f"* {title} - {url}")
        else:
            lines.append(f"* {title}")
    return lines


def format_list_section(title: str, items: list[str]) -> str:
    safe_items = [clean_string(item) for item in items if clean_string(item)]
    if not safe_items:
        safe_items = ["none"]
    return title + "\n" + "\n".join(f"* {item}" for item in safe_items)


def format_web_research_response(result: dict, *, stemlab: bool = False) -> str:
    query = clean_string(result.get("query"), "unknown")

    if not result.get("available"):
        if stemlab:
            return (
                "StemLab live web research unavailable:\n"
                f"* requested query: {query}\n"
                "* what Bishop would research: source-backed StemLab workflow, competitor, quality, and Ableton-ready evidence.\n"
                f"* missing configuration: {clean_string(result.get('missing_configuration'), 'unknown')}"
            )

        return (
            "Live web research unavailable:\n"
            f"* requested query: {query}\n"
            f"* missing configuration: {clean_string(result.get('missing_configuration'), 'unknown')}\n"
            f"* next setup step: {clean_string(result.get('next_setup_step'), 'Configure RESEARCH_PROVIDER and RESEARCH_API_KEY.')}"
        )

    sources = result.get("sources") if isinstance(result.get("sources"), list) else []
    findings = result.get("findings") if isinstance(result.get("findings"), list) else []
    implications = (
        result.get("product_implications")
        if isinstance(result.get("product_implications"), list)
        else []
    )
    open_questions = (
        result.get("open_questions")
        if isinstance(result.get("open_questions"), list)
        else []
    )

    if stemlab:
        sections = [
            "StemLab live web research result:",
            f"Query: {query}",
            format_list_section("Findings:", findings),
            format_list_section("Product implications:", implications),
            format_list_section(
                "What not to build:",
                ["Do not build or claim anything based on unsourced findings or single-source weak evidence."],
            ),
            format_list_section("Open questions:", open_questions),
            "Sources checked:\n" + "\n".join(format_sources_for_slack(sources)),
            f"Suggested memory item: {clean_string(result.get('suggested_memory_item'), 'none yet')}",
        ]
        return "\n".join(sections)

    sections = [
        "Live web research result:",
        f"Query: {query}",
        "Sources checked:\n" + "\n".join(format_sources_for_slack(sources)),
        format_list_section("Findings:", findings),
        f"Confidence: {clean_string(result.get('confidence'), 'unknown')}",
        format_list_section("Product implications:", implications),
        format_list_section("Open questions:", open_questions),
        f"Suggested memory item: {clean_string(result.get('suggested_memory_item'), 'none yet')}",
    ]
    return "\n".join(sections)


def stemlab_project_text(command: str) -> str:
    if command == "stemlab plan":
        return stemlab_plan_text()
    if command == "stemlab next":
        return stemlab_next_text()
    if command == "stemlab mvp":
        return stemlab_mvp_text()
    if command == "stemlab founder":
        return stemlab_founder_text()
    if command == "stemlab product":
        return stemlab_product_text()
    if command == "stemlab positioning":
        return stemlab_positioning_text()
    if command == "stemlab customer":
        return stemlab_customer_text()
    if command == "stemlab validation":
        return stemlab_validation_text()
    if command == "stemlab assumptions":
        return stemlab_assumptions_text()
    if command == "stemlab research":
        return stemlab_research_text()
    if command == "stemlab ableton research":
        return stemlab_ableton_research_text()
    if command == "stemlab reddit research":
        return stemlab_reddit_research_text()
    if command == "stemlab competitor research":
        return stemlab_competitor_research_text()
    if command == "stemlab technical research":
        return stemlab_technical_research_text()
    if command == "stemlab what not to build":
        return stemlab_what_not_to_build_text()
    if command == "stemlab research questions":
        return stemlab_research_questions_text()
    if command == "stemlab web research":
        return stemlab_web_research_text()
    if command == "stemlab reddit search plan":
        return stemlab_reddit_search_plan_text()
    if command == "stemlab source backed finding":
        return stemlab_source_backed_finding_text()
    return stemlab_overview_text()


def normalize_stemlab_memory_content(content: str) -> str:
    content = clean_string(content)
    content = re.sub(r"^\s*[-*•]\s*", "", content)
    content = re.sub(r"^\s*\d+[.)]\s*", "", content)
    return content.strip()


def stemlab_memory_category_for_text(text: str) -> str | None:
    content = normalize_stemlab_memory_content(text)
    lowered = content.casefold()
    if len(content) < 18:
        return None

    if "stem maker" in lowered or "founder mode" in lowered:
        return None

    if lowered.startswith(("open question:", "question:")) or lowered.endswith("?"):
        return "StemLab Open Question"
    if lowered.startswith("risk:") or re.search(r"\brisk\b|\bconcern\b|\bblocker\b", lowered):
        return "StemLab Risk"
    if lowered.startswith(("next action:", "action:")) or re.search(
        r"\b(next action|interview|test with|validate with|research|decide whether|compare)\b",
        lowered,
    ):
        return "StemLab Next Action"
    if lowered.startswith(("research finding:", "finding:")) or re.search(
        r"\bresearch finding\b|\bwe learned\b|\bresearch shows\b|\bfinding\b",
        lowered,
    ):
        return "StemLab Research Finding"
    if lowered.startswith(("decision:", "decided:")) or re.search(
        r"\bwe decided\b|\bdecision\b|\bshould validate\b|\bshould prioritize\b|\bshould focus\b|\bshould avoid\b|\bmust\b",
        lowered,
    ):
        return "StemLab Decision"
    if lowered.startswith(("product direction:", "direction:")) or re.search(
        r"\bwedge\b|\bnot just suno\b|\bproducer-ready\b|\bableton-ready\b|\bworkflow\b|\bbuilding blocks\b",
        lowered,
    ):
        return "StemLab Product Direction"

    return None


def is_low_value_stemlab_memory_text(text: str) -> bool:
    lowered = normalize_stemlab_memory_content(text).casefold().rstrip(".!?")
    return lowered in {
        "",
        "great",
        "thanks",
        "thank you",
        "let's go",
        "lets go",
        "sounds good",
        "ok",
        "okay",
    }


def split_stemlab_memory_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    for raw_line in (text or "").splitlines():
        line = normalize_stemlab_memory_content(raw_line)
        if line:
            candidates.append(line)

    if len(candidates) <= 1:
        sentence_parts = re.split(r"(?<=[.!?])\s+", text or "")
        candidates.extend(normalize_stemlab_memory_content(part) for part in sentence_parts)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        candidate = normalize_stemlab_memory_content(candidate)
        key = candidate.casefold()
        if not candidate or key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def explicit_stemlab_memory_pattern() -> re.Pattern:
    category_names = "|".join(
        re.escape(name) for name in sorted(STEMLAB_EXPLICIT_MEMORY_CATEGORIES, key=len, reverse=True)
    )
    return re.compile(
        rf"\bfor\s+stemlab\s*,?\s*({category_names})\s*:\s*",
        flags=re.IGNORECASE,
    )


def extract_stemlab_memory_items(user_text: str, response_text: str) -> list[dict]:
    if "stemlab" not in (user_text or "").casefold():
        return []

    pattern = explicit_stemlab_memory_pattern()
    matches = list(pattern.finditer(user_text or ""))
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for index, match in enumerate(matches):
        next_match_start = matches[index + 1].start() if index + 1 < len(matches) else len(user_text)
        category_key = match.group(1).casefold()
        content_body = normalize_stemlab_memory_content(user_text[match.end():next_match_start])
        if is_low_value_stemlab_memory_text(content_body):
            continue

        category = STEMLAB_EXPLICIT_MEMORY_CATEGORIES.get(category_key)
        if not category:
            continue

        category_label = category.replace("StemLab ", "")
        content = f"{category_label}: {content_body}"
        key = (category, content.casefold())
        if key in seen:
            continue
        seen.add(key)
        items.append({"category": category, "content": content})
    return items[:5]


def is_stemlab_auto_memory_eligible_command(lowered: str) -> bool:
    if lowered == "help":
        return False
    if lowered in MODE_GUIDE_MESSAGES or lowered in MODE_RECOMMENDATION_MESSAGES:
        return False
    if lowered in STEMLAB_PROJECT_MESSAGES or lowered in STEMLAB_MEMORY_QUERY_MESSAGES:
        return False
    if lowered in MODE_QUERY_MESSAGES or lowered in LANE_QUERY_MESSAGES:
        return False
    if lowered in {"provider", "show provider", "model", "status", "show config"}:
        return False
    if lowered.startswith("provider "):
        return False
    return True


def stemlab_memory_already_exists(user_id: str, category: str, content: str) -> bool:
    existing = get_safe_memory_items(
        get_memories(user_id=user_id, lane=STEMLAB_MEMORY_LANE, limit=100),
        STEMLAB_MEMORY_LANE,
    )
    normalized_content = normalize_stemlab_memory_content(content).casefold()
    normalized_category = category.casefold()
    for item in existing:
        existing_category = clean_string(item.get("category")).casefold()
        existing_content = normalize_stemlab_memory_content(item.get("content")).casefold()
        if existing_category == normalized_category and existing_content == normalized_content:
            return True
    return False


def capture_stemlab_project_memory(user_id: str, user_text: str, response_text: str) -> list[dict]:
    captured: list[dict] = []
    for item in extract_stemlab_memory_items(user_text, response_text):
        category = item["category"]
        content = item["content"]
        if stemlab_memory_already_exists(user_id, category, content):
            continue
        result = add_memory(
            user_id=user_id,
            category=category,
            content=content,
            lane=STEMLAB_MEMORY_LANE,
            visibility="private",
        )
        if isinstance(result, dict) and not result.get("skipped"):
            captured.append(result)
    return captured


def build_stemlab_memory_response(user_id: str, category: str | None = None) -> str:
    raw_memories = get_memories(user_id=user_id, lane=STEMLAB_MEMORY_LANE, limit=100)
    memories = get_safe_memory_items(raw_memories, STEMLAB_MEMORY_LANE)
    memories = [
        item
        for item in memories
        if clean_string(item.get("category")) in STEMLAB_MEMORY_CATEGORIES
    ]
    if category:
        memories = [
            item
            for item in memories
            if clean_string(item.get("category")).casefold() == category.casefold()
        ]

    memories = dedupe_memory_items(memories)

    if not memories:
        if category:
            return f"No saved {category} items yet."
        return "No saved StemLab project memory yet."

    if category:
        lines = [f"{category}:"]
        lines.extend(f"* {clean_string(item.get('content'))}" for item in memories)
        return "\n".join(lines)

    lines = ["StemLab project memory:"]
    for group in sorted(STEMLAB_MEMORY_CATEGORIES):
        group_items = [
            item
            for item in memories
            if clean_string(item.get("category")).casefold() == group.casefold()
        ]
        if not group_items:
            continue
        lines.append(f"{group}:")
        lines.extend(f"* {clean_string(item.get('content'))}" for item in group_items)
    return "\n".join(lines)


def format_recent_conversations_for_slack(items: list[dict]) -> str:
    if not items:
        return "I do not have any recent conversations for you yet."

    lines = ["Here are your recent conversations:"]

    for item in items:
        created_at = item.get("created_at", "")
        timestamp = created_at.replace("T", " ")[:19] if created_at else "unknown time"

        user_message = (item.get("user_message") or "").strip().replace("\n", " ")
        assistant_response = (item.get("assistant_response") or "").strip().replace("\n", " ")

        if len(user_message) > 80:
            user_message = user_message[:77] + "..."
        if len(assistant_response) > 120:
            assistant_response = assistant_response[:117] + "..."

        lines.append(
            f"* {timestamp}\n"
            f"  You: {user_message}\n"
            f"  Bishop: {assistant_response}"
        )

    return "\n".join(lines)


def format_tasks_for_slack(
    items: list[dict],
    *,
    title: str = "Pending tasks:",
    empty_text: str = "No pending tasks right now.",
) -> str:
    if not items:
        return empty_text

    lines = [title]
    for item in items:
        created_at = item.get("created_at", "")
        timestamp = created_at.replace("T", " ")[:19] if created_at else "unknown time"
        task_text = (item.get("task_text") or "").strip()
        assistant_commitment = (item.get("assistant_commitment") or "").strip().replace("\n", " ")

        if len(task_text) > 120:
            task_text = task_text[:117] + "..."
        if len(assistant_commitment) > 120:
            assistant_commitment = assistant_commitment[:117] + "..."

        lines.append(f"* {timestamp}: {task_text}")
        if assistant_commitment:
            lines.append(f"  Commitment: {assistant_commitment}")

    return "\n".join(lines)


def format_all_tasks_for_slack(pending_items: list[dict], done_items: list[dict]) -> str:
    if not pending_items and not done_items:
        return "No tasks right now."

    sections = []

    sections.append(
        format_tasks_for_slack(
            pending_items,
            title="Pending tasks:",
            empty_text="No pending tasks right now.",
        )
    )
    sections.append("")
    sections.append(
        format_tasks_for_slack(
            done_items,
            title="Completed tasks:",
            empty_text="No completed tasks right now.",
        )
    )

    return "\n".join(sections)


def get_requested_conversation_limit(lowered: str) -> int | None:
    if lowered == "show recent conversations":
        return 5

    match = re.fullmatch(r"show last (\d+) conversations", lowered)
    if not match:
        return None

    requested_limit = int(match.group(1))
    if requested_limit < 1:
        return 1
    if requested_limit > 10:
        return 10
    return requested_limit


def is_short_followup_message(user_text: str) -> bool:
    normalized = normalize_message_for_dedupe(user_text)
    return normalized in SHORT_FOLLOWUP_MESSAGES


def assistant_invited_followup(assistant_response: str) -> bool:
    lowered = (assistant_response or "").strip().lower()

    followup_signals = [
        "want 3 more",
        "want three more",
        "want more",
        "want another",
        "want a sharper",
        "want a darker",
        "want one",
        "want me to",
        "i can make them",
        "i can make them:",
        "i can make them more",
    ]

    return any(signal in lowered for signal in followup_signals)


def expand_short_followup_message(user_id: str, user_text: str) -> str:
    if not is_short_followup_message(user_text):
        return user_text

    items = get_recent_conversations_for_user(
        user_id=user_id,
        limit=1,
        platform="slack",
        exclude_utility_commands=True,
        fetch_limit=10,
    )

    if not items:
        return user_text

    previous_item = items[0]
    previous_user_message = (previous_item.get("user_message") or "").strip()
    previous_assistant_response = (previous_item.get("assistant_response") or "").strip()

    if not previous_user_message or not previous_assistant_response:
        return user_text

    if not assistant_invited_followup(previous_assistant_response):
        return user_text

    return (
        "You are continuing a Slack conversation.\n\n"
        f"User's previous message: {previous_user_message}\n"
        f"Your previous reply: {previous_assistant_response}\n"
        f"User's new reply: {user_text}\n\n"
        "Treat the new reply as a short follow-up to the previous exchange. "
        "Directly fulfill the implied request instead of asking what the user wants, "
        "if the previous assistant message already offered a clear next step."
    )


def log_system_response(
    user_id: str,
    channel_id: str,
    user_text: str,
    response_text: str,
    *,
    memory_used: bool = False,
    model: str | None = None,
):
    log_conversation(
        platform="slack",
        user_id=user_id,
        channel_id=channel_id,
        session_id=channel_id,
        user_message=user_text,
        assistant_response=response_text,
        memory_used=memory_used,
        mode=get_mode(user_id),
        provider="system",
        model=model,
    )


def get_active_model_for_effective_provider() -> str:
    effective_provider = get_effective_provider()
    return get_provider_model(effective_provider) or "not set"


def build_provider_summary_text() -> tuple[str, str]:
    resolution = get_provider_resolution()
    effective_provider = resolution["effective_provider"]
    active_model = get_provider_model(effective_provider) or "not set"

    lines = [
        f"Effective provider: {effective_provider}",
        f"Active model: {active_model}",
        f"Override: {resolution['override'] or 'none'}",
        f"Override status: {'OK' if resolution['override_ok'] else resolution['override_message']}",
        f"Default provider: {resolution['default_provider']}",
        f"Default status: {'OK' if resolution['default_ok'] else resolution['default_message']}",
        f"Resolution source: {resolution['effective_from']}",
    ]

    return "\n".join(lines), active_model


def build_lane_text(channel_id: str, lane: str, default_visibility: str) -> str:
    return (
        f"Current lane: {lane}\n"
        f"Channel ID: {channel_id}\n"
        f"Default visibility: {default_visibility}"
    )


def get_tasks_for_lane(user_id: str, lane: str, status: str, limit: int = 10):
    try:
        return get_tasks(user_id=user_id, lane=lane, status=status, limit=limit)
    except TypeError:
        return get_tasks(user_id=user_id, status=status, limit=limit)


def clear_tasks_for_lane(user_id: str, lane: str, status: str):
    try:
        return clear_tasks(user_id=user_id, lane=lane, status=status)
    except TypeError:
        return clear_tasks(user_id=user_id, status=status)


def mark_task_done_for_lane(user_id: str, lane: str, task_text: str):
    try:
        return mark_task_done(user_id=user_id, lane=lane, task_text=task_text)
    except TypeError:
        return mark_task_done(user_id=user_id, task_text=task_text)


def remove_task_for_lane(user_id: str, lane: str, task_text: str, status: str):
    try:
        return remove_task(user_id=user_id, lane=lane, task_text=task_text, status=status)
    except TypeError:
        return remove_task(user_id=user_id, task_text=task_text, status=status)


def add_task_for_lane(
    *,
    user_id: str,
    lane: str,
    channel_id: str,
    session_id: str,
    source_message: str,
    task_text: str,
    assistant_commitment: str,
    status: str = "pending",
):
    try:
        return add_task(
            user_id=user_id,
            lane=lane,
            channel_id=channel_id,
            session_id=session_id,
            source_message=source_message,
            task_text=task_text,
            assistant_commitment=assistant_commitment,
            status=status,
        )
    except TypeError:
        return add_task(
            user_id=user_id,
            channel_id=channel_id,
            session_id=session_id,
            source_message=source_message,
            task_text=task_text,
            assistant_commitment=assistant_commitment,
            status=status,
        )


def get_partitioned_lane_memories(user_id: str, lane: str) -> tuple[list[dict], list[dict]]:
    raw_memories = get_memories(user_id=user_id, lane=lane, limit=20)
    memories = get_safe_memory_items(raw_memories, lane)
    memories = rerank_memory_items(dedupe_memory_items(memories))
    suppressed = suppress_boilerplate_memory_items(memories)
    if suppressed or not memories:
        memories = suppressed
    return partition_memory_items_by_profile(memories)


ATTENTION_BULLET = "•"


def _format_attention_tasks(items: list[dict]) -> str:
    lines = ["Pending tasks"]
    for item in items:
        task_text = (item.get("task_text") or "").strip()
        if not task_text:
            continue
        if len(task_text) > 120:
            task_text = task_text[:117] + "..."
        lines.append(f"{ATTENTION_BULLET} {task_text}")
    return "\n".join(lines)


def _format_attention_memory(items: list[dict]) -> str:
    lines = ["Operational context"]
    for item in items:
        if not isinstance(item, dict):
            continue
        content = clean_string(item.get("content"))
        if not content:
            continue
        lines.append(f"{ATTENTION_BULLET} {content}")
    return "\n".join(lines)


def is_attention_actionable(item: dict) -> bool:
    """Items that should appear as urgent attention items.
    Profile/preference content is durable background, not actionable —
    even if the working partition has uplifted it via operational keywords."""
    if not isinstance(item, dict):
        return False
    content = clean_string(item.get("content"))
    if not content:
        return False
    category = clean_string(item.get("category")).casefold()
    if category in LOW_SIGNAL_MEMORY_CATEGORIES:
        return False
    if not category or category == "note":
        inferred = (infer_memory_category(content, "note") or "").strip().lower()
        if inferred in LOW_SIGNAL_MEMORY_CATEGORIES:
            return False
    return True


def build_attention_response(user_id: str, lane: str) -> str:
    pending_tasks = get_tasks_for_lane(
        user_id=user_id, lane=lane, status="pending", limit=10
    )
    working_memory, _background_memory = get_partitioned_lane_memories(user_id, lane)

    operational = [m for m in working_memory if is_attention_actionable(m)]

    if not pending_tasks and not operational:
        return (
            f"Nothing urgent in the {lane} lane right now.\n\n"
            "I have background context saved, but nothing that needs action."
        )

    sections = [f"Here’s what needs your attention in the {lane} lane:"]

    if pending_tasks:
        sections.append("")
        sections.append(_format_attention_tasks(pending_tasks))

    if operational:
        sections.append("")
        sections.append(_format_attention_memory(operational))

    return "\n".join(sections)


def build_status_text(user_id: str, lane: str) -> tuple[str, str]:
    current_mode = get_mode(user_id)
    resolution = get_provider_resolution()
    effective_provider = resolution["effective_provider"]
    active_model = get_provider_model(effective_provider) or "not set"
    pending_tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="pending", limit=10)
    working_memory, background_profile = get_partitioned_lane_memories(user_id, lane)

    openai_ok, openai_message = validate_provider_config("openai")
    claude_ok, claude_message = validate_provider_config("claude")

    response_text = (
        "*Bishop Status*\n\n"
        f"*Mode:* {current_mode}\n"
        f"*Lane:* {lane}\n"
        f"*Effective provider:* {effective_provider}\n"
        f"*Active model:* {active_model}\n"
        f"*Provider override:* {resolution['override'] or 'none'}\n"
        f"*Override status:* {'OK' if resolution['override_ok'] else resolution['override_message']}\n"
        f"*Railway default provider:* {resolution['default_provider']}\n"
        f"*Default provider status:* {'OK' if resolution['default_ok'] else resolution['default_message']}\n"
        f"*Resolution source:* {resolution['effective_from']}\n"
        f"*Pending tasks:* {len(pending_tasks)}\n"
        f"*Working memory:* {len(working_memory)}\n"
        f"*Background profile:* {len(background_profile)}\n\n"
        "*Provider checks:*\n"
        f"* OpenAI: {'OK' if openai_ok else 'Missing'} , {openai_message}\n"
        f"* Claude: {'OK' if claude_ok else 'Missing'} , {claude_message}"
    )

    return response_text, active_model


def extract_by_patterns(message: str, patterns: list[str]) -> str | None:
    original = (message or "").strip()
    if not original:
        return None

    lowered = original.lower()
    for pattern in patterns:
        match = re.match(pattern, lowered)
        if match:
            extracted = original[match.end():].strip()
            extracted = re.sub(r"\s+", " ", extracted).strip()
            return extracted or None

    return None


def extract_task_text_for_completion(message: str) -> str | None:
    return extract_by_patterns(message, COMPLETE_TASK_PATTERNS)


def extract_task_text_for_done_removal(message: str) -> str | None:
    return extract_by_patterns(message, REMOVE_DONE_TASK_PATTERNS)


def extract_task_text_for_removal(message: str) -> str | None:
    return extract_by_patterns(message, REMOVE_TASK_PATTERNS)


def extract_memory_text_for_remember(message: str) -> str | None:
    return extract_by_patterns(message, REMEMBER_PATTERNS)


def extract_memory_text_for_remember_shared(message: str) -> str | None:
    return extract_by_patterns(message, REMEMBER_SHARED_PATTERNS)


def extract_memory_text_for_remember_private(message: str) -> str | None:
    return extract_by_patterns(message, REMEMBER_PRIVATE_PATTERNS)


def extract_memory_text_for_recall(message: str) -> str | None:
    return extract_by_patterns(message, RECALL_PATTERNS)


def extract_memory_text_for_forget(message: str) -> str | None:
    return extract_by_patterns(message, FORGET_MEMORY_PATTERNS)


def extract_memory_text_for_exact_forget(message: str) -> str | None:
    return extract_by_patterns(message, EXACT_FORGET_MEMORY_PATTERNS)


def resolve_memory_visibility(user_text: str, lane_default_visibility: str) -> tuple[str, str | None, bool]:
    remembered_text = extract_memory_text_for_remember_shared(user_text)
    if remembered_text:
        return "shared", remembered_text, True

    remembered_text = extract_memory_text_for_remember_private(user_text)
    if remembered_text:
        return "private", remembered_text, True

    remembered_text = extract_memory_text_for_remember(user_text)
    if remembered_text:
        return lane_default_visibility, remembered_text, False

    return lane_default_visibility, None, False


def get_result_status(result: object) -> str | None:
    if not isinstance(result, dict):
        return None

    status = result.get("status")
    if not isinstance(status, str):
        return None

    normalized_status = status.strip().lower()
    return normalized_status or None


def get_result_flag(result: object, flag_name: str) -> bool:
    if not isinstance(result, dict):
        return False

    if bool(result.get(flag_name)):
        return True

    status = get_result_status(result)

    if flag_name == "updated":
        return status == "updated"

    if flag_name == "deleted":
        return status == "deleted"

    return False


def get_result_task_text(result: object, fallback_text: str) -> str:
    if isinstance(result, dict):
        nested_task = result.get("task")
        if isinstance(nested_task, dict):
            nested_text = (nested_task.get("task_text") or "").strip()
            if nested_text:
                return nested_text

        top_level_text = (result.get("task_text") or "").strip()
        if top_level_text:
            return top_level_text

    return fallback_text


def get_deleted_count(result: object) -> int:
    if not isinstance(result, dict):
        return 0

    deleted_value = result.get("deleted", 0)
    if isinstance(deleted_value, bool):
        return int(deleted_value)

    try:
        return int(deleted_value)
    except (TypeError, ValueError):
        return 0


def clean_string(value: object, fallback: str = "") -> str:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip()
    return cleaned or fallback


LOW_SIGNAL_MEMORY_CATEGORIES = frozenset({"profile", "preference"})

OPERATIONAL_SIGNAL_KEYWORDS = (
    "bishop",
    "building",
    "working",
    "workflow",
    "terminal",
    "full-file",
    "pytest",
    "commit",
    "push",
    "actionable",
    "project",
    "priority",
)

_OPERATIONAL_SIGNAL_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(keyword) for keyword in OPERATIONAL_SIGNAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def has_operational_signal(content: str) -> bool:
    if not content:
        return False
    return bool(_OPERATIONAL_SIGNAL_PATTERN.search(content))

BOILERPLATE_MEMORY_CONTENTS = frozenset(
    {
        "user's name is matt.",
        "matt is an advertising executive and dj.",
        "bishop is a private ai workspace for work, dj/music, family, carmen, and general life.",
        "matt prefers clear, practical, strategic help.",
        "matt wants bishop to feel like a personal ai operating system, not a generic chatbot.",
    }
)

_SUPPRESSION_WHITESPACE_PATTERN = re.compile(r"\s+")
_SUPPRESSION_SPACE_BEFORE_COMMA_PATTERN = re.compile(r"\s+,")
_SUPPRESSION_TRAILING_PUNCT_PATTERN = re.compile(r"[.!?]+$")


def normalize_memory_content_for_suppression(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = (
        value.replace("‘", "'")
        .replace("’", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("—", ",")
        .replace("–", ",")
    )
    normalized = _SUPPRESSION_WHITESPACE_PATTERN.sub(" ", normalized).strip()
    normalized = _SUPPRESSION_SPACE_BEFORE_COMMA_PATTERN.sub(",", normalized)
    normalized = _SUPPRESSION_TRAILING_PUNCT_PATTERN.sub("", normalized)
    return normalized.casefold()


_NORMALIZED_BOILERPLATE_MEMORY_CONTENTS = frozenset(
    normalize_memory_content_for_suppression(entry) for entry in BOILERPLATE_MEMORY_CONTENTS
)


def suppress_boilerplate_memory_items(items: list[dict]) -> list[dict]:
    filtered = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = normalize_memory_content_for_suppression(item.get("content"))
        if normalized in _NORMALIZED_BOILERPLATE_MEMORY_CONTENTS:
            continue
        filtered.append(item)
    return filtered


def normalize_memory_item(item: object, fallback_lane: str) -> dict | None:
    if not isinstance(item, dict):
        return None

    content = clean_string(item.get("content"))
    if not content:
        return None

    lane = clean_string(item.get("lane"), fallback_lane)
    visibility = clean_string(item.get("visibility"), "unknown")
    category = clean_string(item.get("category"))

    owner_user_id = clean_string(item.get("owner_user_id"))
    if not owner_user_id:
        owner_user_id = clean_string(item.get("user_id"), "unknown")

    owner_display_name = clean_string(get_display_name_for_bishop_user_id(owner_user_id))
    if not owner_display_name and owner_user_id != "unknown":
        owner_display_name = owner_user_id

    return {
        "lane": lane,
        "visibility": visibility,
        "category": category,
        "content": content,
        "owner_user_id": owner_user_id,
        "owner_display_name": owner_display_name,
    }


def dedupe_memory_items(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (
            clean_string(item.get("lane"), "unknown"),
            clean_string(item.get("visibility"), "unknown"),
            clean_string(item.get("owner_user_id"), "unknown"),
            clean_string(item.get("content")).casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def rerank_memory_items(items: list[dict]) -> list[dict]:
    def is_low_signal(item: dict) -> int:
        category = clean_string(item.get("category")).casefold()
        return 1 if category in LOW_SIGNAL_MEMORY_CATEGORIES else 0

    return sorted(items, key=is_low_signal)


def get_safe_memory_items(result: object, fallback_lane: str) -> list[dict]:
    if not isinstance(result, (list, tuple)):
        return []

    normalized_items = []
    for item in result:
        normalized_item = normalize_memory_item(item, fallback_lane)
        if normalized_item is not None:
            normalized_items.append(normalized_item)

    return normalized_items


def format_memory_category_label(category: str) -> str:
    normalized = clean_string(category).casefold()
    if not normalized or normalized == "note":
        return ""
    return f"[{normalized.title()}] "


def format_memory_line(item: dict) -> str:
    if not isinstance(item, dict):
        return "* unknown in unknown:"

    owner_display_name = clean_string(item.get("owner_display_name"))
    visibility = clean_string(item.get("visibility"), "unknown")
    lane = clean_string(item.get("lane"), "unknown")
    content = clean_string(item.get("content"))
    label = format_memory_category_label(clean_string(item.get("category")))
    display = f"{label}{content}"

    if owner_display_name:
        return f"* {owner_display_name} {visibility} in {lane}: {display}"

    return f"* {visibility} in {lane}: {display}"


def format_memory_lines(items: list[dict]) -> list[str]:
    return [format_memory_line(item) for item in items]


def partition_memory_items_by_profile(items: list[dict]) -> tuple[list[dict], list[dict]]:
    working: list[dict] = []
    background: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        category = clean_string(item.get("category")).casefold()
        if category not in LOW_SIGNAL_MEMORY_CATEGORIES:
            working.append(item)
        elif has_operational_signal(clean_string(item.get("content"))):
            working.append(item)
        else:
            background.append(item)
    return working, background


def was_memory_deleted(result: object) -> bool:
    return get_deleted_count(result) > 0


def get_deleted_memory_lane(result: object, fallback_lane: str) -> str:
    if not isinstance(result, dict):
        return fallback_lane
    return clean_string(result.get("lane"), fallback_lane)


def build_lane_memory_response(
    user_id: str, lane: str, include_boilerplate: bool = False
) -> str:
    raw_memories = get_memories(user_id=user_id, lane=lane, limit=20)
    memories = get_safe_memory_items(raw_memories, lane)
    memories = rerank_memory_items(dedupe_memory_items(memories))
    if not include_boilerplate:
        suppressed = suppress_boilerplate_memory_items(memories)
        if suppressed or not memories:
            memories = suppressed
    if not memories:
        return f"I do not have any saved memory yet in the {lane} lane."

    header = f"Here is what I remember in the {lane} lane:"

    if include_boilerplate:
        return header + "\n" + "\n".join(format_memory_lines(memories))

    working, background = partition_memory_items_by_profile(memories)
    sections: list[str] = [header]
    if working:
        sections.append("Working memory:")
        sections.extend(format_memory_lines(working))
    if background:
        sections.append("Background profile:")
        sections.extend(format_memory_lines(background))
    return "\n".join(sections)


def build_lane_memory_section_response(user_id: str, lane: str, section: str) -> str:
    raw_memories = get_memories(user_id=user_id, lane=lane, limit=20)
    memories = get_safe_memory_items(raw_memories, lane)
    memories = rerank_memory_items(dedupe_memory_items(memories))
    suppressed = suppress_boilerplate_memory_items(memories)
    if suppressed or not memories:
        memories = suppressed

    working, background = partition_memory_items_by_profile(memories)

    if section == "working":
        items = working
        header = f"Working memory in the {lane} lane:"
        empty = f"I do not have any working memory yet in the {lane} lane."
    else:
        items = background
        header = f"Background profile in the {lane} lane:"
        empty = f"I do not have any background profile yet in the {lane} lane."

    if not items:
        return empty

    return header + "\n" + "\n".join(format_memory_lines(items))


@router.post("/slack/events")
async def slack_events(request: Request):
    body = await request.json()

    if body.get("type") == "url_verification":
        return {"challenge": body.get("challenge")}

    event_id = body.get("event_id")
    if event_id:
        if event_id in processed_event_ids:
            print(f"Skipping duplicate Slack event_id: {event_id}")
            return {"ok": True}
        processed_event_ids.add(event_id)

        if len(processed_event_ids) > MAX_PROCESSED_EVENT_IDS:
            processed_event_ids.pop()

    if request.headers.get("x-slack-retry-num"):
        print("Skipping Slack retry event")
        return {"ok": True}

    if body.get("type") != "event_callback":
        return {"ok": True}

    event = body.get("event", {})

    if event.get("type") != "app_mention":
        return {"ok": True}

    if event.get("bot_id"):
        return {"ok": True}

    slack_user_id = event.get("user")
    user_id = resolve_bishop_user_id(slack_user_id or "")
    channel_id = event.get("channel")
    raw_text = event.get("text", "")
    user_text = strip_app_mention(raw_text)

    if not user_id or not channel_id or not user_text:
        return {"ok": True}

    if is_duplicate_recent_message(user_id=user_id, channel_id=channel_id, user_text=user_text):
        return {"ok": True}

    lane = get_lane_from_channel(channel_id, resolver=resolve_slack_channel_name)
    default_visibility = get_default_visibility_for_lane(lane)

    try:
        lowered = user_text.lower().strip()

        if lowered == "help":
            response_text = help_text()
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in MODE_GUIDE_MESSAGES:
            response_text = mode_guide_text()
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in MODE_RECOMMENDATION_MESSAGES:
            response_text = mode_recommendation_text()
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in RESEARCH_MESSAGES:
            response_text = research_command_text(lowered)
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        stemlab_live_query = extract_stemlab_live_web_research_query(user_text)
        if stemlab_live_query:
            result = run_web_research(stemlab_live_query, stemlab=True)
            response_text = format_web_research_response(result, stemlab=True)
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        web_research_query = extract_web_research_query(user_text)
        if web_research_query:
            result = run_web_research(web_research_query)
            response_text = format_web_research_response(result)
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in STEMLAB_PROJECT_MESSAGES:
            response_text = stemlab_project_text(lowered)
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in STEMLAB_MEMORY_QUERY_MESSAGES:
            response_text = build_stemlab_memory_response(
                user_id=user_id,
                category=STEMLAB_MEMORY_QUERY_MESSAGES[lowered],
            )
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        memory_command_key = lowered.rstrip(" \t?!.,;:")

        if memory_command_key in {"what do you remember", "show memory"}:
            response_text = build_lane_memory_response(user_id=user_id, lane=lane)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if memory_command_key in {"show all memory", "what do you remember in full"}:
            response_text = build_lane_memory_response(
                user_id=user_id, lane=lane, include_boilerplate=True
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if memory_command_key == "show working memory":
            response_text = build_lane_memory_section_response(
                user_id=user_id, lane=lane, section="working"
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if memory_command_key == "show background profile":
            response_text = build_lane_memory_section_response(
                user_id=user_id, lane=lane, section="background"
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if memory_command_key == "what needs my attention":
            response_text = build_attention_response(user_id=user_id, lane=lane)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        if lowered in LANE_QUERY_MESSAGES:
            response_text = build_lane_text(
                channel_id=channel_id,
                lane=lane,
                default_visibility=default_visibility,
            )
            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        memory_visibility, remembered_text, is_explicit_visibility = resolve_memory_visibility(
            user_text=user_text,
            lane_default_visibility=default_visibility,
        )
        if remembered_text:
            result = add_memory(
                user_id=user_id,
                category="note",
                content=remembered_text,
                lane=lane,
                visibility=memory_visibility,
            )
            if isinstance(result, dict) and result.get("skipped"):
                response_text = (
                    "I already know that basic identity detail, so I won't add it again."
                )
            elif is_explicit_visibility:
                response_text = (
                    f"Got it. I'll remember this as {memory_visibility} in the {lane} lane: "
                    f"{remembered_text}"
                )
            else:
                response_text = f"Got it. I'll remember this in the {lane} lane: {remembered_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        recalled_query = extract_memory_text_for_recall(user_text)
        if recalled_query:
            raw_results = search_memories(
                user_id=user_id,
                query=recalled_query,
                lane=lane,
                limit=5,
            )
            results = get_safe_memory_items(raw_results, lane)
            if results:
                response_text = "Here is what I found:\n" + "\n".join(format_memory_lines(results))
            else:
                response_text = f"I could not find anything matching that in the {lane} lane."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, memory_used=True)
            return {"ok": True}

        exact_forget_query = extract_memory_text_for_exact_forget(user_text)
        if exact_forget_query:
            deleted = delete_memory_by_exact_content(
                user_id=user_id,
                content=exact_forget_query,
                lane=lane,
            )
            if was_memory_deleted(deleted):
                deleted_lane = get_deleted_memory_lane(deleted, lane)
                response_text = (
                    f"Forgot exact memory in the {deleted_lane} lane: {exact_forget_query}"
                )
            else:
                response_text = (
                    f"I could not find an exact match to forget in the {lane} lane: "
                    f"{exact_forget_query}"
                )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        forgotten_query = extract_memory_text_for_forget(user_text)
        if forgotten_query:
            deleted = delete_memory_by_query(
                user_id=user_id,
                query=forgotten_query,
                lane=lane,
            )
            if was_memory_deleted(deleted):
                deleted_lane = get_deleted_memory_lane(deleted, lane)
                response_text = f"Forgot memory in the {deleted_lane} lane matching: {forgotten_query}"
            else:
                response_text = f"I could not find anything to forget for: {forgotten_query} in the {lane} lane."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        requested_limit = get_requested_conversation_limit(lowered)
        if requested_limit is not None:
            items = get_recent_conversations_for_user(
                user_id=user_id,
                limit=requested_limit,
                platform="slack",
                exclude_utility_commands=True,
                fetch_limit=50,
            )
            response_text = format_recent_conversations_for_slack(items)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in TASK_QUERY_MESSAGES:
            tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="pending", limit=10)
            response_text = format_tasks_for_slack(
                tasks,
                title="Pending tasks:",
                empty_text="No pending tasks right now.",
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in DONE_TASK_QUERY_MESSAGES:
            tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="done", limit=10)
            response_text = format_tasks_for_slack(
                tasks,
                title="Completed tasks:",
                empty_text="No completed tasks right now.",
            )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in ALL_TASK_QUERY_MESSAGES:
            pending_tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="pending", limit=10)
            done_tasks = get_tasks_for_lane(user_id=user_id, lane=lane, status="done", limit=10)
            response_text = format_all_tasks_for_slack(pending_tasks, done_tasks)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in CLEAR_TASK_MESSAGES:
            result = clear_tasks_for_lane(user_id=user_id, lane=lane, status="pending")
            deleted_count = get_deleted_count(result)
            response_text = f"Cleared {deleted_count} pending task(s)."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in CLEAR_DONE_TASK_MESSAGES:
            result = clear_tasks_for_lane(user_id=user_id, lane=lane, status="done")
            deleted_count = get_deleted_count(result)
            response_text = f"Cleared {deleted_count} completed task(s)."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        completed_task_text = extract_task_text_for_completion(user_text)
        if completed_task_text:
            result = mark_task_done_for_lane(user_id=user_id, lane=lane, task_text=completed_task_text)
            if get_result_flag(result, "updated"):
                result_task_text = get_result_task_text(result, completed_task_text)
                response_text = f"Marked done: {result_task_text}"
            else:
                response_text = f"I could not find a pending task matching: {completed_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        removed_done_task_text = extract_task_text_for_done_removal(user_text)
        if removed_done_task_text:
            result = remove_task_for_lane(
                user_id=user_id,
                lane=lane,
                task_text=removed_done_task_text,
                status="done",
            )
            if get_result_flag(result, "deleted"):
                result_task_text = get_result_task_text(result, removed_done_task_text)
                response_text = f"Removed completed task: {result_task_text}"
            else:
                response_text = f"I could not find a completed task matching: {removed_done_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        removed_task_text = extract_task_text_for_removal(user_text)
        if removed_task_text:
            result = remove_task_for_lane(
                user_id=user_id,
                lane=lane,
                task_text=removed_task_text,
                status="pending",
            )
            if get_result_flag(result, "deleted"):
                result_task_text = get_result_task_text(result, removed_task_text)
                response_text = f"Removed pending task: {result_task_text}"
            else:
                response_text = f"I could not find a pending task matching: {removed_task_text}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if should_capture_task_from_user_message(user_text):
            task_text = build_task_text_from_user_message(user_text)
            if task_text:
                task_result = add_task_for_lane(
                    user_id=user_id,
                    lane=lane,
                    channel_id=channel_id,
                    session_id=channel_id,
                    source_message=user_text,
                    task_text=task_text,
                    assistant_commitment="Saved as a pending task.",
                    status="pending",
                )
                if isinstance(task_result, dict):
                    result_task_text = task_result.get("task_text", task_text)
                    if task_result.get("deduped"):
                        response_text = f"Already in pending tasks: {result_task_text}"
                    else:
                        response_text = f"Saved to pending tasks: {result_task_text}"
                else:
                    response_text = f"Saved to pending tasks: {task_text}"
            else:
                response_text = "I could not figure out the task text. Please try again."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered.startswith("mode "):
            requested_mode = lowered.replace("mode ", "", 1).strip()

            if requested_mode in VALID_MODES:
                set_mode(user_id, requested_mode)
                if requested_mode == "cmo":
                    response_text = (
                        "CMO mode active.\n"
                        "I’ll think in terms of audience, positioning, offer, "
                        "channel, creative, budget, and measurable next action."
                    )
                elif requested_mode == "stemlab":
                    response_text = (
                        "StemLab mode active.\n"
                        "I’ll think like a music-tech founder, EDM producer, DJ, product strategist, "
                        "and workflow designer. I’ll focus on usable stems, DJ-ready arrangements, "
                        "Ableton workflows, prompt strategy, competitive gaps, MVP definition, "
                        "and practical next actions."
                    )
                elif requested_mode == "product":
                    response_text = (
                        "Product mode active.\n"
                        "I’ll think like a product strategist, founder, operator, and practical builder. "
                        "I’ll focus on user pain, MVP scope, positioning, workflows, monetization, "
                        "test plans, tradeoffs, and the next useful decision."
                    )
                else:
                    response_text = f"Mode set to {requested_mode}."
            else:
                response_text = (
                    "Unknown mode. Available modes: "
                    + ", ".join(sorted(VALID_MODES))
                )

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in MODE_QUERY_MESSAGES:
            current_mode = get_mode(user_id)
            response_text = f"Current mode: {current_mode}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text)
            return {"ok": True}

        if lowered in {"provider", "show provider"}:
            response_text, active_model = build_provider_summary_text()

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        if lowered == "model":
            active_model = get_active_model_for_effective_provider()
            response_text = f"Active model: {active_model}"

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        if lowered in {"status", "show config"}:
            response_text, active_model = build_status_text(user_id, lane)

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        if lowered.startswith("provider "):
            requested_provider = lowered.replace("provider ", "", 1).strip()

            if requested_provider == "default":
                clear_provider_override()
                response_text, active_model = build_provider_summary_text()
                response_text = "Provider override cleared.\n" + response_text
            elif requested_provider in {"openai", "claude"}:
                ok, message = validate_provider_config(requested_provider)
                if not ok:
                    response_text, active_model = build_provider_summary_text()
                    response_text = (
                        f"Cannot switch to {requested_provider}: {message}\n"
                        + response_text
                    )
                else:
                    set_provider_override(requested_provider)
                    response_text, active_model = build_provider_summary_text()
                    response_text = (
                        f"Provider override set to {requested_provider}.\n"
                        + response_text
                    )
            else:
                active_model = get_active_model_for_effective_provider()
                response_text = "Unknown provider. Available options: openai, claude, default."

            post_message(channel_id, response_text)
            log_system_response(user_id, channel_id, user_text, response_text, model=active_model)
            return {"ok": True}

        expanded_user_text = expand_short_followup_message(user_id=user_id, user_text=user_text)

        if should_send_working_message(user_text):
            working_messages = [
                "Got it, working through that now.",
                "Working on this now, I’ll make it practical.",
                "Thinking it through and putting structure around it.",
            ]
            post_message(channel_id, random.choice(working_messages))

        try:
            response_text = generate_reply(user_id=user_id, message=expanded_user_text)
            if not response_text or not response_text.strip():
                raise ValueError("Empty response from generate_reply")
        except Exception as e:
            print(f"[Bishop] generate_reply failed: {str(e)}")
            response_text = (
                "I hit an issue while putting that together. "
                "Send it again and I’ll take another pass."
            )

        post_message(channel_id, response_text)

        try:
            effective_provider = get_effective_provider()
            active_model = get_provider_model(effective_provider) or "not set"

            if response_contains_commitment(response_text):
                task_result = add_task_for_lane(
                    user_id=user_id,
                    lane=lane,
                    channel_id=channel_id,
                    session_id=channel_id,
                    source_message=user_text,
                    task_text=user_text,
                    assistant_commitment=response_text,
                    status="pending",
                )
                if isinstance(task_result, dict) and task_result.get("deduped"):
                    result_task_text = task_result.get("task_text", user_text)
                    print(f"Skipped duplicate commitment task for user {user_id} in {lane}: {result_task_text}")

            if is_stemlab_auto_memory_eligible_command(lowered):
                captured_memories = capture_stemlab_project_memory(
                    user_id=user_id,
                    user_text=user_text,
                    response_text=response_text,
                )
                if captured_memories:
                    print(
                        f"Captured {len(captured_memories)} StemLab project memory item(s) "
                        f"for user {user_id}"
                    )

            log_conversation(
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                session_id=channel_id,
                user_message=user_text,
                assistant_response=response_text,
                memory_used=True,
                mode=get_mode(user_id),
                provider=effective_provider,
                model=active_model,
            )
        except Exception as e:
            print(f"[Bishop] post-processing failed: {str(e)}")

        return {"ok": True}

    except Exception as e:
        print(f"Slack route unexpected error for user {user_id} in channel {channel_id}: {str(e)}")
        response_text = "Sorry, something went wrong while handling that Slack message."
        post_message(channel_id, response_text)
        return {"ok": True}
