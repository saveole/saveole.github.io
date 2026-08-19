const fs = require('fs');
const path = require('path');
const ejs = require('ejs');

const { processPosts } = require('./lib/posts');
const { aggregateTokenUsage } = require('./lib/tokenUsage');
const { loadRunningMap, mergeRunningMap, buildRunningPageData } = require('./lib/running');
const { buildReadingPageData } = require('./lib/reading');

const POSTS_DIR = path.join(__dirname, 'posts');
const DIST_DIR = path.join(__dirname, 'dist');
const THEME_DIR = path.join(__dirname, 'theme');
const TOKEN_USAGE_DIR = process.env.TOKEN_USAGE_DIR || path.join(__dirname, 'token-usage');
const RUNNING_DATA_DIR = path.join(__dirname, 'running-data');
const READING_DATA_DIR = path.join(__dirname, 'reading-data');

const ejsOpts = { root: THEME_DIR, views: [THEME_DIR] };

// 1. 清理并准备输出目录
if (fs.existsSync(DIST_DIR)) fs.rmSync(DIST_DIR, { recursive: true });
fs.mkdirSync(DIST_DIR);

// 2. 拷贝 CSS 和静态资源
fs.copyFileSync(path.join(THEME_DIR, 'style.css'), path.join(DIST_DIR, 'style.css'));
if (fs.existsSync(path.join(__dirname, 'assets'))) {
    fs.cpSync(path.join(__dirname, 'assets'), path.join(DIST_DIR, 'assets'), { recursive: true });
}

// 3. 处理所有文章
const { posts, tagIndex } = processPosts(POSTS_DIR);

// 4. 渲染文章详情页（在标签索引构建完成后）
posts.forEach(postData => {
    const postHtml = ejs.render(fs.readFileSync(path.join(THEME_DIR, 'layout.ejs'), 'utf-8'), {
        ...postData,
        tagIndex: JSON.stringify(tagIndex)
    }, ejsOpts);
    fs.writeFileSync(path.join(DIST_DIR, postData.url), postHtml);
});

// 5. 首页渲染（按时间倒序 + token/跑步数据合并）
posts.sort((a, b) => b.rawDate - a.rawDate);

const tokenView = aggregateTokenUsage(TOKEN_USAGE_DIR);
tokenView.days = mergeRunningMap(tokenView.days, loadRunningMap(RUNNING_DATA_DIR));

const indexHtml = ejs.render(fs.readFileSync(path.join(THEME_DIR, 'index.ejs'), 'utf-8'), {
    posts,
    dailyData: JSON.stringify(tokenView)
}, ejsOpts);
fs.writeFileSync(path.join(DIST_DIR, 'index.html'), indexHtml);

// 6. 跑步页面
const runningPageData = buildRunningPageData(RUNNING_DATA_DIR);
if (runningPageData) {
    const runningHtml = ejs.render(fs.readFileSync(path.join(THEME_DIR, 'running.ejs'), 'utf-8'), runningPageData, ejsOpts);
    fs.writeFileSync(path.join(DIST_DIR, 'running.html'), runningHtml);
}

// 7. 阅读页面
const readingPageData = buildReadingPageData(READING_DATA_DIR);
if (readingPageData) {
    const readingHtml = ejs.render(
        fs.readFileSync(path.join(THEME_DIR, 'reading.ejs'), 'utf-8'),
        readingPageData,
        ejsOpts
    );
    fs.writeFileSync(path.join(DIST_DIR, 'reading.html'), readingHtml);
    console.log('Reading page generated.');
}

console.log(`🚀 构建成功！已生成 ${posts.length} 篇文章和 1 个首页。`);

// 8. 复制独立页面（如 token-usage）
const PAGES_DIR = path.join(__dirname, 'pages');
if (fs.existsSync(PAGES_DIR)) {
    fs.cpSync(PAGES_DIR, DIST_DIR, { recursive: true });
    console.log('已复制 pages/ 目录到 dist/。');
}