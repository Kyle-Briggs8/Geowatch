import os
import sys
import json
import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

url = ("https://api.apify.com/v2/acts/"
       "kaitoeasyapi~twitter-x-data-tweet-scraper-pay-per-result-cheapest/"
       "run-sync-get-dataset-items")
payload = {
    "searchTerms": ["Ukraine lang:en -filter:replies min_faves:2 filter:media"],
    "maxItems": 20,
    "queryType": "Latest",
    "lang": "en",
}
r = requests.post(url, json=payload,
                  headers={"Authorization": f"Bearer {os.getenv('APIFY_TOKEN')}"},
                  timeout=240)
print("status:", r.status_code)
items = [i for i in r.json() if isinstance(i, dict) and i.get("type") == "tweet"]
print("tweets:", len(items))
for t in items[:4]:
    print("---")
    print("text:", (t.get("text") or "")[:60])
    # dump any media-looking keys
    for key in ("media", "extendedEntities", "entities", "photos", "videos", "mediaDetails"):
        if key in t and t[key]:
            print(f"{key}:", json.dumps(t[key], indent=1)[:900])
