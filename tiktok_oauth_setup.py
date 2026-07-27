#!/usr/bin/env python3
"""
Chay 1 LAN DUY NHAT script nay de lay access_token/refresh_token cua TikTok
cho nguoi dung THAT (client_key + client_secret KHONG du de dang video len
TikTok - TikTok bat buoc phai co su dong y qua man hinh OAuth cua 1 tai
khoan TikTok that su).

YEU CAU TRUOC KHI CHAY:
  1. Vao https://developers.tiktok.com/apps/ -> app cua ban -> Login Kit
     -> them 1 "Redirect URI". URI nay BAT BUOC phai la https, tinh (khong
     query string/fragment), vi du: https://abcd1234.ngrok-free.app/callback

     Neu ban chua co domain https rieng, cach don gian nhat la dung ngrok:
       brew install ngrok   # (hoac tai tu https://ngrok.com/download)
       ngrok http 8765
     ngrok se in ra 1 URL dang https://xxxx.ngrok-free.app - dung
     https://xxxx.ngrok-free.app/callback lam Redirect URI o buoc tren, va
     GIU CHO ngrok CHAY trong luc thuc hien script nay (no forward tu URL
     https do ve may ban tren port 8765).

  2. Set 3 bien moi truong (KHONG hardcode secret vao file nay):
       export TIKTOK_CLIENT_KEY="..."       # client_key cua app
       export TIKTOK_CLIENT_SECRET="..."    # client_secret cua app (ROTATE lai
                                             # neu da tung dan vao noi khong an toan)
       export TIKTOK_REDIRECT_URI="https://xxxx.ngrok-free.app/callback"

  3. Chay: python tiktok_oauth_setup.py
     Script se in ra 1 URL - mo URL do trong trinh duyet, dang nhap TikTok,
     bam dong y. Sau khi dong y, TikTok se redirect ve redirect_uri (qua
     ngrok) va script (dang lang nghe tren 127.0.0.1:8765) se tu dong bat
     duoc "code", doi lay access_token/refresh_token, va ghi ra
     tiktok_tokens.json trong BASE_DIR (duong dan xem trong Load Config cua
     generate_shorts_workflow.py).

Sau buoc nay, workflow n8n se TU DONG refresh access_token truoc moi lan
dang video (khong can lam lai OAuth thu cong nay nua, tru khi refresh_token
het han sau 365 ngay hoac ban bam "Revoke" quyen truy cap tu phia TikTok).
"""
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI")
LOCAL_PORT = int(os.environ.get("TIKTOK_LOCAL_PORT", "8765"))
BASE_DIR = os.environ.get("TIKTOK_BASE_DIR", "/Users/tuht1/tui-dau-tu-videos")
TOKENS_FILE = os.path.join(BASE_DIR, "tiktok_tokens.json")
SCOPE = "video.publish"

if not CLIENT_KEY or not CLIENT_SECRET or not REDIRECT_URI:
    print(
        "Thieu bien moi truong. Can set ca 3: TIKTOK_CLIENT_KEY, "
        "TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI (xem huong dan o dau file nay).",
        file=sys.stderr,
    )
    sys.exit(1)

_state = secrets.token_urlsafe(24)
_result = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # im lang, khong spam log ra console

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != urllib.parse.urlparse(REDIRECT_URI).path:
            self.send_response(404)
            self.end_headers()
            return

        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        state = qs.get("state", [None])[0]
        error = qs.get("error", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        if error:
            _result["error"] = qs.get("error_description", [error])[0]
            self.wfile.write(f"<h2>Loi: {_result['error']}</h2>".encode("utf-8"))
        elif state != _state:
            _result["error"] = "state khong khop - co the bi CSRF, huy bo."
            self.wfile.write(b"<h2>Loi: state khong khop.</h2>")
        elif not code:
            _result["error"] = "khong nhan duoc 'code' tu TikTok."
            self.wfile.write(b"<h2>Loi: thieu code.</h2>")
        else:
            _result["code"] = code
            self.wfile.write(
                b"<h2>Thanh cong! Ban co the dong tab nay va quay lai terminal.</h2>"
            )


def main():
    server = http.server.HTTPServer(("127.0.0.1", LOCAL_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    auth_url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={urllib.parse.quote(CLIENT_KEY)}"
        f"&scope={urllib.parse.quote(SCOPE)}"
        "&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&state={_state}"
    )

    print("=" * 70)
    print("Mo URL nay trong trinh duyet, dang nhap TikTok va bam dong y:")
    print(auth_url)
    print("=" * 70)
    print(f"(dang lang nghe tren 127.0.0.1:{LOCAL_PORT} qua redirect_uri = {REDIRECT_URI})")

    while "code" not in _result and "error" not in _result:
        thread.join(timeout=0.5)
        if not thread.is_alive():
            break

    server.shutdown()

    if "error" in _result:
        print(f"THAT BAI: {_result['error']}", file=sys.stderr)
        sys.exit(1)

    code = _result["code"]
    print("Da nhan duoc code, dang doi lay access_token...")

    body = urllib.parse.urlencode(
        {
            "client_key": CLIENT_KEY,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://open.tiktokapis.com/v2/oauth/token/",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        token_data = json.loads(resp.read().decode("utf-8"))

    if "access_token" not in token_data:
        print(f"THAT BAI khi doi token: {token_data}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(BASE_DIR, exist_ok=True)
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {
                "access_token": token_data["access_token"],
                "refresh_token": token_data["refresh_token"],
                "open_id": token_data.get("open_id"),
                "obtained_at": __import__("datetime").datetime.now().isoformat(),
            },
            f,
            indent=2,
        )

    print(f"XONG! Da ghi token vao: {TOKENS_FILE}")
    print("Workflow n8n se tu dong refresh token nay truoc moi lan dang video.")


if __name__ == "__main__":
    main()
