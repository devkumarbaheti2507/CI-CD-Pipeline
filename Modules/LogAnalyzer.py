import re
import json
import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

FAILURE_PATTERNS = {
    "BUILD_ERROR": [
        r"error:.*compilation failed",
        r"make\[.*\].*Error",
        r"BUILD FAILED",
        r"Cannot find module",
        r"ModuleNotFoundError",
        r"ImportError",
    ],
    "TEST_FAILURE": [
        r"FAILED\s+tests/",
        r"\d+ failed",
        r"AssertionError",
        r"FAIL:\s+test_",
        r"Test suite failed to run",
    ],
    "DEPLOY_ERROR": [
        r"deployment failed",
        r"Error response from daemon",
        r"kubectl.*Error",
        r"container exited with code [^0]",
        r"Connection refused",
        r"docker.*failed",
    ],
    "DEPENDENCY_ERROR": [
        r"Could not resolve",
        r"npm ERR!",
        r"pip.*ERROR",
        r"Package.*not found",
        r"requirements.*failed",
    ],
    "TIMEOUT": [
        r"timeout exceeded",
        r"Timed out",
        r"ETIMEDOUT",
        r"exceeded.*deadline",
    ],
}


def analyze_log(log_text: str) -> dict:
    lines = log_text.splitlines()
    detected = []

    for line_no, line in enumerate(lines, start=1):
        for failure_type, patterns in FAILURE_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    detected.append({
                        "line": line_no,
                        "content": line.strip(),
                        "failure_type": failure_type,
                        "pattern_matched": pattern,
                    })

    seen = set()
    unique = []
    for d in detected:
        if d["line"] not in seen:
            seen.add(d["line"])
            unique.append(d)

    if unique:
        priority = ["DEPLOY_ERROR", "BUILD_ERROR", "TEST_FAILURE",
                    "DEPENDENCY_ERROR", "TIMEOUT"]
        found_types = {d["failure_type"] for d in unique}
        overall_type = next((t for t in priority if t in found_types), unique[0]["failure_type"])
        status = "FAILED"
    else:
        overall_type = None
        status = "SUCCESS"

    return {
        "status": status,
        "failure_type": overall_type,
        "total_lines": len(lines),
        "failures_found": len(unique),
        "details": unique,
        "analyzed_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def analyze_log_file(filepath: str) -> dict:
    path = Path(filepath)
    if not path.exists():
        return {"error": f"File not found: {filepath}"}
    return {"file": str(path), **analyze_log(path.read_text())}




class LogAnalyzerHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):  
        pass

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/analyze":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON"}, 400)
                return
            log_text = payload.get("log", "")
            result = analyze_log(log_text)
            self.send_json(result)
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self.send_json({"status": "ok", "component": "LogAnalyzer"})
        elif parsed.path == "/analyze-file":
            qs = parse_qs(parsed.query)
            filepath = qs.get("path", [""])[0]
            if not filepath:
                self.send_json({"error": "Missing ?path= parameter"}, 400)
                return
            result = analyze_log_file(filepath)
            self.send_json(result)
        else:
            self.send_json({"error": "Not found"}, 404)


def start_server(host: str = "0.0.0.0", port: int = 5001):
    server = HTTPServer((host, port), LogAnalyzerHandler)
    print(f"[LogAnalyzer] Server running at http://{host}:{port}")
    print(f"  POST /analyze        — analyze log text (JSON body: {{\"log\": \"...\"}}) ")
    print(f"  GET  /analyze-file   — analyze a file (?path=<filepath>)")
    print(f"  GET  /health         — health check")
    server.serve_forever()


SAMPLE_LOGS = {
    "build_failure": """
[2024-06-01 10:01:00] Starting build pipeline...
[2024-06-01 10:01:02] Cloning repository... done
[2024-06-01 10:01:10] Installing dependencies...
npm ERR! 404 Not Found - GET https://registry.npmjs.org/react-dom
[2024-06-01 10:01:15] BUILD FAILED
[2024-06-01 10:01:15] Exit code: 1
""",
    "test_failure": """
[2024-06-01 10:05:00] Running test suite...
[2024-06-01 10:05:10] test_login_valid ... ok
[2024-06-01 10:05:11] test_login_invalid ... ok
[2024-06-01 10:05:12] test_dashboard_load ... FAIL: test_dashboard_load
AssertionError: Expected status 200, got 500
[2024-06-01 10:05:12] 1 failed, 2 passed
""",
    "deploy_failure": """
[2024-06-01 10:10:00] Starting deployment...
[2024-06-01 10:10:05] Pulling docker image... done
[2024-06-01 10:10:10] docker run -d app:latest
Error response from daemon: driver failed programming external connectivity
container exited with code 1
[2024-06-01 10:10:12] deployment failed
""",
    "clean_run": """
[2024-06-01 10:15:00] Pipeline started
[2024-06-01 10:15:05] Build... SUCCESS
[2024-06-01 10:15:20] Tests... 15 passed, 0 failed
[2024-06-01 10:15:30] Deploy... container started successfully
[2024-06-01 10:15:31] Pipeline COMPLETE
""",
}


def run_demo():
    print("=" * 60)
    print("  CI/CD Log Analyzer — Demo Run")
    print("=" * 60)
    for name, log in SAMPLE_LOGS.items():
        result = analyze_log(log)
        print(f"\n[Scenario: {name}]")
        print(f"  Status       : {result['status']}")
        print(f"  Failure Type : {result['failure_type']}")
        print(f"  Lines Scanned: {result['total_lines']}")
        print(f"  Failures Found: {result['failures_found']}")
        for d in result["details"]:
            print(f"    Line {d['line']:>3}: [{d['failure_type']}] {d['content'][:70]}")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    import sys
    if "--server" in sys.argv:
        start_server()
    else:
        run_demo()
