# Nordic SSG - 极简静态博客生成器

一个基于 Node.js 的轻量级静态博客生成器，使用 Markdown 编写文章，通过 EJS 模板渲染生成 HTML。

## 特性

- 📝 Markdown 写作，支持 YAML 前置元数据
- 🎨 代码语法高亮（基于 highlight.js）
- 🏷️ 双标签系统（YAML 标签 + 内联 #标签）
- 💡 GitHub 风格的任务列表
- 🚀 自动部署到 GitHub Pages
- 🎯 北欧极简设计风格

## 快速开始

### 安装依赖

```bash
npm install
```

### 本地构建

```bash
node build.js
```

构建完成后，生成的 HTML 文件将在 `dist/` 目录中。你可以使用任何静态服务器预览：

```bash
npx serve dist
# 或
python -m http.server 8000 -d dist
```

## 写作指南

### 文章格式

在 `posts/` 目录下创建 Markdown 文件，文件名建议格式：`YYYY-MM-DD-title.md`

### 前置元数据

每篇文章的开头使用 YAML 格式定义元数据：

```yaml
---
title: 文章标题
date: 2026-01-07 20:59:59 +0800
categories: [分类]
tags: [标签1, 标签2]
description: 文章描述
subtitle: 副标题（可选）
---
```

### 标签使用

支持两种标签方式：

1. **YAML 标签**：在 frontmatter 中定义
2. **内联标签**：在正文中使用 `#标签` 格式

两种方式会自动合并，点击标签会弹窗显示所有相关文章。

## 项目结构

```
├── assets/          # 静态资源（图片、favicon 等）
├── dist/            # 构建输出目录（不提交到 Git）
├── posts/           # Markdown 文章
├── theme/           # 主题文件
│   ├── layout.ejs   # 文章页模板
│   ├── index.ejs    # 首页模板
│   └── style.css    # 样式文件
├── .github/
│   └── workflows/
│       └── pages-deploy.yml  # GitHub Pages 部署配置
├── build.js         # 构建脚本
└── package.json
```

## 部署

项目已配置 GitHub Actions，推送到 `main` 分支后自动构建并部署到 GitHub Pages。

部署流程：
1. 安装依赖 (`npm ci`)
2. 构建站点 (`node build.js`)
3. 部署 `dist/` 目录到 GitHub Pages

## 自定义主题

### 修改样式

编辑 `theme/style.css`，支持 CSS 自定义属性：

```css
:root {
    --bg-color: #F8F9FA;
    --text-main: #1A202C;
    --text-muted: #64748B;
    --primary-color: #2563EB;
    --border-color: #E5E7EB;
    --code-bg: #F3F4F6;
    --content-width: 720px;
}
```

### 修改模板

- `layout.ejs` - 文章详情页模板
- `index.ejs` - 首页文章列表模板

## 依赖项

- [markdown-it](https://github.com/markdown-it/markdown-it) - Markdown 解析
- [highlight.js](https://highlightjs.org/) - 代码高亮
- [gray-matter](https://github.com/jonschlinkert/gray-matter) - 前置元数据解析
- [ejs](https://ejs.co/) - 模板引擎
- [markdown-it-task-lists](https://github.com/revin/markdown-it-task-lists) - 任务列表支持

## License

ISC
