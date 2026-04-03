import os
import re
import csv
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from search_engines import duckduckgo, brightdata, tavily
from scraper import scrape_and_export

# Load environment variables
load_dotenv()

# Configure logging - set to logging.INFO for verbose, logging.WARNING for quiet
logging.basicConfig(
    level=logging.WARNING,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _load_priority_sites() -> tuple[set, set]:
    """Load TIER_1 and TIER_2 domain sets from priority_sites.json."""
    json_path = Path(__file__).parent / "priority_sites.json"
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tier_1 = {entry["url"] for entry in data.get("tier_1", [])}
        tier_2 = {entry["url"] for entry in data.get("tier_2", [])}
        logging.getLogger(__name__).info(
            f"[Config] Loaded {len(tier_1)} tier-1 and {len(tier_2)} tier-2 domains "
            f"from {json_path.name}"
        )
        return tier_1, tier_2
    except Exception as e:
        logging.getLogger(__name__).error(
            f"[Config] Could not load priority_sites.json: {e}. Falling back to empty sets."
        )
        return set(), set()

TIER_1_DOMAINS, TIER_2_DOMAINS = _load_priority_sites()

RECENCY_PATTERNS = [
    r'/2026/0[1-9]/',
    r'/2025/1[0-2]/',
    r'/2025/0[7-9]/',
    r'2026-0[1-9]-\d{2}',
    r'2025-1[0-2]-\d{2}',
]

SNIPPET_RECENCY = [
    (r'\b(\d+)\s+hour[s]?\s+ago\b', 10),
    (r'\b(\d+)\s+day[s]?\s+ago\b', 7),
    (r'\btoday\b', 10),
    (r'\byesterday\b', 8),
]

def score_result(res: Dict[str, Any]) -> int:
    url = str(res.get("link", "")).lower()
    snippet = str(res.get("snippet", "") or "")
    sources = res.get("sources", [])

    source_score: int = len(sources) * 10
    domain_score: int = 0
    try:
        domain = re.sub(r'^https?://(www\.)?', '', url).split('/')[0]
        if any(domain.endswith(d) for d in TIER_1_DOMAINS):
            domain_score = 10
        elif any(domain.endswith(d) for d in TIER_2_DOMAINS):
            domain_score = 5
        else:
            domain_score = 2
    except Exception:
        pass

    recency_score: int = 0
    for pattern in RECENCY_PATTERNS:
        if re.search(pattern, url):
            recency_score = max(recency_score, 8)
            break

    snippet_lower = snippet.lower()
    for pattern, base_pts in SNIPPET_RECENCY:
        match = re.search(pattern, snippet_lower)
        if match:
            if 'hour' in pattern or 'today' in pattern or 'yesterday' in pattern:
                recency_score = max(recency_score, base_pts)
            elif 'day' in pattern:
                try:
                    days = int(match.group(1))
                    pts = max(0, base_pts - days)
                    recency_score = max(recency_score, pts)
                except (IndexError, ValueError):
                    recency_score = max(recency_score, 3)
            break

    total: int = source_score + domain_score + recency_score
    return total


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def safe_print(text, **kwargs):
    """Safely handles logging of text messages."""
    msg = str(text)
    if len(msg) > 5000:
        msg = msg[:5000] + "... [TRUNCATED]"
    
    if "ERROR" in msg.upper() or "FAILED" in msg.upper():
        logger.error(msg)
    else:
        logger.info(msg)


def export_tsv(query: str, all_results: Dict[str, List[Dict[str, Any]]], path: str = "search_results.tsv"):
    """Exports all raw search results to a TSV file."""
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
    
    logger.info(f"[Export] Saved {sum(len(v) for v in all_results.values())} rows → '{path}'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_search_pipeline(query: str, max_results: int = 5, log_callback=None) -> List[Dict[str, Any]]:
    def log(msg, **kwargs):
        safe_print(msg, **kwargs)
        if log_callback:
            try:
                log_callback(str(msg))
            except:
                pass

    try:
        log(f"\n[Run] Executing Search Quality Test: '{query}'")

        engines = [
            ("DuckDuckGo", duckduckgo),
            ("Tavily", tavily),
            ("Brightdata", brightdata),
        ]

        all_results: Dict[str, List[Dict[str, Any]]] = {}
        consolidated_map: Dict[str, Dict[str, Any]] = {}

        for name, engine in engines:
            log(f"Searching {name}...", end=" ")
            try:
                results = engine.search(query, max_results=max_results)
                all_results[name] = results
                log(f"Done (Found {len(results)})")

                for res in results:
                    url = res.get("link")
                    if url:
                        norm_url = str(url).lower().rstrip('/')
                        if norm_url not in consolidated_map:
                            new_entry = dict(res)
                            new_entry["sources"] = [name]
                            consolidated_map[norm_url] = new_entry
                        else:
                            sources = consolidated_map[norm_url].get("sources", [])
                            if name not in sources:
                                sources.append(name)
            except Exception as e:
                log(f"ERROR: {e}")

        consolidated_list = list(consolidated_map.values())
        for res in consolidated_list:
            res["_score"] = score_result(res)
        consolidated_list.sort(key=lambda x: x.get("_score", 0), reverse=True)
        top_3 = consolidated_list[:3]

        log("\n============================================================")
        log("Web Research Done")
        log(f"Gathered {len(consolidated_list)} sources. Related to: {query[:50]}...")

        export_tsv(query, all_results)

        # [Scraper] Skipping content extraction for speed as requested
        # try:
        #    scrape_and_export(query, consolidated_list, output_path="search_text.md")
        #    log(f"[Scraper] Successfully exported to search_text.md")
        # except Exception as e:
        #    log(f"[Scraper] ERROR: {e}")
            
    except Exception as e:
        import traceback
        err_msg = f"ERROR IN PIPELINE: {str(e)}\n{traceback.format_exc()}"
        logger.error(err_msg)
        # Obey logging level for the UI callback as per user recommendation
        if logger.isEnabledFor(logging.INFO) and log_callback:
            log_callback(err_msg)
        return []
    
    log(f"\n[Run] Pipeline finished.")
    return top_3


def main():
    query = "What is the latest from Prof Jiang on Iran War?"
    run_search_pipeline(query)

if __name__ == "__main__":
    main()
