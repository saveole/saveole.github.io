const fs = require('fs');
const path = require('path');

const KNOWN_SOURCES = new Set(['claude', 'opencode', 'hermes', 'agy', 'zcode', 'pi', 'codex']);

function aggregateTokenUsage(dataDir) {
    const view = { days: [], bySourceTotal: {}, byOsTotal: {} };
    if (!fs.existsSync(dataDir)) return view;

    const dayMap = {};
    const bySourceTotal = {};
    const byOsTotal = {};
    const dataFiles = fs.readdirSync(dataDir).filter(f => /^\d{4}-\d{2}-\d{2}(_.+)?\.data$/.test(f)).sort();

    for (const df of dataFiles) {
        const date = df.replace(/_.+$/, '').replace(/\.data$/, '');
        const suffixMatch = df.match(/^\d{4}-\d{2}-\d{2}_(.+)-(\w+)\.data$/);
        const os = suffixMatch ? suffixMatch[2] : null;
        const lines = fs.readFileSync(path.join(dataDir, df), 'utf-8').trim().split('\n');
        if (lines.length < 2) continue;
        const header = lines[0].split('\t');
        const sourceIdx = header.indexOf('source');
        for (let i = 1; i < lines.length; i++) {
            const cols = lines[i].split('\t');
            const get = (name) => parseInt(cols[header.indexOf(name)] || '0', 10) || 0;
            const rawSource = sourceIdx >= 0 ? (cols[sourceIdx] || 'unknown') : 'unknown';
            const source = KNOWN_SOURCES.has(rawSource) ? rawSource : 'unknown';
            const vals = {
                input: get('tokens_input'),
                output: get('tokens_output'),
                cache_read: get('tokens_cache_read'),
                cache_creation: get('tokens_cache_creation'),
                reasoning: get('tokens_reasoning')
            };
            if (!dayMap[date]) dayMap[date] = { input: 0, output: 0, cache_read: 0, cache_creation: 0, reasoning: 0, bySource: {} };
            dayMap[date].input += vals.input;
            dayMap[date].output += vals.output;
            dayMap[date].cache_read += vals.cache_read;
            dayMap[date].cache_creation += vals.cache_creation;
            dayMap[date].reasoning += vals.reasoning;
            const rowTotal = vals.input + vals.output + vals.cache_read + vals.cache_creation + vals.reasoning;
            if (!dayMap[date].bySource[source]) dayMap[date].bySource[source] = 0;
            dayMap[date].bySource[source] += rowTotal;
            if (source !== 'unknown') {
                bySourceTotal[source] = (bySourceTotal[source] || 0) + rowTotal;
            }
            if (os) {
                byOsTotal[os] = (byOsTotal[os] || 0) + rowTotal;
            }
        }
    }

    view.days = Object.keys(dayMap).sort().map(date => ({
        date,
        total_tokens: dayMap[date]
    }));
    view.bySourceTotal = bySourceTotal;
    view.byOsTotal = byOsTotal;
    return view;
}

module.exports = { aggregateTokenUsage, KNOWN_SOURCES };