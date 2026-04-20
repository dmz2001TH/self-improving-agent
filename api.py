"""
api.py — REST API สำหรับ Self-Improving Agent Memory Engine

Endpoints:
  POST   /api/mistake/log          — บันทึกความผิดพลาด
  GET    /api/mistake/list         — ดูรายการความผิดพลาด
  GET    /api/mistake/:id          — ดูรายละเอียด
  POST   /api/mistake/:id/reflect  — วิเคราะห์ → สร้างบทเรียน
  GET    /api/lesson/list          — ดูบทเรียน
  GET    /api/lesson/:id           — ดูรายละเอียดบทเรียน
  POST   /api/check                — Pre-flight check
  GET    /api/stats                — สถิติ
  GET    /api/dashboard            — Dashboard data
"""

import json
import sys
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, str(Path(__file__).parent))

from core.memory_engine import MemoryEngine
from core.reflector import Reflector
from core.preflight import PreFlightChecker

DB_PATH = str(Path(__file__).parent / "data" / "memory.db")
engine = MemoryEngine(DB_PATH)
reflector = Reflector(engine)
checker = PreFlightChecker(engine)


class APIHandler(BaseHTTPRequestHandler):

    def _json_response(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.rstrip("/")
        params = {}

        if "?" in path:
            path, qs = path.split("?", 1)
            for pair in qs.split("&"):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    params[k] = v

        try:
            if path == "/api/mistake/list":
                mistakes = engine.list_mistakes(
                    agent_name=params.get("agent"),
                    severity=params.get("severity"),
                    limit=int(params.get("limit", 20)),
                )
                self._json_response({"mistakes": mistakes, "count": len(mistakes)})

            elif path.startswith("/api/mistake/") and path.count("/") == 3:
                mid = path.split("/")[-1]
                m = engine.get_mistake(mid)
                if m:
                    self._json_response(m)
                else:
                    self._json_response({"error": "Not found"}, 404)

            elif path == "/api/lesson/list":
                lessons = engine.get_relevant_lessons(
                    task_description=params.get("filter", ""),
                    min_confidence=float(params.get("min_confidence", 0.0)),
                    limit=int(params.get("limit", 20)),
                )
                self._json_response({"lessons": lessons, "count": len(lessons)})

            elif path.startswith("/api/lesson/") and path.count("/") == 3:
                lid = path.split("/")[-1]
                l = engine.get_lesson(lid)
                if l:
                    self._json_response(l)
                else:
                    self._json_response({"error": "Not found"}, 404)

            elif path == "/api/stats":
                stats = engine.get_stats(
                    agent_name=params.get("agent"),
                    days=int(params.get("days", 30)),
                )
                self._json_response(stats)

            elif path == "/api/dashboard":
                stats = engine.get_stats(days=30)
                mistakes = engine.list_mistakes(limit=10)
                lessons = engine.get_relevant_lessons(task_description="", min_confidence=0.0, limit=10)
                self._json_response({
                    "stats": stats,
                    "recent_mistakes": mistakes,
                    "active_lessons": lessons,
                })

            elif path == "/api/health":
                self._json_response({"status": "ok", "engine": "self-improving-agent"})

            else:
                self._json_response({"error": f"Unknown endpoint: {path}"}, 404)

        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def do_POST(self):
        path = self.path.rstrip("/")

        try:
            if path == "/api/mistake/log":
                body = self._read_body()
                mid = engine.log_mistake(
                    agent_name=body.get("agent", "unknown"),
                    task_description=body.get("task", ""),
                    error_type=body.get("type", "Unknown"),
                    error_message=body.get("message", ""),
                    context=body.get("context", {}),
                    tags=body.get("tags", []),
                    severity=body.get("severity", "warning"),
                )
                self._json_response({"mistake_id": mid, "status": "logged"})

            elif path.endswith("/reflect") and "/api/mistake/" in path:
                mid = path.split("/")[-2]
                lid = reflector.reflect_on_mistake(mid)
                if lid:
                    lesson = engine.get_lesson(lid)
                    self._json_response({"lesson_id": lid, "lesson": lesson})
                else:
                    self._json_response({"error": "Reflection failed"}, 500)

            elif path == "/api/check":
                body = self._read_body()
                warnings = checker.check(
                    action=body.get("action", ""),
                    agent_name=body.get("agent"),
                    tags=body.get("tags"),
                    min_confidence=float(body.get("min_confidence", 0.3)),
                )
                self._json_response({
                    "safe": len(warnings) == 0,
                    "warnings": [
                        {
                            "lesson_id": w.lesson_id,
                            "rule": w.prevention_rule,
                            "confidence": w.confidence,
                            "severity": w.severity,
                            "how_to_prevent": w.how_to_prevent,
                        }
                        for w in warnings
                    ],
                })

            else:
                self._json_response({"error": f"Unknown endpoint: {path}"}, 404)

        except Exception as e:
            self._json_response({"error": str(e)}, 500)

    def log_message(self, format, *args):
        # Suppress default logging
        pass


def run_server(host="0.0.0.0", port=7890):
    server = HTTPServer((host, port), APIHandler)
    print(f"🧠 Self-Improving Agent Memory API running on http://{host}:{port}")
    print(f"   Health: http://{host}:{port}/api/health")
    print(f"   Dashboard: http://{host}:{port}/api/dashboard")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()
        engine.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=7890)
    args = parser.parse_args()
    run_server(args.host, args.port)
