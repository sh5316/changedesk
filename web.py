"""
자리 바꾸기 웹 화면

  python web.py            # http://localhost:8000 에서 실행 (브라우저가 자동으로 열림)
  python web.py --port 9000

추가 설치 없이 파이썬 기본 라이브러리만 사용한다.
학생 명단(students.csv)과 기록(history.json)은 이 컴퓨터에만 저장된다.
"""

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import seat_changer as sc

INDEX_FILE = sc.BASE_DIR / "static" / "index.html"
lock = threading.Lock()  # 파일을 동시에 읽고 쓰지 않도록


def student_list(students):
    return [{"name": n, "gender": s["gender"], "score": s["score"]} for n, s in students.items()]


def get_state():
    try:
        students = sc.load_students(check_count=False)
    except sc.StudentError:
        students = {}
    return {
        "students": student_list(students),
        "history": sc.load_history(),
        "max_students": sc.MAX_STUDENTS,
        "gender_mode": sc.GENDER_MODE or "none",
    }


def arrange(body):
    students = sc.parse_students(body.get("students", []))
    mode = body.get("gender_mode") or "none"
    if mode not in ("mixed", "same", "none"):
        raise sc.StudentError(f"알 수 없는 성별 배치 방식입니다: {mode}")

    sc.save_students(students)
    arranger = sc.Arranger(students, sc.load_history(), None if mode == "none" else mode)
    desks = arranger.arrange()
    return {"desks": desks, "report": arranger.report(desks)}


def confirm(body):
    desks = body.get("desks")
    students = sc.load_students()
    if (not isinstance(desks, list)
            or not all(isinstance(g, list) and 1 <= len(g) <= 2 for g in desks)
            or sorted(n for g in desks for n in g) != sorted(students)
            or len(desks) != (len(students) + 1) // 2):
        raise sc.StudentError("배치 이후 학생 명단이 바뀌었습니다. 자리를 다시 바꿔주세요.")

    history = sc.load_history()
    history.append(sc.make_record(desks))
    sc.save_history(history)
    return {"history": history}


def reset_history():
    if sc.HISTORY_FILE.exists():
        sc.HISTORY_FILE.unlink()
    return {"history": []}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def handle_api(self, action, *args):
        try:
            with lock:
                self.send_json(action(*args))
        except sc.StudentError as e:
            self.send_json({"error": str(e)}, 400)
        except json.JSONDecodeError:
            self.send_json({"error": "잘못된 요청입니다."}, 400)

    def do_GET(self):
        if self.path == "/":
            body = INDEX_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/state":
            self.handle_api(get_state)
        else:
            self.send_json({"error": "없는 페이지입니다."}, 404)

    def do_POST(self):
        routes = {"/api/arrange": arrange, "/api/confirm": confirm}
        if self.path not in routes:
            return self.send_json({"error": "없는 페이지입니다."}, 404)
        try:
            body = self.read_json()
        except json.JSONDecodeError:
            return self.send_json({"error": "잘못된 요청입니다."}, 400)
        self.handle_api(routes[self.path], body)

    def do_DELETE(self):
        if self.path == "/api/history":
            self.handle_api(reset_history)
        else:
            self.send_json({"error": "없는 페이지입니다."}, 404)

    def log_message(self, format, *args):
        pass  # 요청마다 로그를 찍지 않음


def main():
    parser = argparse.ArgumentParser(description="자리 바꾸기 웹 화면")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"자리 바꾸기 웹 화면: {url}  (종료: Ctrl+C)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
