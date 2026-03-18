# animal-photosynthesis

## 项目地址

https://github.com/mebtte/animal-photosynthesis

在线预览: https://mebtte.com

## 技术栈

- **构建工具**: Node.js + EJS
- **文章格式**: Markdown + YAML frontmatter
- **依赖**: showdown (MD→HTML), front-matter, fontmin, ejs, cheerio

## 实现原理

### 核心流程

```
初始化 → 生成字体 → 解析文章 → 渲染模板 → 生成 sitemap/rss
```

### 核心特性 - 字体子集化

这是该项目最独特的设计：

1. **三层字体架构**
   - `title_font` - 首页标题字体（包含所有文章标题字符）
   - `common_font` - 通用字体（包含所有固定文本）
   - `article_font_{id}` - 每篇文章独立字体（仅包含该文章内容使用的字符）

2. **字体生成逻辑**
   - 使用 `fontmin` 按需裁剪字体
   - 每篇文章只打包实际使用的字符
   - 大幅减小字体文件体积

## UI 风格分析

### 设计理念

- **极简主义**: 干净、专注阅读
- **内容优先**: 840px 最大宽度限制
- **无干扰**: 无侧边栏

### 配色方案

```css
--primary-color: rgb(237 106 94)   /* 珊瑚红 */
--normal-color: #333                /* 正文 */
--secondary-color: #888             /* 次要信息 */
--tertiary-color: #ddd              /* 边框 */
```

### 排版特点

- 标题字体: 自定义 title_font
- 正文: 16px, 1.8 行高
- 代码: Prism.js + Fira Code
- 响应式标题: `min(8vw, 56px)`

### 交互细节

- 行内代码: 主色半透明背景
- 圆形无序列表项目符号
- blockquote 左侧主色竖条
- 链接下划线使用主色

## 优点

1. **性能优化极致**: 字体子集化设计非常独特，显著减小字体体积
2. **代码整洁**: 构建脚本结构清晰，易于理解和修改
3. **阅读体验好**: 排版注重可读性，行高、间距舒适
4. **技术选型务实**: 不依赖复杂框架，用最少的依赖实现功能
5. **CSS 使用逻辑属性**: `margin-inline` 等 RTL 友好写法

## 可借鉴的设计

1. 字体子集化策略
2. 三层字体架构分离
3. 简洁的文章操作栏（讨论/编辑/分享）
4. CSS 逻辑属性的使用
5. 首页文章列表的简洁呈现

## 目录结构

```
├── articles/           # Markdown 文章
├── scripts/            # 构建脚本
├── src/
│   ├── assets/        # 字体、图标等资源
│   ├── static/        # 静态文件
│   └── template/      # EJS 模板
└── build.js           # 主构建脚本
```
