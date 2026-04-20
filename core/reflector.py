"""
reflector.py — วิเคราะห์ความผิดพลาดด้วย LLM → สร้างบทเรียน

ใช้ pattern นี้:
  mistake → ให้ LLM วิเคราะห์ → สร้าง prevention rule → เก็บเป็น lesson
"""

import json
import subprocess
from typing import Optional
from dataclasses import dataclass

from .memory_engine import MemoryEngine, Lesson


REFLECTION_PROMPT = """คุณเป็น AI analyst ที่เชี่ยวชาญด้านการวิเคราะห์ความผิดพลาดของ agent

## ความผิดพลาดที่เกิดขึ้น
- **Agent:** {agent_name}
- **งาน:** {task_description}
- **ประเภท Error:** {error_type}
- **ข้อความ Error:** {error_message}
- **Context:** {context}
- **Stack Trace:** {stack_trace}

## บทเรียนที่เคยมี (ถ้ามี)
{existing_lessons}

## หน้าที่
วิเคราะห์ความผิดพลาดนี้แล้วตอบเป็น JSON เท่านั้น (ไม่มี markdown wrapper):

{{
  "root_cause": "สาเหตุหลักสั้นๆ",
  "why_it_happened": "อธิบายเหตุผลเชิงลึกว่าทำไมถึงเกิด",
  "how_to_prevent": "วิธีป้องกันอย่างละเอียด",
  "prevention_rule": "rule สั้นๆ สำหรับ pre-flight check (เช่น 'ห้ามเรียก API โดยไม่มี timeout')",
  "confidence": 0.8,
  "tags": ["tag1", "tag2"]
}}

กฎ:
- prevention_rule ต้องสั้น กระชับ ตรวจสอบได้โปรแกรม
- confidence 0.0-1.0 ตามความมั่นใจ
- ตอบเป็น JSON ล้วน ไม่มี ```json``` wrapper"""


class Reflector:
    """วิเคราะห์ความผิดพลาด → สร้างบทเรียน"""

    def __init__(self, engine: MemoryEngine, llm_provider: str = "local"):
        self.engine = engine
        self.llm_provider = llm_provider

    def reflect_on_mistake(self, mistake_id: str) -> Optional[str]:
        """
        วิเคราะห์ mistake → สร้าง lesson → เก็บลง engine
        คืนค่า lesson_id หรือ None ถ้าวิเคราะห์ไม่ได้
        """
        mistake = self.engine.get_mistake(mistake_id)
        if not mistake:
            return None

        # หาบทเรียนที่มีอยู่แล้วสำหรับ context
        existing = self.engine.get_relevant_lessons(
            task_description=mistake["task_description"],
            agent_name=mistake["agent_name"],
        )
        existing_text = ""
        if existing:
            existing_text = "\n".join(
                f"- [{l['id']}] {l['prevention_rule']} (confidence: {l['confidence']:.1f})"
                for l in existing[:5]
            )

        prompt = REFLECTION_PROMPT.format(
            agent_name=mistake["agent_name"],
            task_description=mistake["task_description"],
            error_type=mistake["error_type"],
            error_message=mistake["error_message"],
            context=json.dumps(mistake["context"], ensure_ascii=False, indent=2),
            stack_trace=mistake["stack_trace"][:2000],
            existing_lessons=existing_text or "ยังไม่มี",
        )

        response = self._call_llm(prompt)
        if not response:
            return None

        try:
            analysis = json.loads(response)
        except json.JSONDecodeError:
            # ลอง strip markdown wrapper
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[1:])
            if cleaned.endswith("```"):
                cleaned = "\n".join(cleaned.split("\n")[:-1])
            try:
                analysis = json.loads(cleaned.strip())
            except json.JSONDecodeError:
                return None

        lesson_id = self.engine.add_lesson(
            mistake_id=mistake_id,
            root_cause=analysis.get("root_cause", "ไม่ทราบสาเหตุ"),
            why_it_happened=analysis.get("why_it_happened", ""),
            how_to_prevent=analysis.get("how_to_prevent", ""),
            prevention_rule=analysis.get("prevention_rule", ""),
            confidence=analysis.get("confidence", 0.5),
            tags=analysis.get("tags", []),
        )

        # มาร์ค mistake เป็น resolved
        self.engine.mark_resolved(mistake_id)

        return lesson_id

    def quick_reflect(
        self,
        agent_name: str,
        task: str,
        error_type: str,
        error_msg: str,
        context: dict = None,
    ) -> Optional[str]:
        """
        ทางลัด: log mistake + reflect ในครั้งเดียว
        """
        mid = self.engine.log_mistake(
            agent_name=agent_name,
            task_description=task,
            error_type=error_type,
            error_message=error_msg,
            context=context or {},
        )
        return self.reflect_on_mistake(mid)

    def _call_llm(self, prompt: str) -> Optional[str]:
        """เรียก LLM — ปรับแต่งตาม provider ที่ใช้"""

        if self.llm_provider == "local":
            # ใช้ subprocess เรียก Python script ที่มี LLM
            return self._call_local_llm(prompt)
        elif self.llm_provider == "openclaw":
            return self._call_openclaw_llm(prompt)
        else:
            return self._call_local_llm(prompt)

    def _call_local_llm(self, prompt: str) -> Optional[str]:
        """ใช้ pattern-based analysis ไม่ต้องพึ่ง API"""
        # Fallback: heuristic analysis
        lines = prompt.split("\n")
        error_msg = ""
        error_type = ""
        for line in lines:
            if "**ข้อความ Error:**" in line:
                error_msg = line.split("**ข้อความ Error:**")[1].strip()
            if "**ประเภท Error:**" in line:
                error_type = line.split("**ประเภท Error:**")[1].strip()

        analysis = {
            "root_cause": f"{error_type}: {error_msg[:100]}",
            "why_it_happened": f"Agent เจอ {error_type} ระหว่างทำงาน",
            "how_to_prevent": f"ตรวจสอบ {error_type} ก่อนทำงาน",
            "prevention_rule": f"check_{error_type.lower().replace(' ', '_')}_before_action",
            "confidence": 0.4,
            "tags": [error_type.lower().replace(" ", "_"), "auto_analyzed"],
        }
        return json.dumps(analysis, ensure_ascii=False)

    def _call_openclaw_llm(self, prompt: str) -> Optional[str]:
        """ใช้ OpenClaw sessions_spawn เพื่อวิเคราะห์"""
        # สำหรับ integration กับ OpenClaw
        return self._call_local_llm(prompt)
