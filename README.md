# 🧠 Self-Improving Agent Memory Engine

ระบบที่ทำให้ AI Agent **จำความผิดพลาด → วิเคราะห์ → ป้องกันไม่ให้เกิดซ้ำ**

## Architecture

```
Agent ทำผิดพลาด
    │
    ▼
┌─────────────┐     ┌──────────────┐     ┌───────────────┐
│ Mistake      │────▶│ Reflector    │────▶│ Lesson Store  │
│ Logger       │     │ (LLM分析)    │     │ (SQLite)      │
└─────────────┘     └──────────────┘     └───────┬───────┘
                                                  │
                                            ┌─────▼───────┐
                                            │ Pre-flight   │
                                            │ Checker      │
                                            └─────┬───────┘
                                                  │
                                            ┌─────▼───────┐
                                            │ Agent Action │
                                            │ (with guard) │
                                            └─────────────┘
```

## Components

| Component | File | Role |
|---|---|---|
| **Memory Engine** | `core/memory_engine.py` | SQLite-backed store สำหรับ mistakes, lessons, action logs |
| **Reflector** | `core/reflector.py` | วิเคราะห์ความผิดพลาด → สร้างบทเรียน + prevention rules |
| **Pre-flight Checker** | `core/preflight.py` | ตรวจสอบก่อนทำงาน ป้องกันความผิดพลาดซ้ำ |
| **CLI** | `cli/main.py` | Command line interface |
| **API Server** | `api.py` | REST API (port 7890) |

## Quick Start

### 1. CLI

```bash
# บันทึกความผิดพลาด
python -m cli.main mistake add \
  --agent email-bot \
  --task "ส่งอีเมล" \
  --type TimeoutError \
  --msg "SMTP timeout" \
  --reflect

# ดูรายการความผิดพลาด
python -m cli.main mistake list

# Pre-flight check ก่อนทำงาน
python -m cli.main check --action "ส่งอีเมล" --agent email-bot

# วิเคราะห์ทุก mistake ที่ยังไม่ resolved
python -m cli.main reflect --all-unresolved

# ดูสถิติ
python -m cli.main stats --days 30

# Dashboard
python -m cli.main dashboard
```

### 2. Python API

```python
from core.memory_engine import MemoryEngine
from core.reflector import Reflector
from core.preflight import PreFlightChecker, with_preflight

engine = MemoryEngine("data/memory.db")
reflector = Reflector(engine)
checker = PreFlightChecker(engine)

# บันทึกความผิดพลาด
mid = engine.log_mistake(
    agent_name="my-bot",
    task_description="เรียก API",
    error_type="ConnectionError",
    error_message="Connection refused",
)

# วิเคราะห์ → สร้างบทเรียน
lesson_id = reflector.reflect_on_mistake(mid)

# ตรวจสอบก่อนทำงาน
warnings = checker.check(action="เรียก API", agent_name="my-bot")
for w in warnings:
    print(f"⚠ {w.severity}: {w.prevention_rule}")

# ทำงานพร้อม guard
result = checker.execute_with_guard(
    action_name="เรียก API",
    func=my_function,
    agent_name="my-bot",
)

# ใช้ decorator
@with_preflight(engine, "send_email", agent_name="email-bot")
def send_email(to, subject, body):
    ...
```

### 3. REST API

```bash
# รัน server
python api.py --port 7890

# บันทึกความผิดพลาด
curl -X POST http://localhost:7890/api/mistake/log \
  -d '{"agent":"my-bot","task":"call API","type":"Timeout","message":"timed out"}'

# Pre-flight check
curl -X POST http://localhost:7890/api/check \
  -d '{"action":"call API","agent":"my-bot"}'

# วิเคราะห์
curl -X POST http://localhost:7890/api/mistake/{id}/reflect

# ดูสถิติ
curl http://localhost:7890/api/stats

# Dashboard
curl http://localhost:7890/api/dashboard
```

## Flow: วงจรการเรียนรู้

```
1. Agent ทำงาน → ล้มเหลว
2. log_mistake() → บันทึก error + context
3. reflector.reflect() → LLM วิเคราะห์ → สร้าง prevention rule
4. ครั้งต่อไป → preflight.check() → เจอ warning
5. ทำงานพร้อม guard → ป้องกัน / บันทึกผล
6. confidence ปรับอัตโนมัติ:
   - lesson ป้องกันได้ → confidence ↑
   - lesson เตือนเกินจริง → confidence ↓
7. Dashboard → ดูสถิติ improvement ของ agent
```

## Data Model

### Mistake
- `id`, `timestamp`, `agent_name`, `task_description`
- `error_type`, `error_message`, `context` (JSON)
- `tags`, `severity` (critical/warning/info), `resolved`

### Lesson
- `id`, `mistake_id`, `root_cause`, `why_it_happened`
- `how_to_prevent`, `prevention_rule` (short checkable rule)
- `confidence` (0.0-1.0, auto-adjusted)
- `times_applied`, `times_prevented`, `false_positive`

### Action Log
- บันทึกทุก action ที่ผ่าน pre-flight check
- ติดตาม outcome: success / failed / prevented

## Demo

```bash
python demo.py
```
