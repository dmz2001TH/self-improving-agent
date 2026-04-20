#!/usr/bin/env python3
"""
Usage examples — ตัวอย่างการใช้งาน Self-Improving Agent Memory Engine
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.memory_engine import MemoryEngine
from core.reflector import Reflector
from core.preflight import PreFlightChecker, with_preflight


def demo_full_cycle():
    """สาธิตวงจรเต็ม: ผิด → จำ → วิเคราะห์ → ป้องกัน"""

    engine = MemoryEngine("data/memory.db")
    reflector = Reflector(engine)
    checker = PreFlightChecker(engine)

    print("=" * 60)
    print("🧠 Self-Improving Agent — Full Cycle Demo")
    print("=" * 60)

    # ─── Step 1: Agent ทำงานแล้วผิดพลาด ─────────────────────
    print("\n📌 Step 1: Agent ทำงานล้มเหลว...")

    mid = engine.log_mistake(
        agent_name="email-bot",
        task_description="ส่งอีเมลแจ้งเตือนลูกค้า",
        error_type="ConnectionError",
        error_message="SMTP server timeout after 30s: smtp.company.com:587",
        context={
            "smtp_host": "smtp.company.com",
            "smtp_port": 587,
            "recipient": "customer@example.com",
            "timeout": 30,
        },
        tags=["email", "network", "timeout"],
        severity="critical",
    )
    print(f"   ✗ Mistake logged: {mid}")

    # ─── Step 2: วิเคราะห์ → สร้างบทเรียน ──────────────────
    print("\n📌 Step 2: วิเคราะห์ความผิดพลาด...")

    lid = reflector.reflect_on_mistake(mid)
    lesson = engine.get_lesson(lid)
    print(f"   💭 Lesson created: {lid}")
    print(f"   Rule: {lesson['prevention_rule']}")
    print(f"   Root Cause: {lesson['root_cause']}")
    print(f"   Confidence: {lesson['confidence']}")

    # ─── Step 3: ครั้งต่อไป → Pre-flight check ────────────────
    print("\n📌 Step 3: ครั้งต่อไป Agent จะส่งอีเมลอีก...")

    warnings = checker.check(
        action="ส่งอีเมลแจ้งเตือนลูกค้า",
        agent_name="email-bot",
    )

    if warnings:
        print(f"   ⚠ Pre-flight warnings found:")
        for w in warnings:
            print(f"      [{w.severity.upper()}] {w.prevention_rule}")
            print(f"      → {w.how_to_prevent}")

    # ─── Step 4: ทำงานพร้อม guard ────────────────────────────
    print("\n📌 Step 4: ทำงานพร้อม guard...")

    def send_email_safe():
        """จำลองการส่งอีเมลที่ปลอดภัย"""
        # ตรวจสอบ SMTP ก่อน (ตาม lesson)
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            sock.connect(("smtp.company.com", 587))
            sock.close()
            return "Email sent successfully"
        except Exception as e:
            raise ConnectionError(f"SMTP check failed: {e}")

    result = checker.execute_with_guard(
        action_name="ส่งอีเมล (with guard)",
        func=send_email_safe,
        agent_name="email-bot",
        on_warning=lambda warnings: True,  # ดำเนินการต่อ
    )

    print(f"   Result: success={result['success']}, error={result['error']}")

    # ─── Step 5: ดูสถิติ ──────────────────────────────────────
    print("\n📌 Step 5: ดูสถิติ...")
    stats = engine.get_stats(days=30)
    print(f"   Total mistakes: {stats['total_mistakes']}")
    print(f"   Total lessons: {stats['total_lessons']}")
    print(f"   Actions: {stats['actions']}")

    engine.close()
    print("\n✅ Demo complete!")


def demo_decorator_usage():
    """สาธิตการใช้ @with_preflight decorator"""

    engine = MemoryEngine("data/memory.db")

    print("\n" + "=" * 60)
    print("🔧 Decorator Usage Demo")
    print("=" * 60)

    # สร้าง lesson ก่อน
    mid = engine.log_mistake(
        agent_name="api-bot",
        task_description="เรียก API ภายนอก",
        error_type="TimeoutError",
        error_message="Request to https://api.example.com timed out",
        context={"url": "https://api.example.com", "timeout": 5},
    )
    reflector = Reflector(engine)
    reflector.reflect_on_mistake(mid)

    # ใช้ decorator
    @with_preflight(engine, "call_external_api", agent_name="api-bot")
    def call_api(url, timeout=30):
        import urllib.request
        return urllib.request.urlopen(url, timeout=timeout).read()

    try:
        result = call_api("https://httpbin.org/get", timeout=10)
        print(f"   ✓ API call succeeded: {len(result)} bytes")
    except Exception as e:
        print(f"   ✗ API call failed: {e}")

    engine.close()


if __name__ == "__main__":
    demo_full_cycle()
    demo_decorator_usage()
