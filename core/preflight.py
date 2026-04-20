"""
preflight.py — ตรวจสอบก่อนทำงาน ป้องกันความผิดพลาดซ้ำ

Flow:
  Agent กำลังจะทำงาน
    → PreFlightChecker.check() — โหลดบทเรียนที่เกี่ยวข้อง
    → ถ้ามี warning → แจ้งเตือน / block / ปรับ behavior
    → ทำงาน (พร้อม guard)
    → บันทึกผลลัพธ์ → ปรับ confidence
"""

import json
import time
from typing import Optional, Callable
from dataclasses import dataclass
from functools import wraps

from .memory_engine import MemoryEngine


@dataclass
class PreflightWarning:
    lesson_id: str
    prevention_rule: str
    confidence: float
    times_prevented: int
    how_to_prevent: str
    severity: str  # block / warn / info


class PreFlightChecker:
    """ตรวจสอบก่อนทำงาน — โหลดบทเรียนมาป้องกัน"""

    def __init__(self, engine: MemoryEngine):
        self.engine = engine

    def check(
        self,
        action: str,
        agent_name: str = None,
        tags: list[str] = None,
        min_confidence: float = 0.3,
    ) -> list[PreflightWarning]:
        """
        ตรวจสอบ action ก่อนทำงาน
        คืนค่า list ของ warning ที่เกี่ยวข้อง
        """
        lessons = self.engine.get_relevant_lessons(
            task_description=action,
            agent_name=agent_name,
            tags=tags,
            min_confidence=min_confidence,
        )

        warnings = []
        for lesson in lessons:
            # คำนวณ severity จาก confidence + effectiveness
            effectiveness = 0
            if lesson["times_applied"] > 0:
                effectiveness = lesson["times_prevented"] / lesson["times_applied"]

            severity = "info"
            if lesson["confidence"] > 0.7 and effectiveness > 0.5:
                severity = "block"
            elif lesson["confidence"] > 0.5:
                severity = "warn"

            warnings.append(PreflightWarning(
                lesson_id=lesson["id"],
                prevention_rule=lesson["prevention_rule"],
                confidence=lesson["confidence"],
                times_prevented=lesson["times_prevented"],
                how_to_prevent=lesson["how_to_prevent"],
                severity=severity,
            ))

        return warnings

    def execute_with_guard(
        self,
        action_name: str,
        func: Callable,
        agent_name: str = None,
        tags: list[str] = None,
        on_warning: Callable = None,
        *args,
        **kwargs,
    ) -> dict:
        """
        ทำงานพร้อม guard — ตรวจบทเรียนก่อน → ทำงาน → บันทึกผล

        Returns:
            {
                "success": bool,
                "warnings": list[PreflightWarning],
                "lessons_applied": list[str],
                "result": any,
                "error": str or None,
            }
        """
        warnings = self.check(action_name, agent_name=agent_name, tags=tags)
        lessons_applied = [w.lesson_id for w in warnings]

        # ถ้ามี warning ระดับ block → ให้ on_warning ตัดสินใจ
        blocked = [w for w in warnings if w.severity == "block"]
        if blocked and on_warning:
            should_proceed = on_warning(blocked)
            if not should_proceed:
                # บันทึกว่า prevented
                for w in blocked:
                    self.engine.record_lesson_applied(w.lesson_id, prevented=True)
                self.engine.log_action(
                    agent_name=agent_name or "unknown",
                    action=action_name,
                    lessons_checked=lessons_applied,
                    outcome="prevented",
                )
                return {
                    "success": False,
                    "warnings": warnings,
                    "lessons_applied": lessons_applied,
                    "result": None,
                    "error": "Blocked by pre-flight warning",
                }

        # ทำงาน
        try:
            result = func(*args, **kwargs)
            # สำเร็จ → บันทึก
            self.engine.log_action(
                agent_name=agent_name or "unknown",
                action=action_name,
                lessons_checked=lessons_applied,
                outcome="success",
            )
            # ถ้ามี warning แต่สำเร็จ → บางที false positive
            for w in warnings:
                self.engine.record_lesson_applied(w.lesson_id, prevented=False)

            return {
                "success": True,
                "warnings": warnings,
                "lessons_applied": lessons_applied,
                "result": result,
                "error": None,
            }

        except Exception as e:
            # ล้มเหลว → บันทึก mistake
            error_type = type(e).__name__
            mid = self.engine.log_mistake(
                agent_name=agent_name or "unknown",
                task_description=action_name,
                error_type=error_type,
                error_message=str(e),
                context={"args": str(args), "kwargs": str(kwargs)},
            )
            self.engine.log_action(
                agent_name=agent_name or "unknown",
                action=action_name,
                lessons_checked=lessons_applied,
                outcome="failed",
                mistake_id=mid,
            )
            # ถ้ามี warning แล้วยัง fail → lesson ใช้ได้
            for w in warnings:
                self.engine.record_lesson_applied(w.lesson_id, prevented=False)

            return {
                "success": False,
                "warnings": warnings,
                "lessons_applied": lessons_applied,
                "result": None,
                "error": str(e),
                "mistake_id": mid,
            }


def with_preflight(
    engine: MemoryEngine,
    action_name: str,
    agent_name: str = None,
    tags: list[str] = None,
):
    """
    Decorator สำหรับ protect function ด้วย preflight check

    Usage:
        @with_preflight(engine, "call_api", agent_name="my_agent")
        def call_api(url, timeout=30):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            checker = PreFlightChecker(engine)
            warnings = checker.check(action_name, agent_name=agent_name, tags=tags)
            lessons_applied = [w.lesson_id for w in warnings]

            blocked = [w for w in warnings if w.severity == "block"]
            if blocked:
                for w in blocked:
                    engine.record_lesson_applied(w.lesson_id, prevented=True)
                engine.log_action(
                    agent_name=agent_name or "unknown",
                    action=action_name,
                    lessons_checked=lessons_applied,
                    outcome="prevented",
                )
                raise RuntimeError(
                    f"Action '{action_name}' blocked by pre-flight: "
                    + "; ".join(w.prevention_rule for w in blocked)
                )

            try:
                result = func(*args, **kwargs)
                engine.log_action(
                    agent_name=agent_name or "unknown",
                    action=action_name,
                    lessons_checked=lessons_applied,
                    outcome="success",
                )
                for w in warnings:
                    engine.record_lesson_applied(w.lesson_id, prevented=False)
                return result
            except Exception as e:
                error_type = type(e).__name__
                mid = engine.log_mistake(
                    agent_name=agent_name or "unknown",
                    task_description=action_name,
                    error_type=error_type,
                    error_message=str(e),
                    context={"args": str(args), "kwargs": str(kwargs)},
                )
                engine.log_action(
                    agent_name=agent_name or "unknown",
                    action=action_name,
                    lessons_checked=lessons_applied,
                    outcome="failed",
                    mistake_id=mid,
                )
                raise
        return wrapper
    return decorator
