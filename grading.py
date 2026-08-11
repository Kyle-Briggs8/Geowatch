"""Intelligence tradecraft grading: NATO Admiralty source codes and ICD 203 confidence.

Source reliability (A–F) comes from a curated table of known outlets; information
credibility (1–6) is assessed per-article by the LLM. The combined two-character
code (e.g. "B2") follows the NATO Admiralty System (AJP-2.1).

Analytic confidence follows ICD 203: derived deterministically from the breadth
and quality of sourcing, never from model self-assessment.
"""

import re
from collections import Counter

# Reliability grades are working defaults for open-source news triage, not an
# authoritative ranking. Wire services and major internationals get B ("usually
# reliable" — A is reserved for fully vetted/controlled sources), state-run or
# heavily partisan outlets get D, unknown outlets get F ("cannot be judged").
_SOURCE_RELIABILITY: dict[str, str] = {
    "reuters": "B",
    "associated press": "B",
    "ap news": "B",
    "afp": "B",
    "agence france-presse": "B",
    "bbc news": "B",
    "bbc": "B",
    "the guardian": "B",
    "the new york times": "B",
    "the washington post": "B",
    "the wall street journal": "B",
    "financial times": "B",
    "bloomberg": "B",
    "the economist": "B",
    "npr": "B",
    "al jazeera english": "C",
    "al jazeera": "C",
    "cnn": "C",
    "abc news": "C",
    "nbc news": "C",
    "cbs news": "C",
    "politico": "C",
    "the hill": "C",
    "axios": "C",
    "newsweek": "C",
    "time": "C",
    "the times of israel": "C",
    "the jerusalem post": "C",
    "kyiv independent": "C",
    "the kyiv independent": "C",
    "ukrinform": "D",
    "tass": "D",
    "rt": "E",
    "sputnik": "E",
    "press tv": "E",
    "xinhua": "D",
    "global times": "E",
    "fox news": "C",
    "daily mail": "D",
    "the sun": "D",
    "new york post": "D",
    "breitbart": "E",
    "euronews": "C",
    "rte": "B",
    "dw": "B",
    "deutsche welle": "B",
    "france 24": "B",
    "sky news": "B",
    "the independent": "C",
    "the telegraph": "C",
    "usa today": "C",
    "cnbc": "C",
    "forbes": "C",
    "nrc": "B",
    "le monde": "B",
    "der spiegel": "B",
    "spiegel online": "B",
    "haaretz": "C",
    "the times of india": "C",
    "times higher education": "C",
    "timeshighereducation": "C",
    "nbcsports": "C",
    "nbc sports": "C",
    "mediaite": "D",
    "slashdot": "D",
    "prnewswire": "D",
    "pr newswire": "D",
    "globe newswire": "D",
    "globenewswire": "D",
    "business wire": "D",
    "freerepublic": "E",
    "biztoc": "E",
}

RELIABILITY_DESC: dict[str, str] = {
    "A": "completely reliable",
    "B": "usually reliable",
    "C": "fairly reliable",
    "D": "not usually reliable",
    "E": "unreliable",
    "F": "reliability cannot be judged",
}

CREDIBILITY_DESC: dict[int, str] = {
    1: "confirmed by independent sources",
    2: "probably true",
    3: "possibly true",
    4: "doubtful",
    5: "improbable",
    6: "truth cannot be judged",
}

# ICD 203 confidence levels with the sourcing rationale template for each.
_CONFIDENCE_ORDER = ["low", "moderate", "high"]


def _normalize_source(source: str) -> str:
    """Normalize an outlet name for table lookup: lowercase, drop parentheticals
    like '(English)', a leading 'www.', and a trailing domain suffix."""
    s = re.sub(r"\s*\(.*?\)\s*$", "", source.strip().lower())
    s = re.sub(r"^www\.", "", s)
    return s


def source_reliability(source: str | None) -> str:
    """Return the Admiralty reliability letter (A–F) for a news outlet name."""
    if not source:
        return "F"
    s = _normalize_source(source)
    if s in _SOURCE_RELIABILITY:
        return _SOURCE_RELIABILITY[s]
    # Retry with a trailing domain suffix removed: "euronews.com" → "euronews"
    s = re.sub(r"\.(com|co\.uk|org|net|co|de|fr|ie|nl|uk)$", "", s)
    return _SOURCE_RELIABILITY.get(s, "F")


def _credibility_digit(analysis: dict | None) -> int:
    """Return the LLM-assessed credibility as a clamped int 1–6 (6 if absent/invalid)."""
    if not analysis:
        return 6
    try:
        digit = int(analysis.get("credibility", 6))
    except (TypeError, ValueError):
        return 6
    return digit if 1 <= digit <= 6 else 6


def grade_event(event: dict) -> str:
    """Return the combined Admiralty code (e.g. 'B2') for one analyzed event."""
    letter = source_reliability(event.get("article", {}).get("source"))
    digit = _credibility_digit(event.get("analysis"))
    return f"{letter}{digit}"


def grade_post(x_event: dict) -> str:
    """Return the Admiralty code for a social post: reliability is always 'F'
    (individual account reliability cannot be judged); credibility per-post."""
    return f"F{_credibility_digit(x_event.get('analysis'))}"


def describe_grade(grade: str) -> str:
    """Return a human-readable gloss for a two-character Admiralty code."""
    if len(grade) != 2:
        return ""
    rel = RELIABILITY_DESC.get(grade[0].upper(), "")
    try:
        cred = CREDIBILITY_DESC.get(int(grade[1]), "")
    except ValueError:
        cred = ""
    if rel and cred:
        return f"{rel} / {cred}"
    return rel or cred


def assess_confidence(events: list[dict]) -> tuple[str, str]:
    """Return (ICD 203 confidence level, sourcing rationale) for a set of events.

    Confidence is a function of corroboration: how many independently analyzed
    reports exist, how many distinct outlets they come from, and what share of
    those outlets grade C ('fairly reliable') or better on the Admiralty scale.
    """
    analyzed = [e for e in events if e.get("analysis")]
    sources = {
        (e.get("article", {}).get("source") or "").strip().lower()
        for e in analyzed
        if e.get("article", {}).get("source")
    }
    graded_ok = sum(1 for s in sources if source_reliability(s) <= "C")
    ok_share = graded_ok / len(sources) if sources else 0.0

    if len(analyzed) >= 10 and len(sources) >= 5 and ok_share >= 0.5:
        level = "high"
    elif len(analyzed) >= 5 and len(sources) >= 3 and ok_share >= 0.25:
        level = "moderate"
    else:
        level = "low"

    rationale = (
        f"{len(analyzed)} independently analyzed reports from "
        f"{len(sources)} distinct outlets; "
        f"{graded_ok} outlet(s) graded C (fairly reliable) or better on the Admiralty scale"
    )
    return level, rationale


def grade_distribution(events: list[dict]) -> Counter:
    """Return a Counter of Admiralty codes across all analyzed events."""
    return Counter(grade_event(e) for e in events if e.get("analysis"))
