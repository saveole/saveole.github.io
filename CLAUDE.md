# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a minimal static site generator for a personal blog. It converts Markdown posts with YAML frontmatter into HTML using EJS templates, with support for syntax highlighting and inline hashtag tags.

## Development Commands

- `npm ci` - Install dependencies (used in CI)
- `node build.js` - Build the site (outputs to `dist/`)

## Build & Deployment

The site is automatically deployed to GitHub Pages via `.github/workflows/pages-deploy.yml` when pushing to the `main` branch. The workflow:
1. Uses Node.js 22
2. Runs `npm ci` then `node build.js`
3. Deploys the `dist/` directory

## Architecture

### Build Process (`build.js`)

The build script orchestrates the entire site generation:

1. **Cleanup**: Removes and recreates `dist/` directory
2. **Asset copying**: Copies `theme/style.css` and `assets/` to `dist/`
3. **Post processing**: For each `.md` file in `posts/`:
   - Parses YAML frontmatter with `gray-matter`
   - Extracts tags from both `tags:` field and inline `#hashtag` patterns in content
   - Renders Markdown to HTML using `markdown-it` with syntax highlighting
   - Converts inline `#tag` to clickable links that trigger a popup
   - Renders using `theme/layout.ejs` template
4. **Index generation**: Sorts posts by date (descending) and renders `theme/index.ejs`

### Post Frontmatter Format

Posts use YAML frontmatter with these fields:
```yaml
---
title: Post Title
date: 2026-01-07 20:59:59 +0800
categories: [Category]
tags: [tag1, tag2]
description: Optional description
subtitle: Optional subtitle
---
```

Post filenames should follow the pattern: `YYYY-MM-DD-title.md`

### Tag System

The site has a dual tag system:
1. **Frontmatter tags**: Specified in `tags:` field
2. **Inline tags**: Any `#hashtag` pattern in the post body

Both types are merged into a single `tags` array. Inline `#tag` patterns are converted to styled `<a>` links that trigger a client-side popup showing all posts with that tag. The full post list is injected as JSON into templates for this functionality.

### Theme Files (`theme/`)

- `layout.ejs` - Template for individual post pages
- `index.ejs` - Template for homepage listing all posts
- `style.css` - All site styles, uses CSS custom properties for theming

### Directory Structure

```
├── assets/          # Static assets (images, favicons) - copied to dist/
├── dist/            # Generated output (not in git)
├── posts/           # Markdown blog posts
├── theme/           # EJS templates and CSS
├── .github/         # GitHub Actions workflows
└── build.js         # Main build script
```

## Key Dependencies

- `markdown-it` - Markdown parsing with plugins
- `highlight.js` - Code syntax highlighting
- `gray-matter` - Frontmatter parsing
- `ejs` - HTML templating
- `markdown-it-task-lists` - GitHub-style task lists
