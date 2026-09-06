"""Console-specific styling, layered on the report's palette.

The colour tokens come from `recon.dashboard.styles` so the console and the
emailed report look like one product rather than two.
"""

CONSOLE_CSS = """
.topbar { display: flex; align-items: baseline; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; margin-bottom: 22px; }
.actions { display: flex; gap: 10px; align-items: center; }
button { font: inherit; font-weight: 600; font-size: 13px; cursor: pointer;
  border-radius: 9px; padding: 9px 15px; border: 1px solid var(--line);
  background: var(--panel); color: var(--ink); transition: all .12s ease; }
button:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
button:disabled { opacity: .45; cursor: not-allowed; }
button.primary { background: var(--accent); border-color: var(--accent);
  color: #fff; }
button.primary:hover:not(:disabled) { filter: brightness(1.08); color: #fff; }
button.yes { color: var(--good);
  border-color: color-mix(in srgb, var(--good) 40%, var(--line)); }
button.no { color: var(--bad);
  border-color: color-mix(in srgb, var(--bad) 40%, var(--line)); }
button.ghost { background: transparent; color: var(--muted); }

.card .value { transition: color .3s ease; }
.card.moved { animation: pulse .9s ease; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--accent) 55%, transparent); }
  100% { box-shadow: 0 0 0 14px transparent; }
}
.delta { font-size: 13px; font-weight: 600; color: var(--accent); }

.banner { border: 1px solid color-mix(in srgb, var(--good) 45%, var(--line));
  background: color-mix(in srgb, var(--good) 8%, var(--panel));
  border-radius: 12px; padding: 14px 16px; margin: 18px 0; }
.banner h3 { margin: 0 0 6px; font-size: 14px; color: var(--good); }
.banner ul { margin: 0; padding-left: 18px; font-size: 13.5px; }

.case { background: var(--panel); border: 1px solid var(--line);
  border-radius: 12px; padding: 14px 16px; margin-bottom: 10px;
  display: grid; grid-template-columns: 1fr auto; gap: 14px;
  transition: opacity .2s ease, border-color .2s ease; }
.case.settled { opacity: .5; }
.case.settled.confirmed { border-color: color-mix(in srgb, var(--good) 45%, var(--line)); }
.case.settled.rejected { border-color: color-mix(in srgb, var(--bad) 45%, var(--line)); }
.case h4 { margin: 0 0 4px; font-size: 14px; display: flex; gap: 9px;
  align-items: center; flex-wrap: wrap; }
.case p { margin: 0 0 6px; font-size: 13.5px; color: var(--ink); }
.case .why { color: var(--muted); font-size: 12.5px; }
.case .side { display: flex; flex-direction: column; align-items: flex-end;
  gap: 8px; white-space: nowrap; }
.case .amount { font-weight: 650; font-variant-numeric: tabular-nums;
  font-size: 14px; }
.case .buttons { display: flex; gap: 8px; }
.verdict { font-size: 12px; font-weight: 700; letter-spacing: .04em;
  text-transform: uppercase; }
.verdict.confirmed { color: var(--good); }
.verdict.rejected { color: var(--bad); }

.empty { background: var(--panel); border: 1px dashed var(--line);
  border-radius: 12px; padding: 28px; text-align: center; color: var(--muted); }
.facts li { font-size: 13.5px; margin-bottom: 5px; }
@media (max-width: 640px) {
  .case { grid-template-columns: 1fr; }
  .case .side { align-items: flex-start; }
}
"""
