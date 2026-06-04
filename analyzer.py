import json
import os
import time

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_SYSTEM_PROMPT = """You are an intelligence analyst. Given a news article, extract the following in valid JSON only.
No preamble, no markdown, just raw JSON.

{
  "event_type": "one of: conflict, political, natural_disaster, economic, protest, terrorism, other",
  "entities": ["list of key people or organizations mentioned"],
  "severity": "one of: low, medium, high, critical",
  "location_mentioned": "most specific location mentioned in the article or null",
  "one_line_summary": "one sentence summary of the event"
}"""


def _get_client() -> Groq:
    """Return an authenticated Groq client."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_groq_api_key_here":
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Add it to your .env file.\n"
            "Get a free key at https://console.groq.com"
        )
    return Groq(api_key=api_key)


def analyze_article(article: dict) -> dict | None:
    """Send a news article to Groq and return structured intelligence as a dict.

    Returns None if the API call fails or the response cannot be parsed as JSON.
    """
    client = _get_client()

    user_content = f"Title: {article.get('title', '')}\n\nDescription: {article.get('description', '')}"

    try:
        response = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=512,
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
    except json.JSONDecodeError:
        return None
    except Exception:
        return None
    finally:
        time.sleep(0.5)

    return result
