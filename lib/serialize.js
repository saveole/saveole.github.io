/**
 * Serialize a value for embedding inside an inline <script> block.
 *
 * Plain JSON.stringify can be broken (or exploited) by content that closes
 * the script tag, e.g. a post titled `</script><img onerror=...>`. Escaping
 * `<`, `>` and `&` as unicode escapes keeps the payload valid JSON while
 * making it inert to the HTML parser. U+2028/U+2029 are also escaped because
 * they are line terminators in older JS engines (and invalid raw in JSON
 * text contexts).
 */
function toScriptJson(value) {
    return JSON.stringify(value)
        .replace(/</g, '\\u003c')
        .replace(/>/g, '\\u003e')
        .replace(/&/g, '\\u0026')
        .replace(/\u2028/g, '\\u2028')
        .replace(/\u2029/g, '\\u2029');
}

module.exports = { toScriptJson };
