"""Assemble the console page.

One document, everything inlined. The console is a local tool, so it should
start from a clean checkout with no network and no asset pipeline.
"""

from __future__ import annotations

from html import escape

from recon.dashboard.styles import CSS
from recon.server.ui_script import CONSOLE_JS
from recon.server.ui_styles import CONSOLE_CSS


def render_console(token: str, total_cases: int, seed: int) -> str:
    """The single page the review console serves.

    `token` is embedded so the page can authenticate its own requests; every
    write endpoint requires it, which keeps another site open in the same
    browser from posting decisions to this server.
    """
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Review console</title>
<style>{CSS}{CONSOLE_CSS}</style></head>
<body data-token="{escape(token)}"><div class="wrap">

<div class="topbar">
  <div>
    <h1>Review console</h1>
    <p class="sub">{total_cases} cases &middot; seed {seed} &middot; everything the
    rules and the agent could not settle on their own</p>
  </div>
  <div class="actions">
    <button id="promote" class="primary" disabled>Promote confirmed decisions</button>
    <button id="reset" class="ghost">Reset</button>
  </div>
</div>

<div class="cards" id="metrics"></div>
<div id="banner"></div>

<h2>What the system has learned</h2>
<div id="learned"></div>

<h2>Needs a person <span class="sub" id="count"></span></h2>
<div id="queue"></div>

<footer>
Confirming a case appends to <span class="mono">state/decisions.jsonl</span>.
Promoting mines those decisions, writes
<span class="mono">state/knowledge.json</span>, and re-runs the period with the
rules it justified &mdash; nothing below
three independent confirmations is ever promoted, and every learned
value is bounded.
</footer>

</div><script>{CONSOLE_JS}</script></body></html>
"""
