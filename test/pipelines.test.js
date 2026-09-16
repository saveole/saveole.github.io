const assert = require('assert');
const { processPosts } = require('../lib/posts');
const { aggregateTokenUsage } = require('../lib/tokenUsage');
const { loadRunningMap, mergeRunningMap, buildRunningPageData } = require('../lib/running');
const { buildReadingPageData } = require('../lib/reading');

const { posts, tagIndex } = processPosts('posts');
assert.strictEqual(posts.length, 14, 'all 14 published posts processed');
assert.ok(Object.keys(tagIndex).length > 0, 'tag index built');
posts.forEach(p => assert.ok(p.content.length > 0, `post ${p.url} has content`));

const fs = require('fs');
const path = require('path');

const tokenDir = process.env.TOKEN_USAGE_DIR || 
    (fs.existsSync(path.join(__dirname, '..', 'token-usage')) 
        ? path.join(__dirname, '..', 'token-usage') 
        : path.join(__dirname, '..', '..', 'token-usage'));
const runningDir = process.env.RUNNING_DATA_DIR || 
    (fs.existsSync(path.join(__dirname, '..', 'running-data', 'activities.json')) 
        ? path.join(__dirname, '..', 'running-data') 
        : path.join(__dirname, '..', '..', 'running', 'running-data'));

const token = aggregateTokenUsage(tokenDir);
if (token.days.length > 0) {
    assert.ok(token.days.length > 0, 'token days aggregated');
    assert.ok(Object.keys(token.bySourceTotal).length >= 1, 'bySource rollup present');
    token.days.forEach(d => assert.ok(d.total_tokens, `day ${d.date} has totals`));
}

const runningMap = loadRunningMap(runningDir);
const merged = mergeRunningMap(token.days.slice(), runningMap);
assert.ok(merged.length >= token.days.length, 'running days merged into token days');
assert.ok(merged.every(d => typeof d.running_km === 'number'), 'every merged day has running_km');

const rpd = buildRunningPageData(runningDir);
if (rpd) {
    assert.ok(JSON.parse(rpd.timelineJSON).length > 0, 'running timeline built');
    assert.ok(JSON.parse(rpd.activitiesJSON).length > 0, 'running activities formatted');
    assert.ok(JSON.parse(rpd.tracksJSON).length > 0, 'running tracks filtered');
}

const read = buildReadingPageData('reading-data');
assert.ok(read, 'reading page data present');
assert.ok(JSON.parse(read.booksJSON).length > 0, 'reading books loaded');
assert.ok(JSON.parse(read.statsJSON).total > 0, 'reading stats computed');

console.log('ALL PIPELINE TESTS PASSED');