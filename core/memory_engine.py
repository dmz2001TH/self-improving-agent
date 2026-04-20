"""
memory_engine.py — SQLite-backed persistent memory for self-improving agents
"""

import sqlite3
import json
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict


@dataclass
class Mistake:
    id: Optional[str]
    timestamp: str
    agent_name: str
    task_description: str
    error_type: str
    error_message: str
    context: dict          # บริบทตอนเกิด error
    stack_trace: str
    tags: list[str]
    severity: str          # critical / warning / info
    resolved: bool


@dataclass
class Lesson:
    id: Optional[str]
    mistake_id: str
    timestamp: str
    root_cause: str         # สาเหตุหลัก
    why_it_happened: str    # ทำไมถึงเกิด
    how_to_prevent: str     # ป้องกันยังไง
    prevention_rule: str    # rule สั้นๆ สำหรับ pre-flight check
    confidence: float       # 0.0 - 1.0
    times_applied: int      # ใช้กี่ครั้งแล้ว
    times_prevented: int    # ป้องกันได้กี่ครั้ง
    false_positive: int     # เตือนแต่ไม่จริงกี่ครั้ง
    tags: list[str]


@dataclass
class ActionLog:
    id: Optional[str]
    timestamp: str
    agent_name: str
    action: str
    lessons_checked: list[str]  # lesson ids ที่เช็คก่อนทำ
    outcome: str                # success / failed / prevented
    mistake_id: Optional[str]
    metadata: dict


class MemoryEngine:
    """Core memory engine — เก็บความผิดพลาดและบทเรียน"""

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS mistakes (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                task_description TEXT NOT NULL,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '{}',
                stack_trace TEXT DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                severity TEXT NOT NULL DEFAULT 'warning',
                resolved INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS lessons (
                id TEXT PRIMARY KEY,
                mistake_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                root_cause TEXT NOT NULL,
                why_it_happened TEXT NOT NULL,
                how_to_prevent TEXT NOT NULL,
                prevention_rule TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                times_applied INTEGER NOT NULL DEFAULT 0,
                times_prevented INTEGER NOT NULL DEFAULT 0,
                false_positive INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '[]',
                FOREIGN KEY (mistake_id) REFERENCES mistakes(id)
            );

            CREATE TABLE IF NOT EXISTS action_logs (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                action TEXT NOT NULL,
                lessons_checked TEXT NOT NULL DEFAULT '[]',
                outcome TEXT NOT NULL,
                mistake_id TEXT,
                metadata TEXT NOT NULL DEFAULT '{}'
            );

            CREATE INDEX IF NOT EXISTS idx_mistakes_agent ON mistakes(agent_name);
            CREATE INDEX IF NOT EXISTS idx_mistakes_type ON mistakes(error_type);
            CREATE INDEX IF NOT EXISTS idx_mistakes_severity ON mistakes(severity);
            CREATE INDEX IF NOT EXISTS idx_lessons_mistake ON lessons(mistake_id);
            CREATE INDEX IF NOT EXISTS idx_lessons_confidence ON lessons(confidence);
            CREATE INDEX IF NOT EXISTS idx_action_logs_agent ON action_logs(agent_name);
            CREATE INDEX IF NOT EXISTS idx_action_logs_outcome ON action_logs(outcome);
        """)
        self.conn.commit()

    # ─── Mistakes ───────────────────────────────────────────────

    def _gen_id(self, prefix: str = "") -> str:
        raw = f"{prefix}{time.time_ns()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def log_mistake(
        self,
        agent_name: str,
        task_description: str,
        error_type: str,
        error_message: str,
        context: dict = None,
        stack_trace: str = "",
        tags: list[str] = None,
        severity: str = "warning",
    ) -> str:
        """บันทึกความผิดพลาด"""
        mid = self._gen_id("mistake_")
        now = datetime.utcnow().isoformat()

        # ตรวจสอบว่า mistake ซ้ำมั้ย (dedup)
        existing = self._find_similar_mistake(agent_name, error_type, error_message)
        if existing:
            return existing["id"]  # ไม่บันทึกซ้ำ

        self.conn.execute(
            """INSERT INTO mistakes
               (id, timestamp, agent_name, task_description, error_type,
                error_message, context, stack_trace, tags, severity, resolved)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                mid, now, agent_name, task_description, error_type,
                error_message,
                json.dumps(context or {}, ensure_ascii=False),
                stack_trace,
                json.dumps(tags or [], ensure_ascii=False),
                severity,
            ),
        )
        self.conn.commit()
        return mid

    def _find_similar_mistake(self, agent_name: str, error_type: str, error_message: str) -> Optional[dict]:
        """หา mistake ที่คล้ายกัน (dedup)"""
        row = self.conn.execute(
            """SELECT * FROM mistakes
               WHERE agent_name = ? AND error_type = ?
               AND error_message = ?
               ORDER BY timestamp DESC LIMIT 1""",
            (agent_name, error_type, error_message),
        ).fetchone()
        return dict(row) if row else None

    def get_mistake(self, mistake_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM mistakes WHERE id = ?", (mistake_id,)).fetchone()
        if row:
            d = dict(row)
            d["context"] = json.loads(d["context"])
            d["tags"] = json.loads(d["tags"])
            d["resolved"] = bool(d["resolved"])
            return d
        return None

    def list_mistakes(
        self,
        agent_name: str = None,
        error_type: str = None,
        severity: str = None,
        resolved: bool = None,
        limit: int = 50,
    ) -> list[dict]:
        query = "SELECT * FROM mistakes WHERE 1=1"
        params = []
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        if error_type:
            query += " AND error_type = ?"
            params.append(error_type)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if resolved is not None:
            query += " AND resolved = ?"
            params.append(1 if resolved else 0)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["context"] = json.loads(d["context"])
            d["tags"] = json.loads(d["tags"])
            d["resolved"] = bool(d["resolved"])
            results.append(d)
        return results

    def mark_resolved(self, mistake_id: str):
        self.conn.execute("UPDATE mistakes SET resolved = 1 WHERE id = ?", (mistake_id,))
        self.conn.commit()

    # ─── Lessons ────────────────────────────────────────────────

    def add_lesson(
        self,
        mistake_id: str,
        root_cause: str,
        why_it_happened: str,
        how_to_prevent: str,
        prevention_rule: str,
        confidence: float = 0.5,
        tags: list[str] = None,
    ) -> str:
        """เพิ่มบทเรียนจากความผิดพลาด"""
        lid = self._gen_id("lesson_")
        now = datetime.utcnow().isoformat()

        self.conn.execute(
            """INSERT INTO lessons
               (id, mistake_id, timestamp, root_cause, why_it_happened,
                how_to_prevent, prevention_rule, confidence, times_applied,
                times_prevented, false_positive, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?)""",
            (
                lid, mistake_id, now, root_cause, why_it_happened,
                how_to_prevent, prevention_rule, confidence,
                json.dumps(tags or [], ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return lid

    def get_lesson(self, lesson_id: str) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        if row:
            d = dict(row)
            d["tags"] = json.loads(d["tags"])
            return d
        return None

    def get_relevant_lessons(
        self,
        task_description: str,
        agent_name: str = None,
        tags: list[str] = None,
        min_confidence: float = 0.3,
        limit: int = 10,
    ) -> list[dict]:
        """หาบทเรียนที่เกี่ยวข้องกับงานที่กำลังจะทำ"""
        query = """
            SELECT l.*, m.agent_name as mistake_agent, m.error_type
            FROM lessons l
            JOIN mistakes m ON l.mistake_id = m.id
            WHERE l.confidence >= ?
        """
        params: list = [min_confidence]

        if agent_name:
            query += " AND m.agent_name = ?"
            params.append(agent_name)

        query += " ORDER BY l.confidence DESC, l.times_prevented DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"])
            results.append(d)
        return results

    def record_lesson_applied(self, lesson_id: str, prevented: bool = False):
        """บันทึกว่าใช้บทเรียนแล้ว"""
        if prevented:
            self.conn.execute(
                "UPDATE lessons SET times_applied = times_applied + 1, times_prevented = times_prevented + 1 WHERE id = ?",
                (lesson_id,),
            )
        else:
            self.conn.execute(
                "UPDATE lessons SET times_applied = times_applied + 1 WHERE id = ?",
                (lesson_id,),
            )
        self.conn.commit()

    def record_false_positive(self, lesson_id: str):
        """บทเรียนนี้เตือนเกินจริง"""
        self.conn.execute(
            "UPDATE lessons SET false_positive = false_positive + 1 WHERE id = ?",
            (lesson_id,),
        )
        # ลด confidence อัตโนมัติ
        self.conn.execute(
            """UPDATE lessons SET confidence = MAX(0.1, confidence - 0.1)
               WHERE id = ?""",
            (lesson_id,),
        )
        self.conn.commit()

    def boost_confidence(self, lesson_id: str, amount: float = 0.1):
        """เพิ่ม confidence เมื่อบทเรียนพิสูจน์ว่ามีประโยชน์"""
        self.conn.execute(
            """UPDATE lessons SET confidence = MIN(1.0, confidence + ?)
               WHERE id = ?""",
            (amount, lesson_id),
        )
        self.conn.commit()

    # ─── Action Logs ────────────────────────────────────────────

    def log_action(
        self,
        agent_name: str,
        action: str,
        lessons_checked: list[str] = None,
        outcome: str = "success",
        mistake_id: str = None,
        metadata: dict = None,
    ) -> str:
        """บันทึกการกระทำ"""
        aid = self._gen_id("action_")
        now = datetime.utcnow().isoformat()

        self.conn.execute(
            """INSERT INTO action_logs
               (id, timestamp, agent_name, action, lessons_checked,
                outcome, mistake_id, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                aid, now, agent_name, action,
                json.dumps(lessons_checked or [], ensure_ascii=False),
                outcome, mistake_id,
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return aid

    def get_stats(self, agent_name: str = None, days: int = 30) -> dict:
        """สถิติภาพรวม"""
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        query_base = " WHERE timestamp >= ?"
        params: list = [since]

        if agent_name:
            query_base += " AND agent_name = ?"
            params.append(agent_name)

        # Total mistakes
        row = self.conn.execute(
            f"SELECT COUNT(*) as cnt FROM mistakes{query_base}", params
        ).fetchone()
        total_mistakes = row["cnt"]

        # Resolved mistakes
        row = self.conn.execute(
            f"SELECT COUNT(*) as cnt FROM mistakes{query_base} AND resolved = 1",
            params,
        ).fetchone()
        resolved = row["cnt"]

        # Total lessons
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM lessons").fetchone()
        total_lessons = row["cnt"]

        # Action stats
        row = self.conn.execute(
            f"""SELECT
                COUNT(*) as total,
                SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) as successes,
                SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END) as failures,
                SUM(CASE WHEN outcome = 'prevented' THEN 1 ELSE 0 END) as prevented
                FROM action_logs{query_base}""",
            params,
        ).fetchone()
        actions = dict(row) if row else {}

        # Top mistake types
        rows = self.conn.execute(
            f"""SELECT error_type, COUNT(*) as cnt
                FROM mistakes{query_base}
                GROUP BY error_type ORDER BY cnt DESC LIMIT 5""",
            params,
        ).fetchall()
        top_errors = [dict(r) for r in rows]

        # Best lessons (most prevented)
        rows = self.conn.execute(
            """SELECT id, prevention_rule, times_prevented, confidence
               FROM lessons
               WHERE times_prevented > 0
               ORDER BY times_prevented DESC LIMIT 5"""
        ).fetchall()
        best_lessons = [dict(r) for r in rows]

        return {
            "period_days": days,
            "total_mistakes": total_mistakes,
            "resolved_mistakes": resolved,
            "total_lessons": total_lessons,
            "actions": actions,
            "top_error_types": top_errors,
            "best_lessons": best_lessons,
        }

    def close(self):
        self.conn.close()
