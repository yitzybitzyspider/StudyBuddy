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

from . import ingest as ingest_mod
from . import paths, seed, store
from .models import MaterialType, PromptTask
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


def cmd_ingest(args: argparse.Namespace, client: Any | None = None) -> int:
    root = paths.knowledge_root(args.root)
    try:
        summary = ingest_mod.ingest(
            args.subject,
            args.files,
            material_type=MaterialType(args.type),
            root=root,
            client=client,
        )
    except ClaudeCallError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Ingested {summary['materials']} material(s) into subject '{args.subject}':")
    print(f"  files:    {', '.join(summary['files'])}")
    print(f"  concepts: {summary['concepts']}")
    print(f"  items:    {summary['items']} (retrieved)")
    return 0


def cmd_show_topics(args: argparse.Namespace) -> int:
    root = paths.knowledge_root(args.root)
    concepts = store.load_concepts(args.subject, root=root)
    if not concepts:
        print(f"No topics for subject '{args.subject}'. Run `ingest` first.")
        return 0
    children: dict[str | None, list] = {}
    for c in concepts:
        children.setdefault(c.parent_id, []).append(c)
    ids_present = {c.id for c in concepts}

    def show(parent_id, depth):
        for c in sorted(children.get(parent_id, []), key=lambda x: x.name):
            print("  " * depth + f"- {c.name}")
            show(c.id, depth + 1)

    print(f"Topics for subject '{args.subject}' ({len(concepts)} concepts):")
    show(None, 1)
    # Show any concepts whose parent isn't itself a known concept as top-level too.
    for c in sorted(concepts, key=lambda x: x.name):
        if c.parent_id is not None and c.parent_id not in ids_present:
            print(f"  - {c.name}")
            show(c.id, 1)
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

    p_ingest = sub.add_parser(
        "ingest", parents=[common],
        help="Stage 1: ingest material (.txt/.md/.pdf), extract concepts, harvest real items",
    )
    p_ingest.add_argument("--subject", required=True, help="subject to ingest into")
    p_ingest.add_argument(
        "--type", default="section", choices=[t.value for t in MaterialType],
        help="material type (default: section)",
    )
    p_ingest.add_argument("files", nargs="+", help="material files (.txt/.md/.pdf)")
    p_ingest.set_defaults(func=cmd_ingest)

    p_topics = sub.add_parser(
        "show-topics", parents=[common], help="print the extracted topic hierarchy for a subject"
    )
    p_topics.add_argument("--subject", required=True)
    p_topics.set_defaults(func=cmd_show_topics)

    p_log = sub.add_parser("show-runlog", parents=[common], help="print the run log")
    p_log.add_argument("-n", "--limit", type=int, default=0, help="show only the last N entries")
    p_log.set_defaults(func=cmd_show_runlog)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
