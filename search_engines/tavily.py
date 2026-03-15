import os
import requests
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

def search(query, max_results=5):
    """
    Performs a search using Tavily API.
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []

    results = []
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            data = response.json()
            for r in data.get("results", []):
                title = r.get("title") or ""
                snippet = r.get("content") or ""
                try:
                    title = title.encode('ascii', 'ignore').decode('ascii')
                    snippet = snippet.encode('ascii', 'ignore').decode('ascii')
                except:
                    pass
                results.append({
                    "title": title,
                    "link": r.get("url"),
                    "snippet": snippet,
                    "source": "Tavily"
                })
    except Exception as e:
        logger.error(f"Error searching Tavily: {e}")
    
    return results


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    
    parser = argparse.ArgumentParser(description="Tavily Search")
    parser.add_argument("--search", required=True, help="Search query string")
    parser.add_argument("--max", type=int, default=5, help="Max results (default: 5)")
    args = parser.parse_args()

    results = search(args.search, max_results=args.max)
    if not results:
        print("No results found.")
    else:
        for i, r in enumerate(results, 1):
            print(f"\n{i}. {r['title']}")
            print(f"   URL: {r['link']}")
            if r.get('snippet'):
                print(f"   Snippet: {r['snippet'][:200]}")
