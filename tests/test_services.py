import pytest

from app.services import chat_service, mode_service, task_service


STEMLAB_TEMPLATE_MARKERS = [
    "One-page MVP spec",
    "Product name / working title",
    "User flow",
    "Entry point",
    "Feature priority stack",
    "v0 must-have",
    "Competitor gap analysis",
    "Where they fall short for EDM/DJs/producers",
    "DJ/producer test plan",
    "Pricing signal",
]


PRODUCT_BRAIN_MARKERS = [
    "Product Brain v1",
    "productized service",
    "Product thesis",
    "User testing plan",
    "Monetization options",
    "Product roadmap",
    "Build / buy / partner recommendation",
    "Decision memo",
]


STEMLAB_PRODUCT_THESIS = (
    "StemLab is Matt’s AI product idea for DJs, EDM producers, remixers, and creators. "
    "It is not just 'Suno for EDM.' "
    "Suno-style products are strong at generating full songs, vocals, lyrics, beats, and musical ideas. "
    "StemLab's wedge is useful, producer-ready stems and workflows: controllable EDM-specific building blocks "
    "that can be brought into Ableton. "
    "Think in terms of BPM, key, warping, clips, Session View, Arrangement View, clean audio, stems, loops, scenes, "
    "drums, bass, vocals, hooks, synths, FX, MIDI when possible, dry/wet versions, loop points, arrangement sections, "
    "and drag-and-drop exportable material. "
    "The MVP should validate workflow before trying to train a giant model. "
    "If a StemLab question requires research, say what needs to be researched instead of pretending technical certainty."
)


NO_WEAK_ENDING_MARKERS = [
    "Do not end responses with weak permission-based offers",
    "If you want, I can...",
    "If you’d like...",
    "Let me know if...",
    "Would you like me to...",
    "Prefer a concrete next action",
    "Next move:",
    "or no follow-up line",
]

EXPLICIT_TOPIC_MARKERS = [
    "the current user message is the source of truth for topic",
    "Active focus is only a default when the message is ambiguous",
    "Mode controls thinking style, not topic ownership",
    "If Matt explicitly names a brand, project, campaign, domain, or subject, answer that subject",
    "Do not redirect RTG, Rooms To Go, retail, TV, social, or campaign prompts into StemLab",
]

CREATIVE_TASTE_FILTER_LABELS = [
    "Safe",
    "Solid",
    "Strong",
    "Brave",
    "Too generic",
    "Too expensive",
    "Too hard to produce",
    "Too social-only",
    "Too TV-only",
]


@pytest.fixture(autouse=True)
def use_temp_task_db(tmp_path, monkeypatch):
    test_db_path = tmp_path / "bishop_memory_test.db"
    monkeypatch.setattr(task_service, "DB_PATH", test_db_path)


def test_response_contains_commitment_true():
    assert chat_service.response_contains_commitment("On it. I'll proceed with that.") is True


def test_response_contains_commitment_false():
    assert chat_service.response_contains_commitment("Here is the completed draft.") is False


def test_generate_reply_uses_effective_provider(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "work")
    monkeypatch.setattr(chat_service, "generate_memory_context", lambda user_id, message: "Ben is Matt's son")
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "- Do 1, 2, and 3")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "claude")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["provider"] = provider
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "test reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(user_id="U123", message="Tell me about Ben")

    assert result == "test reply"
    assert captured["provider"] == "claude"
    assert "work mode" in captured["system_prompt"]
    assert "Do 1, 2, and 3" in captured["user_prompt"]
    assert "Ben is Matt's son" in captured["user_prompt"]
    assert "Tell me about Ben" in captured["user_prompt"]


def test_base_system_prompt_includes_no_weak_ending_instruction():
    prompt = chat_service.get_base_system_prompt()

    for marker in NO_WEAK_ENDING_MARKERS:
        assert marker in prompt, f"missing no-weak-ending marker: {marker}"


def test_product_mode_inherits_no_weak_ending_instruction():
    prompt = chat_service.get_mode_system_prompt("product")

    for marker in NO_WEAK_ENDING_MARKERS:
        assert marker in prompt, f"Product prompt missing no-weak-ending marker: {marker}"


def test_stemlab_mode_inherits_no_weak_ending_instruction():
    prompt = chat_service.get_mode_system_prompt("stemlab")

    for marker in NO_WEAK_ENDING_MARKERS:
        assert marker in prompt, f"StemLab prompt missing no-weak-ending marker: {marker}"


def test_cmo_mode_inherits_no_weak_ending_instruction():
    prompt = chat_service.get_mode_system_prompt("cmo")

    for marker in NO_WEAK_ENDING_MARKERS:
        assert marker in prompt, f"CMO prompt missing no-weak-ending marker: {marker}"


def test_website_mode_inherits_no_weak_ending_instruction():
    prompt = chat_service.get_mode_system_prompt("website")

    for marker in NO_WEAK_ENDING_MARKERS:
        assert marker in prompt, f"Website prompt missing no-weak-ending marker: {marker}"


def test_get_mode_system_prompt_cmo_contains_lens_and_keywords():
    prompt = chat_service.get_mode_system_prompt("cmo")

    assert "BISHOP MODE: CMO + EXPERT CREATIVE TEAM" in prompt
    for keyword in [
        "audience",
        "positioning",
        "offer",
        "channel",
        "creative",
        "budget",
        "measurable next action",
    ]:
        assert keyword in prompt, f"missing CMO lens keyword: {keyword}"

    assert "Do not over-format unless the user asks for a plan." in prompt


def test_get_mode_system_prompt_cmo_requires_diagnosis_before_ideas():
    prompt = chat_service.get_mode_system_prompt("cmo")

    for marker in [
        "Diagnose the real business or creative constraint before concepting",
        "CMO Diagnosis",
        "Primary Constraint",
        "Campaign Spine",
        "Performance Creative Layer",
        "Production Reality Check",
        "hook, pattern interrupt, story/proof, payoff, offer, and CTA",
    ]:
        assert marker in prompt, f"missing CMO diagnosis marker: {marker}"


def test_creative_mode_prompt_includes_explicit_topic_overrides_focus_rule():
    prompt = chat_service.get_mode_system_prompt("creative")

    for marker in EXPLICIT_TOPIC_MARKERS:
        assert marker in prompt, f"Creative prompt missing topic rule marker: {marker}"


def test_cmo_mode_prompt_includes_explicit_topic_overrides_focus_rule():
    prompt = chat_service.get_mode_system_prompt("cmo")

    for marker in EXPLICIT_TOPIC_MARKERS:
        assert marker in prompt, f"CMO prompt missing topic rule marker: {marker}"


def test_creative_mode_prompt_includes_taste_filter_labels():
    prompt = chat_service.get_mode_system_prompt("creative")

    assert "Creative Taste Filter" in prompt
    assert "polished-but-average ideas" in prompt
    assert "weak naming" in prompt
    assert "Declare Your Home Independents" in prompt
    for label in CREATIVE_TASTE_FILTER_LABELS:
        assert label in prompt, f"Creative prompt missing taste filter label: {label}"


def test_cmo_mode_prompt_includes_taste_filter_labels():
    prompt = chat_service.get_mode_system_prompt("cmo")

    assert "Creative Taste Filter" in prompt
    assert "weak territories" in prompt
    for label in CREATIVE_TASTE_FILTER_LABELS:
        assert label in prompt, f"CMO prompt missing taste filter label: {label}"


def test_get_mode_system_prompt_stemlab_contains_music_product_lens():
    prompt = chat_service.get_mode_system_prompt("stemlab")

    assert "StemLab mode" in prompt
    for keyword in [
        "usable stem generation",
        "DJ-ready arrangements",
        "Ableton workflows",
        "Suno and Udio style prompting",
        "MVP planning",
        "monetization strategy",
        "practical next actions",
    ]:
        assert keyword in prompt, f"missing StemLab lens keyword: {keyword}"


def test_product_is_in_valid_modes():
    assert "product" in mode_service.VALID_MODES


def test_creative_is_in_valid_modes():
    assert "creative" in mode_service.VALID_MODES


def test_mode_aliases_normalize_to_creative():
    assert mode_service.normalize_mode("concept") == "creative"
    assert mode_service.normalize_mode("concept lab") == "creative"
    assert mode_service.normalize_mode("performance creative") == "creative"


def test_get_mode_system_prompt_creative_uses_cmo_creative_brain():
    prompt = chat_service.get_mode_system_prompt("creative")

    for marker in [
        "Creative mode",
        "Diagnose before ideas",
        "TV ideas",
        "paid social concepts",
        "AI video prompt concepts",
        "CMO Brain v2",
        "CMO + Expert Creative Team Operating Role",
        "Primary Constraint",
    ]:
        assert marker in prompt, f"missing Creative mode marker: {marker}"


def test_get_mode_system_prompt_product_contains_product_founder_lens():
    prompt = chat_service.get_mode_system_prompt("product")

    assert "Product mode" in prompt
    for keyword in [
        "product strategist",
        "founder",
        "user pain",
        "ICP and target user",
        "MVP definition",
        "feature prioritization",
        "customer discovery",
        "user testing",
        "monetization strategy",
        "build-versus-buy thinking",
        "fastest test of demand",
    ]:
        assert keyword in prompt, f"missing Product lens keyword: {keyword}"


def test_get_mode_system_prompt_default_does_not_contain_cmo_lens():
    prompt = chat_service.get_mode_system_prompt("default")

    assert "CMO mode" not in prompt
    assert "audience, positioning, offer" not in prompt
    assert "StemLab mode" not in prompt


def test_generate_reply_in_cmo_mode_passes_cmo_lens_to_model(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "cmo")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "strategic reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(
        user_id="U123",
        message="How should we launch the new event series?",
    )

    assert result == "strategic reply"
    assert "BISHOP MODE: CMO + EXPERT CREATIVE TEAM" in captured["system_prompt"]
    assert "audience" in captured["system_prompt"]
    assert "positioning" in captured["system_prompt"]
    assert "measurable next action" in captured["system_prompt"]
    assert "How should we launch the new event series?" in captured["user_prompt"]


def test_generate_reply_in_creative_mode_passes_creative_lens_to_model(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "creative")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "creative reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(
        user_id="U123",
        message="Concept TV and social ideas for July 4.",
    )

    assert result == "creative reply"
    assert "Creative mode" in captured["system_prompt"]
    assert "Diagnose before ideas" in captured["system_prompt"]
    assert "CMO Brain v2" in captured["system_prompt"]
    assert "Concept TV and social ideas for July 4." in captured["user_prompt"]


def test_generate_reply_in_stemlab_mode_passes_stemlab_lens_to_model(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "stemlab")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "music product reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(
        user_id="U123",
        message="How should StemLab generate DJ-ready stems?",
    )

    assert result == "music product reply"
    assert "StemLab mode" in captured["system_prompt"]
    assert "usable stem generation" in captured["system_prompt"]
    assert "DJ-ready arrangements" in captured["system_prompt"]
    assert "Ableton" in captured["system_prompt"]
    assert "How should StemLab generate DJ-ready stems?" in captured["user_prompt"]


def test_generate_reply_in_product_mode_includes_stemlab_context_when_mentioned(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "product")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return "product reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    result = chat_service.generate_reply(
        user_id="U123",
        message="Build a feature priority stack from v0 to v2 for StemLab.",
    )

    assert result == "product reply"
    assert "Product context:" in captured["user_prompt"]
    assert STEMLAB_PRODUCT_THESIS in captured["user_prompt"]


def test_generate_reply_in_stemlab_mode_includes_stemlab_product_thesis(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "stemlab")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["user_prompt"] = user_prompt
        return "stemlab reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    chat_service.generate_reply(user_id="U123", message="What should we test next?")

    assert "Product context:" in captured["user_prompt"]
    assert STEMLAB_PRODUCT_THESIS in captured["user_prompt"]


def test_generate_reply_in_default_mode_only_includes_stemlab_context_when_mentioned(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = []

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured.append(user_prompt)
        return "default reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    chat_service.generate_reply(user_id="U123", message="What should I build this week?")
    chat_service.generate_reply(user_id="U123", message="What should I build for StemLab this week?")

    assert STEMLAB_PRODUCT_THESIS not in captured[0]
    assert "Product context:" not in captured[0]
    assert STEMLAB_PRODUCT_THESIS in captured[1]
    assert "Product context:" in captured[1]


def test_generate_reply_in_cmo_mode_only_includes_stemlab_context_when_mentioned(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "cmo")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = []

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured.append(user_prompt)
        return "cmo reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    chat_service.generate_reply(user_id="U123", message="How should we launch a product?")
    chat_service.generate_reply(user_id="U123", message="How should we launch StemLab?")

    assert STEMLAB_PRODUCT_THESIS not in captured[0]
    assert "Product context:" not in captured[0]
    assert STEMLAB_PRODUCT_THESIS in captured[1]
    assert "Product context:" in captured[1]


def test_generate_reply_in_default_mode_does_not_include_cmo_lens(monkeypatch):
    monkeypatch.setattr(chat_service, "get_mode", lambda user_id: "default")
    monkeypatch.setattr(
        chat_service, "generate_memory_context", lambda user_id, message: "No relevant memory found."
    )
    monkeypatch.setattr(chat_service, "generate_task_context", lambda user_id: "No pending tasks.")
    monkeypatch.setattr(chat_service, "get_effective_provider", lambda: "openai")

    captured = {}

    def fake_generate_text(provider, system_prompt, user_prompt):
        captured["system_prompt"] = system_prompt
        return "default reply"

    monkeypatch.setattr(chat_service, "generate_text", fake_generate_text)

    chat_service.generate_reply(user_id="U123", message="What's a good dinner idea?")

    assert "CMO mode" not in captured["system_prompt"]
    assert "audience, positioning, offer" not in captured["system_prompt"]
    assert "StemLab mode" not in captured["system_prompt"]


def test_cmo_mode_system_prompt_includes_cmo_brain():
    prompt = chat_service.get_mode_system_prompt("cmo")

    assert "CMO Brain v2" in prompt
    assert "Rooms To Go" in prompt
    assert "coordinated room package" in prompt


def test_stemlab_mode_system_prompt_includes_stemlab_brain():
    prompt = chat_service.get_mode_system_prompt("stemlab")

    assert "StemLab Brain v1" in prompt
    assert "Moises" in prompt
    assert "Rekordbox stems" in prompt
    assert "Core recommendation" in prompt


def test_stemlab_mode_system_prompt_includes_product_development_templates():
    prompt = chat_service.get_mode_system_prompt("stemlab")

    for marker in STEMLAB_TEMPLATE_MARKERS:
        assert marker in prompt, f"missing StemLab template marker: {marker}"


def test_product_mode_system_prompt_includes_product_brain():
    prompt = chat_service.get_mode_system_prompt("product")

    for marker in PRODUCT_BRAIN_MARKERS:
        assert marker in prompt, f"missing Product brain marker: {marker}"


def test_default_mode_system_prompt_does_not_include_stemlab_template_guidance():
    prompt = chat_service.get_mode_system_prompt("default")

    for marker in STEMLAB_TEMPLATE_MARKERS:
        assert marker not in prompt, f"default prompt leaked StemLab template marker: {marker}"


def test_default_mode_system_prompt_does_not_include_product_brain_guidance():
    prompt = chat_service.get_mode_system_prompt("default")

    for marker in PRODUCT_BRAIN_MARKERS:
        assert marker not in prompt, f"default prompt leaked Product brain marker: {marker}"


def test_cmo_mode_system_prompt_does_not_include_stemlab_template_guidance():
    prompt = chat_service.get_mode_system_prompt("cmo")

    for marker in STEMLAB_TEMPLATE_MARKERS:
        assert marker not in prompt, f"CMO prompt leaked StemLab template marker: {marker}"


def test_cmo_mode_system_prompt_does_not_include_product_brain_guidance():
    prompt = chat_service.get_mode_system_prompt("cmo")

    for marker in PRODUCT_BRAIN_MARKERS:
        assert marker not in prompt, f"CMO prompt leaked Product brain marker: {marker}"


def test_stemlab_mode_system_prompt_does_not_include_product_brain_guidance():
    prompt = chat_service.get_mode_system_prompt("stemlab")

    for marker in PRODUCT_BRAIN_MARKERS:
        assert marker not in prompt, f"StemLab prompt leaked Product brain marker: {marker}"


def test_default_mode_system_prompt_does_not_include_cmo_brain():
    prompt = chat_service.get_mode_system_prompt("default")

    assert "CMO Brain v2" not in prompt
    assert "StemLab Brain v1" not in prompt


def test_cmo_mode_system_prompt_resilient_to_missing_brain_file(monkeypatch):
    monkeypatch.setattr(chat_service, "load_mode_brain", lambda mode: "")

    prompt = chat_service.get_mode_system_prompt("cmo")

    assert "BISHOP MODE: CMO + EXPERT CREATIVE TEAM" in prompt
    assert "CMO Brain v2" not in prompt


def test_stemlab_mode_system_prompt_resilient_to_missing_brain_file(monkeypatch):
    monkeypatch.setattr(chat_service, "load_mode_brain", lambda mode: "")

    prompt = chat_service.get_mode_system_prompt("stemlab")

    assert "StemLab mode" in prompt
    assert "StemLab Brain v1" not in prompt


def test_cmo_mode_system_prompt_includes_slack_concision_shape():
    prompt = chat_service.get_mode_system_prompt("cmo")

    for marker in [
        "Recommendation:",
        "Why:",
        "Next move:",
        "2 to 3 bullets",
        "plan, strategy, rollout, deck, full breakdown, outline, or deep dive",
        "CMO Diagnosis",
        "Primary Constraint",
    ]:
        assert marker in prompt, f"missing CMO Slack concision marker: {marker}"


def test_default_mode_system_prompt_still_excludes_cmo_brain():
    prompt = chat_service.get_mode_system_prompt("default")

    assert "CMO Brain v2" not in prompt
    assert "StemLab Brain v1" not in prompt


def test_looks_like_explicit_task_command():
    assert task_service.looks_like_explicit_task_command("add task review the deck") is True
    assert task_service.looks_like_explicit_task_command("save task call John") is True
    assert task_service.looks_like_explicit_task_command("add this to my list pick up dry cleaning") is True
    assert task_service.looks_like_explicit_task_command("hello bishop") is False


def test_extract_task_text_from_explicit_command():
    assert task_service.extract_task_text_from_explicit_command("add task review the deck") == "review the deck"
    assert task_service.extract_task_text_from_explicit_command("save task call John") == "call John"
    assert (
        task_service.extract_task_text_from_explicit_command(
            "add this to my list pick up dry cleaning"
        )
        == "pick up dry cleaning"
    )


def test_looks_like_reminder_request():
    assert task_service.looks_like_reminder_request("remind me tomorrow to review the deck") is True
    assert task_service.looks_like_reminder_request("please remind me next week to send the invoice") is True
    assert task_service.looks_like_reminder_request("could you remind me to call John") is True
    assert task_service.looks_like_reminder_request("what mode are you in") is False


def test_extract_task_text_from_reminder_request():
    assert (
        task_service.extract_task_text_from_reminder_request(
            "remind me tomorrow to review the deck"
        )
        == "review the deck"
    )
    assert (
        task_service.extract_task_text_from_reminder_request(
            "please remind me next week to send the invoice"
        )
        == "send the invoice"
    )
    assert (
        task_service.extract_task_text_from_reminder_request(
            "could you remind me to call John"
        )
        == "call John"
    )


def test_should_capture_task_from_user_message():
    assert task_service.should_capture_task_from_user_message("add task review the deck") is True
    assert task_service.should_capture_task_from_user_message("remind me tomorrow to review the deck") is True
    assert task_service.should_capture_task_from_user_message("hello bishop") is False


def test_build_task_text_from_user_message():
    assert task_service.build_task_text_from_user_message("add task review the deck") == "review the deck"
    assert (
        task_service.build_task_text_from_user_message("remind me tomorrow to review the deck")
        == "review the deck"
    )


def test_add_task_rejects_empty_task_text():
    with pytest.raises(ValueError):
        task_service.add_task(
            user_id="U123",
            source_message="add task",
            task_text="",
            assistant_commitment="Saved as a task.",
        )


def test_add_task_creates_pending_task():
    result = task_service.add_task(
        user_id="U123",
        channel_id="C123",
        session_id="C123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    assert result["created"] is True
    assert result["deduped"] is False
    assert result["status"] == "pending"
    assert result["task_text"] == "review the deck"

    tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(tasks) == 1
    assert tasks[0]["task_text"] == "review the deck"


def test_add_task_dedupes_matching_pending_task():
    first = task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    second = task_service.add_task(
        user_id="U123",
        source_message="add task Review the deck!!!",
        task_text="Review the deck!!!",
        assistant_commitment="Saved as a pending task.",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["deduped"] is True
    assert second["task_text"] == "review the deck"

    tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(tasks) == 1


def test_mark_task_done_marks_matching_pending_task_done():
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.mark_task_done(
        user_id="U123",
        task_text="Send the invoice!!!",
    )

    assert result["updated"] is True
    assert result["task"]["task_text"] == "send the invoice"
    assert result["task"]["status"] == "done"

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    done_tasks = task_service.get_tasks(user_id="U123", status="done")

    assert pending_tasks == []
    assert len(done_tasks) == 1
    assert done_tasks[0]["task_text"] == "send the invoice"
    assert done_tasks[0]["status"] == "done"


def test_mark_task_done_returns_false_when_no_pending_match():
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.mark_task_done(
        user_id="U123",
        task_text="review the deck",
    )

    assert result["updated"] is False
    assert result["task"] is None

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(pending_tasks) == 1
    assert pending_tasks[0]["task_text"] == "send the invoice"


def test_remove_task_deletes_matching_pending_task():
    task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.remove_task(
        user_id="U123",
        task_text="Review the deck!!!",
        status="pending",
    )

    assert result["deleted"] is True
    assert result["task"]["task_text"] == "review the deck"
    assert result["task"]["status"] == "pending"

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert pending_tasks == []


def test_remove_task_returns_false_when_no_pending_match():
    task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.remove_task(
        user_id="U123",
        task_text="send the invoice",
        status="pending",
    )

    assert result["deleted"] is False
    assert result["task"] is None

    pending_tasks = task_service.get_tasks(user_id="U123", status="pending")
    assert len(pending_tasks) == 1
    assert pending_tasks[0]["task_text"] == "review the deck"


def test_remove_task_can_delete_done_task_when_status_is_done():
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.mark_task_done(user_id="U123", task_text="send the invoice")

    result = task_service.remove_task(
        user_id="U123",
        task_text="send the invoice",
        status="done",
    )

    assert result["deleted"] is True
    assert result["task"]["task_text"] == "send the invoice"
    assert result["task"]["status"] == "done"

    done_tasks = task_service.get_tasks(user_id="U123", status="done")
    assert done_tasks == []


def test_clear_tasks_deletes_only_requested_status():
    task_service.add_task(
        user_id="U123",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.mark_task_done(user_id="U123", task_text="send the invoice")

    result = task_service.clear_tasks(user_id="U123", status="pending")

    assert result["deleted"] == 1
    assert task_service.get_tasks(user_id="U123", status="pending") == []

    done_tasks = task_service.get_tasks(user_id="U123", status="done")
    assert len(done_tasks) == 1
    assert done_tasks[0]["task_text"] == "send the invoice"


def test_add_task_same_text_can_exist_in_multiple_lanes():
    first = task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    second = task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    assert first["created"] is True
    assert second["created"] is True
    assert first["deduped"] is False
    assert second["deduped"] is False

    work_tasks = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_tasks = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert len(work_tasks) == 1
    assert len(dj_tasks) == 1
    assert work_tasks[0]["task_text"] == "review the deck"
    assert dj_tasks[0]["task_text"] == "review the deck"


def test_add_task_dedupes_only_within_same_lane():
    first = task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    second = task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task Review the deck!!!",
        task_text="Review the deck!!!",
        assistant_commitment="Saved as a pending task.",
    )

    third = task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert second["deduped"] is True
    assert third["created"] is True
    assert third["deduped"] is False

    work_tasks = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_tasks = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert len(work_tasks) == 1
    assert len(dj_tasks) == 1


def test_mark_task_done_only_updates_matching_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.mark_task_done(
        user_id="U123",
        lane="work",
        task_text="Send the invoice!!!",
    )

    assert result["updated"] is True
    assert result["task"]["task_text"] == "send the invoice"
    assert result["task"]["status"] == "done"

    work_pending = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    work_done = task_service.get_tasks(user_id="U123", lane="work", status="done")
    dj_pending = task_service.get_tasks(user_id="U123", lane="dj", status="pending")
    dj_done = task_service.get_tasks(user_id="U123", lane="dj", status="done")

    assert work_pending == []
    assert len(work_done) == 1
    assert len(dj_pending) == 1
    assert dj_done == []


def test_remove_task_only_deletes_matching_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.remove_task(
        user_id="U123",
        lane="work",
        task_text="Review the deck!!!",
        status="pending",
    )

    assert result["deleted"] is True
    assert result["task"]["task_text"] == "review the deck"

    work_pending = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_pending = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert work_pending == []
    assert len(dj_pending) == 1
    assert dj_pending[0]["task_text"] == "review the deck"


def test_clear_tasks_only_clears_requested_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    result = task_service.clear_tasks(user_id="U123", lane="work", status="pending")

    assert result["deleted"] == 1

    work_pending = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_pending = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert work_pending == []
    assert len(dj_pending) == 1
    assert dj_pending[0]["task_text"] == "send the invoice"


def test_get_tasks_returns_only_requested_lane():
    task_service.add_task(
        user_id="U123",
        lane="work",
        source_message="add task review the deck",
        task_text="review the deck",
        assistant_commitment="Saved as a pending task.",
    )
    task_service.add_task(
        user_id="U123",
        lane="dj",
        source_message="add task send the invoice",
        task_text="send the invoice",
        assistant_commitment="Saved as a pending task.",
    )

    work_tasks = task_service.get_tasks(user_id="U123", lane="work", status="pending")
    dj_tasks = task_service.get_tasks(user_id="U123", lane="dj", status="pending")

    assert len(work_tasks) == 1
    assert len(dj_tasks) == 1
    assert work_tasks[0]["task_text"] == "review the deck"
    assert dj_tasks[0]["task_text"] == "send the invoice"
