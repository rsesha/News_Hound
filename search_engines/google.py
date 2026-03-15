import os
from dotenv import load_dotenv

load_dotenv()

def search(query, max_results=5):
    """
    Performs a Google Search using the Gemini 2.0 Flash native Google Search tool.
    This uses the official API-backed grounding search — reliable and no scraping.
    """
    results = []
    
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Google: No GEMINI_API_KEY or GOOGLE_API_KEY found in .env")
        return results

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=query,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
        )

        # Extract grounding chunks (sources) from the response metadata
        grounding_meta = None
        if response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
                grounding_meta = candidate.grounding_metadata

        if grounding_meta and hasattr(grounding_meta, "grounding_chunks"):
            for chunk in grounding_meta.grounding_chunks[:max_results]:
                web = getattr(chunk, "web", None)
                if web:
                    results.append({
                        "title": getattr(web, "title", "Google Result"),
                        "link": getattr(web, "uri", ""),
                        "snippet": "Result from Gemini Google Search Tool",
                        "source": "Google"
                    })

    except Exception as e:
        print(f"Error searching Google (Gemini): {e}")

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Google Search (via Gemini Grounding)")
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
