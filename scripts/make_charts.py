#!/usr/bin/env python3
"""Generate theme-aware inline-SVG charts as Hugo shortcodes from measured session data.

All figures come from /tmp/agent_snapshot.json + /tmp/chartdata.json, which were
frozen at the same message cut the article reports (351 messages / 168 API calls).
No raster images: SVG uses the site's CSS custom properties so charts follow
light/dark mode automatically.
"""
import json, os

SNAP = json.load(open('/tmp/agent_snapshot.json'))
CD   = json.load(open('/tmp/chartdata.json'))
OUT  = os.path.expanduser('~/projects/devtool-digest/layouts/shortcodes')
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- helpers
def fmt(n):
    return f"{n:,}"

def plate(x, y, text, cls="lbl", fs=12.5, anchor="start", pad=5):
    """Text with an opaque background plate so gridlines/curves never cross it.

    SVG has no text background, and paint-order tricks look like outlines.
    A rect sized from an em-width estimate is crude but deterministic.
    """
    w = len(text) * fs * 0.505
    if anchor == "middle":
        rx = x - w / 2
    elif anchor == "end":
        rx = x - w
    else:
        rx = x
    return (f'<rect x="{rx-pad:.1f}" y="{y-fs+1:.1f}" width="{w+pad*2:.1f}" '
            f'height="{fs+5:.1f}" fill="var(--entry)" opacity="0.93" rx="2"/>'
            f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="{cls}">{text}</text>')


def wrap(inner, title, subtitle, vb_w=680, vb_h=300):
    """Common figure chrome: caption above, SVG below, all theme-aware."""
    return f'''<figure class="chart">
  <figcaption class="chart-title">{title}</figcaption>
  <p class="chart-sub">{subtitle}</p>
  <div class="chart-scroll">
    <svg viewBox="0 0 {vb_w} {vb_h}" role="img" class="chart-svg"
         xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
{inner}
    </svg>
  </div>
</figure>'''

# ---------------------------------------------------------------- 1. integral
def chart_integral():
    curve = CD['curve']                      # [msg_i, minutes, cum_tokens]
    W, H = 680, 300
    L, R, T, B = 58, 18, 26, 42
    pw, ph = W - L - R, H - T - B
    max_min = curve[-1][1]
    max_tok = curve[-1][2]

    def X(m): return L + (m / max_min) * pw
    def Y(t): return T + ph - (t / max_tok) * ph

    pts = " ".join(f"{X(m):.1f},{Y(t):.1f}" for _, m, t in curve)
    area = f"{L},{T+ph} " + pts + f" {X(max_min):.1f},{T+ph}"

    # gridlines every 20k tokens
    grid = ""
    for gt in range(0, max_tok + 1, 20000):
        y = Y(gt)
        grid += (f'<line x1="{L}" y1="{y:.1f}" x2="{L+pw}" y2="{y:.1f}" '
                 f'stroke="var(--border)" stroke-width="1" stroke-dasharray="2 4"/>'
                 f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" class="ax">{gt//1000}K</text>')
    # x ticks every 15 min
    xt = ""
    for mm in range(0, int(max_min) + 1, 15):
        x = X(mm)
        xt += (f'<line x1="{x:.1f}" y1="{T+ph}" x2="{x:.1f}" y2="{T+ph+5}" stroke="var(--border)"/>'
               f'<text x="{x:.1f}" y="{T+ph+20}" text-anchor="middle" class="ax">{mm}m</text>')

    inner = f'''    {grid}{xt}
    <polygon points="{area}" fill="var(--accent)" opacity="0.16"/>
    <polyline points="{pts}" fill="none" stroke="var(--accent)" stroke-width="2.5"
              stroke-linejoin="round"/>
    <line x1="{L}" y1="{T+ph}" x2="{L+pw}" y2="{T+ph}" stroke="var(--secondary)" stroke-width="1.2"/>
    <!-- final height marker -->
    <line x1="{X(max_min):.1f}" y1="{Y(max_tok):.1f}" x2="{X(max_min):.1f}" y2="{T+ph}"
          stroke="var(--primary)" stroke-width="1.5" stroke-dasharray="3 3"/>
    <circle cx="{X(max_min):.1f}" cy="{Y(max_tok):.1f}" r="4" fill="var(--accent)"/>
    {plate(X(max_min)-8, Y(max_tok)-11, f"final history {fmt(max_tok)} tok", "lbl", 12.5, "end")}
    {plate(L+pw*0.30, T+ph*0.60, f"area = {SNAP['prompt_total']/1e6:.1f}M tokens billed", "lbl-big", 15, "middle")}
    {plate(L+pw*0.30, T+ph*0.60+18, f"history re-sent on every one of {SNAP['calls']} calls", "ax", 11.5, "middle")}'''
    return wrap(inner,
                "You pay for the area, not the height",
                f"Context size over {max_min:.0f} minutes. The curve ends at "
                f"{fmt(max_tok)} tokens — but every API call re-sends everything "
                f"below it, so the shaded area ({SNAP['prompt_total']/1e6:.1f}M tokens) is the real bill: "
                f"{SNAP['ratio']:.0f}x the final size.")

# ---------------------------------------------------------------- 2. pareto
def chart_pareto():
    par = CD['pareto']
    W, H = 680, 290
    L, R, T, B = 52, 18, 26, 42
    pw, ph = W - L - R, H - T - B
    def X(p): return L + p / 100 * pw
    def Y(p): return T + ph - p / 100 * ph

    pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in par)
    # marker: 5% of calls -> 50% of output
    m5 = next(b for a, b in par if a >= 5)
    grid = ""
    for g in (25, 50, 75, 100):
        y = Y(g)
        grid += (f'<line x1="{L}" y1="{y:.1f}" x2="{L+pw}" y2="{y:.1f}" stroke="var(--border)" '
                 f'stroke-width="1" stroke-dasharray="2 4"/>'
                 f'<text x="{L-8}" y="{y+4:.1f}" text-anchor="end" class="ax">{g}%</text>')
    xt = ""
    for g in (0, 25, 50, 75, 100):
        x = X(g)
        xt += (f'<text x="{x:.1f}" y="{T+ph+20}" text-anchor="middle" class="ax">{g}%</text>')

    inner = f'''    {grid}{xt}
    <line x1="{L}" y1="{T+ph}" x2="{L+pw}" y2="{T}" stroke="var(--secondary)"
          stroke-width="1" stroke-dasharray="4 4" opacity="0.5"/>
    {plate(L+pw*0.70, T+ph*0.26, "perfectly even would be this line", "ax", 11.5)}
    <polyline points="{pts}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>
    <line x1="{X(5):.1f}" y1="{Y(m5):.1f}" x2="{X(5):.1f}" y2="{T+ph}"
          stroke="var(--primary)" stroke-width="1.4" stroke-dasharray="3 3"/>
    <line x1="{L}" y1="{Y(m5):.1f}" x2="{X(5):.1f}" y2="{Y(m5):.1f}"
          stroke="var(--primary)" stroke-width="1.4" stroke-dasharray="3 3"/>
    <circle cx="{X(5):.1f}" cy="{Y(m5):.1f}" r="4.5" fill="var(--accent)"/>
    <line x1="{X(5)+5:.1f}" y1="{Y(m5)+4:.1f}" x2="{X(12):.1f}" y2="{Y(m5)+26:.1f}"
          stroke="var(--secondary)" stroke-width="1" opacity="0.7"/>
    {plate(X(12)+4, Y(m5)+30, f"9 of {CD['n_tool']} results (5%) = {m5:.0f}% of all tool output", "lbl", 12.5)}
    <line x1="{L}" y1="{T+ph}" x2="{L+pw}" y2="{T+ph}" stroke="var(--secondary)" stroke-width="1.2"/>
    <text x="{L+pw/2:.1f}" y="{H-6}" text-anchor="middle" class="ax">share of tool calls, largest first</text>'''
    return wrap(inner,
                "A handful of tool calls eat the context window",
                f"Cumulative share of tool output. {CD['n_tool']} tool results, "
                f"but the top 5% produced half the bytes the model re-reads on every call.",
                W, H)

# ---------------------------------------------------------------- 3. token mix
def chart_tokenmix():
    W, H = 680, 176
    L, R = 20, 20
    bw = W - L - R
    cr, cw, ti = SNAP['tcr'], SNAP['tcw'], SNAP['ti']
    tot = cr + cw + ti
    w_cr, w_cw = bw * cr / tot, bw * cw / tot
    w_ti = max(bw * ti / tot, 1.0)
    y = 54
    inner = f'''    <rect x="{L}" y="{y}" width="{w_cr:.2f}" height="46" fill="var(--accent)" rx="3"/>
    <rect x="{L+w_cr:.2f}" y="{y}" width="{max(w_cw,2):.2f}" height="46" fill="var(--accent)" opacity="0.45"/>
    <rect x="{L+w_cr+w_cw:.2f}" y="{y}" width="{w_ti:.2f}" height="46" fill="var(--primary)"/>
    <text x="{L+w_cr/2:.1f}" y="{y+29}" text-anchor="middle" class="bar-in">{cr/tot*100:.1f}% cache reads</text>
    <text x="{L}" y="{y-12}" class="ax">{fmt(tot)} prompt tokens, by billing class</text>
    <text x="{L+w_cr+2:.1f}" y="{y+62}" class="ax">cache writes {fmt(cw)} ({cw/tot*100:.2f}%)</text>
    <text x="{L+w_cr+2:.1f}" y="{y+78}" class="ax">fresh input {fmt(ti)} tokens ({ti/tot*100:.4f}%) — the only genuinely new bytes</text>
    <text x="{L}" y="{y+108}" class="lbl">Cache reads bill at 0.1x input rate. Break the prefix and this bar turns 10x more expensive.</text>'''
    return wrap(inner,
                "96% of what you send is a re-read",
                "Of 21.4M prompt tokens, 336 were new. Everything else was the "
                "conversation being replayed to a stateless model.", W, H)

# ---------------------------------------------------------------- 4. tool budget
def chart_toolbudget():
    data = SNAP['by_tool']          # (name, n, avg, sum, pct)
    W = 680
    rowh, top = 40, 40
    H = top + rowh * len(data) + 26
    L, R = 112, 58          # R reserves room for the % label inside the viewBox
    bw = W - L - R
    mx = max(d[3] for d in data)
    rows = ""
    for i, (name, n, avg, s, pct) in enumerate(data):
        y = top + i * rowh
        w = bw * s / mx
        rows += f'''<text x="{L-10}" y="{y+19}" text-anchor="end" class="lbl-mono">{name}</text>
    <rect x="{L}" y="{y+4}" width="{w:.1f}" height="21" fill="var(--accent)" rx="2"
          opacity="{0.95 - i*0.17:.2f}"/>
    <text x="{L+w+8:.1f}" y="{y+20}" class="lbl">{pct}%</text>
'''
    inner = f'''    <text x="{L-10}" y="24" text-anchor="end" class="ax">tool</text>
    <text x="{L}" y="24" class="ax">share of all tool output ({fmt(SNAP['tool_chars'])} chars) — calls &amp; averages in table below</text>
    {rows}    <text x="{L}" y="{H-6}" class="lbl">skill_view: 5 calls, 26% of the budget — loading docs feels free, it isn't.</text>'''
    return wrap(inner, "Where the context budget actually goes",
                "Tool output is 91.7% of accumulated history. Two tools account for "
                "nearly two thirds of it.", W, H)

# ---------------------------------------------------------------- 5. cost
def chart_cost():
    W, H = 680, 190
    L = 132
    bw = W - L - 108
    a, b = SNAP['cached_cost'], SNAP['naive_cost']
    wa, wb = bw * a / b, bw
    inner = f'''    <text x="{L-10}" y="52" text-anchor="end" class="lbl-mono">with caching</text>
    <rect x="{L}" y="34" width="{wa:.1f}" height="26" fill="var(--accent)" rx="3"/>
    {plate(L+wa+9, 52, f"${a:.2f}", "lbl", 12.5)}

    <text x="{L-10}" y="100" text-anchor="end" class="lbl-mono">no caching</text>
    <rect x="{L}" y="82" width="{wb:.1f}" height="26" fill="var(--secondary)" rx="3" opacity="0.55"/>
    <text x="{L+wb+9:.1f}" y="100" class="lbl">${b:.2f}</text>

    <line x1="{L+wa:.1f}" y1="30" x2="{L+wa:.1f}" y2="116" stroke="var(--primary)"
          stroke-width="1.2" stroke-dasharray="3 3"/>
    <text x="{L}" y="144" class="lbl">Same {SNAP['prompt_total']/1e6:.1f}M tokens, same work — {SNAP['mult']:.1f}x the cost.</text>
    <text x="{L}" y="164" class="ax">Sonnet-class list rates applied to measured token counts. Illustrative, not an invoice.</text>'''
    return wrap(inner, "Prompt caching was worth 6x on this session",
                "Cache reads price at 0.1x input; writes at 1.25x. The whole saving "
                "depends on never mutating the front of the context.", W, H)

# ---------------------------------------------------------------- write
charts = {
    'chart-integral.html':   chart_integral(),
    'chart-pareto.html':     chart_pareto(),
    'chart-tokenmix.html':   chart_tokenmix(),
    'chart-toolbudget.html': chart_toolbudget(),
    'chart-cost.html':       chart_cost(),
}
for fn, svg in charts.items():
    with open(os.path.join(OUT, fn), 'w') as f:
        f.write(svg + "\n")
    print(f"wrote {fn:26} {len(svg):>6} bytes")
