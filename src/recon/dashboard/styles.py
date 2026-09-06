"""Inline stylesheet for the generated dashboard.

Inlined on purpose: the report is a single file a controller can email, attach
to a close checklist, or open from a USB stick with no network.
"""

CSS = """
:root {
  color-scheme: light dark;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --ink: #12151a;
  --muted: #5c6672;
  --line: #e2e6eb;
  --good: #0a7d4b;
  --warn: #9a6400;
  --bad: #b3261e;
  --accent: #1a4fd6;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1216; --panel: #171b21; --ink: #e8ecf1; --muted: #9aa5b1;
    --line: #262c34; --good: #4ad295; --warn: #e3b341; --bad: #ff7b72;
    --accent: #6f9bff;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 32px 24px 64px;
  background: var(--bg); color: var(--ink);
  font: 15px/1.55 ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1080px; margin: 0 auto; }
header { margin-bottom: 28px; }
h1 { font-size: 26px; margin: 0 0 6px; letter-spacing: -0.01em; }
h2 { font-size: 17px; margin: 36px 0 12px; letter-spacing: -0.005em; }
.sub { color: var(--muted); font-size: 14px; margin: 0; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 14px;
  }
.card {
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 12px; padding: 16px 18px;
}
.card .label { color: var(--muted); font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.06em; margin-bottom: 8px; }
.card .value { font-size: 30px; font-weight: 650; letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums; }
.card .note { color: var(--muted); font-size: 13px; margin-top: 4px; }
.good { color: var(--good); } .warn { color: var(--warn); } .bad { color: var(--bad); }
table { width: 100%; border-collapse: collapse; background: var(--panel);
  border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
th, td { text-align: left; padding: 10px 14px; border-bottom: 1px solid var(--line);
  font-size: 14px; vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.05em; }
tbody tr:last-child td { border-bottom: none; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.bar { height: 8px; border-radius: 999px; background: var(--line); overflow: hidden; }
.bar > span { display: block; height: 100%; background: var(--accent); }
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px;

  font-size: 12px; font-weight: 600; border: 1px solid var(--line); }
.pill.review { color: var(--warn); } .pill.escalate { color: var(--bad); }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px; }
.reason { color: var(--muted); font-size: 13px; margin-top: 3px; }
footer { margin-top: 48px; color: var(--muted); font-size: 13px;
  border-top: 1px solid var(--line); padding-top: 16px; }
"""
