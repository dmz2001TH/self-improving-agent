"""
cli/main.py — Command Line Interface สำหรับ Self-Improving Agent Memory Engine

Usage:
    python -m cli.main mistake add --agent mybot --task "call API" --type TimeoutError --msg "API timed out"
    python -m cli.main mistake list [--agent mybot] [--severity critical]
    python -m cli.main lesson list [--min-confidence 0.5]
    python -m cli.main check --action "send email" --agent mybot
    python -m cli.main reflect --mistake-id abc123
    python -m cli.main stats [--agent mybot] [--days 30]
    python -m cli.main dashboard
"""

import sys
import os
import json
import argparse
from pathlib import Path

# เพิ่ม parent directory เข้า path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.memory_engine import MemoryEngine
from core.reflector import Reflector
from core.preflight import PreFlightChecker

DB_PATH = str(Path(__file__).parent.parent / "data" / "memory.db")


def get_engine():
    return MemoryEngine(DB_PATH)


# ─── Colors ─────────────────────────────────────────────────────

class C:
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def severity_color(sev: str) -> str:
    return {
        "critical": C.RED,
        "warning": C.YELLOW,
        "info": C.CYAN,
        "block": C.RED,
        "warn": C.YELLOW,
    }.get(sev, "")


# ─── Mistake Commands ──────────────────────────────────────────

def cmd_mistake_add(args):
    engine = get_engine()
    mid = engine.log_mistake(
        agent_name=args.agent,
        task_description=args.task,
        error_type=args.type,
        error_message=args.msg,
        context=json.loads(args.context) if args.context else {},
        tags=args.tags.split(",") if args.tags else [],
        severity=args.severity,
    )
    print(f"{C.GREEN}✓ Mistake logged: {C.BOLD}{mid}{C.END}")

    if args.reflect:
        reflector = Reflector(engine)
        lid = reflector.reflect_on_mistake(mid)
        if lid:
            print(f"{C.CYAN}💭 Lesson created: {C.BOLD}{lid}{C.END}")
            lesson = engine.get_lesson(lid)
            print(f"   Rule: {lesson['prevention_rule']}")
            print(f"   Confidence: {lesson['confidence']:.1f}")

    engine.close()


def cmd_mistake_list(args):
    engine = get_engine()
    mistakes = engine.list_mistakes(
        agent_name=args.agent,
        severity=args.severity,
        resolved=args.resolved,
        limit=args.limit,
    )

    if not mistakes:
        print(f"{C.DIM}No mistakes found.{C.END}")
        engine.close()
        return

    print(f"\n{C.BOLD}{'='*70}{C.END}")
    print(f"{C.BOLD}  Mistakes ({len(mistakes)} total){C.END}")
    print(f"{C.BOLD}{'='*70}{C.END}\n")

    for m in mistakes:
        sc = severity_color(m["severity"])
        status = f"{C.GREEN}✓ resolved{C.END}" if m["resolved"] else f"{C.RED}✗ open{C.END}"
        print(f"  {sc}■{C.END} {C.BOLD}{m['id']}{C.END}  {status}")
        print(f"    Agent: {m['agent_name']}  |  Type: {m['error_type']}  |  {C.DIM}{m['timestamp'][:16]}{C.END}")
        print(f"    Task: {m['task_description']}")
        print(f"    Error: {m['error_message'][:100]}")
        print()

    engine.close()


def cmd_mistake_show(args):
    engine = get_engine()
    m = engine.get_mistake(args.id)
    if not m:
        print(f"{C.RED}✗ Mistake not found: {args.id}{C.END}")
        engine.close()
        return

    sc = severity_color(m["severity"])
    print(f"\n{C.BOLD}{'='*70}{C.END}")
    print(f"  {sc}■{C.END} {C.BOLD}Mistake: {m['id']}{C.END}")
    print(f"{C.BOLD}{'='*70}{C.END}")
    print(f"  Agent:     {m['agent_name']}")
    print(f"  Task:      {m['task_description']}")
    print(f"  Type:      {m['error_type']}")
    print(f"  Severity:  {sc}{m['severity']}{C.END}")
    print(f"  Error:     {m['error_message']}")
    print(f"  Timestamp: {m['timestamp']}")
    print(f"  Resolved:  {'Yes' if m['resolved'] else 'No'}")
    print(f"  Tags:      {', '.join(m['tags']) or 'none'}")
    if m["context"]:
        print(f"\n  {C.BOLD}Context:{C.END}")
        print(f"  {json.dumps(m['context'], indent=4, ensure_ascii=False)}")
    if m["stack_trace"]:
        print(f"\n  {C.BOLD}Stack Trace:{C.END}")
        print(f"  {m['stack_trace'][:500]}")
    print()
    engine.close()


# ─── Lesson Commands ───────────────────────────────────────────

def cmd_lesson_list(args):
    engine = get_engine()
    lessons = engine.get_relevant_lessons(
        task_description=args.filter or "",
        min_confidence=args.min_confidence,
        limit=args.limit,
    )

    if not lessons:
        print(f"{C.DIM}No lessons found.{C.END}")
        engine.close()
        return

    print(f"\n{C.BOLD}{'='*70}{C.END}")
    print(f"{C.BOLD}  Lessons ({len(lessons)} total){C.END}")
    print(f"{C.BOLD}{'='*70}{C.END}\n")

    for l in lessons:
        conf_color = C.GREEN if l["confidence"] > 0.7 else C.YELLOW if l["confidence"] > 0.4 else C.RED
        print(f"  {C.BOLD}{l['id']}{C.END}")
        print(f"    Rule: {C.CYAN}{l['prevention_rule']}{C.END}")
        print(f"    Confidence: {conf_color}{l['confidence']:.1f}{C.END}  |  "
              f"Applied: {l['times_applied']}x  |  "
              f"Prevented: {l['times_prevented']}x  |  "
              f"False+: {l['false_positive']}x")
        print(f"    Root Cause: {l['root_cause'][:80]}")
        print(f"    Prevent: {l['how_to_prevent'][:80]}")
        print()

    engine.close()


def cmd_lesson_show(args):
    engine = get_engine()
    l = engine.get_lesson(args.id)
    if not l:
        print(f"{C.RED}✗ Lesson not found: {args.id}{C.END}")
        engine.close()
        return

    print(f"\n{C.BOLD}{'='*70}{C.END}")
    print(f"  {C.BOLD}Lesson: {l['id']}{C.END}")
    print(f"{C.BOLD}{'='*70}{C.END}")
    print(f"  From Mistake: {l['mistake_id']}")
    print(f"  Root Cause:   {l['root_cause']}")
    print(f"  Why:          {l['why_it_happened']}")
    print(f"  How to Fix:   {l['how_to_prevent']}")
    print(f"  Rule:         {C.CYAN}{l['prevention_rule']}{C.END}")
    print(f"  Confidence:   {l['confidence']:.1f}")
    print(f"  Applied:      {l['times_applied']}x")
    print(f"  Prevented:    {l['times_prevented']}x")
    print(f"  False+:       {l['false_positive']}x")
    print(f"  Tags:         {', '.join(l['tags']) or 'none'}")
    print()
    engine.close()


# ─── Pre-flight Check ──────────────────────────────────────────

def cmd_check(args):
    engine = get_engine()
    checker = PreFlightChecker(engine)
    warnings = checker.check(
        action=args.action,
        agent_name=args.agent,
        tags=args.tags.split(",") if args.tags else None,
        min_confidence=args.min_confidence,
    )

    if not warnings:
        print(f"{C.GREEN}✓ No warnings — safe to proceed!{C.END}")
        engine.close()
        return

    print(f"\n{C.YELLOW}⚠ Pre-flight warnings for: {C.BOLD}{args.action}{C.END}\n")

    for w in warnings:
        sc = severity_color(w.severity)
        icon = "🚫" if w.severity == "block" else "⚠️" if w.severity == "warn" else "ℹ️"
        print(f"  {icon} {sc}[{w.severity.upper()}]{C.END} {w.prevention_rule}")
        print(f"     Confidence: {w.confidence:.1f}  |  Prevented: {w.times_prevented}x")
        print(f"     {C.DIM}{w.how_to_prevent[:100]}{C.END}")
        print()

    engine.close()


# ─── Reflect ───────────────────────────────────────────────────

def cmd_reflect(args):
    engine = get_engine()
    reflector = Reflector(engine)

    if args.mistake_id:
        lid = reflector.reflect_on_mistake(args.mistake_id)
        if lid:
            lesson = engine.get_lesson(lid)
            print(f"{C.GREEN}✓ Lesson created: {C.BOLD}{lid}{C.END}")
            print(f"  Rule: {C.CYAN}{lesson['prevention_rule']}{C.END}")
            print(f"  Root Cause: {lesson['root_cause']}")
            print(f"  How to Prevent: {lesson['how_to_prevent']}")
        else:
            print(f"{C.RED}✗ Could not reflect on mistake {args.mistake_id}{C.END}")

    elif args.all_unresolved:
        mistakes = engine.list_mistakes(resolved=False)
        print(f"Reflecting on {len(mistakes)} unresolved mistakes...")
        for m in mistakes:
            lid = reflector.reflect_on_mistake(m["id"])
            if lid:
                print(f"  {C.GREEN}✓{C.END} {m['id']} → {lid}")
            else:
                print(f"  {C.RED}✗{C.END} {m['id']} — failed")

    engine.close()


# ─── Stats ─────────────────────────────────────────────────────

def cmd_stats(args):
    engine = get_engine()
    stats = engine.get_stats(agent_name=args.agent, days=args.days)

    print(f"\n{C.BOLD}{'='*70}{C.END}")
    print(f"{C.BOLD}  📊 Agent Memory Stats (last {stats['period_days']} days){C.END}")
    print(f"{C.BOLD}{'='*70}{C.END}\n")

    print(f"  {C.BOLD}Mistakes:{C.END}     {stats['total_mistakes']} total, {stats['resolved_mistakes']} resolved")
    print(f"  {C.BOLD}Lessons:{C.END}      {stats['total_lessons']}")

    actions = stats["actions"]
    if actions.get("total"):
        total = actions["total"]
        success_rate = (actions.get("successes", 0) / total * 100) if total > 0 else 0
        print(f"  {C.BOLD}Actions:{C.END}      {total} total")
        print(f"    ✓ Success:   {actions.get('successes', 0)} ({success_rate:.0f}%)")
        print(f"    ✗ Failed:    {actions.get('failures', 0)}")
        print(f"    🛡 Prevented: {actions.get('prevented', 0)}")

    if stats["top_error_types"]:
        print(f"\n  {C.BOLD}Top Error Types:{C.END}")
        for et in stats["top_error_types"]:
            print(f"    • {et['error_type']}: {et['cnt']}x")

    if stats["best_lessons"]:
        print(f"\n  {C.BOLD}Best Lessons:{C.END}")
        for l in stats["best_lessons"]:
            print(f"    🛡 {l['prevention_rule']} (prevented {l['times_prevented']}x)")

    print()
    engine.close()


# ─── Dashboard ─────────────────────────────────────────────────

def cmd_dashboard(args):
    engine = get_engine()
    stats = engine.get_stats(days=30)
    mistakes = engine.list_mistakes(limit=10)
    lessons = engine.get_relevant_lessons(task_description="", min_confidence=0.0, limit=10)

    print(f"""
{C.BOLD}╔══════════════════════════════════════════════════════════════════════╗
║           🧠 Self-Improving Agent Memory Dashboard                  ║
╠══════════════════════════════════════════════════════════════════════╣{C.END}
{C.CYAN}║  Mistakes:{C.END} {stats['total_mistakes']:>4} total  │  {C.GREEN}{stats['resolved_mistakes']:>4} resolved{C.END}  │  {C.RED}{stats['total_mistakes'] - stats['resolved_mistakes']:>4} open{C.END}
{C.CYAN}║  Lessons:{C.END}  {stats['total_lessons']:>4}
{C.CYAN}║  Actions:{C.END}  {stats['actions'].get('total', 0):>4}        │  {C.GREEN}✓ {stats['actions'].get('successes', 0)}{C.END}  │  {C.RED}✗ {stats['actions'].get('failures', 0)}{C.END}  │  {C.YELLOW}🛡 {stats['actions'].get('prevented', 0)}{C.END}
{C.BOLD}╠══════════════════════════════════════════════════════════════════════╣
║  Recent Mistakes                                                     ║
╠══════════════════════════════════════════════════════════════════════╣{C.END}""")

    for m in mistakes[:5]:
        sc = severity_color(m["severity"])
        status = f"{C.GREEN}✓{C.END}" if m["resolved"] else f"{C.RED}✗{C.END}"
        print(f"  {status} {sc}■{C.END} {m['id']}  {m['error_type']}  {C.DIM}{m['timestamp'][:16]}{C.END}")

    print(f"""{C.BOLD}╠══════════════════════════════════════════════════════════════════════╣
║  Active Lessons                                                     ║
╠══════════════════════════════════════════════════════════════════════╣{C.END}""")

    for l in lessons[:5]:
        conf = l["confidence"]
        bar = "█" * int(conf * 10) + "░" * (10 - int(conf * 10))
        conf_color = C.GREEN if conf > 0.7 else C.YELLOW if conf > 0.4 else C.RED
        print(f"  {conf_color}{bar}{C.END} {conf:.1f}  {l['prevention_rule'][:50]}")

    print(f"""{C.BOLD}╚══════════════════════════════════════════════════════════════════════╝{C.END}
""")
    engine.close()


# ─── Main Parser ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="agent-memory",
        description="🧠 Self-Improving Agent Memory Engine",
    )
    sub = parser.add_subparsers(dest="command")

    # mistake
    p_mistake = sub.add_parser("mistake", help="Manage mistakes")
    ms = p_mistake.add_subparsers(dest="subcommand")

    # mistake add
    p_ma = ms.add_parser("add", help="Log a mistake")
    p_ma.add_argument("--agent", required=True, help="Agent name")
    p_ma.add_argument("--task", required=True, help="Task description")
    p_ma.add_argument("--type", required=True, help="Error type")
    p_ma.add_argument("--msg", required=True, help="Error message")
    p_ma.add_argument("--context", help="JSON context")
    p_ma.add_argument("--tags", help="Comma-separated tags")
    p_ma.add_argument("--severity", default="warning", choices=["critical", "warning", "info"])
    p_ma.add_argument("--reflect", action="store_true", help="Auto-reflect after logging")

    # mistake list
    p_ml = ms.add_parser("list", help="List mistakes")
    p_ml.add_argument("--agent", help="Filter by agent")
    p_ml.add_argument("--severity", choices=["critical", "warning", "info"])
    p_ml.add_argument("--resolved", type=lambda x: x.lower() == "true")
    p_ml.add_argument("--limit", type=int, default=20)

    # mistake show
    p_ms = ms.add_parser("show", help="Show mistake details")
    p_ms.add_argument("id", help="Mistake ID")

    # lesson
    p_lesson = sub.add_parser("lesson", help="Manage lessons")
    ls = p_lesson.add_subparsers(dest="subcommand")

    # lesson list
    p_ll = ls.add_parser("list", help="List lessons")
    p_ll.add_argument("--filter", help="Filter by task description")
    p_ll.add_argument("--min-confidence", type=float, default=0.0)
    p_ll.add_argument("--limit", type=int, default=20)

    # lesson show
    p_ls = ls.add_parser("show", help="Show lesson details")
    p_ls.add_argument("id", help="Lesson ID")

    # check
    p_check = sub.add_parser("check", help="Pre-flight check")
    p_check.add_argument("--action", required=True, help="Action to check")
    p_check.add_argument("--agent", help="Agent name")
    p_check.add_argument("--tags", help="Comma-separated tags")
    p_check.add_argument("--min-confidence", type=float, default=0.3)

    # reflect
    p_reflect = sub.add_parser("reflect", help="Reflect on mistakes")
    p_reflect.add_argument("--mistake-id", help="Specific mistake to reflect on")
    p_reflect.add_argument("--all-unresolved", action="store_true", help="Reflect on all unresolved")

    # stats
    p_stats = sub.add_parser("stats", help="Show statistics")
    p_stats.add_argument("--agent", help="Filter by agent")
    p_stats.add_argument("--days", type=int, default=30)

    # dashboard
    sub.add_parser("dashboard", help="Show dashboard")

    args = parser.parse_args()

    handlers = {
        "mistake": {
            "add": cmd_mistake_add,
            "list": cmd_mistake_list,
            "show": cmd_mistake_show,
        },
        "lesson": {
            "list": cmd_lesson_list,
            "show": cmd_lesson_show,
        },
        "check": {"": cmd_check},
        "reflect": {"": cmd_reflect},
        "stats": {"": cmd_stats},
        "dashboard": {"": cmd_dashboard},
    }

    if args.command in handlers:
        subcmd = getattr(args, "subcommand", "") or ""
        handler = handlers[args.command].get(subcmd)
        if handler:
            handler(args)
        else:
            parser.parse_args([args.command, "--help"])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
