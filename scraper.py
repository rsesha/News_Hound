"""
scraper.py — Scrapes URLs from search results and saves to search_text.md.

Uses Crawlee (BeautifulSoupCrawler) for article pages.
Social media / video platforms (YouTube, Facebook, Instagram) are handled
with a lightweight metadata-only approach (oEmbed / page title) since
their content is behind JS or login walls.

Output: search_text.md (overwritten on each run)
"""

import asyncio
import re
import requests
from datetime import datetime
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# Detect what kind of URL we have
# ---------------------------------------------------------------------------

SOCIAL_DOMAINS = {"youtube.com", "youtu.be", "facebook.com", "instagram.com",
                  "twitter.com", "x.com", "tiktok.com"}

def _root_domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.replace("www.", "").lower()
        return host
    except Exception:
        return ""


def _is_social(url: str) -> bool:
    domain = _root_domain(url)
    return any(domain.endswith(s) for s in SOCIAL_DOMAINS)


# ---------------------------------------------------------------------------
# YouTube metadata via oEmbed (no API key needed)
# ---------------------------------------------------------------------------

def _youtube_meta(url: str) -> dict:
    try:
        oembed = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=8
        )
        if oembed.status_code == 200:
            data = oembed.json()
            return {
                "title": data.get("title", "YouTube Video"),
                "author": data.get("author_name", ""),
                "thumbnail": data.get("thumbnail_url", ""),
                "type": "video"
            }
    except Exception:
        pass
    return {"title": url, "type": "video"}


# ---------------------------------------------------------------------------
# Article scraping with Crawlee BeautifulSoupCrawler
# ---------------------------------------------------------------------------

async def _scrape_articles(urls: list[str]) -> dict[str, str]:
    """
    Returns a dict of {url: extracted_text}.
    Uses Crawlee's BeautifulSoupCrawler for static article pages.
    """
    results = {}
    
    try:
        from crawlee.crawlers import BeautifulSoupCrawler
        from crawlee import Request

        async def handler(context):
            url = context.request.url
            soup = context.soup
            
            # Remove nav, footer, ads, scripts, styles
            for tag in soup.find_all(["script", "style", "nav", "footer",
                                       "header", "aside", "noscript"]):
                tag.decompose()
            
            # Grab article body — try common selectors
            content = (
                soup.find("article") or
                soup.find("main") or
                soup.find("div", {"id": re.compile(r"content|article|story|body", re.I)}) or
                soup.find("div", {"class": re.compile(r"content|article|story|body|post", re.I)}) or
                soup.body
            )
            
            text = content.get_text(separator="\n", strip=True) if content else ""
            
            # Collect images on the page
            images = []
            for img in (soup.find_all("img", src=True)[:5]):  # cap at 5
                src = img.get("src", "")
                alt = img.get("alt", "")
                if src.startswith("http"):
                    images.append((alt or "image", src))
            
            results[url] = {"text": text[:8000], "images": images}  # cap text at 8k chars

        crawler = BeautifulSoupCrawler(max_requests_per_crawl=len(urls))
        crawler.router.default_handler(handler)
        
        requests_list = [Request.from_url(u) for u in urls]
        await crawler.run(requests_list)

    except Exception as e:
        print(f"Crawlee scraping error: {e}")
    
    return results


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------

def scrape_and_export(query: str, results: list[dict], output_path: str = "search_text.md"):
    """
    Takes the consolidated search results list and generates a rich .md file.
    Scrapes article pages, extracts metadata for social/video URLs.
    """
    # Separate article vs social URLs
    article_urls = []
    social_urls = []
    
    for r in results:
        url = r.get("link", "")
        if not url:
            continue
        if _is_social(url):
            social_urls.append(r)
        else:
            article_urls.append(r)
    
    # Scrape articles
    print(f"\n[Scraper] Crawling {len(article_urls)} article URL(s)...")
    scraped = asyncio.run(_scrape_articles([r["link"] for r in article_urls]))
    
    # YouTube metadata
    print(f"[Scraper] Fetching metadata for {len(social_urls)} social/video URL(s)...")
    social_meta = {}
    for r in social_urls:
        url = r["link"]
        domain = _root_domain(url)
        if "youtube" in domain or "youtu.be" in domain:
            social_meta[url] = _youtube_meta(url)
        else:
            social_meta[url] = {"title": r.get("title", url), "type": "social"}
    
    # Build the markdown document
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Search Results\n",
        f"**Query:** {query}  ",
        f"**Generated:** {now}  ",
        f"**Total sources:** {len(results)}\n",
        "---\n"
    ]
    
    result_num = 0
    
    # Articles first
    for r in article_urls:
        url = r["link"]
        result_num += 1
        title = r.get("title", url)
        snippet = r.get("snippet") or ""
        source_engines = ", ".join(r.get("sources", []))
        score = r.get("_score", "")
        score_str = f" | Score: {score}" if score else ""
        
        scraped_data = scraped.get(url, {})
        body_text = scraped_data.get("text", "")
        images = scraped_data.get("images", [])
        
        lines.append(f"## {result_num}. {title}\n")
        lines.append(f"**URL:** {url}  ")
        lines.append(f"**Found by:** {source_engines}{score_str}  ")
        if snippet:
            lines.append(f"**Snippet:** {snippet}\n")
        
        if images:
            lines.append("### Images\n")
            for alt, src in images:
                lines.append(f"![{alt}]({src})\n")
        
        if body_text:
            lines.append("### Full Content\n")
            lines.append("```\n" + body_text + "\n```\n")
        else:
            lines.append("*Could not extract article content (blocked or JS-rendered).*\n")
        
        lines.append("---\n")
    
    # Social / video next
    for r in social_urls:
        url = r["link"]
        result_num += 1
        title = r.get("title", url)
        snippet = r.get("snippet") or ""
        source_engines = ", ".join(r.get("sources", []))
        score = r.get("_score", "")
        score_str = f" | Score: {score}" if score else ""
        
        meta = social_meta.get(url, {})
        content_type = meta.get("type", "social")
        
        lines.append(f"## {result_num}. {title}\n")
        lines.append(f"**URL:** {url}  ")
        lines.append(f"**Type:** {content_type}  ")
        lines.append(f"**Found by:** {source_engines}{score_str}  ")
        
        if snippet:
            lines.append(f"**Snippet:** {snippet}\n")
        
        if content_type == "video" and meta.get("thumbnail"):
            lines.append(f"**Creator:** {meta.get('author', 'Unknown')}  \n")
            lines.append(f"[![Video Thumbnail]({meta['thumbnail']})]({url})\n")
        elif content_type == "video":
            lines.append(f"**Creator:** {meta.get('author', 'Unknown')}  \n")
            lines.append(f"> 🎬 [Watch Video]({url})\n")
        else:
            lines.append(f"> 📱 [View on Social Media]({url})\n")
        
        lines.append("---\n")
    
    # Write to file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    
    print(f"[Scraper] Saved to '{output_path}' ({len(results)} results, {len(lines)} lines)")
    return output_path
