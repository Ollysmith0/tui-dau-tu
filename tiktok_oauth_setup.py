#!/usr/bin/env python3
"""
Chay 1 LAN DUY NHAT script nay de lay access_token/refresh_token cua TikTok
cho nguoi dung THAT (client_key + client_secret KHONG du de dang video len
TikTok - TikTok bat buoc phai co su dong y qua man hinh OAuth cua 1 tai
khoan TikTok that su).

YEU CAU TRUOC KHI CHAY:
  1. Vao https://developers.tiktok.com/apps/ -> app cua ban -> Login Kit ->
     "Redirect URI" (tab Web) -> them URI sau (dung CHINH XAC, khong doi):
       https://ollysmith0.github.io/tui-dau-tu/tiktok-callback.html
     Day la 1 trang tinh (static) da co san trong repo (docs/tiktok-callback.
     html), tu doc "code" tu URL sau khi TikTok redirect ve va hien thi de
     ban COPY THU CONG - khong can ngrok/server local nao ca.

  2. Set 2 bien moi truong (KHONG hardcode secret vao file nay):
       export TIKTOK_CLIENT_KEY="..."       # client_key cua app
       export TIKTOK_CLIENT_SECRET="..."    # client_secret cua app (ROTATE lai
                                             # neu da tung dan vao noi khong an toan)

  3. Chay: python tiktok_oauth_setup.py
     Script in ra 1 URL - mo URL do trong trinh duyet, dang nhap TikTok, bam
     dong y. TikTok se redirect ve trang tiktok-callback.html, trang do hien
     thi gia tri "code" - COPY gia tri do va PASTE lai vao terminal khi script
     hoi. Script se doi code lay access_token/refresh_token va ghi ra
     tiktok_tokens.json trong BASE_DIR (duong dan xem trong Load Config cua
     generate_shorts_workflow.py).

Sau buoc nay, workflow n8n se TU DONG refresh access_token truoc moi lan
dang video (khong can lam lai OAuth thu cong nay nua, tru khi refresh_token
het han sau 365 ngay hoac ban bam "Revoke" quyen truy cap tu phia TikTok).
"""
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request

CLIENT_KEY = os.environ.get("TIKTOK_CLIENT_KEY")
CLIENT_SECRET = os.environ.get("TIKTOK_CLIENT_SECRET")
REDIRECT_URI = os.environ.get(
    "TIKTOK_REDIRECT_URI",
    "https://ollysmith0.github.io/tui-dau-tu/tiktok-callback.html",
)
BASE_DIR = os.environ.get("TIKTOK_BASE_DIR", "/Users/tuht1/tui-dau-tu-videos")
TOKENS_FILE = os.path.join(BASE_DIR, "tiktok_tokens.json")
SCOPE = "user.info.basic,video.publish"

if not CLIENT_KEY or not CLIENT_SECRET:
    print(
        "Thieu bien moi truong. Can set TIKTOK_CLIENT_KEY va TIKTOK_CLIENT_SECRET "
        "(xem huong dan o dau file nay).",
        file=sys.stderr,
    )
    sys.exit(1)


def main():
    state = secrets.token_urlsafe(24)

    auth_url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={urllib.parse.quote(CLIENT_KEY)}"
        f"&scope={urllib.parse.quote(SCOPE)}"
        "&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
        f"&state={state}"
    )

    print("=" * 70)
    print("Mo URL nay trong trinh duyet, dang nhap TikTok va bam dong y:")
    print(auth_url)
    print("=" * 70)
    print(
        "Sau khi dong y, TikTok se redirect ve trang tiktok-callback.html - "
        "trang do se hien thi gia tri 'code'. Copy gia tri do."
    )

    code = input("Dan (paste) gia tri 'code' vao day roi Enter: ").strip()
    if not code:
        print("Khong co code, huy bo.", file=sys.stderr)
        sys.exit(1)

    print("Dang doi code lay access_token...")

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
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            token_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"THAT BAI khi doi token (HTTP {e.code}): {e.read().decode('utf-8')}", file=sys.stderr)
        sys.exit(1)

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

