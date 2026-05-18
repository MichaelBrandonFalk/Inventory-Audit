"""Endpoint requirements for Inventory Audit."""

from __future__ import annotations

APP_NAME = "Inventory Audit"
APP_VERSION = "1.2"

ART_FIELDS = [
    "ca_16x9",
    "ca_1x1",
    "ca_4x3",
    "ca_2x3",
    "ca_3x4",
    "bg_16x9",
    "bg_2x3",
    "tt_9x5",
]

ENDPOINT_ORDER = ["Axinom", "Amazon", "Roku", "Frndly", "T+", "YouTube"]

# These rules are backed into v1 from the supplied "Streamlined Logic For Art Req
# in Rally Publishes (9).xlsx" matrix. Optional sheet entries are intentionally
# not required.
ART_REQUIREMENTS: dict[str, dict[str, set[str]]] = {
    "Axinom": {
        "Movie": set(),
        "Series": set(),
        "Season": set(),
        "Episode": set(),
    },
    "Amazon": {
        "Movie": {"ca_16x9", "ca_2x3", "ca_3x4", "bg_16x9", "tt_9x5"},
        "Season": {"ca_16x9", "ca_4x3", "ca_2x3", "bg_16x9", "tt_9x5"},
        "Episode": {"bg_16x9"},
    },
    "Roku": {
        "Movie": {"ca_16x9", "ca_2x3", "bg_16x9"},
        "Series": {"ca_16x9", "ca_2x3", "bg_16x9"},
        "Episode": {"bg_16x9"},
    },
    "Frndly": {
        "Movie": {"ca_16x9", "ca_2x3"},
        "Series": {"ca_16x9", "ca_2x3"},
        "Episode": {"bg_16x9"},
    },
    "T+": {
        "Movie": {"ca_16x9", "ca_2x3"},
        "Season": {"ca_16x9", "ca_2x3"},
        "Episode": {"bg_16x9"},
    },
    "YouTube": {
        "Movie": {"ca_16x9", "ca_2x3", "bg_16x9", "tt_9x5"},
        "Series": {"ca_16x9", "ca_1x1", "bg_16x9", "tt_9x5"},
        "Episode": {"bg_16x9"},
    },
}


def get_art_requirements(endpoint: str, content_type: str) -> set[str]:
    """Return required art fields for an endpoint and row type.

    Some endpoints in the v1 matrix define Series but not Season. Season rows
    fall back to Series rules in those cases because the app is expected to
    audit Season rows for every endpoint.
    """

    endpoint_rules = ART_REQUIREMENTS.get(endpoint, {})
    if content_type in endpoint_rules:
        return set(endpoint_rules[content_type])
    if content_type == "Season" and "Series" in endpoint_rules:
        return set(endpoint_rules["Series"])
    return set()


def get_media_requirements(endpoint: str, content_type: str) -> set[str]:
    """Return required media/caption fields for an endpoint and row type."""

    if content_type not in {"Movie", "Episode"}:
        return set()

    requirements = {"mov"}
    if endpoint == "Amazon":
        requirements.add("srt")
    else:
        requirements.add("vtt")
    return requirements
