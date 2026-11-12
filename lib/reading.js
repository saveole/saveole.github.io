const fs = require('fs');
const path = require('path');
const { toScriptJson } = require('./serialize');

function buildReadingPageData(dir) {
    if (!fs.existsSync(dir)) return null;

    const booksRaw = JSON.parse(fs.readFileSync(path.join(dir, 'books.json'), 'utf-8'));
    const quotesRaw = JSON.parse(fs.readFileSync(path.join(dir, 'quotes.json'), 'utf-8'));

    const currentYear = String(new Date().getFullYear());
    const stats = {
        total: booksRaw.length,
        reading: booksRaw.filter(b => b.status === 'reading').length,
        finished: booksRaw.filter(b => b.status === 'finished').length,
        wishlist: booksRaw.filter(b => b.status === 'wishlist').length,
        yearFinished: booksRaw.filter(b => b.status === 'finished' && b.finished_at && b.finished_at.startsWith(currentYear)).length
    };

    return {
        booksJSON: toScriptJson(booksRaw),
        quotesJSON: toScriptJson(quotesRaw),
        statsJSON: toScriptJson(stats)
    };
}

module.exports = { buildReadingPageData };