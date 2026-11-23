/**
 * Zero-dependency flat SVG charts following data-terminal styling.
 */

export function renderTrafficChart(container, hourlyBuckets) {
    if (!container) return;

    if (!hourlyBuckets || hourlyBuckets.length === 0) {
        container.innerHTML = `<div class="chart-empty">Belum ada data trafik 24 jam terakhir.</div>`;
        return;
    }

    const totalSum = hourlyBuckets.reduce((acc, b) => acc + (b.requests || 0), 0);
    if (totalSum === 0) {
        container.innerHTML = `<div class="chart-empty">0 request tercatat dalam 24 jam terakhir.</div>`;
        return;
    }

    const width = 640;
    const height = 190;
    const padLeft = 36;
    const padRight = 10;
    const padTop = 14;
    const padBottom = 24;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;

    const maxVal = Math.max(4, ...hourlyBuckets.map((b) => b.requests || 0));
    const step = Math.ceil(maxVal / 4);
    const yMax = step * 4;

    const gridLines = [];
    for (let i = 0; i <= 4; i++) {
        const val = i * step;
        const y = padTop + plotH - (val / yMax) * plotH;
        gridLines.push(
            `<line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="#232732" stroke-width="1" />` +
            `<text x="${padLeft - 8}" y="${y + 4}" text-anchor="end" fill="#606776" font-size="10.5" font-family="JetBrains Mono, monospace">${val}</text>`
        );
    }

    const barGap = 4;
    const barW = Math.max(4, plotW / hourlyBuckets.length - barGap);
    const bars = hourlyBuckets.map((bucket, idx) => {
        const count = bucket.requests || 0;
        const barH = count > 0 ? Math.max(3, (count / yMax) * plotH) : 1;
        const x = padLeft + idx * (plotW / hourlyBuckets.length) + barGap / 2;
        const y = padTop + plotH - barH;
        const dt = new Date(bucket.timestamp * 1000);
        const hourLabel = dt.getHours().toString().padStart(2, "0") + ":00";
        const fill = count > 0 ? "#10b981" : "#232732";

        const xTick =
            idx % 6 === 0
                ? `<text x="${x + barW / 2}" y="${height - 5}" text-anchor="middle" fill="#606776" font-size="10.5" font-family="JetBrains Mono, monospace">${hourLabel}</text>`
                : "";

        return (
            `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${barH.toFixed(1)}" rx="2" fill="${fill}">` +
            `<title>${hourLabel} — ${count} req (${(bucket.tokens || 0).toLocaleString()} tokens)</title>` +
            `</rect>` +
            xTick
        );
    });

    container.innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="190" preserveAspectRatio="none">
            ${gridLines.join("")}
            ${bars.join("")}
        </svg>
    `;
}

export function renderModelBreakdown(container, breakdown) {
    if (!container) return;

    if (!breakdown || breakdown.length === 0) {
        container.innerHTML = `<div class="chart-empty">Belum ada distribusi model yang tercatat.</div>`;
        return;
    }

    const rows = breakdown.slice(0, 6).map((item) => {
        return `
            <div class="bar-row">
                <div class="bar-row-top">
                    <span class="mono" style="color: var(--text);">${escapeHtml(item.model)}</span>
                    <span class="tabular" style="color: var(--text-muted);">${item.requests} req · ${item.pct}%</span>
                </div>
                <div class="bar-track">
                    <div class="bar-fill" style="width: ${Math.max(2, item.pct)}%;"></div>
                </div>
            </div>
        `;
    });

    container.innerHTML = `<div class="bar-list">${rows.join("")}</div>`;
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
