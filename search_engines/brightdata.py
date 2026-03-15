import os
import requests
import json
import urllib.parse
import time
from dotenv import load_dotenv

load_dotenv()

def search(query, max_results=5):
    """
    Performs a search using Bright Data SERP API.
    Uses the configuration documented in test_api_direct and test_serp.
    """
    api_key = os.getenv("BRIGHTDATA_API_KEY")
    if not api_key:
        return []

    results = []
    try:
        # Properly encode the query for Google Search URL
        encoded_query = urllib.parse.quote(query, safe=':')
        search_url = f"https://www.google.com/search?q={encoded_query}"
        
        # API endpoint and authentication
        base_url = "https://api.brightdata.com/request"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Payload based on provided test scripts
        payload = {
            "zone": "serp_api1",
            "url": search_url,
            "format": "json"
        }
        
        # Increase timeout to handle slow proxy/serp responses and add retry
        for attempt in range(2):
            try:
                response = requests.post(base_url, headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    break
            except requests.exceptions.Timeout:
                if attempt == 0:
                    print("Brightdata timed out, retrying...")
                    time.sleep(2)
                    continue
                else:
                    raise
        
        if response.status_code == 200:
            data = response.json()
            body = data.get("body", {})
            
            # Handle string body
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    print("Failed to parse Brightdata string body as JSON")
                    return []

            # Check for organic results in various possible fields
            organic = body.get("organic_results") or body.get("organic") or body.get("results")
            
            if organic and isinstance(organic, list):
                for r in organic[:max_results]:
                    results.append({
                        "title": r.get("title") or r.get("name"),
                        "link": r.get("link") or r.get("url"),
                        "snippet": r.get("snippet") or r.get("description") or r.get("content"),
                        "source": "Brightdata"
                    })
        else:
            print(f"Brightdata API Error: {response.status_code} - {response.text}")
            
    except Exception as e:
        print(f"Error searching Brightdata: {e}")
    
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Brightdata SERP Search")
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
