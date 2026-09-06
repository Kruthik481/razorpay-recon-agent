"""Command line entry point.

    python -m recon.cli run                    # the whole loop, before and after
    python -m recon.cli evaluate               # deterministic matcher only
    python -m recon.cli queue                  # what still needs a person
    python -m recon.cli review                 # decide on the queue
    python -m recon.cli promote                # turn confirmations into rules
    python -m recon.cli serve                  # the review console, in a browser
    python -m recon.cli dashboard --out report.html
    python -m recon.cli export --out data/

Add `--resolver anthropic` to any command that runs the agent to use a live
model instead of the built-in policy.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from recon.agent.providers import RESOLVER_NAMES, build_resolver
from recon.commands import data, loop, review_cmd
from recon.generator import config
from recon.generator.dataset import generate_dataset
from recon.knowledge.model import Knowledge
from recon.knowledge.store import load as load_knowledge
from recon.review.decisions import ReviewDecision
from recon.review.decisions import load as load_decisions
from recon.server.app import serve

DEFAULT_KNOWLEDGE = Path("state/knowledge.json")
DEFAULT_DECISIONS = Path("state/decisions.jsonl")
DEFAULT_DASHBOARD = Path("reports/dashboard.html")

# Commands that need the full loop; everything else only needs a dataset.
NEEDS_PIPELINE = ("run", "dashboard", "queue", "review", "promote")

# The console builds its own session rather than a two-pass pipeline.
STANDALONE = ("serve",)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="recon",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "command",
        choices=(
            "run",
            "serve",
            "evaluate",
            "export",
            "dashboard",
            "queue",
            "review",
            "promote",
        ),
    )
    parser.add_argument("--cases", type=int, default=config.DEFAULT_CASE_COUNT)
    parser.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    parser.add_argument("--resolver", choices=RESOLVER_NAMES, default="policy")
    parser.add_argument("--model", default=None, help="model id for a live resolver")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--port", type=int, default=8765, help="port for `serve`")
    parser.add_argument("--knowledge", type=Path, default=DEFAULT_KNOWLEDGE)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument(
        "--replay-decisions",
        action="store_true",
        help="learn from the decision log instead of the scripted reviewer",
    )
    return parser


def _knowledge(args: argparse.Namespace) -> Knowledge:
    try:
        return load_knowledge(args.knowledge)
    except ValueError as exc:
        print(f"ignoring unusable knowledge file: {exc}", file=sys.stderr)
        return Knowledge()


def _decisions(args: argparse.Namespace) -> tuple[ReviewDecision, ...] | None:
    if not args.replay_decisions:
        return None
    try:
        return load_decisions(args.decisions)
    except ValueError as exc:
        print(f"cannot read decision log: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    knowledge = _knowledge(args)

    try:
        if args.command in STANDALONE:
            return serve(
                total_cases=args.cases,
                seed=args.seed,
                knowledge_path=args.knowledge,
                decisions_path=args.decisions,
                port=args.port,
            )
        if args.command not in NEEDS_PIPELINE:
            dataset = generate_dataset(total_cases=args.cases, seed=args.seed)
            if args.command == "evaluate":
                return data.cmd_evaluate(dataset, knowledge)
            return data.cmd_export(dataset, args.out or Path("data"))

        result = loop.build(
            total_cases=args.cases,
            seed=args.seed,
            resolver=build_resolver(args.resolver, args.model),
            knowledge=knowledge,
            decisions=_decisions(args),
        )
    except (ValueError, KeyError, RuntimeError, OSError) as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1

    if args.command == "run":
        return loop.cmd_run(result)
    if args.command == "dashboard":
        return loop.cmd_dashboard(result, args.out or DEFAULT_DASHBOARD)
    if args.command == "queue":
        return review_cmd.cmd_queue(result)
    if args.command == "review":
        return review_cmd.cmd_review(result, args.decisions)
    return review_cmd.cmd_promote(result, args.decisions, args.knowledge, knowledge)


if __name__ == "__main__":
    raise SystemExit(main())
