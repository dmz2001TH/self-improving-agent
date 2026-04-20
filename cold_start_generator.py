#!/usr/bin/env python3
"""
cold_start_generator.py — สร้าง COLD_START.md อัตโนมัติจาก memory files

Usage:
    python3 cold_start_generator.py --memory-dir /path/to/memory --output COLD_START.md
    python3 cold_start_generator.py --memory-dir /path/to/memory --output COLD_START.md --agent builder
"""

import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta


def read_recent_memories(memory_dir: str, days: int = 7) -> list[dict]:
    """อ่าน memory files ล่าสุด"""
    memory_path = Path(memory_dir)
    if not memory_path.exists():
        return []

    memories = []
    cutoff = datetime.now() - timedelta(days=days)

    for f in sorted(memory_path.glob("*.md"), reverse=True):
        # ลอง parse ชื่อไฟล์เป็นวันที่
        name = f.stem
        try:
            date = datetime.strptime(name, "%Y-%m-%d")
            if date < cutoff:
                continue
        except ValueError:
            pass  # ไม่ใช่ไฟล์วันที่ แต่ก็อ่านได้

        content = f.read_text(encoding="utf-8", errors="replace")
        if content.strip():
            memories.append({
                "file": f.name,
                "content": content[:2000],  # จำกัดความยาว
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    return memories[:10]  # จำกัดแค่ 10 ไฟล์ล่าสุด


def read_static_files(workspace_dir: str) -> dict:
    """อ่านไฟล์ static (SOUL.md, USER.md, TOOLS.md)"""
    static = {}
    for name in ["SOUL.md", "USER.md", "TOOLS.md", "IDENTITY.md"]:
        path = Path(workspace_dir) / name
        if path.exists():
            static[name] = path.read_text(encoding="utf-8", errors="replace")[:1000]
    return static


def generate_cold_start(
    agent_name: str,
    workspace_dir: str,
    memory_dir: str,
    lessons_db: str = None,
) -> str:
    """สร้าง COLD_START.md content"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # อ่าน static files
    static = read_static_files(workspace_dir)

    # อ่าน recent memories
    memories = read_recent_memories(memory_dir)

    # อ่าน lessons (ถ้ามี)
    lessons = []
    if lessons_db and Path(lessons_db).exists():
        try:
            import sqlite3
            conn = sqlite3.connect(lessons_db)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT prevention_rule, how_to_prevent, confidence
                   FROM lessons WHERE confidence >= 0.3
                   ORDER BY confidence DESC, times_prevented DESC LIMIT 10"""
            ).fetchall()
            lessons = [dict(r) for r in rows]
            conn.close()
        except Exception:
            pass

    # สร้าง content
    lines = [
        f"# 🚀 {agent_name} — Cold Start Memory",
        f"",
        f"> Auto-generated: {now}",
        f"> ไฟล์นี้สร้างอัตโนมัติ อ่านไฟล์เดียว = จำได้เลย",
        f"",
        f"---",
        f"",
    ]

    # Identity
    if "IDENTITY.md" in static:
        lines.append(f"## ฉันคือใคร")
        lines.append(f"")
        for line in static["IDENTITY.md"].split("\n")[:5]:
            if line.strip():
                lines.append(f"- {line.strip()}")
        lines.append(f"")

    # Current context from latest memory
    if memories:
        lines.append(f"## ความจำล่าสุด")
        lines.append(f"")
        latest = memories[0]
        lines.append(f"### {latest['file']}")
        lines.append(f"")
        # ดึง bullet points สำคัญ
        for line in latest["content"].split("\n"):
            stripped = line.strip()
            if stripped and (stripped.startswith("-") or stripped.startswith("*") or stripped.startswith("#")):
                lines.append(stripped)
            elif len(stripped) > 20 and len(stripped) < 200:
                lines.append(f"- {stripped}")
        lines.append(f"")

    # Other recent memories (summary only)
    if len(memories) > 1:
        lines.append(f"## ความจำก่อนหน้า")
        lines.append(f"")
        for mem in memories[1:5]:
            lines.append(f"### {mem['file']}")
            # ดึงแค่ header หรือ bullet แรก
            for line in mem["content"].split("\n")[:10]:
                stripped = line.strip()
                if stripped.startswith("#") or (stripped.startswith("-") and len(stripped) > 10):
                    lines.append(stripped)
            lines.append(f"")

    # Lessons
    if lessons:
        lines.append(f"## ⚡ บทเรียน (ต้องจำ)")
        lines.append(f"")
        for l in lessons:
            conf = l["confidence"]
            icon = "🔴" if conf > 0.7 else "🟡" if conf > 0.4 else "⚪"
            lines.append(f"- {icon} **{l['prevention_rule']}** — {l['how_to_prevent'][:80]} (conf: {conf:.1f})")
        lines.append(f"")

    # User preferences from USER.md
    if "USER.md" in static:
        lines.append(f"## ข้อมูลผู้ใช้")
        lines.append(f"")
        for line in static["USER.md"].split("\n"):
            if line.strip().startswith("-") and ":" in line:
                lines.append(line)
        lines.append(f"")

    lines.extend([
        f"---",
        f"",
        f"> 💡 **อ่านไฟล์นี้แล้วทำงานได้เลย**",
        f"> ถ้างานซับซ้อน ค่อยอ่านไฟล์อื่นเพิ่ม",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate cold-start memory snapshot")
    parser.add_argument("--agent", default="builder", help="Agent name")
    parser.add_argument("--workspace", default=".", help="Workspace directory")
    parser.add_argument("--memory-dir", default=None, help="Memory directory (default: workspace/memory)")
    parser.add_argument("--output", default="COLD_START.md", help="Output file")
    parser.add_argument("--lessons-db", default=None, help="Path to lessons SQLite DB")
    args = parser.parse_args()

    memory_dir = args.memory_dir or str(Path(args.workspace) / "memory")

    content = generate_cold_start(
        agent_name=args.agent,
        workspace_dir=args.workspace,
        memory_dir=memory_dir,
        lessons_db=args.lessons_db,
    )

    output_path = Path(args.output)
    output_path.write_text(content, encoding="utf-8")
    print(f"✓ Generated {output_path} ({len(content)} chars)")
    print(f"  Agent: {args.agent}")
    print(f"  Memory dir: {memory_dir}")


if __name__ == "__main__":
    main()
