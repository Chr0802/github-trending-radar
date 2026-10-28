"""生成层：深色单文件 HTML（最新 index / 当期报告 / archive 历史索引）。

风格对齐工作区约定：深蓝灰底、Caddy 友好的纯静态结构。
generate 只负责渲染，跨期 diff（is_new / streak）由 run.py 注入到 repo dict。
"""
from __future__ import annotations

import html
import os

BG = "#0d1117"
CARD = "#161b22"
CARD2 = "#21262d"
TEXT = "#e6edf3"
MUTED = "#8b949e"
ACCENT = "#58a6ff"
STAR = "#e3b341"
RISK = "#f85149"
GREEN = "#3fb950"


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


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
        b.append('<span class="badge new">🆕 新上榜</span>')
    st = r.get("streak")
    if st and st >= 2 and not r.get("is_new"):
        b.append(f'<span class="badge streak">🔥 连续 {st} 天</span>')
    for f in r.get("hype_flags", []) or []:
        b.append(f'<span class="badge risk">{_esc(f)}</span>')
    return "".join(b)


def _card(r: dict, idx: int) -> str:
    stars = r.get("stars_total") or r.get("stars_period") or 0
    try:
        stars_s = f"{int(stars):,}"
    except Exception:  # noqa: BLE001
        stars_s = str(stars)
    return f"""
    <div class="card">
      <div class="rank">#{idx + 1}</div>
      <div class="body">
        <div class="title"><a href="{_esc(r.get('html_url', '#'))}" target="_blank" rel="noopener">{_esc(r.get('full_name'))}</a></div>
        <div class="meta">{_esc(r.get('language') or '—')} · ⭐ {stars_s} · {_esc(r.get('active', ''))} · 许可证 {_esc(r.get('license') or '未声明')}</div>
        <div class="badges">{_badges(r)}</div>
        <div class="summary">{_esc(r.get('summary', ''))}</div>
      </div>
    </div>"""


def _css() -> str:
    return f"""
    * {{ box-sizing: border-box; }}
    body {{ margin:0; background:{BG}; color:{TEXT}; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.6; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 32px 20px 80px; }}
    h1 {{ font-size: 26px; margin: 0 0 4px; }}
    .sub {{ color:{MUTED}; font-size: 14px; margin-bottom: 24px; }}
    a {{ color:{ACCENT}; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .nav {{ margin-bottom: 28px; }}
    .nav a {{ margin-right: 16px; font-size: 14px; }}
    .card {{ display:flex; gap:14px; background:{CARD}; border:1px solid {CARD2}; border-radius:12px; padding:16px 18px; margin-bottom:14px; }}
    .rank {{ font-size:20px; font-weight:700; color:{STAR}; min-width:42px; }}
    .body {{ flex:1; min-width:0; }}
    .title {{ font-size:18px; font-weight:600; word-break:break-all; }}
    .meta {{ color:{MUTED}; font-size:13px; margin:4px 0 8px; }}
    .badges {{ margin-bottom:8px; }}
    .badge {{ display:inline-block; font-size:12px; padding:2px 8px; border-radius:999px; margin:0 6px 4px 0; background:{CARD2}; color:{TEXT}; border:1px solid #30363d; }}
    .badge.tier {{ color:{STAR}; border-color:{STAR}; }}
    .badge.dom {{ color:{ACCENT}; border-color:{ACCENT}; }}
    .badge.risk {{ color:{RISK}; border-color:{RISK}; }}
    .badge.new, .badge.streak {{ color:{GREEN}; border-color:{GREEN}; }}
    .summary {{ font-size:14px; color:#c9d1d9; }}
    .archive-item {{ display:flex; justify-content:space-between; align-items:center; background:{CARD}; border:1px solid {CARD2}; border-radius:10px; padding:12px 16px; margin-bottom:10px; }}
    .archive-item .d {{ font-weight:600; }}
    .archive-item .m {{ color:{MUTED}; font-size:13px; }}
    footer {{ color:{MUTED}; font-size:12px; margin-top:40px; text-align:center; }}
    """


def build_report_html(repos: list[dict], date_str: str, is_latest: bool = False) -> str:
    cards = "\n".join(_card(r, i) for i, r in enumerate(repos))
    nav = '<div class="nav"><a href="index.html">最新</a><a href="archive.html">历史存档</a></div>' if not is_latest \
        else '<div class="nav"><a href="archive.html">历史存档</a><a href="reports/' + date_str + '.html">本期固定链接</a></div>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GitHub 热门雷达 · {_esc(date_str)}</title>
<style>{_css()}</style></head>
<body><div class="wrap">
  <h1>GitHub 热门雷达</h1>
  <div class="sub">每日热门开源项目 · 采集于 {_esc(date_str)} · 共 {len(repos)} 个</div>
  {nav}
  {cards}
  <footer>由 github-trending-radar 自动生成 · 数据来自 OSS Insight & GitHub Search API</footer>
</div></body></html>"""


def build_archive_html(history: dict) -> str:
    items = []
    for d in sorted(history.keys(), reverse=True):
        rec = history[d]
        n = len(rec.get("repos", []))
        link = rec.get("report_path", f"reports/{d}.html")
        items.append(f"""<div class="archive-item"><div><div class="d">{_esc(d)}</div><div class="m">共 {n} 个热门项目</div></div><a href="{_esc(link)}">查看 →</a></div>""")
    items_html = "\n".join(items) if items else '<p style="color:#8b949e">暂无历史存档。</p>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>历史存档 · GitHub 热门雷达</title>
<style>{_css()}</style></head>
<body><div class="wrap">
  <h1>历史存档</h1>
  <div class="sub">每日一期，可回看任意往期热门榜单</div>
  <div class="nav"><a href="index.html">最新</a></div>
  {items_html}
  <footer>由 github-trending-radar 自动生成</footer>
</div></body></html>"""


def write_all(repos: list[dict], date_str: str, history: dict, output_dir: str, report_dir: str) -> None:
    os.makedirs(report_dir, exist_ok=True)
    # 最新一期 index.html
    with open(os.path.join(output_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(build_report_html(repos, date_str, is_latest=True))
    # 当期固定链接 reports/YYYY-MM-DD.html
    with open(os.path.join(report_dir, f"{date_str}.html"), "w", encoding="utf-8") as f:
        f.write(build_report_html(repos, date_str, is_latest=False))
    # 历史索引
    with open(os.path.join(output_dir, "archive.html"), "w", encoding="utf-8") as f:
        f.write(build_archive_html(history))
