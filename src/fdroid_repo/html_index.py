from __future__ import annotations

import html
from datetime import UTC, datetime
from urllib.parse import quote

from fdroid_repo.models import BuiltAppSummary


def render_landing_html(
    repo_name: str,
    repo_description: str,
    repo_url: str,
    fingerprint: str | None,
    apps: list[BuiltAppSummary],
) -> str:
    escaped_name = html.escape(repo_name)
    escaped_desc = html.escape(repo_description)
    escaped_url = html.escape(repo_url)

    if fingerprint:
        fdroid_link = f"https://fdroid.link/#{quote(repo_url, safe=':/')}?fingerprint={fingerprint}"
        fp_formatted = " ".join(
            fingerprint[i : i + 4] for i in range(0, len(fingerprint), 4)
        )
        fp_block = (
            f'<div class="meta-row"><span class="label">SHA-256 Fingerprint</span>'
            f'<code class="fingerprint">{html.escape(fp_formatted)}</code></div>'
        )
        add_btn = (
            f'<a class="btn primary" href="{html.escape(fdroid_link)}">'
            f"Add to F-Droid</a>"
        )
    else:
        fp_block = ""
        add_btn = ""

    cards_html: list[str] = []
    for app in apps:
        icon_html = (
            f'<img class="app-icon" src="fdroid/repo/{html.escape(app.icon_relpath)}" '
            f'alt="{html.escape(app.display_name)} icon">'
            if app.icon_relpath
            else '<div class="app-icon placeholder">APK</div>'
        )
        badges: list[str] = []
        if app.current_version:
            badges.append(
                f'<span class="badge stable">Stable: v{html.escape(app.current_version)}</span>'
            )
        for beta in app.beta_tags:
            badges.append(f'<span class="badge beta">Beta: {html.escape(beta)}</span>')
        if app.license_name:
            badges.append(f'<span class="badge neutral">{html.escape(app.license_name)}</span>')

        versions_list = ", ".join(
            html.escape(t) for t in (*app.beta_tags, *app.stable_tags)
        )
        source_link = (
            f'<a href="{html.escape(app.source_code)}">Source Code</a>'
            if app.source_code
            else html.escape(app.repo)
        )
        summary_text = html.escape(
            app.summary or "Android application hosted in hddq's F-Droid repo."
        )
        cards_html.append(
            f"""
            <article class="card">
              <div class="card-head">
                {icon_html}
                <div>
                  <h2>{html.escape(app.display_name or app.app_id)}</h2>
                  <p class="pkg">{html.escape(app.app_id)}</p>
                </div>
              </div>
              <p class="summary">{summary_text}</p>
              <div class="badges">{"".join(badges)}</div>
              <p class="versions">Retained releases: <code>{versions_list or "none"}</code></p>
              <div class="card-footer">{source_link}</div>
            </article>
            """
        )

    updated_utc = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_name}</title>
  <style>
    :root {{
      color-scheme: light dark;
      --bg: #0f172a;
      --surface: #1e293b;
      --border: #334155;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #38bdf8;
      --accent-fg: #082f49;
      --stable-bg: #14532d;
      --stable-fg: #bbf7d0;
      --beta-bg: #78350f;
      --beta-fg: #fde68a;
    }}
    @media (prefers-color-scheme: light) {{
      :root {{
        --bg: #f8fafc;
        --surface: #ffffff;
        --border: #e2e8f0;
        --text: #0f172a;
        --muted: #475569;
        --accent: #0284c7;
        --accent-fg: #ffffff;
        --stable-bg: #dcfce7;
        --stable-fg: #166534;
        --beta-bg: #fef3c7;
        --beta-fg: #92400e;
      }}
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}
    .container {{ max-width: 900px; margin: 0 auto; padding: 2.5rem 1.25rem; }}
    header {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 1.75rem;
      margin-bottom: 2rem;
    }}
    h1 {{ margin: 0 0 0.5rem; font-size: 1.85rem; }}
    .desc {{ margin: 0 0 1.25rem; color: var(--muted); }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 1.25rem; }}
    .btn {{
      display: inline-block;
      padding: 0.6rem 1rem;
      border-radius: 10px;
      font-weight: 600;
      text-decoration: none;
      border: 1px solid var(--border);
      color: var(--text);
      background: transparent;
      cursor: pointer;
      font-size: 0.95rem;
    }}
    .btn.primary {{
      background: var(--accent); color: var(--accent-fg); border-color: transparent;
    }}
    .meta-row {{ margin-top: 0.65rem; font-size: 0.875rem; }}
    .label {{
      display: block; color: var(--muted); font-size: 0.78rem;
      text-transform: uppercase; letter-spacing: 0.04em;
    }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      word-break: break-all;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
      gap: 1rem;
    }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}
    .card-head {{ display: flex; align-items: center; gap: 0.85rem; }}
    .app-icon {{
      width: 52px; height: 52px; border-radius: 12px;
      object-fit: cover; flex-shrink: 0;
    }}
    .app-icon.placeholder {{
      display: flex; align-items: center; justify-content: center;
      background: var(--border); font-weight: 700; font-size: 0.8rem;
    }}
    .card h2 {{ margin: 0; font-size: 1.15rem; }}
    .pkg {{
      margin: 0; color: var(--muted); font-size: 0.8rem;
      font-family: ui-monospace, monospace;
    }}
    .summary {{ margin: 0; font-size: 0.95rem; }}
    .badges {{ display: flex; flex-wrap: wrap; gap: 0.4rem; }}
    .badge {{
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.2rem 0.55rem;
      border-radius: 999px;
      background: var(--border);
    }}
    .badge.stable {{ background: var(--stable-bg); color: var(--stable-fg); }}
    .badge.beta {{ background: var(--beta-bg); color: var(--beta-fg); }}
    .versions {{ margin: 0; font-size: 0.8rem; color: var(--muted); }}
    .card-footer {{ margin-top: auto; font-size: 0.85rem; }}
    .card-footer a {{ color: var(--accent); text-decoration: none; font-weight: 500; }}
    footer {{ margin-top: 2rem; color: var(--muted); font-size: 0.8rem; text-align: center; }}
  </style>
</head>
<body>
  <main class="container">
    <header>
      <h1>{escaped_name}</h1>
      <p class="desc">{escaped_desc}</p>
      <div class="actions">
        {add_btn}
        <a class="btn" href="fdroid/repo/index.html">Browse F-Droid Index</a>
        <button class="btn" type="button"
          onclick="navigator.clipboard.writeText('{escaped_url}')">Copy Repo URL</button>
      </div>
      <div class="meta-row">
        <span class="label">Repository URL</span>
        <code>{escaped_url}</code>
      </div>
      {fp_block}
    </header>
    <section class="grid">
      {"".join(cards_html)}
    </section>
    <footer>
      Last updated: {updated_utc}
    </footer>
  </main>
</body>
</html>
"""
