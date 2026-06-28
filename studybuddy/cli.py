"""The CLI harness for the StudyBuddy pipeline (Phase 0, Loop 5).

The pipeline is UI-agnostic; this is the thin way to drive it from a terminal. Phase 0
exposes three commands; one subcommand per pipeline stage is added as stages are built
(Phase 1+):

    studybuddy init                         create/verify the knowledge layer + seed v1
    studybuddy run-call <task> -i in.json   run one Claude call through the validated wrapper
    studybuddy show-runlog                   print the append-only run log
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import paths, seed
from .models import PromptTask
from .runlog import RunLog
from .wrapper import ClaudeCallError, run_call


def cmd_init(args: argparse.Namespace) -> int:
    root = paths.knowledge_root(args.root)
    for d in paths.KNOWLEDGE_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "runs" / "blobs").mkdir(parents=True, exist_ok=True)
    result = seed.seed_knowledge_layer(root=root)
    print(f"Knowledge layer ready at {root}")
    print(f"  directories: {', '.join(paths.KNOWLEDGE_DIRS)}")
    print(f"  registry/heuristics seeded: {len(result['written'])} new, "
          f"{len(result['skipped'])} already present")
    return 0


def cmd_run_call(args: argparse.Namespace, client: Any | None = None) -> int:
    root = paths.knowledge_root(args.root)
    try:
        structured_input = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: could not read input {args.input!r}: {e}", file=sys.stderr)
        return 1
    try:
        result = run_call(
            args.task,
            structured_input,
            version=args.version,
            root=root,
            client=client,
            model=args.model,
            phase=args.phase,
        )
    except ClaudeCallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


def cmd_show_runlog(args: argparse.Namespace) -> int:
    root = paths.knowledge_root(args.root)
    entries = RunLog(root).read_all()
    if args.limit:
        entries = entries[-args.limit :]
    if not entries:
        print("(run log is empty)")
        return 0
    for e in entries:
        print(
            f"{e.ts.isoformat()}  {e.phase:<22}  {e.validation_status.value:<9}  "
            f"{e.disposition.value:<8}  {e.id}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studybuddy",
        description="Drive the StudyBuddy adaptive-study pipeline.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root", default=None,
        help="knowledge-layer root (default: $STUDYBUDDY_HOME or auto-detect)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser(
        "init", parents=[common],
        help="create/verify the knowledge layer and seed the v1 registry + heuristics",
    )
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser(
        "run-call", parents=[common],
        help="run one Claude call through the validated wrapper",
    )
    p_run.add_argument("task", choices=[t.value for t in PromptTask], help="the scoped call")
    p_run.add_argument(
        "-i", "--input", required=True, help="path to a JSON file with the structured input"
    )
    p_run.add_argument("--version", default="current", help="template version (default: current)")
    p_run.add_argument("--model", default=None, help="override the model")
    p_run.add_argument("--phase", default=None, help="run-log phase label (default: task name)")
    p_run.set_defaults(func=cmd_run_call)

    p_log = sub.add_parser("show-runlog", parents=[common], help="print the run log")
    p_log.add_argument("-n", "--limit", type=int, default=0, help="show only the last N entries")
    p_log.set_defaults(func=cmd_show_runlog)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
