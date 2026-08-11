import json
import os
import sys
import time

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_SYSTEM_PROMPT = """You are an intelligence analyst. Given a news article, extract the following in valid JSON only.
No preamble, no markdown, just raw JSON.

{
  "relevant": "true/false — is the article primarily about events in, or directly concerning, the stated location of interest? News round-ups where the location is only one brief item among unrelated stories, and articles that merely name-drop the location, are false. If no location of interest is stated, always true.",
  "event_type": "one of: conflict, political, natural_disaster, economic, protest, terrorism, other",
  "entities": ["list of key people or organizations mentioned"],
  "severity": "one of: low, medium, high, critical",
  "location_mentioned": "the most specific place named in the article — city, town, facility, or region (e.g. 'Kharkiv', 'Zaporizhzhia oblast', 'Taneco refinery, Tatarstan'). Only give a bare country name if no more specific place appears; null if none.",
  "one_line_summary": "one sentence summary of the event",
  "credibility": "NATO Admiralty information-credibility digit, integer 1-6: 1=confirmed by independent sources, 2=probably true (consistent with other reporting), 3=possibly true, 4=doubtful, 5=improbable, 6=truth cannot be judged. Judge the claim itself (attribution, corroboration, specificity), not the outlet. Reserve 1 for claims the article explicitly corroborates with multiple independent sources; single-outlet reporting with named attribution is 2, vaguer sourcing is 3."
}"""


_X_BATCH_PROMPT = """You are an intelligence analyst triaging social media posts about {location}.
Given a numbered list of X/Twitter posts, return a JSON array (no preamble, no markdown) with
one object per post:

{{
  "index": <the post's number>,
  "relevant": true/false — is this post actually about security, political, disaster, economic, or conflict events in or concerning {location}? Spam, jokes, ads, and off-topic posts are false,
  "event_type": "one of: conflict, political, natural_disaster, economic, protest, terrorism, other",
  "severity": "one of: low, medium, high, critical",
  "credibility": "NATO Admiralty information-credibility digit, integer 1-6: 1=confirmed by independent sources, 2=probably true, 3=possibly true, 4=doubtful, 5=improbable, 6=truth cannot be judged. Social posts are uncorroborated by default — reserve 1-2 for posts citing verifiable specifics; most should be 3-6."
}}

Return exactly one object for every input index."""

# Bulk social triage uses the fast 8B model: it has its own rate quota separate
# from the 70B model used for article analysis, and structured classification
# doesn't need the big model. Tiered triage by volume.
# The 8B free tier caps requests at 6k tokens/minute — batches are sized so
# prompt + max_tokens stays under it, with a pause between batches.
_POST_MODEL = "llama-3.1-8b-instant"
_POST_BATCH_SIZE = 25
_POST_MAX_TOKENS = 2000
_POST_BATCH_SLEEP = 20


def _default_post_analysis() -> dict:
    """Conservative fallback analysis when batch classification fails."""
    return {"event_type": "other", "severity": "low", "credibility": 6}


def analyze_posts(posts: list[dict], location: str) -> list[dict | None]:
    """Classify X posts in batched Groq calls (one call per 40 posts).

    Returns one entry per input post, aligned by position: an analysis dict
    {event_type, severity, credibility} or None if the post was judged
    irrelevant. If a batch call fails entirely, every post in that batch gets
    a conservative default analysis rather than being dropped.
    """
    if not posts:
        return []
    client = _get_client()
    results: list[dict | None] = [None] * len(posts)

    for start in range(0, len(posts), _POST_BATCH_SIZE):
        chunk = posts[start:start + _POST_BATCH_SIZE]
        lines = []
        for i, p in enumerate(chunk):
            text = (p.get("text") or "")[:280].replace("\n", " ")
            lines.append(f"[{i}] {p.get('author', '?')} "
                         f"({p.get('followers', 0)}f) {p.get('date', '?')}: {text}")
        user_content = "\n".join(lines)

        try:
            response = client.chat.completions.create(
                model=_POST_MODEL,
                messages=[
                    {"role": "system",
                     "content": _X_BATCH_PROMPT.format(location=location)},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=_POST_MAX_TOKENS,
                timeout=60,
            )
            raw = response.choices[0].message.content.strip().strip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("expected a JSON array")
            for obj in parsed:
                if not isinstance(obj, dict):
                    continue
                try:
                    idx = int(obj.get("index"))
                except (TypeError, ValueError):
                    continue
                if not 0 <= idx < len(chunk):
                    continue
                if obj.get("relevant") is False:
                    results[start + idx] = None
                else:
                    results[start + idx] = {
                        "event_type":  obj.get("event_type", "other"),
                        "severity":    obj.get("severity", "low"),
                        "credibility": obj.get("credibility", 6),
                    }
        except Exception as exc:  # broad: degrade to unclassified rather than losing the batch
            print(f"  [WARN] X post classification failed for batch: {exc}", file=sys.stderr)
            for i in range(len(chunk)):
                results[start + i] = _default_post_analysis()
        finally:
            # pace batches to stay under the 8B model's per-minute token cap
            if start + _POST_BATCH_SIZE < len(posts):
                time.sleep(_POST_BATCH_SLEEP)

    return results


def _get_client() -> Groq:
    """Return an authenticated Groq client."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Add it to your .env file.\n"
            "Get a free key at https://console.groq.com"
        )
    return Groq(api_key=api_key)


def analyze_article(article: dict, location: str | None = None) -> dict | None:
    """Send a news article to Groq and return structured intelligence as a dict.

    When a location is given, the analysis includes a relevance judgment so the
    pipeline can drop round-ups and name-drop articles that slipped past the
    keyword filter. Returns None if the API call fails or the response cannot
    be parsed as JSON.
    """
    client = _get_client()

    loc_line = f"Location of interest: {location}\n\n" if location else ""
    user_content = (f"{loc_line}Title: {article.get('title', '')}\n\n"
                    f"Description: {article.get('description', '')}")

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=512,
            timeout=30,
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
    except json.JSONDecodeError:
        return None
    except Exception:  # broad: Groq SDK raises multiple exception types (APIError, RateLimitError, etc.)
        return None
    finally:
        time.sleep(0.1)

    return result
