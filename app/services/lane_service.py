import time
from typing import Callable, Dict, Optional

VALID_LANES = {
    "matt",
    "carmen",
    "ben",
    "family",
    "dj",
    "creative",
    "work",
}

CHANNEL_TO_LANE: Dict[str, str] = {
    "matt": "matt",
    "carmen": "carmen",
    "ben": "ben",
    "family": "family",
    "dj": "dj",
    "music": "dj",
    "creative": "creative",
    "work": "work",
}

LANE_DEFAULT_VISIBILITY: Dict[str, str] = {
    "matt": "private",
    "carmen": "private",
    "ben": "private",
    "family": "shared",
    "dj": "private",
    "creative": "private",
    "work": "private",
}

CHANNEL_NAME_CACHE: Dict[str, Dict[str, float | str]] = {}
CHANNEL_NAME_CACHE_TTL_SECONDS = 300


def normalize_channel_name(channel_name: str) -> str:
    normalized = (channel_name or "").strip().lower()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    return normalized


def get_cached_channel_name(channel_id: str) -> Optional[str]:
    item = CHANNEL_NAME_CACHE.get(channel_id)
    if not item:
        return None

    cached_at = float(item["cached_at"])
    if time.time() - cached_at > CHANNEL_NAME_CACHE_TTL_SECONDS:
        CHANNEL_NAME_CACHE.pop(channel_id, None)
        return None

    return str(item["channel_name"])


def set_cached_channel_name(channel_id: str, channel_name: str) -> None:
    CHANNEL_NAME_CACHE[channel_id] = {
        "channel_name": normalize_channel_name(channel_name),
        "cached_at": time.time(),
    }


def get_channel_name(
    channel_id: str,
    resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    cached_name = get_cached_channel_name(channel_id)
    if cached_name:
        return cached_name

    if resolver:
        try:
            resolved_name = resolver(channel_id)
            if resolved_name:
                normalized = normalize_channel_name(resolved_name)
                set_cached_channel_name(channel_id, normalized)
                return normalized
        except Exception:
            pass

    fallback = normalize_channel_name(channel_id)
    return fallback


def get_lane_from_channel(
    channel_id: str,
    resolver: Optional[Callable[[str], Optional[str]]] = None,
) -> str:
    channel_name = get_channel_name(channel_id, resolver=resolver)

    exact_match = CHANNEL_TO_LANE.get(channel_name)
    if exact_match:
        return exact_match

    for key, lane in CHANNEL_TO_LANE.items():
        if key in channel_name:
            return lane

    return "matt"


def get_default_visibility_for_lane(lane: str) -> str:
    return LANE_DEFAULT_VISIBILITY.get(lane, "private")
