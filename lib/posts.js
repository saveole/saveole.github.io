const fs = require('fs');
const path = require('path');
const hljs = require('highlight.js');
const taskLists = require('markdown-it-task-lists');
const matter = require('gray-matter');

const md = require('markdown-it')({
    html: true,
    linkify: true,
    typographer: true,
    highlight: function (str, lang) {
        if (lang && hljs.getLanguage(lang)) {
            try {
                return '<pre class="hljs"><code>' +
                       hljs.highlight(str, { language: lang, ignoreIllegals: true }).value +
                       '</code></pre>';
            } catch (__) {}
        }
        return '<pre class="hljs"><code>' + md.utils.escapeHtml(str) + '</code></pre>';
    }
}).use(taskLists, { label: true });

function extractInlineTags(content) {
    const tags = new Set();
    const cleaned = content
        .replace(/```[\s\S]*?```/g, '')
        .replace(/`[^`]*`/g, '')
        .replace(/^#{1,6}\s+.*/gm, '');
    const tagRegex = /(?:^|\s)#([\w一-鿿぀-ゟ゠-ヿ]+)/g;
    let match;
    while ((match = tagRegex.exec(cleaned)) !== null) {
        tags.add(match[1]);
    }
    return Array.from(tags);
}

function replaceInlineTags(html, tags) {
    tags.forEach(tag => {
        const escapedTag = tag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp('(?<![\\w/])#' + escapedTag + '(?![\\w])', 'g');
        html = html.replace(regex, '<a href="#" class="inline-tag" data-tag="' + tag + '">#' + tag + '</a>');
    });
    return html;
}

function processPosts(postsDir) {
    const files = fs.readdirSync(postsDir).filter(f => f.endsWith('.md'));
    const posts = [];
    const tagIndex = {};

    files.forEach(file => {
        const rawContent = fs.readFileSync(path.join(postsDir, file), 'utf-8');
        const { data, content } = matter(rawContent);

        if (data.published === false) return;

        const fixedContent = content.replace(/\.\.\/assets\//g, './assets/');

        const frontmatterTags = (data.tags || []).map(t => String(t));
        const inlineTags = extractInlineTags(fixedContent);
        const mergedTags = [...new Set([...frontmatterTags, ...inlineTags])];

        let htmlContent = md.render(fixedContent);
        htmlContent = replaceInlineTags(htmlContent, inlineTags);

        const postDate = data.date ? new Date(data.date) : new Date(0);
        const isValidDate = !isNaN(postDate.getTime());

        const postData = {
            title: data.title || '无题',
            subtitle: data.subtitle || '',
            date: isValidDate ? postDate.toISOString().split('T')[0] : '未知日期',
            rawDate: postDate,
            url: file.replace('.md', '.html'),
            content: htmlContent,
            tags: mergedTags,
            categories: data.categories || []
        };

        mergedTags.forEach(tag => {
            if (!tagIndex[tag]) tagIndex[tag] = [];
            tagIndex[tag].push({ title: postData.title, url: postData.url, date: postData.date });
        });

        posts.push(postData);
    });

    return { posts, tagIndex };
}

module.exports = { processPosts };