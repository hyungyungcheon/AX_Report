# -*- coding: utf-8 -*-
"""
AX 인텔리전스 리포트 생성기

키워드/지시문을 입력하면:
  1. Claude CLI(헤드리스 모드) + 웹 검색으로 최근 기사를 수집·요약
  2. 엔터프라이즈 AX 관점의 인사이트 리포트를 생성
  3. 결과를 data/posts/*.json 에 게시글로 저장
  4. site/ 아래에 게시판(index.html) + 리포트 페이지(HTML)를 렌더링

가장 쉬운 사용법 (웹 UI):
  python ax_report.py --serve
  → 브라우저가 열리면 상단 입력창에 키워드 입력 후 [리포트 생성] 클릭
  (또는 AX리포트_시작.bat 더블클릭)

명령줄 사용법:
  python ax_report.py "키워드 또는 지시문"
  python ax_report.py "키워드" --days 30 --articles 10
  python ax_report.py --rebuild          # 저장된 JSON으로 HTML만 재생성
  python ax_report.py --list             # 저장된 리포트 목록 출력
"""
import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / "data" / "posts"
SITE_DIR = BASE / "site"
POSTS_DIR = SITE_DIR / "posts"
TPL_DIR = BASE / "templates"

CLAUDE_TIMEOUT = 900  # 초
DEFAULT_PORT = 8940


class ReportError(Exception):
    """리포트 생성 과정의 예상 가능한 오류."""


# ---------------------------------------------------------------- 수집/분석

PROMPT_TEMPLATE = """당신은 엔터프라이즈 AX(AI Transformation) 전문 애널리스트입니다.

주제 또는 지시문: "{keyword}"

작업:
1. 웹 검색을 사용해 위 주제에 대한 최근 {days}일 이내의 기사·발표·보고서를 조사하세요.
   - 위 입력에 특정 지시(예: 특정 산업/지역/관점 위주)가 포함되어 있으면 그 지시를 따르세요.
   - 한국어와 영어 검색어를 모두 사용해 여러 번 검색하세요.
   - 서로 다른 출처에서 {n_articles}건 내외(최소 6건)를 선별하세요. 중복 내용은 제외하세요.
   - URL은 반드시 실제 검색 결과에 나온 URL만 사용하세요. URL을 지어내면 안 됩니다.
2. 각 기사를 한국어 2~3문장으로 요약하세요.
3. 전체 내용을 종합해 "엔터프라이즈 AX 전환" 관점에서 분석하세요.

최종 출력은 아래 JSON 스키마를 정확히 따르는 **JSON 하나만** 출력하세요.
다른 설명 문장, 마크다운 코드펜스 없이 순수 JSON만 출력하세요.

{{
  "title": "리포트 제목 (한국어, '~동향 브리핑' 같은 형식)",
  "keyword": "{keyword}",
  "scores": [
    {{"label": "전환 속도", "value": "0.0 / 10", "desc": "근거 한 문장"}},
    {{"label": "산업 파급력", "value": "0.0 / 10", "desc": "근거 한 문장"}},
    {{"label": "도입 성숙도", "value": "0.0 / 10", "desc": "근거 한 문장"}}
  ],
  "key_message": "전체를 관통하는 핵심 메시지 1~2문장 (\\"인용구\\" — 부연 형식)",
  "articles": [
    {{
      "title": "기사 제목 (한국어로 번역)",
      "date": "YYYY.MM.DD (알 수 없으면 YYYY.MM)",
      "source": "매체/출처명",
      "summary": "한국어 2~3문장 요약",
      "url": "실제 기사 URL"
    }}
  ],
  "insights": {{
    "opportunity": ["기회 관점 인사이트 3개 (각 1~2문장)"],
    "risk": ["리스크 관점 인사이트 3개"],
    "strategy": ["전략 관점 인사이트 3개 (기업이 취해야 할 행동)"],
    "trend": ["트렌드 관점 인사이트 3개"]
  }},
  "sources_line": "출처 매체명을 쉼표로 나열한 한 줄"
}}"""


def find_claude() -> list[str]:
    """claude CLI 실행 커맨드를 찾는다 (Windows .cmd 셔틀 대응)."""
    exe = shutil.which("claude")
    if not exe:
        raise ReportError("claude CLI를 찾을 수 없습니다. Claude Code가 설치되어 있어야 합니다.")
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe]
    return [exe]


def extract_json(text: str) -> dict:
    """텍스트에서 첫 번째 최상위 JSON 객체를 추출한다."""
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip())
    start = text.find("{")
    if start < 0:
        raise ValueError("응답에서 JSON을 찾지 못했습니다.")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[start:])
    return obj


def generate_report(keyword: str, days: int, n_articles: int, model: str | None) -> dict:
    """Claude CLI 헤드리스 모드로 기사 수집 + 분석 리포트 생성."""
    prompt = PROMPT_TEMPLATE.format(keyword=keyword, days=days, n_articles=n_articles)
    cmd = find_claude() + [
        "-p",
        "--output-format", "json",
        "--allowedTools", "WebSearch,WebFetch",
    ]
    if model:
        cmd += ["--model", model]

    print(f"[1/3] Claude로 기사 수집·분석 중... (키워드: {keyword}, 보통 3~7분 소요)")
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLAUDE_TIMEOUT,
            cwd=str(BASE),
        )
    except subprocess.TimeoutExpired:
        raise ReportError(f"시간 초과({CLAUDE_TIMEOUT}초). 잠시 후 다시 시도해 보세요.")
    elapsed = time.time() - t0
    if proc.returncode != 0:
        try:
            detail = str(json.loads(proc.stdout).get("result", ""))[:500]
        except (json.JSONDecodeError, AttributeError):
            detail = (proc.stderr or proc.stdout or "")[:500]
        if "401" in detail or "authenticat" in detail.lower() or "/login" in detail.lower():
            raise ReportError(
                "Claude 로그인이 만료됐습니다. 터미널에서 claude 를 실행해 로그인(/login)한 뒤 "
                f"다시 시도하세요. (원본 오류: {detail})"
            )
        raise ReportError(f"claude 실행 실패 (exit {proc.returncode}): {detail}")

    try:
        envelope = json.loads(proc.stdout)
        result_text = envelope.get("result", proc.stdout)
        if envelope.get("is_error"):
            raise ReportError(f"claude가 오류를 반환했습니다: {str(result_text)[:500]}")
    except json.JSONDecodeError:
        result_text = proc.stdout

    try:
        report = extract_json(result_text)
    except (ValueError, json.JSONDecodeError) as e:
        raw = BASE / "last_response.txt"
        raw.write_text(result_text, encoding="utf-8")
        raise ReportError(f"리포트 JSON 파싱 실패 ({e}). 원본 응답: {raw}")

    if not report.get("articles"):
        raise ReportError("수집된 기사가 없습니다. 키워드를 바꿔 다시 시도해 보세요.")

    print(f"      완료 — 기사 {len(report['articles'])}건 수집 ({elapsed:.0f}초)")
    return report


# ---------------------------------------------------------------- 저장

def save_post(report: dict, keyword: str) -> Path:
    post_id = time.strftime("%Y%m%d-%H%M%S")
    report["id"] = post_id
    report["keyword"] = report.get("keyword") or keyword
    report["generated_at"] = time.strftime("%Y-%m-%d %H:%M")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{post_id}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[2/3] 게시글 저장: {path.relative_to(BASE)}")
    return path


def load_posts() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    posts = []
    for f in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            posts.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            print(f"경고: {f.name} 읽기 실패 — 건너뜀 ({e})")
    return posts


# ---------------------------------------------------------------- 렌더링

def esc(s) -> str:
    return html.escape(str(s or ""))


def render_report_html(report: dict) -> str:
    tpl = (TPL_DIR / "report.html").read_text(encoding="utf-8")

    scores_html = "\n".join(
        f'  <div class="score"><div class="label">{esc(s.get("label"))}</div>'
        f'<div class="val">{esc(s.get("value"))}</div>'
        f'<div class="desc">{esc(s.get("desc"))}</div></div>'
        for s in report.get("scores", [])
    )

    articles_html = []
    for i, a in enumerate(report.get("articles", []), 1):
        url = str(a.get("url") or "")
        link = (
            f'<a href="{esc(url)}" target="_blank" rel="noopener">원문 ↗</a>'
            if url.startswith(("http://", "https://")) else ""
        )
        articles_html.append(
            f'  <div class="article">\n'
            f'    <h3>#{i:02d} {esc(a.get("title"))}</h3>\n'
            f'    <div class="meta-line">{esc(a.get("date"))} · {esc(a.get("source"))}</div>\n'
            f'    <p>{esc(a.get("summary"))}</p>\n'
            f'    {link}\n'
            f'  </div>'
        )

    insights = report.get("insights", {})

    def lis(key: str) -> str:
        return "\n".join(f"        <li>{esc(item)}</li>" for item in insights.get(key, []))

    n = len(report.get("articles", []))
    meta = (
        f'수집 기준일: {esc(report.get("generated_at"))} · 수집 기사: {n}건 · '
        f'분석 관점: 엔터프라이즈 AX 전환'
    )
    footer = (
        f'AX Intelligence Report · Generated {esc(report.get("generated_at"))} · '
        f'Source coverage: {esc(report.get("sources_line") or "-")}'
    )

    out = tpl
    for token, value in [
        ("{{TITLE}}", esc(report.get("title"))),
        ("{{KEYWORD}}", esc(report.get("keyword"))),
        ("{{META}}", meta),
        ("{{SCORECARDS}}", scores_html),
        ("{{KEY_MESSAGE}}", esc(report.get("key_message"))),
        ("{{ARTICLES}}", "\n".join(articles_html)),
        ("{{INSIGHT_OPP}}", lis("opportunity")),
        ("{{INSIGHT_RISK}}", lis("risk")),
        ("{{INSIGHT_STRAT}}", lis("strategy")),
        ("{{INSIGHT_TREND}}", lis("trend")),
        ("{{FOOTER}}", footer),
    ]:
        out = out.replace(token, value)
    return out


def render_index_html(posts: list[dict]) -> str:
    tpl = (TPL_DIR / "index.html").read_text(encoding="utf-8")
    rows = []
    total = len(posts)
    for i, p in enumerate(posts):
        n = len(p.get("articles", []))
        key_msg = str(p.get("key_message") or "")
        if len(key_msg) > 90:
            key_msg = key_msg[:90] + "…"
        rows.append(
            f'    <tr>\n'
            f'      <td class="num">{total - i}</td>\n'
            f'      <td class="kw"><span class="kw-badge">{esc(p.get("keyword"))}</span></td>\n'
            f'      <td class="title"><a href="posts/{esc(p.get("id"))}.html">{esc(p.get("title"))}</a>'
            f'<div class="sub">{esc(key_msg)}</div></td>\n'
            f'      <td class="cnt">{n}건</td>\n'
            f'      <td class="date">{esc(p.get("generated_at"))}</td>\n'
            f'      <td class="del"><button class="del-btn" data-id="{esc(p.get("id"))}" '
            f'title="이 리포트 삭제">✕</button></td>\n'
            f'    </tr>'
        )
    if not rows:
        rows.append('    <tr><td colspan="6" class="empty">아직 생성된 리포트가 없습니다. '
                    '위 입력창에 키워드를 입력하고 [리포트 생성]을 눌러 보세요.</td></tr>')
    out = tpl.replace("{{ROWS}}", "\n".join(rows))
    out = out.replace("{{COUNT}}", str(total))
    out = out.replace("{{UPDATED}}", time.strftime("%Y-%m-%d %H:%M"))
    return out


def rebuild_site() -> Path:
    posts = load_posts()
    POSTS_DIR.mkdir(parents=True, exist_ok=True)
    for p in posts:
        (POSTS_DIR / f"{p['id']}.html").write_text(render_report_html(p), encoding="utf-8")
    index = SITE_DIR / "index.html"
    index.write_text(render_index_html(posts), encoding="utf-8")
    print(f"[3/3] HTML 생성: {index.relative_to(BASE)} (리포트 {len(posts)}건)")
    return index


# ---------------------------------------------------------------- 웹 서버 (--serve)

def serve(port: int, open_browser: bool, model: str | None):
    """게시판 + 리포트 생성 UI를 제공하는 로컬 웹 서버."""
    import http.server
    import webbrowser

    rebuild_site()

    job = {"running": False, "keyword": "", "stage": "", "error": "",
           "done_id": "", "started": 0.0}
    lock = threading.Lock()

    def run_job(keyword: str, days: int, n_articles: int):
        try:
            report = generate_report(keyword, days, n_articles, model)
            save_post(report, keyword)
            rebuild_site()
            with lock:
                job.update(running=False, done_id=report["id"], stage="완료")
            print(f"완료! http://localhost:{port}/posts/{report['id']}.html")
        except ReportError as e:
            with lock:
                job.update(running=False, error=str(e), stage="오류")
            print(f"오류: {e}")
        except Exception as e:  # 예상 못 한 오류도 UI에 표시
            with lock:
                job.update(running=False, error=f"예상치 못한 오류: {e}", stage="오류")
            print(f"오류: {e}")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(SITE_DIR), **kw)

        def log_message(self, *a):  # 요청 로그 소음 제거
            pass

        def _json(self, code: int, payload: dict):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/status":
                with lock:
                    payload = dict(job)
                payload["elapsed"] = (
                    int(time.time() - payload["started"]) if payload["running"] else 0
                )
                del payload["started"]
                self._json(200, payload)
                return
            super().do_GET()

        def do_POST(self):
            if self.path == "/delete":
                self._handle_delete()
                return
            if self.path != "/generate":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                keyword = str(body.get("keyword", "")).strip()
                days = max(1, min(365, int(body.get("days") or 30)))
                n_articles = max(4, min(20, int(body.get("articles") or 10)))
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "잘못된 요청입니다."})
                return
            if not keyword:
                self._json(400, {"error": "키워드나 지시문을 입력하세요."})
                return
            with lock:
                if job["running"]:
                    self._json(409, {"error": f'이미 "{job["keyword"]}" 리포트를 생성 중입니다. 완료 후 다시 시도하세요.'})
                    return
                job.update(running=True, keyword=keyword, stage="기사 수집·분석 중",
                           error="", done_id="", started=time.time())
            threading.Thread(target=run_job, args=(keyword, days, n_articles),
                             daemon=True).start()
            self._json(200, {"ok": True})

        def _handle_delete(self):
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                post_id = str(body.get("id", "")).strip()
            except (ValueError, json.JSONDecodeError):
                self._json(400, {"error": "잘못된 요청입니다."})
                return
            if not re.fullmatch(r"\d{8}-\d{6}", post_id):
                self._json(400, {"error": "잘못된 리포트 ID입니다."})
                return
            json_path = DATA_DIR / f"{post_id}.json"
            if not json_path.exists():
                self._json(404, {"error": "해당 리포트를 찾을 수 없습니다."})
                return
            json_path.unlink()
            html_path = POSTS_DIR / f"{post_id}.html"
            if html_path.exists():
                html_path.unlink()
            rebuild_site()
            print(f"삭제됨: {post_id}")
            self._json(200, {"ok": True})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}/"
    print("=" * 56)
    print("  AX 인텔리전스 리포트 서버 실행 중")
    print(f"  브라우저에서 열기: {url}")
    print("  종료: 이 창에서 Ctrl+C (또는 창 닫기)")
    print("=" * 56)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")


# ---------------------------------------------------------------- CLI

def main():
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="AX 인텔리전스 리포트 생성기")
    ap.add_argument("keyword", nargs="?", help="검색할 키워드 또는 지시문")
    ap.add_argument("--serve", action="store_true", help="웹 UI 서버 실행 (가장 쉬운 사용법)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"서버 포트, 기본 {DEFAULT_PORT}")
    ap.add_argument("--days", type=int, default=30, help="수집 기간(일), 기본 30")
    ap.add_argument("--articles", type=int, default=10, help="목표 기사 수, 기본 10")
    ap.add_argument("--model", default=None, help="claude 모델 지정 (예: sonnet)")
    ap.add_argument("--rebuild", action="store_true", help="저장된 JSON으로 HTML만 재생성")
    ap.add_argument("--list", action="store_true", help="저장된 리포트 목록 출력")
    ap.add_argument("--no-open", action="store_true", help="완료 후 브라우저를 열지 않음")
    args = ap.parse_args()

    if args.serve:
        serve(args.port, open_browser=not args.no_open, model=args.model)
        return

    if args.list:
        posts = load_posts()
        if not posts:
            print("저장된 리포트가 없습니다.")
        for p in posts:
            print(f"{p.get('id')}  [{p.get('keyword')}]  {p.get('title')}  "
                  f"(기사 {len(p.get('articles', []))}건, {p.get('generated_at')})")
        return

    if args.rebuild:
        index = rebuild_site()
        if not args.no_open:
            import os
            os.startfile(index)
        return

    if not args.keyword:
        ap.print_help()
        sys.exit(1)

    try:
        report = generate_report(args.keyword, args.days, args.articles, args.model)
    except ReportError as e:
        sys.exit(f"오류: {e}")
    save_post(report, args.keyword)
    index = rebuild_site()

    post_page = POSTS_DIR / f"{report['id']}.html"
    print(f"\n완료! 리포트: {post_page}")
    print(f"      게시판: {index}")
    if not args.no_open:
        import os
        os.startfile(post_page)


if __name__ == "__main__":
    main()
