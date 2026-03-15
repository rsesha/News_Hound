from ddgs import DDGS
import time

def search(query, max_results=5):
    """
    Performs a search using the new 'ddgs' library.
    """
    results = []
    for attempt in range(2):
        try:
            with DDGS() as ddgs:
                # Use positional argument for query as expected by new version
                ddgs_gen = ddgs.text(query, max_results=max_results)
                if ddgs_gen:
                    for r in ddgs_gen:
                        results.append({
                            "title": r.get("title"),
                            "link": r.get("href"),
                            "snippet": r.get("body"),
                            "source": "DuckDuckGo"
                        })
                if results:
                    break
        except Exception as e:
            if "Ratelimit" in str(e):
                time.sleep(2)
            continue
    
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="DuckDuckGo Search")
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
