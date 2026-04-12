import json
from pathlib import Path
from typing import Dict, Optional

BASE_DIR = Path(__file__).resolve().parents[1]
PROFILE_PATH = BASE_DIR / "data" / "user_profiles.json"


def _load_profiles() -> Dict[str, dict]:
    if not PROFILE_PATH.exists():
        return {}

    try:
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    if not isinstance(data, dict):
        return {}

    normalized = {}
    for slack_user_id, profile in data.items():
        if not isinstance(slack_user_id, str) or not slack_user_id.strip():
            continue
        if not isinstance(profile, dict):
            continue

        key = slack_user_id.strip()
        normalized[key] = {
            "user_id": str(profile.get("user_id") or key).strip() or key,
            "display_name": str(profile.get("display_name") or "").strip(),
            "role": str(profile.get("role") or "").strip(),
        }

    return normalized


def get_profile_by_slack_user_id(slack_user_id: str) -> Optional[dict]:
    if not isinstance(slack_user_id, str) or not slack_user_id.strip():
        return None

    profiles = _load_profiles()
    return profiles.get(slack_user_id.strip())


def get_profile_by_bishop_user_id(user_id: str) -> Optional[dict]:
    if not isinstance(user_id, str) or not user_id.strip():
        return None

    normalized_user_id = user_id.strip()
    profiles = _load_profiles()

    for profile in profiles.values():
        if not isinstance(profile, dict):
            continue
        profile_user_id = str(profile.get("user_id") or "").strip()
        if profile_user_id == normalized_user_id:
            return profile

    return None


def resolve_bishop_user_id(slack_user_id: str) -> str:
    """
    Maps a Slack user ID to Bishop's internal user identity.

    Current behavior:
    - If a profile exists, return profile["user_id"]
    - If not, return the original Slack user ID

    This keeps the system backward compatible while allowing readable
    identities like matt, carmen, and ben.
    """
    if not isinstance(slack_user_id, str) or not slack_user_id.strip():
        return ""

    profile = get_profile_by_slack_user_id(slack_user_id)
    if not profile:
        return slack_user_id.strip()

    resolved_user_id = str(profile.get("user_id") or "").strip()
    if resolved_user_id:
        return resolved_user_id

    return slack_user_id.strip()


def get_display_name(slack_user_id: str) -> str:
    """
    Returns a friendly display name for a Slack user ID.

    Fallback:
    - display_name from profile
    - resolved Bishop user_id
    - original Slack user ID
    """
    if not isinstance(slack_user_id, str) or not slack_user_id.strip():
        return ""

    profile = get_profile_by_slack_user_id(slack_user_id)
    if not profile:
        return slack_user_id.strip()

    display_name = str(profile.get("display_name") or "").strip()
    if display_name:
        return display_name

    resolved_user_id = str(profile.get("user_id") or "").strip()
    if resolved_user_id:
        return resolved_user_id

    return slack_user_id.strip()


def get_display_name_for_bishop_user_id(user_id: str) -> str:
    """
    Returns a friendly display name for a stored Bishop user_id.

    Fallback:
    - display_name from matching profile
    - original Bishop user_id
    """
    if not isinstance(user_id, str) or not user_id.strip():
        return ""

    normalized_user_id = user_id.strip()
    profile = get_profile_by_bishop_user_id(normalized_user_id)
    if not profile:
        return normalized_user_id

    display_name = str(profile.get("display_name") or "").strip()
    if display_name:
        return display_name


