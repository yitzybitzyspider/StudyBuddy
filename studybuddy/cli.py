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

from . import administer as administer_mod
from . import diagnose as diagnose_mod
from . import diagnostic as diagnostic_mod
from . import ingest as ingest_mod
from . import intake as intake_mod
from . import paths, plan as plan_mod, seed, store
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


def cmd_intake(args: argparse.Namespace) -> int:
    root = paths.knowledge_root(args.root)
    if args.answers:
        intake = intake_mod.ingest_answers(
            args.subject, args.answers, root=root, learner_id=args.learner
        )
        print("Intake captured:")
        print(f"  exam format:        {intake.exam_format}")
        print(f"  total study time:   {intake.total_study_time} h")
        print(f"  daily availability: {intake.daily_availability} h")
        print(f"  per-topic confidence: {len(intake.per_topic_confidence)} topic(s)")
        return 0
    path = intake_mod.build_template(args.subject, root=root, learner_id=args.learner)
    print(f"Wrote intake template to {path}")
    print(f"Fill it in, then run: studybuddy intake --subject {args.subject} --answers {path}")
    return 0


def cmd_compose_diagnostic(args: argparse.Namespace, client: Any | None = None) -> int:
    root = paths.knowledge_root(args.root)
    try:
        result = diagnostic_mod.compose(
            args.subject, root=root, client=client, learner_id=args.learner, size=args.size
        )
    except (ValueError, ClaudeCallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    diag = result["diagnostic"]
    print(f"Composed diagnostic {diag.id}: {len(diag.item_ids)} items")
    print(f"  retrieved (real): {result['retrieved']}   generated: {result['generated']}")
    print(f"Answers template: {result['answers_path']}")
    print(f"Fill it in, then run: studybuddy administer --subject {args.subject} --answers {result['answers_path']}")
    return 0


def cmd_administer(args: argparse.Namespace, client: Any | None = None) -> int:
    root = paths.knowledge_root(args.root)
    try:
        result = administer_mod.administer(
            args.subject, answers_path=args.answers, root=root, client=client,
            learner_id=args.learner,
        )
    except (OSError, ClaudeCallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"Graded {result['answered']} answers: {result['correct']} correct.\n")
    for i, f in enumerate(result["feedback"], 1):
        mark = "✓" if f["correct"] else "✗"
        line = f"{i:2}. {mark} [{f['format']}] {f['stem'][:70]}"
        print(line)
        if f.get("blank"):
            print("      (left blank)")
        if not f["correct"] and "correct_answer" in f:
            print(f"      answer: {f['correct_answer']}")
        if "score" in f:
            print(f"      score: {f['score']}  missed: {', '.join(f.get('missed_facets') or []) or '—'}")
    print("\nNext: studybuddy diagnose --subject " + args.subject)
    return 0


def cmd_diagnose(args: argparse.Namespace, client: Any | None = None) -> int:
    root = paths.knowledge_root(args.root)
    try:
        result = diagnose_mod.diagnose(
            args.subject, root=root, client=client, learner_id=args.learner
        )
    except (ValueError, ClaudeCallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    profile = result["gap_profile"]
    print(f"Diagnosed {len(profile.entries)} gap(s):")
    for e in profile.entries:
        sev = f" (severity {e.severity})" if e.severity is not None else ""
        print(f"  - {e.concept_id}: {e.gap_type}{sev}")
    print(f"\nNext: studybuddy plan --subject {args.subject}")
    return 0


def cmd_plan(args: argparse.Namespace, client: Any | None = None) -> int:
    root = paths.knowledge_root(args.root)
    try:
        result = plan_mod.compose(args.subject, root=root, client=client, learner_id=args.learner)
    except (ValueError, ClaudeCallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    plan = result["study_plan"]
    print(f"Study plan ({len(plan.topics)} topics) written to {result['markdown_path']}")
    if result["overview"]:
        print(f"\n{result['overview']}")
    return 0


def cmd_steer(args: argparse.Namespace, client: Any | None = None) -> int:
    root = paths.knowledge_root(args.root)
    if args.shift:
        action, focus = "shift", [args.shift]
    elif args.fewer:
        action, focus = "fewer", None
    else:
        action, focus = "more", None
    try:
        result = plan_mod.steer(
            args.subject, action=action, focus=focus, root=root, client=client,
            learner_id=args.learner,
        )
    except (ValueError, ClaudeCallError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    diag = result["diagnostic"]
    print(f"Steered ({action}): new batch {diag.id} with {len(diag.item_ids)} items.")
    print(f"  retrieved: {result['retrieved']}  generated: {result['generated']}")
    print(f"Answers template: {result['answers_path']}")
    print(f"Fill it in, then run: studybuddy administer --subject {args.subject}")
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

    p_intake = sub.add_parser(
        "intake", parents=[common],
        help="Stage 3: write an intake template, or ingest filled answers with --answers",
    )
    p_intake.add_argument("--subject", required=True)
    p_intake.add_argument("--learner", default=store.DEFAULT_LEARNER)
    p_intake.add_argument("--answers", default=None, help="path to the filled intake answers JSON")
    p_intake.set_defaults(func=cmd_intake)

    p_compose = sub.add_parser(
        "compose-diagnostic", parents=[common],
        help="Stage 4: assemble a ~20-item diagnostic (retrieval-first) + an answers template",
    )
    p_compose.add_argument("--subject", required=True)
    p_compose.add_argument("--learner", default=store.DEFAULT_LEARNER)
    p_compose.add_argument("--size", type=int, default=None, help="override item count (default: heuristics)")
    p_compose.set_defaults(func=cmd_compose_diagnostic)

    p_admin = sub.add_parser(
        "administer", parents=[common],
        help="Stage 5: grade the filled diagnostic answers and record results",
    )
    p_admin.add_argument("--subject", required=True)
    p_admin.add_argument("--learner", default=store.DEFAULT_LEARNER)
    p_admin.add_argument("--answers", default=None, help="answers file (default: the composed one)")
    p_admin.set_defaults(func=cmd_administer)

    p_diag = sub.add_parser(
        "diagnose", parents=[common],
        help="Stage 6: classify gaps and interpret why understanding breaks down",
    )
    p_diag.add_argument("--subject", required=True)
    p_diag.add_argument("--learner", default=store.DEFAULT_LEARNER)
    p_diag.set_defaults(func=cmd_diagnose)

    p_plan = sub.add_parser(
        "plan", parents=[common],
        help="Stage 8: compose the topic-by-topic study plan one-pager",
    )
    p_plan.add_argument("--subject", required=True)
    p_plan.add_argument("--learner", default=store.DEFAULT_LEARNER)
    p_plan.set_defaults(func=cmd_plan)

    p_steer = sub.add_parser(
        "steer", parents=[common],
        help="FR-G2: recompose a follow-up batch (more / fewer / shift focus)",
    )
    p_steer.add_argument("--subject", required=True)
    p_steer.add_argument("--learner", default=store.DEFAULT_LEARNER)
    steer_group = p_steer.add_mutually_exclusive_group()
    steer_group.add_argument("--more", action="store_true", help="more questions like these")
    steer_group.add_argument("--fewer", action="store_true", help="a smaller follow-up batch")
    steer_group.add_argument("--shift", metavar="TOPIC", default=None, help="shift focus to a topic")
    p_steer.set_defaults(func=cmd_steer)

    p_log = sub.add_parser("show-runlog", parents=[common], help="print the run log")
    p_log.add_argument("-n", "--limit", type=int, default=0, help="show only the last N entries")
    p_log.set_defaults(func=cmd_show_runlog)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
