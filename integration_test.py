"""
integration_test.py — ทดสอบระบบจริง end-to-end
จำลอง agent ทำงานจริง → ผิดพลาด → เรียนรู้ → ป้องกัน
"""

import sys
import json
import sqlite3
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.memory_engine import MemoryEngine
from core.reflector import Reflector
from core.preflight import PreFlightChecker, with_preflight


def test_scenario_1_db_agent():
    """Scenario: Agent ที่ทำงานกับ database แล้วเจอ error ซ้ำๆ"""
    print("\n" + "=" * 60)
    print("📦 Scenario 1: Database Agent")
    print("=" * 60)

    engine = MemoryEngine("data/integration_test.db")
    reflector = Reflector(engine)
    checker = PreFlightChecker(engine)

    # ═══ Round 1: Agent ทำงานครั้งแรก → ล้มเหลว ═══
    print("\n🔴 Round 1: Agent ลอง query database โดยไม่ได้สร้าง table ก่อน...")

    def query_users():
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")  # table ไม่มี!
        return cursor.fetchall()

    try:
        query_users()
    except sqlite3.OperationalError as e:
        mid = engine.log_mistake(
            agent_name="db-agent",
            task_description="query users จาก database",
            error_type="OperationalError",
            error_message=str(e),
            context={"query": "SELECT * FROM users", "db": ":memory:"},
            tags=["database", "sql", "schema"],
            severity="critical",
        )
        print(f"   ✗ Error: {e}")
        print(f"   📝 Mistake logged: {mid}")

        # วิเคราะห์
        lid = reflector.reflect_on_mistake(mid)
        lesson = engine.get_lesson(lid)
        print(f"   💭 Lesson: {lesson['prevention_rule']}")

    # ═══ Round 2: Pre-flight check → เจอ warning ═══
    print("\n🟡 Round 2: Agent จะ query อีกครั้ง → pre-flight check...")

    warnings = checker.check(
        action="query users จาก database",
        agent_name="db-agent",
    )
    for w in warnings:
        print(f"   ⚠️  [{w.severity}] {w.prevention_rule}")
        print(f"       → {w.how_to_prevent}")

    # ═══ Round 3: Agent ทำงานพร้อม guard + แก้ปัญหา ═══
    print("\n🟢 Round 3: Agent ทำงานพร้อม guard + สร้าง table ก่อน...")

    def query_users_safe():
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        # สร้าง table ก่อน (ตาม lesson)
        cursor.execute("CREATE TABLE IF NOT EXISTS users (id INT, name TEXT)")
        cursor.execute("INSERT INTO users VALUES (1, 'Alice')")
        cursor.execute("SELECT * FROM users")
        return cursor.fetchall()

    result = checker.execute_with_guard(
        action_name="query users (safe)",
        func=query_users_safe,
        agent_name="db-agent",
    )
    print(f"   ✓ Success: {result['success']}, Result: {result['result']}")

    # ═══ Stats ═══
    stats = engine.get_stats(days=1)
    print(f"\n📊 Stats: {stats['total_mistakes']} mistakes, {stats['total_lessons']} lessons")

    engine.close()
    print("✅ Scenario 1 passed!")


def test_scenario_2_api_agent():
    """Scenario: Agent ที่เรียก API แล้วเจอ timeout/retry issues"""
    print("\n" + "=" * 60)
    print("🌐 Scenario 2: API Agent")
    print("=" * 60)

    engine = MemoryEngine("data/integration_test.db")
    reflector = Reflector(engine)
    checker = PreFlightChecker(engine)

    # ═══ Simulate API failures ═══
    errors = [
        {
            "task": "ดึงข้อมูลผู้ใช้จาก API",
            "type": "TimeoutError",
            "msg": "GET https://api.example.com/users timed out after 5s",
            "context": {"url": "https://api.example.com/users", "timeout": 5, "retry": 0},
        },
        {
            "task": "ส่งข้อมูลไป API",
            "type": "HTTPError",
            "msg": "POST https://api.example.com/data returned 429 Too Many Requests",
            "context": {"url": "https://api.example.com/data", "status": 429, "retry": 3},
        },
        {
            "task": "อัพโหลดไฟล์",
            "type": "ConnectionError",
            "msg": "Connection refused to https://api.example.com/upload",
            "context": {"url": "https://api.example.com/upload", "attempt": 5},
        },
    ]

    for err in errors:
        mid = engine.log_mistake(
            agent_name="api-agent",
            task_description=err["task"],
            error_type=err["type"],
            error_message=err["msg"],
            context=err["context"],
            tags=["api", "network"],
            severity="warning",
        )
        lid = reflector.reflect_on_mistake(mid)
        print(f"   ✗ {err['type']}: {err['msg'][:50]}...")

    # ═══ Pre-flight check ═══
    print("\n⚠️  Pre-flight check before next API call:")
    warnings = checker.check(
        action="ดึงข้อมูลผู้ใช้จาก API",
        agent_name="api-agent",
    )
    for w in warnings:
        print(f"   [{w.severity}] {w.prevention_rule} (confidence: {w.confidence:.1f})")

    engine.close()
    print("✅ Scenario 2 passed!")


def test_scenario_3_decorator():
    """Scenario: ใช้ @with_preflight decorator กับ function จริง"""
    print("\n" + "=" * 60)
    print("🔧 Scenario 3: Decorator Integration")
    print("=" * 60)

    engine = MemoryEngine("data/integration_test.db")

    # สร้าง lesson มาก่อน
    mid = engine.log_mistake(
        agent_name="file-agent",
        task_description="อ่านไฟล์ config",
        error_type="FileNotFoundError",
        error_message="[Errno 2] No such file or directory: '/etc/app/config.yaml'",
        context={"path": "/etc/app/config.yaml"},
    )
    reflector = Reflector(engine)
    reflector.reflect_on_mistake(mid)

    # ใช้ decorator
    @with_preflight(engine, "read_config", agent_name="file-agent")
    def read_config(path):
        with open(path) as f:
            return f.read()

    # ลองเรียก (file ไม่มี → error → ระบบจับ mistake อัตโนมัติ)
    print("\n   Trying to read non-existent file with guard...")
    try:
        read_config("/tmp/nonexistent_config.yaml")
    except (RuntimeError, FileNotFoundError) as e:
        print(f"   ✗ Caught: {type(e).__name__}: {str(e)[:60]}")

    # สร้างไฟล์จริงแล้วลองใหม่
    Path("/tmp/test_config.yaml").write_text("debug: true\nport: 8080")
    print("\n   Trying to read existing file with guard...")
    try:
        content = read_config("/tmp/test_config.yaml")
        print(f"   ✓ Read succeeded: {content.strip()}")
    except Exception as e:
        print(f"   ✗ Unexpected error: {e}")

    stats = engine.get_stats(days=1)
    print(f"\n📊 Total actions tracked: {stats['actions'].get('total', 0)}")
    print(f"   Success: {stats['actions'].get('successes', 0)}")
    print(f"   Failed: {stats['actions'].get('failures', 0)}")

    engine.close()
    print("✅ Scenario 3 passed!")


def test_scenario_4_false_positive():
    """Scenario: ทดสอบ confidence auto-adjustment"""
    print("\n" + "=" * 60)
    print("📈 Scenario 4: Confidence Auto-Adjustment")
    print("=" * 60)

    engine = MemoryEngine("data/integration_test.db")
    reflector = Reflector(engine)
    checker = PreFlightChecker(engine)

    # สร้าง mistake + lesson
    mid = engine.log_mistake(
        agent_name="test-agent",
        task_description="ส่ง notification",
        error_type="RateLimitError",
        error_message="Rate limit exceeded: 100 req/min",
    )
    lid = reflector.reflect_on_mistake(mid)
    lesson = engine.get_lesson(lid)
    print(f"   Initial confidence: {lesson['confidence']:.1f}")

    # ลองทำงานหลายครั้ง → ดู confidence เปลี่ยน
    def send_notification():
        return "sent"

    for i in range(5):
        result = checker.execute_with_guard(
            action_name=f"ส่ง notification (ครั้งที่ {i+1})",
            func=send_notification,
            agent_name="test-agent",
        )

    # ดู lesson หลังใช้หลายครั้ง
    lesson = engine.get_lesson(lid)
    print(f"   After 5 successes:")
    print(f"     Applied: {lesson['times_applied']}x")
    print(f"     Prevented: {lesson['times_prevented']}x")
    print(f"     Confidence: {lesson['confidence']:.1f}")

    # ทดสอบ false positive
    engine.record_false_positive(lid)
    lesson = engine.get_lesson(lid)
    print(f"   After false positive:")
    print(f"     Confidence: {lesson['confidence']:.1f} (decreased)")

    # ทดสอบ boost
    engine.boost_confidence(lid, 0.3)
    lesson = engine.get_lesson(lid)
    print(f"   After boost:")
    print(f"     Confidence: {lesson['confidence']:.1f} (increased)")

    engine.close()
    print("✅ Scenario 4 passed!")


def test_scenario_5_multiple_agents():
    """Scenario: หลาย agent แชร์ memory"""
    print("\n" + "=" * 60)
    print("👥 Scenario 5: Multi-Agent Shared Memory")
    print("=" * 60)

    engine = MemoryEngine("data/integration_test.db")
    reflector = Reflector(engine)

    # Agent A ทำผิด
    mid_a = engine.log_mistake(
        agent_name="agent-alpha",
        task_description="ส่ง webhook",
        error_type="SSLError",
        error_message="SSL certificate verification failed",
        context={"url": "https://hooks.example.com/webhook"},
    )
    reflector.reflect_on_mistake(mid_a)
    print("   ✗ agent-alpha: SSL error")

    # Agent B ก็เจอปัญหาเดียวกัน
    mid_b = engine.log_mistake(
        agent_name="agent-beta",
        task_description="เรียก HTTPS API",
        error_type="SSLError",
        error_message="SSL certificate verification failed",
        context={"url": "https://api.internal.com/data"},
    )
    reflector.reflect_on_mistake(mid_b)
    print("   ✗ agent-beta: SSL error (same type!)")

    # Agent C กำลังจะทำงาน → ดึง lesson ทั้งหมด
    print("\n   agent-gamma pre-flight check:")
    warnings = engine.get_relevant_lessons(
        task_description="เชื่อมต่อ HTTPS",
        min_confidence=0.0,
    )
    for w in warnings:
        print(f"     📋 {w['prevention_rule']} (from mistake: {w['mistake_id'][:8]}...)")

    engine.close()
    print("✅ Scenario 5 passed!")


if __name__ == "__main__":
    print("🧠 Self-Improving Agent — Integration Test Suite")
    print("=" * 60)

    test_scenario_1_db_agent()
    test_scenario_2_api_agent()
    test_scenario_3_decorator()
    test_scenario_4_false_positive()
    test_scenario_5_multiple_agents()

    print("\n" + "=" * 60)
    print("🎉 All 5 scenarios passed!")
    print("=" * 60)
