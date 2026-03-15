import os
import re
import csv
from dotenv import load_dotenv
from search_engines import google, duckduckgo, brightdata, tavily  # google imported but not in active rotation
from scraper import scrape_and_export

# Load environment variables
load_dotenv()

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

# Tier 1: Major established news/reference outlets — highest credibility
TIER_1_DOMAINS = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "nytimes.com",
    "washingtonpost.com", "theguardian.com", "wsj.com", "ft.com",
    "bloomberg.com", "economist.com", "time.com", "newsweek.com",
    "nbcnews.com", "cbsnews.com", "abcnews.go.com", "cnn.com",
    "foxnews.com", "politico.com", "thehill.com", "axios.com",
    "aljazeera.com", "france24.com", "dw.com", "spiegel.de",
    "youtube.com", "vimeo.com",  # Primary video content
    "singjupost.com",            # Known transcript site for this topic
    "palestinechronicle.com", "haaretz.com", "timesofisrael.com",
    "pennlive.com", "dailymail.co.uk", "indiatimes.com",
}

# Tier 2: Known but less authoritative
TIER_2_DOMAINS = {
    "facebook.com", "twitter.com", "x.com", "instagram.com",
    "reddit.com", "substack.com", "medium.com",
    "en.as.com", "ndtv.com", "theroot.com",
}

# Recency patterns: URLs with year/month dates signal fresh content
RECENCY_PATTERNS = [
    r'/2026/0[1-9]/',   # 2026 articles — very fresh
    r'/2025/1[0-2]/',   # Late 2025
    r'/2025/0[7-9]/',   # Mid 2025
    r'2026-0[1-9]-\d{2}',
    r'2025-1[0-2]-\d{2}',
]

# Recency signals in snippets ("X days ago", "X hours ago")
SNIPPET_RECENCY = [
    (r'\b(\d+)\s+hour[s]?\s+ago\b', 10),    # hours ago = very recent
    (r'\b(\d+)\s+day[s]?\s+ago\b', 7),      # days ago = recent (decay by count)
    (r'\btoday\b', 10),
    (r'\byesterday\b', 8),
]


def score_result(res):
    """
    Composite score for a single result.
    Components:
      - source_count: how many engines found it (0-10 pts each)
      - domain_credibility: tier of the domain (0, 5, or 10 pts)
      - recency: URL date pattern + snippet age signals (0-10 pts)
    """
    url = res.get("link", "").lower()
    snippet = res.get("snippet", "") or ""
    sources = res.get("sources", [])

    # --- Source count score ---
    source_score = len(sources) * 10

    # --- Domain credibility ---
    domain_score = 0
    try:
        # Extract root domain from URL
        domain = re.sub(r'^https?://(www\.)?', '', url).split('/')[0]
        if any(domain.endswith(d) for d in TIER_1_DOMAINS):
            domain_score = 10
        elif any(domain.endswith(d) for d in TIER_2_DOMAINS):
            domain_score = 5
        else:
            domain_score = 2  # unknown/obscure
    except Exception:
        pass

    # --- Recency score ---
    recency_score = 0

    # Check URL for date patterns
    for pattern in RECENCY_PATTERNS:
        if re.search(pattern, url):
            recency_score = max(recency_score, 8)
            break

    # Check snippet for natural language recency
    snippet_lower = snippet.lower()
    for pattern, base_pts in SNIPPET_RECENCY:
        match = re.search(pattern, snippet_lower)
        if match:
            if 'hour' in pattern or 'today' in pattern or 'yesterday' in pattern:
                recency_score = max(recency_score, base_pts)
            elif 'day' in pattern:
                try:
                    days = int(match.group(1))
                    pts = max(0, base_pts - days)  # decay: 1 day ago=6pts, 7 days ago=0
                    recency_score = max(recency_score, pts)
                except (IndexError, ValueError):
                    recency_score = max(recency_score, 3)
            break

    total = source_score + domain_score + recency_score
    return total


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def safe_print(text, **kwargs):
    """Safely prints text to handle Windows console encoding issues."""
    try:
        print(text, **kwargs)
    except UnicodeEncodeError:
        clean_text = text.encode('ascii', 'ignore').decode('ascii')
        print(clean_text, **kwargs)


def export_tsv(query: str, all_results: dict, path: str = "search_results.tsv"):
    """Exports all raw search results to a TSV file (overwrites each run)."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["query", "engine", "rank", "title", "url", "snippet"])
        for engine_name, results in all_results.items():
            for rank, r in enumerate(results, 1):
                writer.writerow([
                    query,
                    engine_name,
                    rank,
                    (r.get("title") or "").replace("\t", " ").replace("\n", " "),
                    (r.get("link") or ""),
                    (r.get("snippet") or "").replace("\t", " ").replace("\n", " ")[:300],
                ])
    safe_print(f"[Export] Saved {sum(len(v) for v in all_results.values())} rows → '{path}'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    query = "What is the latest from Prof Jiang on Iran War?"

    safe_print(f"\n[Run] Executing Search Quality Test")
    safe_print(f"Query: '{query}'")
    safe_print("=" * 60)

    engines = [
        ("DuckDuckGo", duckduckgo),
        ("Brightdata", brightdata),
        ("Tavily", tavily),
    ]

    all_results = {}
    consolidated_map = {}

    for name, engine in engines:
        safe_print(f"SEARCHING {name}...", end=" ", flush=True)
        try:
            results = engine.search(query, max_results=5)
            all_results[name] = results
            safe_print(f"DONE. Found {len(results)} results.")

            for res in results:
                url = res.get("link")
                if url:
                    norm_url = url.lower().rstrip('/')
                    if norm_url not in consolidated_map:
                        consolidated_map[norm_url] = dict(res)
                        consolidated_map[norm_url]["sources"] = [name]
                    else:
                        if name not in consolidated_map[norm_url]["sources"]:
                            consolidated_map[norm_url]["sources"].append(name)
        except Exception as e:
            safe_print(f"ERROR: {e}")

    # --- Results per engine ---
    safe_print("\n" + "=" * 20 + " RESULTS PER ENGINE " + "=" * 20)
    for name, results in all_results.items():
        safe_print(f"\n--- {name.upper()} ---")
        if not results:
            safe_print("No results or error.")
            continue
        for i, res in enumerate(results, 1):
            safe_print(f"{i}. {res['title']}")
            safe_print(f"   URL: {res['link'][:100]}...")

    # --- Consolidated + scored top 3 ---
    safe_print("\n" + "*" * 10 + " TOP 3 CONSOLIDATED (SCORED) " + "*" * 10)
    safe_print("   Scoring: Sources(x10) + Domain Credibility(0-10) + Recency(0-10)")
    safe_print("-" * 60)

    consolidated_list = list(consolidated_map.values())

    # Score and sort
    for res in consolidated_list:
        res["_score"] = score_result(res)
    consolidated_list.sort(key=lambda x: x["_score"], reverse=True)

    top_3 = consolidated_list[:3]
    if not top_3:
        safe_print("No results found.")
    else:
        for i, res in enumerate(top_3, 1):
            sources_str = ", ".join(res["sources"])
            score = res["_score"]
            snippet = res.get("snippet") or "No snippet available."
            if len(snippet) > 200:
                snippet = snippet[:197] + "..."
            safe_print(f"\n{i}. [{score} pts] {res['title']}")
            safe_print(f"   URL: {res['link']}")
            safe_print(f"   Sources: {sources_str}")
            safe_print(f"   Snippet: {snippet}")
            safe_print("-" * 60)

    # --- Export TSV ---
    export_tsv(query, all_results)

    # --- Scrape & export full content to markdown ---
    # Pass all consolidated results (with scores) for scraping
    safe_print("\n[Scraper] Starting content extraction...")
    scrape_and_export(query, consolidated_list, output_path="search_text.md")


if __name__ == "__main__":
    main()
