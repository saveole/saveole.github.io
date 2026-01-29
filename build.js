const fs = require('fs-extra'); // 如果没安装可以 npm i fs-extra，或者用原生的 fs
const hljs = require('highlight.js'); // 确保这一行存在且在 markdown-it 配置之前
const taskLists = require('markdown-it-task-lists');
const path = require('path');
const matter = require('gray-matter');

const md = require('markdown-it')({
    hhtml: true,       // 允许 MD 中的 HTML
    linkify: true,    // 自动转换链接
    typographer: true, // 启用一些排版优化
    highlight: function (str, lang) {
        if (lang && hljs.getLanguage(lang)) {
            try {
                // 注意这里：必须外层包裹 hljs 类名
                return '<pre class="hljs"><code>' +
                       hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
                       '</code></pre>';
            } catch (__) {}
        }
        return '<pre class="hljs"><code>' + md.utils.escapeHtml(str) + '</code></pre>';
    }
}).use(taskLists, { label: true });
const ejs = require('ejs');

// 配置路径
const POSTS_DIR = path.join(__dirname, 'posts');
const DIST_DIR = path.join(__dirname, 'dist');
const THEME_DIR = path.join(__dirname, 'theme');

// 1. 清理并准备输出目录
if (fs.existsSync(DIST_DIR)) fs.rmSync(DIST_DIR, { recursive: true });
fs.mkdirSync(DIST_DIR);

// 2. 拷贝 CSS 和静态资源
fs.copyFileSync(path.join(THEME_DIR, 'style.css'), path.join(DIST_DIR, 'style.css'));

// 拷贝 assets 目录到 dist
if (fs.existsSync(path.join(__dirname, 'assets'))) {
    fs.copySync(path.join(__dirname, 'assets'), path.join(DIST_DIR, 'assets'));
}

// 3. 读取所有文章
const files = fs.readdirSync(POSTS_DIR).filter(f => f.endsWith('.md'));

const postList = [];

// 1. 循环处理每一篇文章
files.forEach(file => {
    const rawContent = fs.readFileSync(path.join(POSTS_DIR, file), 'utf-8');
    const { data, content } = matter(rawContent);
    // 修正图片路径：将 ../assets/ 替换为 ./assets/
    const fixedContent = content.replace(/\.\.\/assets\//g, './assets/');
    const htmlContent = md.render(fixedContent);

    // 日期处理逻辑
    const postDate = data.date ? new Date(data.date) : new Date(0);
    const isValidDate = !isNaN(postDate.getTime());

    const postData = {
        title: data.title || '无题',
        subtitle: data.subtitle || '',
        date: isValidDate ? postDate.toLocaleDateString('zh-CN') : '未知日期',
        rawDate: postDate,
        url: file.replace('.md', '.html'),
        content: htmlContent
    };

    // --- 注意这里：文章详情页渲染 ---
    // 使用 layout.ejs 渲染，只传入 postData (包含 title, date, content 等)
    const postHtml = ejs.render(fs.readFileSync(path.join(THEME_DIR, 'layout.ejs'), 'utf-8'), postData);
    fs.writeFileSync(path.join(DIST_DIR, postData.url), postHtml);
    
    postList.push(postData);
});

// 2. 首页渲染（在循环结束后执行一次）
// 按时间倒序
postList.sort((a, b) => b.rawDate - a.rawDate);

// 使用 index.ejs 渲染，传入 posts 列表
const indexHtml = ejs.render(fs.readFileSync(path.join(THEME_DIR, 'index.ejs'), 'utf-8'), {
    posts: postList
});
fs.writeFileSync(path.join(DIST_DIR, 'index.html'), indexHtml);

console.log(`🚀 构建成功！已生成 ${postList.length} 篇文章和 1 个首页。`);