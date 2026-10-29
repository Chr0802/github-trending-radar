"""生成层：深色 tech 风单文件 HTML（最新 index / 当期报告 / archive 历史索引）。

设计参考 design-taste-plus：
- 单一 accent（teal）+ 单一圆角体系，避免 AI 紫渐变与等分卡片堆叠
- editorial 布局：hero 统计条 + 左榜单 + 右侧粘性面板
- 纯静态、无外部字体/CDN，Caddy 直接托管
"""
from __future__ import annotations

import html
import os
from collections import Counter

BG = "#070a0f"
SURFACE = "#0f141c"
SURFACE2 = "#151c26"
LINE = "#1e2836"
TEXT = "#e6edf3"
MUTED = "#8b98a9"
ACCENT = "#5eead4"
STAR = "#f5b942"
RISK = "#f87171"
OK = "#4ade80"


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _stars(r: dict) -> int:
    try:
        return int(r.get("stars_total") or r.get("stars_period") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _badges(r: dict) -> str:
    b = []
    tier = r.get("star_tier")
    if tier:
        b.append(f'<span class="badge tier">{_esc(tier)}</span>')
    if r.get("archived"):
        b.append('<span class="badge risk">已归档</span>')
    dom = r.get("domain")
    if dom and dom != "综合/其他":
        b.append(f'<span class="badge dom">{_esc(dom)}</span>')
    if r.get("is_new"):
        b.append('<span class="badge new">新上榜</span>')
    st = r.get("streak")
    if st and st >= 2 and not r.get("is_new"):
        b.append(f'<span class="badge streak">连续 {st} 天</span>')
    for f in r.get("hype_flags", []) or []:
        b.append(f'<span class="badge risk">{_esc(f)}</span>')
    return "".join(b)


def _highlights(r: dict) -> str:
    items = [h for h in (r.get("highlights") or []) if h]
    if not items:
        return ""
    lis = "".join(f"<li>{_esc(h)}</li>" for h in items[:4])
    return f'<ul class="highlights">{lis}</ul>'


def _pm_block(r: dict) -> str:
    txt = (r.get("pm_insight") or "").strip()
    if not txt:
        return ""
    return (
        '<div class="pm"><span class="pm-tag">产品经理视角</span>'
        f"<p>{_esc(txt)}</p></div>"
    )


def _card(r: dict, idx: int) -> str:
    stars = _stars(r)
    stars_s = f"{stars:,}"
    return f"""
    <article class="item">
      <div class="rank">{idx + 1:02d}</div>
      <div class="main">
        <div class="head">
          <a class="name" href="{_esc(r.get('html_url', '#'))}" target="_blank" rel="noopener">{_esc(r.get('full_name'))}</a>
          <span class="lang">{_esc(r.get('language') or '—')}</span>
        </div>
        <div class="badges">{_badges(r)}</div>
        <p class="summary">{_esc(r.get('summary', ''))}</p>
        {_highlights(r)}
        {_pm_block(r)}
        <div class="metrics">
          <span><b>{stars_s}</b> stars</span>
          <span>{_esc(r.get('license') or '许可证未声明')}</span>
          <span>{_esc(r.get('active') or '—')}</span>
        </div>
      </div>
    </article>"""


def _stats(repos: list[dict]) -> dict:
    domains = {r.get("domain") for r in repos if r.get("domain") and r.get("domain") != "综合/其他"}
    return {
        "count": len(repos),
        "domains": len(domains),
        "new": sum(1 for r in repos if r.get("is_new")),
        "stars": sum(_stars(r) for r in repos),
    }


def _domain_bars(repos: list[dict]) -> str:
    counter = Counter(
        r.get("domain") for r in repos if r.get("domain") and r.get("domain") != "综合/其他"
    )
    if not counter:
        return '<p class="empty">本期无明确领域标签</p>'
    top = counter.most_common(6)
    max_n = top[0][1]
    rows = []
    for name, n in top:
        pct = max(6, round(n / max_n * 100))
        rows.append(
            f'<div class="bar-row"><div class="bar-top"><span>{_esc(name)}</span><b>{n}</b></div>'
            f'<div class="bar"><i style="width:{pct}%"></i></div></div>'
        )
    return "".join(rows)


def _css() -> str:
    return f"""
    :root {{
      --bg:{BG}; --surface:{SURFACE}; --surface-2:{SURFACE2}; --line:{LINE};
      --text:{TEXT}; --muted:{MUTED}; --accent:{ACCENT}; --star:{STAR};
      --risk:{RISK}; --ok:{OK}; --radius:16px; --radius-sm:10px;
      --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin:0; color:var(--text); line-height:1.65;
      font-family: "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", -apple-system, "Segoe UI", Roboto, sans-serif;
      background:
        radial-gradient(1100px 560px at 12% -12%, rgba(94,234,212,.07), transparent 62%),
        radial-gradient(900px 520px at 92% -4%, rgba(56,189,248,.05), transparent 58%),
        var(--bg);
      -webkit-font-smoothing: antialiased;
    }}
    a {{ color:inherit; text-decoration:none; }}
    .page {{ max-width:1120px; margin:0 auto; padding:0 24px 72px; }}

    .bar {{ display:flex; align-items:center; justify-content:space-between; padding:22px 0 10px; }}
    .brand {{ display:flex; align-items:center; gap:9px; font-weight:650; letter-spacing:-.01em; }}
    .dot {{ width:8px; height:8px; border-radius:50%; background:var(--accent); box-shadow:0 0 14px rgba(94,234,212,.8); }}
    .bar nav {{ display:flex; gap:18px; font-size:13.5px; color:var(--muted); }}
    .bar nav a:hover {{ color:var(--accent); }}

    .hero {{ padding:34px 0 30px; border-bottom:1px solid var(--line); }}
    .eyebrow {{
      font:600 11.5px/1 var(--mono); letter-spacing:.16em; text-transform:uppercase;
      color:var(--accent); margin-bottom:16px;
    }}
    .hero h1 {{
      margin:0; font-size:clamp(30px, 4.6vw, 50px); line-height:1.08; letter-spacing:-.035em; font-weight:680;
    }}
    .hero h1 em {{ font-style:normal; color:var(--accent); }}
    .lede {{ margin:14px 0 26px; max-width:620px; font-size:14.5px; color:var(--muted); }}
    .stats {{ display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:10px; }}
    .stat {{
      background:linear-gradient(180deg, var(--surface), rgba(15,20,28,.55));
      border:1px solid var(--line); border-radius:var(--radius-sm); padding:14px 16px;
    }}
    .stat b {{
      display:block; font:650 26px/1.1 var(--mono); letter-spacing:-.02em;
      font-variant-numeric:tabular-nums;
    }}
    .stat b.amber {{ color:var(--star); }}
    .stat span {{ display:block; margin-top:5px; font-size:12px; color:var(--muted); }}

    .grid {{ display:grid; grid-template-columns:minmax(0,1fr) 292px; gap:30px; margin-top:34px; align-items:start; }}
    .feed {{ display:flex; flex-direction:column; gap:14px; }}

    .item {{
      display:grid; grid-template-columns:54px minmax(0,1fr); gap:16px;
      padding:20px 20px 18px; border:1px solid var(--line); border-radius:var(--radius);
      background:linear-gradient(180deg, var(--surface), rgba(15,20,28,.6));
      transition:border-color .18s ease, transform .18s ease, box-shadow .18s ease;
    }}
    .item:hover {{
      border-color:rgba(94,234,212,.42); transform:translateY(-2px);
      box-shadow:0 16px 38px -18px rgba(0,0,0,.75);
    }}
    .rank {{
      font:650 13px/1 var(--mono); color:var(--muted);
      padding-top:5px; letter-spacing:.04em;
    }}
    .item:hover .rank {{ color:var(--accent); }}
    .head {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
    .name {{ font-size:19px; font-weight:660; letter-spacing:-.015em; word-break:break-all; }}
    .name:hover {{ color:var(--accent); }}
    .lang {{
      font:500 11.5px/1 var(--mono); color:var(--muted);
      border:1px solid var(--line); border-radius:999px; padding:3px 9px;
    }}
    .badges {{ margin:9px 0 2px; }}
    .badge {{
      display:inline-block; font-size:11.5px; padding:3px 9px; border-radius:999px;
      margin:0 6px 5px 0; border:1px solid var(--line); color:var(--muted);
      background:rgba(21,28,38,.7);
    }}
    .badge.tier {{ color:var(--star); border-color:rgba(245,185,66,.35); }}
    .badge.dom {{ color:var(--accent); border-color:rgba(94,234,212,.3); }}
    .badge.risk {{ color:var(--risk); border-color:rgba(248,113,113,.35); }}
    .badge.new, .badge.streak {{ color:var(--ok); border-color:rgba(74,222,128,.35); }}

    .summary {{ margin:10px 0 0; font-size:14.5px; line-height:1.78; color:#c3ccd8; }}
    .highlights {{ list-style:none; padding:0; margin:12px 0 0; display:flex; flex-wrap:wrap; gap:8px; }}
    .highlights li {{
      font-size:12.5px; color:var(--accent); background:rgba(94,234,212,.07);
      border:1px solid rgba(94,234,212,.2); border-radius:8px; padding:4px 10px;
    }}
    .pm {{
      margin-top:14px; padding:12px 14px; border-left:2px solid var(--accent);
      background:rgba(94,234,212,.04); border-radius:0 var(--radius-sm) var(--radius-sm) 0;
    }}
    .pm-tag {{
      display:block; font:600 10.5px/1 var(--mono); letter-spacing:.14em;
      text-transform:uppercase; color:var(--accent); margin-bottom:6px;
    }}
    .pm p {{ margin:0; font-size:13.5px; line-height:1.72; color:#c3ccd8; }}
    .metrics {{
      display:flex; gap:20px; margin-top:14px; font-size:12.5px; color:var(--muted);
      font-variant-numeric:tabular-nums;
    }}
    .metrics b {{ color:var(--text); font-weight:600; }}

    .side {{ position:sticky; top:20px; display:flex; flex-direction:column; gap:14px; }}
    .panel {{
      background:var(--surface); border:1px solid var(--line);
      border-radius:var(--radius); padding:18px 18px 16px;
    }}
    .panel h3 {{
      margin:0 0 14px; font:600 11.5px/1 var(--mono);
      letter-spacing:.15em; text-transform:uppercase; color:var(--muted);
    }}
    .bar-row {{ margin-bottom:12px; }}
    .bar-row:last-child {{ margin-bottom:0; }}
    .bar-top {{ display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:6px; }}
    .bar-top b {{ color:var(--accent); font-variant-numeric:tabular-nums; }}
    .bar {{ height:5px; border-radius:999px; background:var(--surface-2); overflow:hidden; }}
    .bar i {{ display:block; height:100%; border-radius:999px; background:linear-gradient(90deg, var(--accent), #38bdf8); }}
    .note {{ margin:0; font-size:12.5px; color:var(--muted); line-height:1.7; }}
    .note b {{ color:var(--text); font-weight:600; }}

    .archive-item {{
      display:flex; align-items:center; justify-content:space-between; gap:16px;
      padding:16px 18px; margin-bottom:10px; border:1px solid var(--line);
      border-radius:var(--radius-sm); background:var(--surface);
      transition:border-color .18s ease, transform .18s ease;
    }}
    .archive-item:hover {{ border-color:rgba(94,234,212,.42); transform:translateY(-1px); }}
    .archive-item .d {{ font:600 15px/1 var(--mono); letter-spacing:-.01em; }}
    .archive-item .m {{ margin-top:6px; font-size:12.5px; color:var(--muted); }}
    .archive-item .go {{ font-size:13px; color:var(--accent); white-space:nowrap; }}
    .empty {{ margin:0; font-size:13px; color:var(--muted); }}

    footer {{
      margin-top:52px; padding-top:20px; border-top:1px solid var(--line);
      font-size:12px; color:var(--muted); display:flex; justify-content:space-between; gap:16px; flex-wrap:wrap;
    }}

    @media (max-width: 900px) {{
      .grid {{ grid-template-columns:1fr; }}
      .side {{ position:static; order:2; }}
      .stats {{ grid-template-columns:repeat(2, minmax(0,1fr)); }}
    }}
    @media (max-width: 560px) {{
      .page {{ padding:0 16px 56px; }}
      .item {{ grid-template-columns:1fr; gap:10px; padding:18px; }}
      .rank {{ padding-top:0; }}
      .metrics {{ flex-wrap:wrap; gap:12px; }}
    }}
    """


def _head(title: str, date_str: str, stats: dict, is_latest: bool) -> str:
    nav = (
        '<a href="../index.html">最新</a><a href="../archive.html">历史存档</a>'
        if not is_latest
        else f'<a href="archive.html">历史存档</a><a href="reports/{_esc(date_str)}.html">本期固定链接</a>'
    )
    return f"""
  <header class="bar">
    <div class="brand"><span class="dot"></span> GitHub 热门雷达</div>
    <nav>{nav}</nav>
  </header>
  <section class="hero">
    <div class="eyebrow">Daily Digest · {_esc(date_str)}</div>
    <h1>今天值得看的<br><em>{stats['count']} 个开源项目</em></h1>
    <p class="lede">从 OSS Insight 与 GitHub Search 采集，结合 README 提炼核心能力与技术亮点。每日一期，跨期追踪新上榜与连续在榜。</p>
    <div class="stats">
      <div class="stat"><b>{stats['count']}</b><span>本期项目</span></div>
      <div class="stat"><b>{stats['domains']}</b><span>覆盖领域</span></div>
      <div class="stat"><b>{stats['new']}</b><span>新上榜</span></div>
      <div class="stat"><b class="amber">{stats['stars']:,}</b><span>累计 stars</span></div>
    </div>
  </section>"""


def build_report_html(repos: list[dict], date_str: str, is_latest: bool = False) -> str:
    stats = _stats(repos)
    cards = "\n".join(_card(r, i) for i, r in enumerate(repos))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>GitHub 热门雷达 · {_esc(date_str)}</title>
<style>{_css()}</style></head>
<body><div class="page">
{_head("GitHub 热门雷达", date_str, stats, is_latest)}
  <main class="grid">
    <section class="feed">
      {cards}
    </section>
    <aside class="side">
      <div class="panel">
        <h3>领域分布</h3>
        {_domain_bars(repos)}
      </div>
      <div class="panel">
        <h3>阅读说明</h3>
        <p class="note">
          <b>新上榜</b> 表示上一期未出现；<b>连续 N 天</b> 表示跨期持续在榜。<br><br>
          摘要由模型结合 README 生成，可能包含概括性表述；红旗标签用于提示停更、营销化等风险。
        </p>
      </div>
    </aside>
  </main>
  <footer>
    <span>由 github-trending-radar 自动生成 · {_esc(date_str)}</span>
    <span>数据来源：OSS Insight · GitHub Search API</span>
  </footer>
</div></body></html>"""


def build_archive_html(history: dict) -> str:
    items = []
    for d in sorted(history.keys(), reverse=True):
        rec = history[d]
        n = len(rec.get("repos", []))
        link = rec.get("report_path", f"reports/{d}.html")
        # 兼容旧数据：历史记录里可能带 output/ 前缀（部署后应相对站点根）
        if link.startswith("output/"):
            link = link[len("output/"):]
        items.append(
            f'<div class="archive-item"><div><div class="d">{_esc(d)}</div>'
            f'<div class="m">共 {n} 个热门项目</div></div>'
            f'<a class="go" href="{_esc(link)}">查看 →</a></div>'
        )
    items_html = "\n".join(items) if items else '<p class="empty">暂无历史存档。</p>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>历史存档 · GitHub 热门雷达</title>
<style>{_css()}</style></head>
<body><div class="page">
  <header class="bar">
    <div class="brand"><span class="dot"></span> GitHub 热门雷达</div>
    <nav><a href="index.html">最新</a></nav>
  </header>
  <section class="hero">
    <div class="eyebrow">Archive</div>
    <h1>历史<em>存档</em></h1>
    <p class="lede">每日一期，可回看任意往期的热门榜单与深度摘要。</p>
  </section>
  <main style="margin-top:34px">
    {items_html}
  </main>
  <footer>
    <span>由 github-trending-radar 自动生成</span>
    <span>共 {len(history)} 期</span>
  </footer>
</div></body></html>"""


def write_all(repos: list[dict], date_str: str, history: dict, output_dir: str, report_dir: str) -> None:
    os.makedirs(report_dir, exist_ok=True)
    with open(os.path.join(output_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_report_html(repos, date_str, is_latest=True))
    with open(os.path.join(report_dir, f"{date_str}.html"), "w", encoding="utf-8") as f:
        f.write(build_report_html(repos, date_str, is_latest=False))
    with open(os.path.join(output_dir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(build_archive_html(history))
