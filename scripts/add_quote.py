#!/usr/bin/env python3
"""Add a reading quote/highlight to reading-data/quotes.json.

Usage:
  python scripts/add_quote.py --content "摘录内容" --book 9787532153626
  python scripts/add_quote.py --content "摘录内容" --book-title "书名" --book-author "作者" --page 42
"""

import argparse
import json
import os
import sys
from datetime import date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
BOOKS_FILE = os.path.join(REPO_DIR, "reading-data", "books.json")
QUOTES_FILE = os.path.join(REPO_DIR, "reading-data", "quotes.json")


def lookup_book(isbn):
    """Look up book title and author from books.json by ISBN."""
    if not os.path.exists(BOOKS_FILE):
        return None, None
    with open(BOOKS_FILE) as f:
        books = json.load(f)
    for b in books:
        if b.get("isbn") == isbn:
            return b.get("title"), b.get("author")
    return None, None


def main():
    parser = argparse.ArgumentParser(
        description="Add a reading quote/highlight to quotes.json"
    )
    parser.add_argument("--content", required=True, help="Quote content")
    book_group = parser.add_mutually_exclusive_group()
    book_group.add_argument("--book", help="ISBN to auto-fill book info from books.json")
    book_group.add_argument("--book-title", help="Book title (manual)")
    parser.add_argument("--book-author", default=None, help="Book author (manual)")
    parser.add_argument("--page", type=int, default=None, help="Page number")
    parser.add_argument("--highlighted-at", default=None, help="Date highlighted (YYYY-MM-DD, default: today)")
    args = parser.parse_args()

    # Resolve book info
    book_title = args.book_title
    book_author = args.book_author
    if args.book:
        t, a = lookup_book(args.book)
        if t is None:
            print(f"❌ ISBN {args.book} 未在 books.json 中找到", file=sys.stderr)
            sys.exit(1)
        book_title = t
        book_author = a

    highlighted_at = args.highlighted_at or date.today().isoformat()

    entry = {
        "content": args.content,
        "book_title": book_title or "",
        "book_author": book_author or "",
        "page": args.page,
        "highlighted_at": highlighted_at,
    }
    # Remove None values
    entry = {k: v for k, v in entry.items() if v is not None}

    # Append to quotes.json
    quotes = []
    if os.path.exists(QUOTES_FILE):
        with open(QUOTES_FILE) as f:
            quotes = json.load(f)

    quotes.append(entry)
    os.makedirs(os.path.dirname(QUOTES_FILE), exist_ok=True)
    with open(QUOTES_FILE, "w") as f:
        json.dump(quotes, f, indent=2, ensure_ascii=False)

    print(f"✅ 已添加摘录:")
    print(json.dumps(entry, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
