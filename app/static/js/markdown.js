/**
 * Lightweight, XSS-safe Markdown renderer for Playground assistant responses.
 * Escapes all raw HTML first, then formats fenced code blocks, inline code,
 * headings, lists, blockquotes, bold/italic, and HTTPS links.
 */

function escapeHtml(str) {
    return String(str ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function renderInline(escaped) {
    const codeTokens = [];
    let out = escaped.replace(/`([^`\n]+)`/g, (_, code) => {
        const idx = codeTokens.length;
        codeTokens.push(`<code class="md-inline-code">${code}</code>`);
        return `\u0000IC${idx}\u0000`;
    });

    // Bold & Italic
    out = out.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

    // Safe links (https:// or http://)
    out = out.replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer" class="md-link">$1</a>'
    );

    out = out.replace(/\u0000IC(\d+)\u0000/g, (_, idx) => codeTokens[Number(idx)]);
    return out;
}

function renderTextSegment(rawText) {
    const lines = rawText.split(/\r?\n/);
    const htmlParts = [];
    let inUl = false;
    let inOl = false;

    const closeLists = () => {
        if (inUl) {
            htmlParts.push("</ul>");
            inUl = false;
        }
        if (inOl) {
            htmlParts.push("</ol>");
            inOl = false;
        }
    };

    for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed) {
            closeLists();
            continue;
        }

        const hMatch = trimmed.match(/^(#{1,3})\s+(.+)$/);
        if (hMatch) {
            closeLists();
            const level = hMatch[1].length;
            htmlParts.push(`<h${level} class="md-h${level}">${renderInline(escapeHtml(hMatch[2]))}</h${level}>`);
            continue;
        }

        if (trimmed.startsWith("> ")) {
            closeLists();
            htmlParts.push(`<blockquote class="md-quote">${renderInline(escapeHtml(trimmed.slice(2)))}</blockquote>`);
            continue;
        }

        const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
        if (ulMatch) {
            if (inOl) {
                htmlParts.push("</ol>");
                inOl = false;
            }
            if (!inUl) {
                htmlParts.push('<ul class="md-list">');
                inUl = true;
            }
            htmlParts.push(`<li>${renderInline(escapeHtml(ulMatch[1]))}</li>`);
            continue;
        }

        const olMatch = trimmed.match(/^\d+\.\s+(.+)$/);
        if (olMatch) {
            if (inUl) {
                htmlParts.push("</ul>");
                inUl = false;
            }
            if (!inOl) {
                htmlParts.push('<ol class="md-list">');
                inOl = true;
            }
            htmlParts.push(`<li>${renderInline(escapeHtml(olMatch[1]))}</li>`);
            continue;
        }

        closeLists();
        htmlParts.push(`<p class="md-p">${renderInline(escapeHtml(line))}</p>`);
    }

    closeLists();
    return htmlParts.join("");
}

export function renderMarkdown(raw) {
    const text = String(raw ?? "");
    if (!text.trim()) return "";

    const fenceRe = /```([a-zA-Z0-9_+-]*)\r?\n([\s\S]*?)```/g;
    const parts = [];
    let lastIndex = 0;
    let match;

    while ((match = fenceRe.exec(text)) !== null) {
        if (match.index > lastIndex) {
            parts.push(renderTextSegment(text.slice(lastIndex, match.index)));
        }
        const lang = match[1] || "text";
        const codeContent = match[2].replace(/\n$/, "");
        const escapedCode = escapeHtml(codeContent);
        parts.push(
            `<div class="md-code-wrap">` +
            `<div class="md-code-header"><span>${escapeHtml(lang)}</span><button type="button" class="btn btn-icon md-copy-code">Copy</button></div>` +
            `<pre><code>${escapedCode}</code></pre>` +
            `</div>`
        );
        lastIndex = fenceRe.lastIndex;
    }

    if (lastIndex < text.length) {
        parts.push(renderTextSegment(text.slice(lastIndex)));
    }

    return `<div class="md-body">${parts.join("")}</div>`;
}
