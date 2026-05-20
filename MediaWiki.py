# MediaWiki.py
"""
Lightweight helper to fetch short Wikipedia search/extract results.

Provides:
    get_search_results(query: str) -> Union[str, list[str], None]

Behavior:
 - If a good page is found, returns the page summary (string).
 - If multiple titles are returned, returns a small list of title strings.
 - Returns None on network errors or when nothing useful is found.
This is intentionally conservative: it avoids heavy dependencies and keeps
Matching.py logic unchanged (it expects either string / list / None).
"""

from typing import Optional, Union, List
import requests
import urllib.parse
import time

WIKI_SEARCH_URL = "https://en.wikipedia.org/w/api.php"
WIKI_REST_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

# small in-memory cache to avoid repeated network hits during a single run
_cache = {}

def _safe_get(url, params=None, timeout=6):
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception:
        return None

def get_search_results(query: str) -> Optional[Union[str, List[str]]]:
    """
    Query Wikipedia for 'query'.
    Returns:
      - a string summary if a matching article is found,
      - a list of title suggestions if several matches,
      - or None if no useful result or on error.
    """
    if not query or not isinstance(query, str):
        return None

    key = ("wiki", query.strip().lower())
    if key in _cache:
        return _cache[key]

    # 1) Try direct summary (REST) using the most-likely title (query cleaned)
    # We encode the query as a title (replace spaces etc.)
    title_candidate = query.strip().replace(" ", "_")
    try:
        summary_url = WIKI_REST_SUMMARY + urllib.parse.quote(title_candidate)
        r = _safe_get(summary_url)
        if r and r.headers.get("Content-Type","").startswith("application/json"):
            data = r.json()
            # If an exact article found, 'extract' or 'extract_html' keys may exist
            if data.get("extract"):
                s = data.get("extract")
                # cache and return
                _cache[key] = s
                return s
            # if it's a disambiguation page or no extract, continue to search
    except Exception:
        pass

    # 2) Perform a search query to get suggestions
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": 6
    }
    r = _safe_get(WIKI_SEARCH_URL, params=params)
    if not r:
        _cache[key] = None
        return None

    try:
        j = r.json()
        results = j.get("query", {}).get("search", [])
        if not results:
            _cache[key] = None
            return None

        # If the top result has a snippet/word match, attempt to fetch its summary
        top_title = results[0].get("title")
        if top_title:
            try:
                summary_url = WIKI_REST_SUMMARY + urllib.parse.quote(top_title)
                r2 = _safe_get(summary_url)
                if r2 and r2.headers.get("Content-Type","").startswith("application/json"):
                    d2 = r2.json()
                    if d2.get("extract"):
                        s = d2.get("extract")
                        _cache[key] = s
                        return s
            except Exception:
                pass

        # Fallback: return list of titles (helpful for caller to see suggestions)
        titles = [r.get("title") for r in results if r.get("title")]
        if titles:
            _cache[key] = titles
            return titles

    except Exception:
        _cache[key] = None
        return None

    _cache[key] = None
    return None
