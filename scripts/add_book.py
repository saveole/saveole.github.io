#!/usr/bin/env python3
"""Query book metadata by ISBN → append to reading-data/books.json.

Data sources (in priority order):
  1. Google Books API (requires GOOGLE_BOOKS_API_KEY)
  2. Open Library API (free, no key needed)

Usage:
  python scripts/add_book.py --isbn 9787532153626 --status reading
  python scripts/add_book.py --isbn 9787532153626 --status finished --rating 5 --tags 写作 文学

The Google Books API key can be provided via:
  - GOOGLE_BOOKS_API_KEY environment variable
  - .env file in project root (GOOGLE_BOOKS_API_KEY=...)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
BOOKS_FILE = os.path.join(REPO_DIR, "reading-data", "books.json")
COVER_DIR = os.path.join(REPO_DIR, "assets", "img", "reading")


def load_dotenv():
    """Load .env file from project root (simple key=value parser)."""
    env_path = os.path.join(REPO_DIR, ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = value


def get_api_key():
    """Get Google Books API key from env."""
    return os.environ.get("GOOGLE_BOOKS_API_KEY")


def query_google_books(isbn, api_key):
    """Query Google Books API by ISBN. Requires API key."""
    params = {"q": f"isbn:{isbn}"}
    if api_key:
        params["key"] = api_key
    url = "https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("❌ Google Books API 403: API key invalid or quota exceeded", file=sys.stderr)
            return None
        raise
    items = data.get("items", [])
    if not items:
        return None
    info = items[0].get("volumeInfo", {})
    image_links = info.get("imageLinks", {})
    cover_url = (
        image_links.get("extraLarge")
        or image_links.get("large")
        or image_links.get("medium")
        or image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or ""
    )
    # Prefer higher resolution: replace zoom parameter
    if cover_url and "zoom=" in cover_url:
        cover_url = cover_url.replace("zoom=1", "zoom=4").replace("zoom=2", "zoom=4")
    # Ensure https
    if cover_url.startswith("http://"):
        cover_url = "https://" + cover_url[7:]

    return {
        "title": info.get("title", ""),
        "subtitle": info.get("subtitle", ""),
        "author": ", ".join(info.get("authors", [])),
        "cover_url": cover_url,
        "isbn": isbn,
        "page_count": info.get("pageCount") or None,
        "description": info.get("description", ""),
        "categories": info.get("categories", []),
        "published_date": info.get("publishedDate", ""),
        "language": info.get("language", ""),
        "snippet": info.get("searchInfo", {}).get("textSnippet", ""),
    }


def query_open_library(isbn):
    """Fallback: Open Library API (free, no key needed)."""
    url = (
        f"https://openlibrary.org/api/books"
        f"?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError:
        return None
    key = f"ISBN:{isbn}"
    if key not in data:
        return None
    info = data[key]
    cover_url = ""
    if info.get("cover"):
        cover_url = info["cover"].get("large") or info["cover"].get("medium") or info["cover"].get("small", "")
    return {
        "title": info.get("title", ""),
        "subtitle": "",
        "author": ", ".join(a.get("name", "") for a in info.get("authors", [])),
        "cover_url": cover_url,
        "isbn": isbn,
        "page_count": info.get("number_of_pages"),
        "description": "",
        "categories": [s.get("name", "") for s in info.get("subjects", [])[:5]],
        "published_date": "",
        "language": "",
        "snippet": "",
    }


def download_cover(url, dest_path):
    """Download cover image."""
    if not url:
        return False
    try:
        urllib.request.urlretrieve(url, dest_path)
        return True
    except (urllib.error.URLError, OSError) as e:
        print(f"⚠️  封面下载失败: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Add a book to reading-data/books.json by ISBN"
    )
    parser.add_argument("--isbn", required=True, help="ISBN (10 or 13 digits)")
    parser.add_argument(
        "--status", default="wishlist",
        choices=["reading", "finished", "wishlist"],
        help="Reading status (default: wishlist)",
    )
    parser.add_argument("--tags", nargs="*", default=[], help="Tags")
    parser.add_argument("--rating", type=int, choices=range(1, 6), default=None, help="Rating 1-5")
    parser.add_argument("--notes", default=None, help="Short notes/review")
    parser.add_argument("--started-at", default=None, help="Date started reading (YYYY-MM-DD)")
    parser.add_argument("--finished-at", default=None, help="Date finished reading (YYYY-MM-DD)")
    args = parser.parse_args()

    # Load .env and get API key
    load_dotenv()
    api_key = get_api_key()

    if not api_key:
        print("⚠️  GOOGLE_BOOKS_API_KEY not set. Trying without key (may fail).", file=sys.stderr)
        print("   Set it via env var or .env file in project root.", file=sys.stderr)

    # Query: Google Books first → Open Library fallback
    book = None
    source = ""
    if api_key:
        book = query_google_books(args.isbn, api_key)
        source = "Google Books"
    if not book:
        print("ℹ️  Google Books 未命中, 尝试 Open Library...", file=sys.stderr)
        book = query_open_library(args.isbn)
        source = "Open Library"
    if not book:
        print(f"❌ 未找到 ISBN {args.isbn}，请手动添加到 {BOOKS_FILE}", file=sys.stderr)
        sys.exit(1)

    print(f"📖 数据源: {source}")
    print(f"   书名: {book['title']}{(' — ' + book['subtitle']) if book['subtitle'] else ''}")
    print(f"   作者: {book['author']}")
    if book.get("page_count"):
        print(f"   页数: {book['page_count']}")
    if book.get("description") or book.get("snippet"):
        desc = book.get("description") or book.get("snippet", "")
        print(f"   简介: {desc[:80]}{'...' if len(desc) > 80 else ''}")

    # Download cover
    os.makedirs(COVER_DIR, exist_ok=True)
    cover_filename = f"{args.isbn}.jpg"
    cover_path = os.path.join(COVER_DIR, cover_filename)
    if download_cover(book.get("cover_url", ""), cover_path):
        print(f"✅ 封面已下载: {cover_path}")
    else:
        print("⚠️  无封面图，页面将显示首字占位符")
        cover_filename = None

    # Build entry
    entry = {
        "title": book["title"],
        "subtitle": book.get("subtitle") or None,
        "author": book["author"],
        "cover": cover_filename,
        "status": args.status,
        "started_at": args.started_at,
        "finished_at": args.finished_at,
        "rating": args.rating,
        "isbn": args.isbn,
        "page_count": book.get("page_count"),
        "tags": args.tags,
        "notes": args.notes,
    }
    # Remove None values for cleanliness
    entry = {k: v for k, v in entry.items() if v is not None}

    # Append to books.json
    books = []
    if os.path.exists(BOOKS_FILE):
        with open(BOOKS_FILE) as f:
            books = json.load(f)

    # Check for duplicate ISBN
    for existing in books:
        if existing.get("isbn") == args.isbn:
            print(f"⚠️  ISBN {args.isbn} 已存在于 books.json，跳过添加", file=sys.stderr)
            print(f"   已有: {existing.get('title')} — {existing.get('author')}", file=sys.stderr)
            sys.exit(1)

    books.append(entry)
    os.makedirs(os.path.dirname(BOOKS_FILE), exist_ok=True)
    with open(BOOKS_FILE, "w") as f:
        json.dump(books, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 已添加到 {BOOKS_FILE}")
    print(json.dumps(entry, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
