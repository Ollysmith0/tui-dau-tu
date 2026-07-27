#!/usr/bin/env python3
"""
Generator for n8n_workflow_shorts.json ("Tui dau tu" Shorts pipeline).

Why a generator script: this workflow now has ~45 nodes with an outer loop
(5 videos/day) wrapping the whole per-video pipeline. Hand-editing that much
JSON is error prone; this script owns the source of truth. Re-run after any
change:
    .venv/bin/python generate_shorts_workflow.py

Changes vs the previous live workflow (per user feedback 2026-07-27):
1. Subscribe outro click sound was out of sync with the hand-click animation
   -> Build Render Script now concatenates with the `concat` FILTER
   (-filter_complex ... concat=n=N:v=1:a=1) instead of the concat DEMUXER
   (-f concat). Demuxer concat + re-encode can subtly drift PTS at segment
   boundaries; filter concat re-times every input against the same clock
   during the single encode pass, which is the correct way to concatenate
   heterogeneous re-encoded clips.
2. Target length raised from 45-60s to 90-120s (~2 min, still within
   YouTube's <=3min Shorts eligibility window).
3. No longer solely scrapes vietstock.vn. A new deterministic (non-agentic,
   see NOTE below) Tavily-based topic picker selects 5 candidates/day mixing
   TAM LY (psychology) and DAU TU (investing) topics, then the whole
   per-video pipeline runs inside an outer Loop Over Headlines so 5 videos
   get produced per run.
4. zoompanExpr's default case used to fall back to a flat, non-zooming
   'static' pan (z=1, no motion) - replaced with a gentle default zoom so
   every scene always has visible Ken Burns motion. Screen Planner's prompt
   also now forbids 'static' as a camera value and requires event_query to
   describe the EXACT thing being narrated in that scene (not a generic
   image), to fix "images don't match the narration" complaints.
5. Real photos must now be >=720p: Validate Tavily Image/Thumbnail parse the
   actual JPEG/PNG header bytes (no external library available in the n8n
   Code sandbox) and reject images whose smaller dimension is <720px.
   Pexels search now requests 5 candidates (was 1) and picks the first one
   whose reported width/height both clear 720px, falling back to the first
   result only if none qualify (keeps the pipeline from dead-ending).
6. Burned-in captions synced to the narration audio: Build Render Script now
   writes an SRT file per video (one cue per scene, timed against the same
   ffprobe-measured audio duration used to render that scene, accumulated
   across scenes) and burns it into the final encode via the `subtitles`
   filter chained after the concat filter.

NOTE on agent design: the Topic Picker uses the deterministic
"Code (build query) -> httpRequest (direct Tavily call) -> Code (digest) ->
tool-free LLM synthesis" pattern (not an agent+ai_tool ReAct loop), matching
the lesson learned in the separate premium-workflow project: local Ollama
models are unreliable at the agent+tool loop and can hit "Max iterations
reached" instead of answering. The existing Research Agent (agent + Tavily
tool + memory) is left as-is since the user has not reported it failing in
this live workflow - only its prompt text is broadened beyond vietstock/
finance-only wording.

Credentials reused from the user's real, already-configured n8n instance
(NOT placeholders - these are the live credential ids from the workflow the
user exported):
  ollamaApi:        LyoMMrEgRWUOqs0p  ("Ollama account")
  tavilyApi:         FzCSQUCeWSUUEBab ("Tavily account")
  youTubeOAuth2Api:  8H6dcwwlUwbkYxZ2 ("YouTube account 2")
  httpHeaderAuth:    MpKrAHcdRHV5PnRV ("Header Auth account", Pexels)
"""
import json
import uuid


def nid():
    return str(uuid.uuid4())


class Workflow:
    def __init__(self):
        self.nodes = []
        self.connections = {}

    def node(self, name, ntype, params, x, y, type_version=1, extra=None):
        n = {
            "parameters": params,
            "type": ntype,
            "typeVersion": type_version,
            "position": [x, y],
            "id": nid(),
            "name": name,
        }
        if extra:
            n.update(extra)
        self.nodes.append(n)
        return name

    def sticky(self, content, x, y, w=380, h=260, color=4):
        n = {
            "parameters": {"content": content, "height": h, "width": w, "color": color},
            "type": "n8n-nodes-base.stickyNote",
            "typeVersion": 1,
            "position": [x, y],
            "id": nid(),
            "name": "Note " + nid()[:8],
        }
        self.nodes.append(n)

    def link(self, src, dst, otype="main", src_index=0, dst_index=0):
        self.connections.setdefault(src, {}).setdefault(otype, [])
        arr = self.connections[src][otype]
        while len(arr) <= src_index:
            arr.append([])
        arr[src_index].append({"node": dst, "type": otype, "index": dst_index})

    def model(self, model_name, agent_name):
        self.link(model_name, agent_name, otype="ai_languageModel")

    def tool(self, tool_name, agent_name):
        self.link(tool_name, agent_name, otype="ai_tool")

    def memory(self, mem_name, agent_name):
        self.link(mem_name, agent_name, otype="ai_memory")

    def export(self):
        return {
            "nodes": self.nodes,
            "connections": self.connections,
            "pinData": {},
            "meta": {"templateCredsSetupCompleted": True, "instanceId": "f820868f59015112916cb180789f95ffb136cb3e701323e49dc86220f1b1040d"},
        }


wf = Workflow()

OLLAMA_CRED = {"ollamaApi": {"id": "LyoMMrEgRWUOqs0p", "name": "Ollama account"}}
TAVILY_CRED = {"tavilyApi": {"id": "FzCSQUCeWSUUEBab", "name": "Tavily account"}}
YOUTUBE_CRED = {"youTubeOAuth2Api": {"id": "8H6dcwwlUwbkYxZ2", "name": "YouTube account 2"}}
PEXELS_CRED = {"httpHeaderAuth": {"id": "MpKrAHcdRHV5PnRV", "name": "Header Auth account"}}
OLLAMA_MODEL = "gemma4:e4b"

Y_MAIN = 5160
Y_MODEL = 5384

# ============================================================================
# MODULE 1 - DAILY TOPIC PICKER (tam ly / dau tu, no vietstock dependency)
# ============================================================================
wf.sticky(
    "## TOPIC PICKER (moi ngay)\n\n"
    "KHONG con phu thuoc mot minh vietstock.vn. Tim chu de TAM LY HOC hoac\n"
    "DAU TU TAI CHINH qua Tavily, chon 5 chu de/ngay (tron 2 nhom), moi chu\n"
    "de se thanh 1 video rieng (xem Loop Over Headlines ben duoi).\n\n"
    "Dung pattern DETERMINISTIC (Code build query -> httpRequest Tavily truc\n"
    "tiep -> Code digest -> LLM tool-free) thay vi agent+tool ReAct, vi agent\n"
    "+tool voi Ollama local da tung bi lap vo han 'Max iterations reached' o\n"
    "workflow khac trong repo nay.",
    -320, 4820, w=520, h=300,
)

wf.node(
    "Schedule Trigger",
    "n8n-nodes-base.scheduleTrigger",
    {"rule": {"interval": [{"triggerAtHour": 6}]}},
    -96, Y_MAIN, type_version=1.3,
)

wf.node(
    "Load Config",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "// ==== CHINH LAI CHO DUNG MAY BAN NEU CAN ====\n"
            "const BASE_DIR = '/Users/tuht1/tui-dau-tu-videos';\n"
            "const VIDEOS_PER_DAY = 5;\n"
            "const NICHES = ['tam_ly', 'dau_tu']; // luan phien 2 nhom noi dung\n"
            "const CHANNEL_NAME = 'Tui dau tu';\n"
            "// --- Facebook Reels (Graph API) ---\n"
            "// FB_PAGE_ID: id so cua Facebook Page (KHONG phai username). Lay tu URL\n"
            "// dang facebook.com/profile.php?id=XXXXXXXXXXXX hoac Page Settings. QUAN\n"
            "// TRONG: PHAI dung dung ID ma Page Access Token duoc cap (kiem tra bang\n"
            "// debug_token: https://graph.facebook.com/debug_token?input_token=TOKEN&\n"
            "// access_token=TOKEN -> field profile_id chinh la ID dung, KHONG phai ID\n"
            "// tuy y lay tu URL profile - da tung bi sai vi 2 gia tri nay khac nhau.\n"
            "const FB_PAGE_ID = '874204112441586';\n"
            "// !!! DAN TOKEN THAT (page access token, da XOAY VONG/rotate lai) vao day.\n"
            "// KHONG commit file nay len git public khi da dien token that.\n"
            "const FB_ACCESS_TOKEN = 'PASTE_YOUR_ROTATED_FACEBOOK_PAGE_ACCESS_TOKEN_HERE';\n"
            "// --- TikTok (Content Posting API - Direct Post) ---\n"
            "// Token nguoi dung (access_token/refresh_token) KHONG the lay chi tu\n"
            "// client_key+client_secret - TikTok bat buoc nguoi dung phai dong y qua\n"
            "// man hinh OAuth that su. Chay 1 lan: `python tiktok_oauth_setup.py`\n"
            "// (xem huong dan trong file do) de tao ra tiktok_tokens.json duoi day.\n"
            "const TIKTOK_TOKENS_FILE = `${BASE_DIR}/tiktok_tokens.json`;\n"
            "const TIKTOK_CLIENT_KEY = 'awmhgdzxwnuw47ix';\n"
            "// !!! DAN client_secret THAT (da XOAY VONG/rotate lai) vao day.\n"
            "const TIKTOK_CLIENT_SECRET = 'PASTE_YOUR_ROTATED_TIKTOK_CLIENT_SECRET_HERE';\n"
            "// unaudited app -> chi duoc dang SELF_ONLY (rieng tu). Doi thanh\n"
            "// 'PUBLIC_TO_EVERYONE' sau khi app da duoc TikTok audit/duyet dang cong khai.\n"
            "const TIKTOK_PRIVACY_LEVEL = 'SELF_ONLY';\n"
            "// ===============================================\n\n"
            "return [{\n"
            "  json: {\n"
            "    BASE_DIR, VIDEOS_PER_DAY, NICHES, channelName: CHANNEL_NAME,\n"
            "    FB_PAGE_ID, FB_ACCESS_TOKEN,\n"
            "    TIKTOK_TOKENS_FILE, TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_PRIVACY_LEVEL,\n"
            "    today: new Date().toISOString().slice(0, 10)\n"
            "  }\n"
            "}];"
        )
    },
    128, Y_MAIN, type_version=2,
)

wf.node(
    "Build Topics Query",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const query = 'Chu de dang duoc quan tam hom nay ve tam ly hoc ung dung "
            "(thau hieu ban than, cam xuc, thoi quen, moi quan he) va dau tu tai chinh "
            "ca nhan (chung khoan, bat dong san, tiet kiem, xu huong thi truong Viet Nam) "
            "trong 3 ngay qua.';\n"
            "return [{ json: { ...$json, topicsQuery: query } }];"
        )
    },
    352, Y_MAIN, type_version=2,
)

wf.node(
    "Tavily Search (Topics)",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://api.tavily.com/search",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "tavilyApi",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ query: $json.topicsQuery, topic: 'news', "
            "search_depth: 'advanced', days: 3, max_results: 10, include_answer: false }) }}"
        ),
        "options": {"timeout": 30000},
    },
    576, Y_MAIN,
    type_version=4.4,
    extra={"credentials": TAVILY_CRED},
)

wf.node(
    "Parse Topics Results",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const prev = $('Build Topics Query').first().json;\n"
            "const results = $json.results || [];\n"
            "const digest = results.slice(0, 10).map((r, i) =>\n"
            "  (i + 1) + '. ' + r.title + '\\n   URL: ' + r.url + '\\n   ' + (r.content || '').slice(0, 300)\n"
            ").join('\\n\\n');\n\n"
            "return [{ json: { ...prev, topicsDigest: digest || 'Khong co ket qua tim kiem.' } }];"
        )
    },
    800, Y_MAIN, type_version=2,
)

wf.node(
    "Ollama Chat Model (Topics)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": OLLAMA_MODEL, "options": {"format": "json"}},
    1024, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Pick Daily Topics Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Ban la Content Strategist cho kenh Shorts \"{{ $json.channelName }}\", noi dung "
            "xoay quanh HAI chu de: TAM LY HOC ung dung (nhan biet cam xuc, thoi quen, "
            "moi quan he, phat trien ban than) va DAU TU TAI CHINH ca nhan.\n\n"
            "Ngay hom nay: {{ $json.today }}\n\n"
            "Ket qua tim kiem Tavily (tin tuc/xu huong 3 ngay qua):\n"
            "{{ $json.topicsDigest }}\n\n"
            "Dua vao ket qua tren, chon ra DUNG {{ $json.VIDEOS_PER_DAY }} chu de cho video "
            "Shorts hom nay, TRON ca hai nhom tam_ly va dau_tu (khong chon toan bo 1 nhom). "
            "Moi chu de PHAI co goc nhin/angle ro rang, khong trung lap y tuong voi nhau. "
            "source_url PHAI la URL that lay tu ket qua tim kiem o tren (khong bia).\n\n"
            "Output CHI JSON, khong markdown, khong giai thich, dung schema:\n"
            "{\n"
            '  "topics": [\n'
            "    {\n"
            '      "niche": "tam_ly" hoac "dau_tu",\n'
            '      "headline": "",\n'
            '      "angle": "",\n'
            '      "source_url": ""\n'
            "    }\n"
            "  ]\n"
            "}"
        ),
        "options": {},
    },
    1248, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (Topics)", "Pick Daily Topics Agent")

wf.node(
    "Parse & Split Topics",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "function parseAgentJson(raw) {\n"
            "  if (typeof raw !== 'string') return raw;\n"
            "  let t = raw.trim();\n"
            "  const fence = t.match(/^```(?:json)?\\s*([\\s\\S]*?)\\s*```$/i);\n"
            "  if (fence) t = fence[1];\n"
            "  if (!/^[\\{\\[]/.test(t.trim())) {\n"
            "    const m = t.match(/\\{[\\s\\S]*\\}/);\n"
            "    if (m) t = m[0];\n"
            "  }\n"
            "  return JSON.parse(t);\n"
            "}\n\n"
            "let data;\n"
            "try {\n"
            "  data = parseAgentJson($json.output);\n"
            "} catch (e) {\n"
            "  throw new Error('Pick Daily Topics Agent khong tra ve JSON hop le: ' + String($json.output).slice(0, 300));\n"
            "}\n\n"
            "if (!data.topics || !Array.isArray(data.topics) || data.topics.length === 0) {\n"
            "  throw new Error('Pick Daily Topics Agent thieu field topics[]');\n"
            "}\n\n"
            "const cfg = $('Load Config').first().json;\n"
            "const topics = data.topics.slice(0, cfg.VIDEOS_PER_DAY);\n"
            "return topics.map(t => ({\n"
            "  json: {\n"
            "    ...cfg,\n"
            "    niche: t.niche === 'tam_ly' ? 'tam_ly' : 'dau_tu',\n"
            "    headline: t.headline,\n"
            "    angle: t.angle || '',\n"
            "    sourceUrl: t.source_url || ''\n"
            "  }\n"
            "}));"
        )
    },
    1472, Y_MAIN, type_version=2,
)

wf.node(
    "Loop Over Headlines",
    "n8n-nodes-base.splitInBatches",
    {"options": {}},
    1696, Y_MAIN, type_version=3,
)

wf.link("Schedule Trigger", "Load Config")
wf.link("Load Config", "Build Topics Query")
wf.link("Build Topics Query", "Tavily Search (Topics)")
wf.link("Tavily Search (Topics)", "Parse Topics Results")
wf.link("Parse Topics Results", "Pick Daily Topics Agent")
wf.link("Pick Daily Topics Agent", "Parse & Split Topics")
wf.link("Parse & Split Topics", "Loop Over Headlines")

print("module 1 (topic picker) nodes so far:", len(wf.nodes))

# ============================================================================
# MODULE 2 - PER-VIDEO PIPELINE (runs once per headline, inside the loop)
# ============================================================================
wf.sticky(
    "## PER-VIDEO PIPELINE (chay 1 lan / chu de, trong Loop Over Headlines)\n\n"
    "Video dai muc tieu 90-120 giay (~2 phut, van trong gioi han Shorts cua\n"
    "YouTube la <=3 phut). Research Agent + Screen Planner giu nguyen kien\n"
    "truc agent+tool cu (chua thay loi trong workflow that), chi cap nhat\n"
    "prompt de tong quat hoa ngoai tin tuc tai chinh (them tam_ly).",
    1920, 4820, w=520, h=280,
)

wf.node(
    "Generate Video ID",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const item = $input.item.json;\n"
            "const now = new Date();\n"
            "const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');\n"
            "const slug = (item.headline || 'video')\n"
            "  .toLowerCase()\n"
            "  .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')\n"
            "  .replace(/đ/g, 'd').replace(/Đ/g, 'd')\n"
            "  .replace(/[^a-z0-9]+/g, '-')\n"
            "  .replace(/(^-|-$)/g, '')\n"
            "  .slice(0, 40);\n"
            "const rand = Math.random().toString(36).slice(2, 7);\n\n"
            "return {\n"
            "  json: {\n"
            "    ...item,\n"
            "    videoId: `${dateStr}-${slug}-${rand}`,\n"
            "    channelName: item.channelName || 'Tui dau tu',\n"
            "    sourceUrl: item.sourceUrl || ''\n"
            "  }\n"
            "};"
        ),
    },
    1976, Y_MAIN, type_version=2,
)

wf.node(
    "Init Paths",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const path = require('path');\n"
            "const fs = require('fs');\n\n"
            "const BASE_DIR = $json.BASE_DIR;\n\n"
            "const videoId = $json.videoId;\n"
            "const videoDir = path.join(BASE_DIR, videoId);\n"
            "fs.mkdirSync(videoDir, { recursive: true });\n\n"
            "return [{\n"
            "  json: {\n"
            "    ...$json,\n"
            "    videoDir,\n"
            "    storyboardPath: path.join(videoDir, 'storyboard.json'),\n"
            "    renderScriptPath: path.join(videoDir, 'render_video.sh'),\n"
            "    thumbnailPath: path.join(videoDir, 'thumbnail_bg.jpg'),\n"
            "    subscribeClip: path.join(BASE_DIR, 'assets', 'subscribe-tui-dau-tu_final.mp4')\n"
            "  }\n"
            "}];"
        )
    },
    2200, Y_MAIN, type_version=2,
)

wf.node(
    "Reset Scene Store",
    "n8n-nodes-base.code",
    {"jsCode": "const staticData = $getWorkflowStaticData('global');\nstaticData.scenes = [];\nreturn $input.all();"},
    2424, Y_MAIN, type_version=2,
)

wf.node(
    "Simple Memory",
    "@n8n/n8n-nodes-langchain.memoryBufferWindow",
    {"sessionIdType": "customKey", "sessionKey": "={{ $json.headline }}", "contextWindowLength": 10},
    2872, Y_MODEL, type_version=1.3,
)
wf.node(
    "Ollama Chat Model (Research)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": OLLAMA_MODEL, "options": {"format": "json"}},
    2744, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Search in Tavily",
    "@tavily/n8n-nodes-tavily.tavilyTool",
    {
        "query": "={{ /*n8n-auto-generated-fromAI-override*/ $fromAI('Query', `Use this tool ONLY when additional background research is needed.\n\nNever use this tool to open or read the original article.\n\nSearch using natural language.\n\nNever search using only a URL.\n\nNever search using only site: operators.\n\nAlways include descriptive keywords.`, 'string') }}",
        "options": {},
    },
    2996, Y_MODEL,
    extra={"credentials": TAVILY_CRED},
)
wf.node(
    "Research Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Ban la BIEN TAP VIEN kenh Shorts \"{{ $json.channelName }}\", chuyen san xuat "
            "video NGAN (duoi 2 phut) ve TAM LY HOC ung dung hoac DAU TU TAI CHINH ca nhan, "
            "dinh dang DOC 9:16.\n\n"
            "Chu de hom nay (niche = {{ $json.niche }}):\n"
            "Headline: {{ $json.headline }}\n"
            "Goc nhin goi y: {{ $json.angle }}\n"
            "Nguon tham khao: {{ $json.sourceUrl }}\n\n"
            "Neu niche la 'tam_ly': tap trung vao mot insight tam ly cu the, de ap dung ngay "
            "vao cuoc song (cam xuc, thoi quen, giao tiep, tu duy). Neu niche la 'dau_tu': tap "
            "trung vao mot su kien/kien thuc dau tu tai chinh cu the, so lieu ro rang, khong "
            "phan tich vi mo lan man.\n\n"
            "Dung tool Tavily NEU can them thong tin nen dang tin cay. Video dai muc tieu "
            "90-120 giay - can du chat lieu cho 8-14 scene, khong chi 1 y ngan gon. Viet "
            "narration cuon hut, nhip nhanh, giong nguoi chia se that su chu khong doc bao "
            "cao kho khan. Bo hoan toan phan chao hoi dai dong, di thang vao noi dung ngay tu "
            "giay dau tien.\n\n"
            "Output CHI JSON, khong markdown, khong giai thich:\n"
            "{\n"
            '  "title": "",\n'
            '  "description": "",\n'
            '  "tags": [],\n'
            '  "hashtags": [],\n'
            '  "report": {}\n'
            "}"
        ),
        "options": {},
    },
    2872, Y_MAIN, type_version=3.1,
)
wf.memory("Simple Memory", "Research Agent")
wf.model("Ollama Chat Model (Research)", "Research Agent")
wf.tool("Search in Tavily", "Research Agent")

wf.node(
    "Ollama Chat Model (Planner)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": OLLAMA_MODEL, "options": {"format": "json"}},
    3352, Y_MAIN - 120,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Screen Planner",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Ban la Senior Storyboard Director cho kenh YouTube SHORTS \"{{ $('Generate Video ID').first().json.channelName }}\" "
            "(noi dung tam ly hoc hoac dau tu tai chinh, tuy niche). Video dinh dang DOC 9:16 - "
            "day la YOUTUBE SHORTS. Tong do dai BAT BUOC nam trong khoang 90-120 giay (tong "
            "duration cac scene cong lai KHONG duoc vuot qua 120 giay va KHONG duoc duoi 90 "
            "giay - day la thay doi so voi ban truoc chi 45-60s). Dung 8-14 scene, moi scene "
            "8-12 giay. Hook phai xuat hien ngay trong 3 giay dau tien. Bo hoan toan phan chao "
            "hoi dai dong, di thang vao noi dung. Narration phai cuon hut, nhip nhanh, cau "
            "ngan - giong nguoi chia se that su, KHONG doc bao cao kho khan.\n\n"
            "QUAN TRONG - MOI SCENE DUNG ANH THAT tai ve tu Tavily (uu tien, anh gan dung su "
            "kien/nhan vat/khai niem that) hoac Pexels (anh stock du phong).\n\n"
            "Voi MOI scene, ban phai cung cap:\n"
            "- \"camera\": BAT BUOC chon 1 trong cac gia tri sau va KHONG BAO GIO de trong hay "
            "dung 'static': slow-zoom, push-in, pull-out, pan-left, pan-right, parallax. Moi "
            "scene PHAI co chuyen dong zoom/pan ro rang, khong duoc dung hinh tinh.\n"
            "- asset gom 2 query:\n"
            "  + \"event_query\": tu khoa tim ANH THAT PHAI mo ta CHINH XAC dieu dang duoc "
            "narration cua SCENE NAY nhac toi (ten nguoi/su kien/khai niem/hanh dong cu the "
            "- KHONG duoc chung chung khong lien quan). Dung cho Tavily.\n"
            "  + \"stock_query\": mo ta tieng Anh chung chung kieu anh stock lien quan chu de "
            "cua scene (VD voi tam_ly: 'person reflecting quietly at window'; voi dau_tu: "
            "'stock exchange trading floor') de du phong tren Pexels.\n\n"
            "INPUT (JSON tu Research Agent):\n"
            "{{ $json.output }}\n\n"
            "Return ONLY JSON theo dung schema sau, khong markdown, khong giai thich, khong "
            "them key nao khac:\n"
            "{\n"
            '  "video_style": "shorts_news",\n'
            '  "theme": "modern",\n'
            '  "aspect_ratio": "9:16",\n'
            '  "fps": 30,\n'
            '  "scenes": [\n'
            "    {\n"
            '      "scene_type": "", "headline": "", "narration": "", "duration": 10,\n'
            '      "camera": "", "animation": "", "transition": "", "subtitle_style": "",\n'
            '      "highlight_words": [], "importance": "medium",\n'
            '      "asset": { "event_query": "", "stock_query": "" }\n'
            "    }\n"
            "  ]\n"
            "}"
        ),
        "options": {},
    },
    3352, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (Planner)", "Screen Planner")

wf.node(
    "normalize scene data",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "return $input.all().flatMap(item => {\n"
            "  let raw = item.json.output;\n"
            "  if (typeof raw === 'string') {\n"
            "    raw = raw.trim();\n"
            "    const fenceMatch = raw.match(/^```(?:json)?\\s*([\\s\\S]*?)\\s*```$/i);\n"
            "    if (fenceMatch) raw = fenceMatch[1];\n"
            "    if (!/^[\\{\\[]/.test(raw.trim())) {\n"
            "      const jsonMatch = raw.match(/\\{[\\s\\S]*\\}/);\n"
            "      if (jsonMatch) raw = jsonMatch[0];\n"
            "    }\n"
            "  }\n\n"
            "  let data;\n"
            "  try {\n"
            "    data = JSON.parse(raw);\n"
            "  } catch (e) {\n"
            "    const preview = String(item.json.output || '').slice(0, 300);\n"
            "    throw new Error(`Screen Planner KHONG tra JSON hop le.\\n--- 300 ky tu dau ---\\n${preview}`);\n"
            "  }\n\n"
            "  if (!data.scenes || !Array.isArray(data.scenes)) {\n"
            "    throw new Error('Screen Planner tra JSON nhung thieu field \"scenes\" dang mang.');\n"
            "  }\n\n"
            "  const cleanScenes = data.scenes.filter(scene => {\n"
            "    const text = (scene.narration || '').trim();\n"
            "    return text.length > 0 && !/^\\(.*\\)$/.test(text);\n"
            "  });\n\n"
            "  const total = cleanScenes.reduce((s, sc) => s + (Number(sc.duration) || 0), 0);\n"
            "  // FIX (workflow bi stuck/that bai toan bo pipeline chi vi uoc luong lech vai\n"
            "  // giay): field 'duration' o day chi la UOC LUONG cua Screen Planner - thoi\n"
            "  // luong THAT cua video duoc quyet dinh boi audio TTS that (ffprobe do truc\n"
            "  // tiep trong Build Render Script), KHONG phai field nay (xem duration: scene.\n"
            "  // duration ben duoi chi de luu vao storyboard.json, khong dung de dung clip).\n"
            "  // Vi vay KHONG throw Error lam dung ca pipeline (mat het cong Research Agent +\n"
            "  // Screen Planner da chay) chi vi model local uoc luong lech nhe so voi muc\n"
            "  // tieu 90-120s - chi canh bao va van tiep tuc chay binh thuong. Chi throw that\n"
            "  // su neu tong qua bat thuong (gan nhu chac chan la output loi/thieu scene).\n"
            "  if (total < 20 || total > 200) {\n"
            "    throw new Error('Tong duration UOC LUONG cua scenes = ' + total.toFixed(1) + 's, qua bat thuong (ngoai 20-200s) - Screen Planner co the da tra ve output loi/thieu scene.');\n"
            "  }\n"
            "  if (total < 90 || total > 120) {\n"
            "    console.log('[CANH BAO] Tong duration UOC LUONG cua scenes = ' + total.toFixed(1) + 's, ngoai muc tieu 90-120s. Van tiep tuc vi thoi luong THAT cua video phu thuoc audio TTS thuc te, khong phai field uoc luong nay.');\n"
            "  }\n\n"
            "  return cleanScenes.map(scene => ({\n"
            "    json: {\n"
            "      video_style: data.video_style,\n"
            "      theme: data.theme,\n"
            "      aspect_ratio: data.aspect_ratio,\n"
            "      fps: data.fps,\n"
            "      ...scene,\n"
            "      camera: (scene.camera && scene.camera !== 'static') ? scene.camera : 'slow-zoom'\n"
            "    }\n"
            "  }));\n"
            "});"
        )
    },
    3800, Y_MAIN, type_version=2,
)

wf.link("Loop Over Headlines", "Generate Video ID", src_index=1)
wf.link("Generate Video ID", "Init Paths")
wf.link("Init Paths", "Reset Scene Store")
wf.link("Reset Scene Store", "Research Agent")
wf.link("Research Agent", "Screen Planner")
wf.link("Screen Planner", "normalize scene data")

print("module 2 (per-video, research+planner) nodes so far:", len(wf.nodes))

# ============================================================================
# MODULE 3 - VOICE (vietTTS) + PER-SCENE REAL PHOTO (Tavily/Pexels)
# ============================================================================
wf.node(
    "Generate audio (vietTTS)",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "http://0.0.0.0:8002/tts",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ text: $json.narration, voice: 'infore', "
            "silence_duration: 0.2, speech_rate: 1.15 }) }}"
        ),
        "options": {"response": {"response": {"responseFormat": "file"}}, "timeout": 60000},
    },
    4024, Y_MAIN,
    type_version=4.4,
)

wf.node(
    "attach audio to scene",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "return $input.all().map((item, index) => ({\n"
            "  json: { ...item.json, sceneId: index + 1 },\n"
            "  binary: { audio: item.binary.data }\n"
            "}));"
        )
    },
    4248, Y_MAIN, type_version=2,
)

wf.node(
    "Loop Over Scenes",
    "n8n-nodes-base.splitInBatches",
    {"options": {}},
    4472, Y_MAIN, type_version=3,
)

wf.node(
    "Build Image Queries",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const scene = $input.item.json;\n"
            "const videoDir = $('Init Paths').first().json.videoDir;\n"
            "const sceneId = scene.sceneId;\n\n"
            "const audioPath = `${videoDir}/scene_${sceneId}_audio.wav`;\n"
            "const imagePath = `${videoDir}/scene_${sceneId}_image.jpg`;\n\n"
            "const eventQuery = (scene.asset && scene.asset.event_query) || scene.headline || (scene.narration || '').slice(0, 80);\n"
            "const stockQuery = (scene.asset && scene.asset.stock_query) || "
            "($('Generate Video ID').first().json.niche === 'tam_ly' ? 'calm lifestyle emotion background' : 'financial news background');\n\n"
            "return {\n"
            "  json: { ...scene, audioPath, imagePath, eventQuery, stockQuery },\n"
            "  binary: $input.item.binary\n"
            "};"
        )
    },
    4696, Y_MAIN - 288, type_version=2,
)

wf.node(
    "Write audio file",
    "n8n-nodes-base.readWriteFile",
    {"operation": "write", "fileName": "={{ $json.audioPath }}", "dataPropertyName": "audio", "options": {}},
    4920, Y_MAIN - 288,
)

wf.node(
    "Tavily Image Search",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://api.tavily.com/search",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "tavilyApi",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ query: $('Build Image Queries').first().json.eventQuery, "
            "search_depth: 'basic', include_images: true, include_image_descriptions: false, max_results: 3 }) }}"
        ),
        "options": {"timeout": 30000},
    },
    5144, Y_MAIN - 288,
    type_version=4.4,
    extra={"credentials": TAVILY_CRED},
)

wf.node(
    "Check Tavily Images",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const bad = (url) => {\n"
            "  if (!url) return true;\n"
            "  url = url.toLowerCase();\n"
            "  return (\n"
            "    url.endsWith('.svg') ||\n"
            "    url.includes('.svg?') ||\n"
            "    url.includes('logo') ||\n"
            "    url.includes('icon') ||\n"
            "    url.includes('favicon') ||\n"
            "    url.includes('lookaside.instagram') ||\n"
            "    url.includes('instagram.com')\n"
            "  );\n"
            "};\n\n"
            "let imageUrl = null;\n\n"
            "if (Array.isArray($json.results)) {\n"
            "  for (const result of $json.results) {\n"
            "    if (!Array.isArray(result.images)) continue;\n"
            "    imageUrl = result.images.find(u => !bad(u));\n"
            "    if (imageUrl) break;\n"
            "  }\n"
            "}\n\n"
            "if (!imageUrl && Array.isArray($json.images)) {\n"
            "  imageUrl = $json.images.find(u => !bad(u));\n"
            "}\n\n"
            "const scene = $('Build Image Queries').first().json;\n\n"
            "return {\n"
            "  json: { ...scene, hasTavilyImage: !!imageUrl, tavilyImageUrl: imageUrl }\n"
            "};"
        )
    },
    5368, Y_MAIN - 288, type_version=2,
)

wf.node(
    "Has Tavily Image?",
    "n8n-nodes-base.if",
    {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 3},
            "conditions": [
                {"id": "cond1", "leftValue": "={{ $json.hasTavilyImage }}", "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}
            ],
            "combinator": "and",
        },
        "options": {},
    },
    5592, Y_MAIN - 288, type_version=2.3,
)

wf.node(
    "Download Image (Tavily)",
    "n8n-nodes-base.httpRequest",
    {"url": "={{ $json.tavilyImageUrl }}", "options": {"response": {"response": {"neverError": True, "responseFormat": "file"}}, "timeout": 12000}},
    5816, Y_MAIN - 360,
    type_version=4.4,
    # FIX (workflow bi crash toan bo vi ECONNABORTED/timeout khi tai anh Tavily tu
    # mot CDN cham/chet - neverError CHI bat loi HTTP status (4xx/5xx), KHONG bat
    # duoc loi ket noi/timeout o tang thap hon). onError=continueRegularOutput de
    # item van di tiep (khong co binary) thay vi lam dung ca pipeline; Validate
    # Tavily Image ben duoi da tu coi khong co binary la anh khong hop le, kich
    # hoat fallback Pexels nhu binh thuong.
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "Validate Tavily Image",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "function getImageDimensions(buf) {\n"
            "  // JPEG: scan markers for a Start-Of-Frame segment (SOF0-3) which holds height/width.\n"
            "  if (buf.length > 4 && buf[0] === 0xFF && buf[1] === 0xD8) {\n"
            "    let offset = 2;\n"
            "    while (offset + 9 < buf.length) {\n"
            "      if (buf[offset] !== 0xFF) { offset++; continue; }\n"
            "      const marker = buf[offset + 1];\n"
            "      if (marker >= 0xC0 && marker <= 0xC3) {\n"
            "        return { width: buf.readUInt16BE(offset + 7), height: buf.readUInt16BE(offset + 5) };\n"
            "      }\n"
            "      const segLength = buf.readUInt16BE(offset + 2);\n"
            "      offset += 2 + segLength;\n"
            "    }\n"
            "    return null;\n"
            "  }\n"
            "  // PNG: IHDR chunk is always the first chunk, right after the 8-byte signature.\n"
            "  if (buf.length > 24 && buf[0] === 0x89 && buf[1] === 0x50) {\n"
            "    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };\n"
            "  }\n"
            "  return null; // WEBP dimension parsing not implemented - skip the resolution check for it.\n"
            "}\n\n"
            "const MIN_DIMENSION = 720; // yeu cau anh that >=720p (theo chieu nho hon)\n\n"
            "// Lay scene tu node 'Check Tavily Images' (KHONG phai $input.item.json) vi\n"
            "// Download Image (Tavily) co the that bai (timeout/mat ket noi) va van tiep\n"
            "// tuc chay (onError=continueRegularOutput) voi json bi thay the (vd {error}),\n"
            "// lam mat het cac field scene that su (sceneId, imagePath, stockQuery,...).\n"
            "const scene = $('Check Tavily Images').first().json;\n"
            "const binary = $input.item.binary && $input.item.binary.data;\n"
            "let isValid = false;\n\n"
            "if (binary) {\n"
            "  const buffer = await this.helpers.getBinaryDataBuffer(0, 'data');\n"
            "  const isJpeg = buffer.length > 4 && buffer[0] === 0xFF && buffer[1] === 0xD8;\n"
            "  const isPng = buffer.length > 8 && buffer[0] === 0x89 && buffer[1] === 0x50;\n"
            "  const isWebp = buffer.length > 12 && buffer.slice(8, 12).toString() === 'WEBP';\n"
            "  const dims = getImageDimensions(buffer);\n"
            "  const meetsResolution = isWebp ? true : (dims ? Math.min(dims.width, dims.height) >= MIN_DIMENSION : false);\n"
            "  isValid = buffer.length > 2000 && (isJpeg || isPng || isWebp) && meetsResolution;\n"
            "}\n\n"
            "return { json: { ...scene, tavilyImageValid: isValid }, binary: $input.item.binary };"
        )
    },
    6040, Y_MAIN - 360, type_version=2,
)

wf.node(
    "Is Tavily Image Valid?",
    "n8n-nodes-base.if",
    {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 3},
            "conditions": [
                {"id": "5008f102-b4dd-4da4-b2ad-e993463b4f8a", "leftValue": "={{ $json.tavilyImageValid }}", "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}
            ],
            "combinator": "and",
        },
        "options": {},
    },
    6264, Y_MAIN - 360, type_version=2.3,
)

wf.node(
    "Pexels Image Search",
    "n8n-nodes-base.httpRequest",
    {
        "url": "=https://api.pexels.com/v1/search?query={{ encodeURIComponent($json.stockQuery) }}&orientation=portrait&per_page=5&size=large",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"timeout": 30000},
    },
    6488, Y_MAIN - 216,
    type_version=4.4,
    extra={"credentials": PEXELS_CRED},
)

wf.node(
    "Extract Pexels Image URL",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const MIN_DIMENSION = 720;\n"
            "const photos = $json.photos || [];\n"
            "// uu tien anh >=720p (Pexels tra ve width/height that trong response);\n"
            "// neu khong co anh nao dat, dung anh dau tien de khong lam gian doan pipeline.\n"
            "const hq = photos.find(p => Math.min(p.width || 0, p.height || 0) >= MIN_DIMENSION);\n"
            "const photo = hq || photos[0];\n"
            "const imageUrl = photo && photo.src && (photo.src.large2x || photo.src.large || photo.src.original);\n\n"
            "const scene = $('Check Tavily Images').first().json;\n\n"
            "if (!imageUrl) {\n"
            "  throw new Error('Pexels khong tra ve anh phu hop cho query: ' + (scene.stockQuery || ''));\n"
            "}\n\n"
            "return { json: { ...scene, pexelsImageUrl: imageUrl } };"
        )
    },
    6712, Y_MAIN - 216, type_version=2,
)

wf.node(
    "Download Image (Pexels)",
    "n8n-nodes-base.httpRequest",
    {"url": "={{ $json.pexelsImageUrl }}", "options": {"response": {"response": {"responseFormat": "file"}}, "timeout": 30000}},
    6936, Y_MAIN - 216,
    type_version=4.4,
)

wf.node(
    "Finalize Scene Image",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const scene = $('Check Tavily Images').first().json;\n\n"
            "const staticData = $getWorkflowStaticData('global');\n"
            "if (!staticData.scenes) staticData.scenes = [];\n"
            "staticData.scenes.push({\n"
            "  sceneId: scene.sceneId,\n"
            "  scene_type: scene.scene_type,\n"
            "  headline: scene.headline,\n"
            "  narration: scene.narration,\n"
            "  duration: scene.duration,\n"
            "  camera: scene.camera,\n"
            "  animation: scene.animation,\n"
            "  transition: scene.transition,\n"
            "  subtitle_style: scene.subtitle_style,\n"
            "  highlight_words: scene.highlight_words,\n"
            "  importance: scene.importance,\n"
            "  audioPath: scene.audioPath,\n"
            "  imagePath: scene.imagePath\n"
            "});\n\n"
            "return {\n"
            "  json: scene,\n"
            "  binary: { image: $input.item.binary.data }\n"
            "};"
        )
    },
    7160, Y_MAIN - 288, type_version=2,
)

wf.node(
    "Write image file",
    "n8n-nodes-base.readWriteFile",
    {"operation": "write", "fileName": "={{ $json.imagePath }}", "dataPropertyName": "image", "options": {}},
    7384, Y_MAIN - 120,
)

wf.link("normalize scene data", "Generate audio (vietTTS)")
wf.link("Generate audio (vietTTS)", "attach audio to scene")
wf.link("attach audio to scene", "Loop Over Scenes")
wf.link("Loop Over Scenes", "Build Image Queries", src_index=1)
wf.link("Build Image Queries", "Write audio file")
wf.link("Write audio file", "Tavily Image Search")
wf.link("Tavily Image Search", "Check Tavily Images")
wf.link("Check Tavily Images", "Has Tavily Image?")
wf.link("Has Tavily Image?", "Download Image (Tavily)", src_index=0)
wf.link("Has Tavily Image?", "Pexels Image Search", src_index=1)
wf.link("Download Image (Tavily)", "Validate Tavily Image")
wf.link("Validate Tavily Image", "Is Tavily Image Valid?")
wf.link("Is Tavily Image Valid?", "Finalize Scene Image", src_index=0)
wf.link("Is Tavily Image Valid?", "Pexels Image Search", src_index=1)
wf.link("Pexels Image Search", "Extract Pexels Image URL")
wf.link("Extract Pexels Image URL", "Download Image (Pexels)")
wf.link("Download Image (Pexels)", "Finalize Scene Image")
wf.link("Finalize Scene Image", "Write image file")
wf.link("Write image file", "Loop Over Scenes")

print("module 3 (voice+images) nodes so far:", len(wf.nodes))

# ============================================================================
# MODULE 4 - STORYBOARD + RENDER (ffmpeg) - fixed zoom + fixed A/V sync
# ============================================================================
wf.node(
    "prepare storyboard.json",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const staticData = $getWorkflowStaticData('global');\n"
            "const videoId = $('Generate Video ID').first().json.videoId;\n\n"
            "const storyboard = {\n"
            "  channel: $('Generate Video ID').first().json.channelName,\n"
            "  videoId,\n"
            "  aspect_ratio: '9:16',\n"
            "  fps: 30,\n"
            "  scenes: (staticData.scenes || []).sort((a, b) => a.sceneId - b.sceneId)\n"
            "};\n\n"
            "const jsonStr = JSON.stringify(storyboard, null, 2);\n"
            "const buffer = Buffer.from(jsonStr, 'utf-8');\n\n"
            "return [{\n"
            "  json: { videoId, storyboardPath: $('Init Paths').first().json.storyboardPath },\n"
            "  binary: { storyboard: await this.helpers.prepareBinaryData(buffer, 'storyboard.json', 'application/json') }\n"
            "}];"
        )
    },
    4696, Y_MAIN, type_version=2,
)

wf.node(
    "Write storyboard.json",
    "n8n-nodes-base.readWriteFile",
    {"operation": "write", "fileName": "={{ $json.storyboardPath }}", "dataPropertyName": "storyboard", "options": {}},
    4920, Y_MAIN,
)

wf.node(
    "Build Render Script",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "// !!! DOI duong dan SUBSCRIBE_CLIP cho dung may ban neu can !!!\n"
            "// !!! DOI SCENE_TIMEOUT_SEC neu may ban render cham/nhanh hon muc mac dinh !!!\n"
            "// Dinh dang SHORTS doc 9:16 (1080x1920)\n"
            "const W = 1080, H = 1920, FPS = 30;\n"
            "// FIX (chuyen canh/zoom bi rung lac nhe - zoompan jitter): filter 'zoompan'\n"
            "// cua ffmpeg lam tron x/y ve so nguyen MOI FRAME. Voi zoom cham (vd +0.0008/\n"
            "// frame), buoc di chuyen thuc te duoi 1 pixel/frame nen bi lam tron thanh cac\n"
            "// buoc nhay 0-hoac-1-pixel khong deu, tao cam giac 'giat/rung' nhe (da kiem\n"
            "// chung: do coefficient-of-variation cua frame-diff giam ~50% khi supersample\n"
            "// 2x roi downscale, so voi lam zoompan truc tiep o do phan giai dich). Cach\n"
            "// khac phuc chuan: cho zoompan chay tren canvas LON HON (SS lan), roi scale\n"
            "// xuong kich thuoc that o buoc cuoi - luoi pixel min hon lam sai so lam tron\n"
            "// tro nen nho hon nhieu (duoi nguong nhin thay) sau khi downscale.\n"
            "const SS = 2;\n"
            "const WS = W * SS, HS = H * SS;\n"
            "const SCENE_TIMEOUT_SEC = 300;\n"
            "const PRESET = 'veryfast';\n"
            "const staticData = $getWorkflowStaticData('global');\n"
            "const scenes = (staticData.scenes || []).slice().sort((a, b) => a.sceneId - b.sceneId);\n"
            "const videoId = $('Generate Video ID').first().json.videoId;\n"
            "const dir = $('Init Paths').first().json.videoDir;\n"
            "const subscribeClip = $('Init Paths').first().json.subscribeClip;\n\n"
            "function zoompanExpr(camera) {\n"
            "  switch (camera) {\n"
            "    case 'push-in':\n"
            "      return `zoompan=z='min(1+0.20*on/$FRAMES,1.20)':d=$FRAMES:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=${WS}x${HS}:fps=${FPS}`;\n"
            "    case 'pull-out':\n"
            "      return `zoompan=z='max(1.20-0.20*on/$FRAMES,1.0)':d=$FRAMES:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=${WS}x${HS}:fps=${FPS}`;\n"
            "    case 'pan-left':\n"
            "      return `zoompan=z=1.15:d=$FRAMES:x='(iw-iw/zoom)*(1-on/$FRAMES)':y='ih/2-(ih/zoom/2)':s=${WS}x${HS}:fps=${FPS}`;\n"
            "    case 'pan-right':\n"
            "      return `zoompan=z=1.15:d=$FRAMES:x='(iw-iw/zoom)*(on/$FRAMES)':y='ih/2-(ih/zoom/2)':s=${WS}x${HS}:fps=${FPS}`;\n"
            "    case 'parallax':\n"
            "      return `zoompan=z='min(zoom+0.0010,1.25)':d=$FRAMES:x='(iw-iw/zoom)*(on/$FRAMES)':y='ih/2-(ih/zoom/2)':s=${WS}x${HS}:fps=${FPS}`;\n"
            "    case 'slow-zoom':\n"
            "    default:\n"
            "      // FIX (khong con 'static' khong zoom): moi scene LUON co Ken Burns zoom nhe,\n"
            "      // ke ca khi model tra ve gia tri camera khong xac dinh.\n"
            "      return `zoompan=z='min(zoom+0.0008,1.15)':d=$FRAMES:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=${WS}x${HS}:fps=${FPS}`;\n"
            "  }\n"
            "}\n\n"
            "// Bo chu (caption) chay theo giong doc: dung dinh dang ASS (khong phai SRT) voi\n"
            "// PlayResX/PlayResY khai bao DUNG bang kich thuoc khung hinh (1080x1920). SRT\n"
            "// chuyen sang ASS ngam dinh cua ffmpeg co ty le scale khong nhat quan (da kiem\n"
            "// chung thuc te: chu bi phong to qua muc, tran het len tren khung hinh). O day\n"
            "// KHONG tu wrap dong nua - de libass tu dong wrap (WrapStyle=0) theo dung\n"
            "// chieu rong that cua khung hinh, tranh bi mat noi dung do gioi han cung 2 dong.\n"
            "const assHeader = [\n"
            "  '[Script Info]',\n"
            "  'ScriptType: v4.00+',\n"
            "  `PlayResX: ${W}`,\n"
            "  `PlayResY: ${H}`,\n"
            "  'WrapStyle: 0',\n"
            "  'ScaledBorderAndShadow: yes',\n"
            "  '',\n"
            "  '[V4+ Styles]',\n"
            "  'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',\n"
            "  'Style: Default,Arial,46,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,3,1,2,60,60,140,1',\n"
            "  '',\n"
            "  '[Events]',\n"
            "  'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text'\n"
            "].join('\\n');\n\n"
            "function cleanCaption(text) {\n"
            "  return String(text || '').trim().replace(/\\s+/g, ' ');\n"
            "}\n"
            "// Escape ky tu dac biet cua ASS ({ } co the bi hieu nham la override tag) roi\n"
            "// den ky tu dac biet cua bash heredoc KHONG quote ($ va backtick) - can de\n"
            "// SUB_START/SUB_END van duoc noi suy binh thuong trong heredoc.\n"
            "function escapeForHeredoc(text) {\n"
            "  return String(text)\n"
            "    .replace(/\\\\/g, '\\\\\\\\')\n"
            "    .replace(/\\{/g, '(').replace(/\\}/g, ')')\n"
            "    .replace(/`/g, '\\\\`').replace(/\\$/g, '\\\\$');\n"
            "}\n\n"
            "let script = `#!/bin/bash\n"
            "set -e\n"
            "# ffmpeg chuan cua Homebrew KHONG co libass/freetype (thieu filter 'ass').\n"
            "# Uu tien dung ffmpeg-full (co libass) neu da cai, fallback ve ffmpeg mac dinh.\n"
            "if [ -d \"/opt/homebrew/opt/ffmpeg-full/bin\" ]; then\n"
            "  export PATH=\"/opt/homebrew/opt/ffmpeg-full/bin:$PATH\"\n"
            "fi\n"
            "cd \"${dir}\"\n\n"
            "exec 2>> \"${dir}/ffmpeg_error.log\"\n\n"
            "PROGRESS_LOG=\"${dir}/render_progress.log\"\n"
            "> \"$PROGRESS_LOG\"\n\n"
            "SUBTITLE_FILE=\"${dir}/subtitles.ass\"\n"
            "cat > \"$SUBTITLE_FILE\" << 'ASSHEADEREOF'\n"
            "${assHeader}\n"
            "ASSHEADEREOF\n"
            "SUB_OFFSET=0\n\n"
            "SUBSCRIBE_SRC=\"${subscribeClip}\"\n"
            "SUBSCRIBE_NORMALIZED=\"${dir}/subscribe_normalized.mp4\"\n"
            "if [ ! -f \"$SUBSCRIBE_NORMALIZED\" ]; then\n"
            "  echo \"[$(date '+%H:%M:%S')] Chuan hoa clip subscribe cho khop ${W}x${H}@${FPS}fps\" | tee -a \"$PROGRESS_LOG\"\n"
            "  ffmpeg -y -hide_banner -loglevel error -i \"$SUBSCRIBE_SRC\" -vf \"scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=${FPS}\" -c:v libx264 -preset ${PRESET} -crf 18 -pix_fmt yuv420p -af \"volume=0.8\" -c:a aac -b:a 192k -ar 44100 -ac 2 \"$SUBSCRIBE_NORMALIZED\"\n"
            "fi\n"
            "`;\n\n"
            "let idx = 0;\n"
            "const processed = [];\n"
            "for (const scene of scenes) {\n"
            "  idx++;\n"
            "  const id = scene.sceneId;\n"
            "  const img = `scene_${id}_image.jpg`;\n"
            "  const audio = `scene_${id}_audio.wav`;\n"
            "  const out = `scene_${id}_clip.mp4`;\n"
            "  const filter = zoompanExpr(scene.camera);\n"
            "  const captionText = escapeForHeredoc(cleanCaption(scene.narration));\n"
            "  processed.push(out);\n\n"
            "  script += `\n"
            "echo \"[$(date '+%H:%M:%S')] BAT DAU scene ${idx}/${scenes.length} (id=${id}, camera=${scene.camera})\" | tee -a \"$PROGRESS_LOG\"\n\n"
            "AUDIO_DUR=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 \"${audio}\")\n"
            "DUR=$(awk -v d=\"$AUDIO_DUR\" 'BEGIN{printf \"%.2f\", d+0.6}')\n"
            "FRAMES=$(awk -v d=\"$DUR\" 'BEGIN{printf \"%d\", d*${FPS}}')\n\n"
            "if ! timeout ${SCENE_TIMEOUT_SEC}s ffmpeg -y -hide_banner -loglevel error -loop 1 -i \"${img}\" -i \"${audio}\" -filter_complex \"[0:v]scale=${WS}:${HS}:force_original_aspect_ratio=increase,crop=${WS}:${HS},setsar=1,${filter},scale=${W}:${H}:flags=lanczos[v]\" -map \"[v]\" -map 1:a -c:v libx264 -preset ${PRESET} -crf 18 -pix_fmt yuv420p -r ${FPS} -c:a aac -b:a 192k -ar 44100 -ac 2 -t \"$DUR\" \"${out}\"; then\n"
            "  echo \"[$(date '+%H:%M:%S')] !!! Scene ${id} loi hoac vuot qua ${SCENE_TIMEOUT_SEC}s\" | tee -a \"$PROGRESS_LOG\"\n"
            "  exit 1\n"
            "fi\n\n"
            "echo \"[$(date '+%H:%M:%S')] XONG scene ${idx}/${scenes.length}\" | tee -a \"$PROGRESS_LOG\"\n\n"
            "SUB_START=$(awk -v s=\"$SUB_OFFSET\" 'BEGIN{h=int(s/3600);m=int((s%3600)/60);sec=s-h*3600-m*60;printf \"%d:%02d:%05.2f\", h, m, sec}')\n"
            "SUB_END=$(awk -v s=\"$SUB_OFFSET\" -v d=\"$DUR\" 'BEGIN{e=s+d;h=int(e/3600);m=int((e%3600)/60);sec=e-h*3600-m*60;printf \"%d:%02d:%05.2f\", h, m, sec}')\n"
            "cat >> \"$SUBTITLE_FILE\" << SUBEOF\n"
            "Dialogue: 0,$SUB_START,$SUB_END,Default,,0,0,0,,${captionText}\n"
            "SUBEOF\n"
            "SUB_OFFSET=$(awk -v o=\"$SUB_OFFSET\" -v d=\"$DUR\" 'BEGIN{printf \"%.3f\", o+d}')\n"
            "`;\n"
            "}\n\n"
            "// FIX (dong bo tieng click voi animation subscribe): dung concat FILTER\n"
            "// (-filter_complex ... concat=n=N:v=1:a=1) thay vi concat DEMUXER (-f concat).\n"
            "// Demuxer concat roi re-encode lai TOAN BO co the lam lech PTS nhe o ranh gioi\n"
            "// giua cac doan (dac biet ro o doan cuoi - clip subscribe), vi no khong quan ly\n"
            "// timestamp tung input rieng biet trong 1 lan encode duy nhat nhu concat filter.\n"
            "//\n"
            "// Sau concat, chain them filter 'ass' de burn caption (subtitles.ass, da duoc\n"
            "// ghi day du sau vong for tren) dong bo voi giong doc. Dung filter 'ass' (khong\n"
            "// phai 'subtitles') vi file da la ASS voi PlayResX/PlayResY dung bang khung\n"
            "// hinh - khong can (va khong nen) truyen them original_size/force_style nua.\n"
            "const allClips = [...processed, 'subscribe_normalized.mp4'];\n"
            "const inputs = allClips.map(f => `-i \"${f}\"`).join(' ');\n"
            "let filterInputs = '';\n"
            "for (let i = 0; i < allClips.length; i++) filterInputs += `[${i}:v][${i}:a]`;\n"
            "const filterComplex = `${filterInputs}concat=n=${allClips.length}:v=1:a=1[concatv][outa];[concatv]ass=subtitles.ass[outv]`;\n\n"
            "script += `\n"
            "echo \"[$(date '+%H:%M:%S')] BAT DAU ghep video cuoi (concat filter + burn caption)\" | tee -a \"$PROGRESS_LOG\"\n\n"
            "if ! timeout ${SCENE_TIMEOUT_SEC}s ffmpeg -y -hide_banner -loglevel error ${inputs} -filter_complex \"${filterComplex}\" -map \"[outv]\" -map \"[outa]\" -c:v libx264 -preset ${PRESET} -crf 18 -pix_fmt yuv420p -r ${FPS} -c:a aac -b:a 192k -ar 44100 -ac 2 -movflags +faststart \"${videoId}_final.mp4\"; then\n"
            "  echo \"[$(date '+%H:%M:%S')] !!! Ghep video cuoi loi hoac vuot qua ${SCENE_TIMEOUT_SEC}s\" | tee -a \"$PROGRESS_LOG\"\n"
            "  exit 1\n"
            "fi\n\n"
            "echo \"[$(date '+%H:%M:%S')] DONE: ${dir}/${videoId}_final.mp4\" | tee -a \"$PROGRESS_LOG\"\n"
            "`;\n\n"
            "const buffer = Buffer.from(script, 'utf-8');\n\n"
            "return [{\n"
            "  json: {\n"
            "    videoId,\n"
            "    scriptPath: `${dir}/render_video.sh`,\n"
            "    finalVideoPath: `${dir}/${videoId}_final.mp4`,\n"
            "    progressLogPath: `${dir}/render_progress.log`\n"
            "  },\n"
            "  binary: { script: await this.helpers.prepareBinaryData(buffer, 'render_video.sh', 'text/x-shellscript') }\n"
            "}];"
        )
    },
    5144, Y_MAIN, type_version=2,
)

wf.node(
    "Write Render Script",
    "n8n-nodes-base.readWriteFile",
    {"operation": "write", "fileName": "={{ $json.scriptPath }}", "dataPropertyName": "script", "options": {}},
    5368, Y_MAIN,
)

wf.node(
    "Execute Render Script (ffmpeg)",
    "n8n-nodes-base.executeCommand",
    {"command": "=bash \"{{ $json.scriptPath }}\""},
    5592, Y_MAIN,
)

wf.link("Loop Over Scenes", "prepare storyboard.json", src_index=0)
wf.link("prepare storyboard.json", "Write storyboard.json")
wf.link("Write storyboard.json", "Build Render Script")
wf.link("Build Render Script", "Write Render Script")
wf.link("Write Render Script", "Execute Render Script (ffmpeg)")

print("module 4 (storyboard+render) nodes so far:", len(wf.nodes))

# ============================================================================
# MODULE 5 - THUMBNAIL + YOUTUBE UPLOAD
# ============================================================================
wf.node(
    "Build Thumbnail Image Query",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "let raw = $json.output;\n"
            "if (typeof raw === 'string') {\n"
            "  raw = raw.trim();\n"
            "  const fenceMatch = raw.match(/^```(?:json)?\\s*([\\s\\S]*?)\\s*```$/i);\n"
            "  if (fenceMatch) raw = fenceMatch[1];\n"
            "}\n\n"
            "let data;\n"
            "try {\n"
            "  data = JSON.parse(raw);\n"
            "} catch (e) {\n"
            "  throw new Error(`Research Agent output khong phai JSON hop le: ${e.message}`);\n"
            "}\n\n"
            "const gv = $('Generate Video ID').first().json;\n"
            "const thumbnailPath = $('Init Paths').first().json.thumbnailPath;\n"
            "const fallbackStock = gv.niche === 'tam_ly' ? 'calm lifestyle emotion background' : 'financial news thumbnail background';\n\n"
            "return {\n"
            "  json: {\n"
            "    videoId: gv.videoId,\n"
            "    niche: gv.niche,\n"
            "    title: data.title,\n"
            "    description: data.description,\n"
            "    tags: data.tags || [],\n"
            "    hashtags: data.hashtags || [],\n"
            "    thumbnailPath,\n"
            "    eventQuery: data.title,\n"
            "    stockQuery: fallbackStock\n"
            "  }\n"
            "};"
        )
    },
    2648, Y_MAIN + 296, type_version=2,
)

wf.node(
    "Tavily Image Search (Thumbnail)",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://api.tavily.com/search",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "tavilyApi",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ query: $('Build Thumbnail Image Query').first().json.eventQuery, "
            "search_depth: 'basic', include_images: true, include_image_descriptions: false, max_results: 3 }) }}"
        ),
        "options": {"timeout": 30000},
    },
    2872, Y_MAIN + 296,
    type_version=4.4,
    extra={"credentials": TAVILY_CRED},
)

wf.node(
    "Check Tavily Images (Thumbnail)",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "let imageUrl = null;\n\n"
            "if (Array.isArray($json.results)) {\n"
            "  for (const result of $json.results) {\n"
            "    if (Array.isArray(result.images) && result.images.length > 0) {\n"
            "      imageUrl = result.images.find(url => !url.includes('instagram.com') && !url.includes('lookaside.instagram.com'));\n"
            "      if (!imageUrl) imageUrl = result.images[0];\n"
            "      if (imageUrl) break;\n"
            "    }\n"
            "  }\n"
            "}\n\n"
            "if (!imageUrl && Array.isArray($json.images) && $json.images.length > 0) {\n"
            "  imageUrl = $json.images.find(url => !url.includes('instagram.com') && !url.includes('lookaside.instagram.com')) || $json.images[0];\n"
            "}\n\n"
            "const ctx = $('Build Thumbnail Image Query').first().json;\n\n"
            "return { json: { ...ctx, hasTavilyImage: !!imageUrl, tavilyImageUrl: imageUrl } };"
        )
    },
    3096, Y_MAIN + 296, type_version=2,
)

wf.node(
    "Has Tavily Image? (Thumbnail)",
    "n8n-nodes-base.if",
    {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 3},
            "conditions": [
                {"id": "cond2", "leftValue": "={{ $json.hasTavilyImage }}", "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}
            ],
            "combinator": "and",
        },
        "options": {},
    },
    3320, Y_MAIN + 296, type_version=2.3,
)

wf.node(
    "Download Thumbnail (Tavily)",
    "n8n-nodes-base.httpRequest",
    {"url": "={{ $json.tavilyImageUrl }}", "options": {"response": {"response": {"neverError": True, "responseFormat": "file"}}, "timeout": 12000}},
    3544, Y_MAIN + 224,
    type_version=4.4,
    # FIX: cung mot ly do voi Download Image (Tavily) o tren - ECONNABORTED/timeout
    # tu mot CDN cham/chet khong duoc neverError bat, phai dung onError de fallback
    # sang Pexels thay vi lam crash toan bo pipeline.
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "Validate Tavily Thumbnail",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "function getImageDimensions(buf) {\n"
            "  if (buf.length > 4 && buf[0] === 0xFF && buf[1] === 0xD8) {\n"
            "    let offset = 2;\n"
            "    while (offset + 9 < buf.length) {\n"
            "      if (buf[offset] !== 0xFF) { offset++; continue; }\n"
            "      const marker = buf[offset + 1];\n"
            "      if (marker >= 0xC0 && marker <= 0xC3) {\n"
            "        return { width: buf.readUInt16BE(offset + 7), height: buf.readUInt16BE(offset + 5) };\n"
            "      }\n"
            "      const segLength = buf.readUInt16BE(offset + 2);\n"
            "      offset += 2 + segLength;\n"
            "    }\n"
            "    return null;\n"
            "  }\n"
            "  if (buf.length > 24 && buf[0] === 0x89 && buf[1] === 0x50) {\n"
            "    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };\n"
            "  }\n"
            "  return null;\n"
            "}\n\n"
            "const MIN_DIMENSION = 720;\n\n"
            "// Lay scene tu node 'Check Tavily Images (Thumbnail)' - xem giai thich trong\n"
            "// Validate Tavily Image (cung fix ECONNABORTED/timeout + onError o Download\n"
            "// Thumbnail (Tavily) ben tren).\n"
            "const scene = $('Check Tavily Images (Thumbnail)').first().json;\n"
            "const binary = $input.item.binary && $input.item.binary.data;\n"
            "let isValid = false;\n\n"
            "if (binary) {\n"
            "  const buffer = await this.helpers.getBinaryDataBuffer(0, 'data');\n"
            "  const isJpeg = buffer.length > 4 && buffer[0] === 0xFF && buffer[1] === 0xD8;\n"
            "  const isPng = buffer.length > 8 && buffer[0] === 0x89 && buffer[1] === 0x50;\n"
            "  const isWebp = buffer.length > 12 && buffer.slice(8, 12).toString() === 'WEBP';\n"
            "  const dims = getImageDimensions(buffer);\n"
            "  const meetsResolution = isWebp ? true : (dims ? Math.min(dims.width, dims.height) >= MIN_DIMENSION : false);\n"
            "  isValid = buffer.length > 2000 && (isJpeg || isPng || isWebp) && meetsResolution;\n"
            "}\n\n"
            "return { json: { ...scene, tavilyImageValid: isValid }, binary: $input.item.binary };"
        )
    },
    3768, Y_MAIN + 224, type_version=2,
)

wf.node(
    "Is Tavily Thumbnail Valid?",
    "n8n-nodes-base.if",
    {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 3},
            "conditions": [
                {"id": "2cd49f0a-495f-4b38-b9fe-098b36e761da", "leftValue": "={{ $json.tavilyImageValid }}", "rightValue": "", "operator": {"type": "boolean", "operation": "true", "singleValue": True}}
            ],
            "combinator": "and",
        },
        "options": {},
    },
    3992, Y_MAIN + 224, type_version=2.3,
)

wf.node(
    "Pexels Image Search (Thumbnail)",
    "n8n-nodes-base.httpRequest",
    {
        "url": "=https://api.pexels.com/v1/search?query={{ encodeURIComponent($json.stockQuery) }}&orientation=portrait&per_page=5&size=large",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"timeout": 30000},
    },
    4216, Y_MAIN + 296,
    type_version=4.4,
    extra={"credentials": PEXELS_CRED},
)

wf.node(
    "Extract Pexels Image URL (Thumbnail)",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const MIN_DIMENSION = 720;\n"
            "const photos = $json.photos || [];\n"
            "const hq = photos.find(p => Math.min(p.width || 0, p.height || 0) >= MIN_DIMENSION);\n"
            "const photo = hq || photos[0];\n"
            "const imageUrl = photo && photo.src && (photo.src.large2x || photo.src.large || photo.src.original);\n\n"
            "const ctx = $('Check Tavily Images (Thumbnail)').first().json;\n\n"
            "if (!imageUrl) {\n"
            "  throw new Error('Pexels khong tra ve anh thumbnail phu hop cho query: ' + (ctx.stockQuery || ''));\n"
            "}\n\n"
            "return { json: { ...ctx, pexelsImageUrl: imageUrl } };"
        )
    },
    4440, Y_MAIN + 296, type_version=2,
)

wf.node(
    "Download Thumbnail (Pexels)",
    "n8n-nodes-base.httpRequest",
    {"url": "={{ $json.pexelsImageUrl }}", "options": {"response": {"response": {"responseFormat": "file"}}, "timeout": 30000}},
    4664, Y_MAIN + 296,
    type_version=4.4,
)

wf.node(
    "Write Thumbnail Background",
    "n8n-nodes-base.readWriteFile",
    {"operation": "write", "fileName": "={{ $('Check Tavily Images (Thumbnail)').first().json.thumbnailPath }}", "options": {}},
    4888, Y_MAIN + 224,
)

wf.node(
    "Merge Video + Thumbnail",
    "n8n-nodes-base.merge",
    {"mode": "combine", "combineBy": "combineByPosition", "options": {}},
    5816, Y_MAIN, type_version=3,
)

wf.node(
    "Prepare YouTube Metadata",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const fs = require('fs');\n"
            "const videoData = $('Build Render Script').first().json;\n"
            "const thumbCtx = $('Build Thumbnail Image Query').first().json;\n"
            "const thumbnailPath = $('Init Paths').first().json.thumbnailPath;\n\n"
            "const hashtags = (thumbCtx.hashtags || []).map((h) => (h.startsWith('#') ? h : `#${h}`));\n"
            "const description = [thumbCtx.description || '', hashtags.join(' ')].filter(Boolean).join('\\n\\n');\n\n"
            "// fileSize duoc tinh 1 lan o day (dung chung cho ca nhanh Facebook Reels va\n"
            "// TikTok ben duoi - ca hai deu can biet chinh xac so byte de upload).\n"
            "const fileSize = fs.statSync(videoData.finalVideoPath).size;\n\n"
            "return [{\n"
            "  json: {\n"
            "    videoId: videoData.videoId,\n"
            "    niche: thumbCtx.niche,\n"
            "    finalVideoPath: videoData.finalVideoPath,\n"
            "    fileSize,\n"
            "    thumbnailPath,\n"
            "    title: thumbCtx.title,\n"
            "    description,\n"
            "    tags: thumbCtx.tags\n"
            "  }\n"
            "}];"
        )
    },
    6040, Y_MAIN, type_version=2,
)

wf.node(
    "Read Final Video File",
    "n8n-nodes-base.readWriteFile",
    {"fileSelector": "={{ $json.finalVideoPath }}", "options": {}},
    6264, Y_MAIN,
)

wf.node(
    "Upload Video To YouTube",
    "n8n-nodes-base.youTube",
    {
        "resource": "video",
        "operation": "upload",
        "title": "={{ $('Prepare YouTube Metadata').first().json.title }}",
        "regionCode": "VN",
        "categoryId": "={{ $('Prepare YouTube Metadata').first().json.niche === 'tam_ly' ? '22' : '25' }}",
        "options": {
            "description": "={{ $('Prepare YouTube Metadata').first().json.description }}",
            "privacyStatus": "private",
            "tags": "={{ ($('Prepare YouTube Metadata').first().json.tags || []).join(',') }}",
        },
    },
    6488, Y_MAIN,
    extra={"credentials": YOUTUBE_CRED},
)

wf.node(
    "Read Thumbnail File",
    "n8n-nodes-base.readWriteFile",
    {"fileSelector": "={{ $('Prepare YouTube Metadata').first().json.thumbnailPath }}", "options": {}},
    6712, Y_MAIN,
)

wf.node(
    "Set YouTube Thumbnail",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "=https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={{ $('Upload Video To YouTube').first().json.id }}",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "youTubeOAuth2Api",
        "sendHeaders": True,
        "headerParameters": {"parameters": [{"name": "Content-Type", "value": "={{ $binary.data.mimeType }}"}]},
        "sendBody": True,
        "contentType": "binaryData",
        "inputDataFieldName": "data",
        "options": {},
    },
    6936, Y_MAIN,
    type_version=4.4,
    extra={"credentials": YOUTUBE_CRED},
)

# ============================================================================
# MODULE 6 - DANG THEM LEN FACEBOOK REELS + TIKTOK (song song voi YouTube)
# ============================================================================
wf.sticky(
    "## DANG THEM FACEBOOK REELS + TIKTOK (2026-07-27)\n\n"
    "Ca 2 nhanh nay chay SONG SONG voi nhanh YouTube (deu bat dau tu 'Prepare\n"
    "YouTube Metadata'), va deu dung onError=continueRegularOutput tren MOI\n"
    "node - neu Facebook hoac TikTok loi (token het han, rate limit, v.v.) thi\n"
    "CHI nhanh do bi anh huong, KHONG lam crash ca video/ca ngay chay.\n\n"
    "FACEBOOK: can Page Access Token (dan vao FB_ACCESS_TOKEN trong Load\n"
    "Config) + FB_PAGE_ID (da dien san). Luu y: token nguoi dung dan vao chat\n"
    "TRUOC DAY DA BI LO - PHAI xoay vong (rotate) token moi truoc khi dung.\n\n"
    "TIKTOK: client_key/client_secret KHONG du de dang video - TikTok bat\n"
    "buoc phai co access_token/refresh_token cua NGUOI DUNG THAT qua man hinh\n"
    "dong y OAuth. Chay 1 LAN DUY NHAT script `tiktok_oauth_setup.py` (dung\n"
    "trang callback tinh docs/tiktok-callback.html tren GitHub Pages - khong\n"
    "can ngrok/server local) de tao ra tiktok_tokens.json. Workflow se tu dong\n"
    "REFRESH token truoc moi lan dang (khong can lam lai buoc OAuth thu cong\n"
    "nay nua tru khi refresh_token het han sau 365 ngay). App unaudited -> chi\n"
    "dang duoc SELF_ONLY (rieng tu) - doi TIKTOK_PRIVACY_LEVEL trong Load\n"
    "Config sau khi TikTok duyet app de dang cong khai.",
    6040, Y_MAIN - 480, w=560, h=380,
)

wf.node(
    "FB: Start Upload",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://graph.facebook.com/v21.0/{{ $('Load Config').first().json.FB_PAGE_ID }}/video_reels",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ upload_phase: 'start', access_token: $('Load Config').first().json.FB_ACCESS_TOKEN }) }}",
        "options": {"timeout": 30000},
    },
    6264, Y_MAIN + 240,
    type_version=4.4,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "FB: Read Video File",
    "n8n-nodes-base.readWriteFile",
    {"fileSelector": "={{ $('Prepare YouTube Metadata').first().json.finalVideoPath }}", "options": {}},
    6488, Y_MAIN + 240,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "FB: Upload Video",
    "n8n-nodes-base.httpRequest",
    {
        "method": "PUT",
        "url": "={{ $('FB: Start Upload').first().json.upload_url }}",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "Authorization", "value": "=OAuth {{ $('Load Config').first().json.FB_ACCESS_TOKEN }}"},
                {"name": "offset", "value": "0"},
                {"name": "file_size", "value": "={{ $('Prepare YouTube Metadata').first().json.fileSize }}"},
            ]
        },
        "sendBody": True,
        "contentType": "binaryData",
        "inputDataFieldName": "data",
        "options": {"timeout": 120000},
    },
    6712, Y_MAIN + 240,
    type_version=4.4,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "FB: Publish Reel",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://graph.facebook.com/v21.0/{{ $('Load Config').first().json.FB_PAGE_ID }}/video_reels",
        "sendQuery": True,
        "queryParameters": {
            "parameters": [
                {"name": "access_token", "value": "={{ $('Load Config').first().json.FB_ACCESS_TOKEN }}"},
                {"name": "video_id", "value": "={{ $('FB: Start Upload').first().json.video_id }}"},
                {"name": "upload_phase", "value": "finish"},
                {"name": "video_state", "value": "PUBLISHED"},
                {"name": "description", "value": "={{ $('Prepare YouTube Metadata').first().json.description }}"},
            ]
        },
        "options": {"timeout": 30000},
    },
    6936, Y_MAIN + 240,
    type_version=4.4,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Load Tokens",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const fs = require('fs');\n"
            "const cfg = $('Load Config').first().json;\n"
            "if (!fs.existsSync(cfg.TIKTOK_TOKENS_FILE)) {\n"
            "  throw new Error('Chua co tiktok_tokens.json - chay 1 lan `python tiktok_oauth_setup.py` truoc (xem huong dan trong file do).');\n"
            "}\n"
            "const tokens = JSON.parse(fs.readFileSync(cfg.TIKTOK_TOKENS_FILE, 'utf-8'));\n"
            "return [{ json: tokens }];"
        )
    },
    6264, Y_MAIN + 480, type_version=2,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Refresh Token",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://open.tiktokapis.com/v2/oauth/token/",
        "sendBody": True,
        "contentType": "form-urlencoded",
        "bodyParameters": {
            "parameters": [
                {"name": "client_key", "value": "={{ $('Load Config').first().json.TIKTOK_CLIENT_KEY }}"},
                {"name": "client_secret", "value": "={{ $('Load Config').first().json.TIKTOK_CLIENT_SECRET }}"},
                {"name": "grant_type", "value": "refresh_token"},
                {"name": "refresh_token", "value": "={{ $('TikTok: Load Tokens').first().json.refresh_token }}"},
            ]
        },
        "options": {"timeout": 20000},
    },
    6488, Y_MAIN + 480,
    type_version=4.4,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Save New Tokens",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const fs = require('fs');\n"
            "const cfg = $('Load Config').first().json;\n"
            "const t = $json;\n"
            "if (!t.access_token) {\n"
            "  throw new Error('TikTok refresh token that bai: ' + JSON.stringify(t).slice(0, 300));\n"
            "}\n"
            "fs.writeFileSync(cfg.TIKTOK_TOKENS_FILE, JSON.stringify({\n"
            "  access_token: t.access_token,\n"
            "  refresh_token: t.refresh_token,\n"
            "  open_id: t.open_id,\n"
            "  obtained_at: new Date().toISOString()\n"
            "}, null, 2));\n"
            "return [{ json: t }];"
        )
    },
    6712, Y_MAIN + 480, type_version=2,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Prepare Upload Info",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const fs = require('fs');\n"
            "const finalVideoPath = $('Prepare YouTube Metadata').first().json.finalVideoPath;\n"
            "const video_size = fs.statSync(finalVideoPath).size;\n"
            "return [{ json: { video_size } }];"
        )
    },
    6936, Y_MAIN + 480, type_version=2,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Init Upload",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://open.tiktokapis.com/v2/post/publish/video/init/",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "Authorization", "value": "=Bearer {{ $('TikTok: Save New Tokens').first().json.access_token }}"},
                {"name": "Content-Type", "value": "application/json; charset=UTF-8"},
            ]
        },
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ post_info: { title: $('Prepare YouTube Metadata').first().json.title, "
            "privacy_level: $('Load Config').first().json.TIKTOK_PRIVACY_LEVEL, disable_duet: false, "
            "disable_comment: false, disable_stitch: false }, source_info: { source: 'FILE_UPLOAD', "
            "video_size: $('TikTok: Prepare Upload Info').first().json.video_size, "
            "chunk_size: $('TikTok: Prepare Upload Info').first().json.video_size, total_chunk_count: 1 } }) }}"
        ),
        "options": {"timeout": 20000},
    },
    7160, Y_MAIN + 480,
    type_version=4.4,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Read Video File",
    "n8n-nodes-base.readWriteFile",
    {"fileSelector": "={{ $('Prepare YouTube Metadata').first().json.finalVideoPath }}", "options": {}},
    7384, Y_MAIN + 480,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Upload Video",
    "n8n-nodes-base.httpRequest",
    {
        "method": "PUT",
        "url": "={{ $('TikTok: Init Upload').first().json.data.upload_url }}",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "Content-Type", "value": "video/mp4"},
                {"name": "Content-Range", "value": "=bytes 0-{{ $('TikTok: Prepare Upload Info').first().json.video_size - 1 }}/{{ $('TikTok: Prepare Upload Info').first().json.video_size }}"},
                {"name": "Content-Length", "value": "={{ $('TikTok: Prepare Upload Info').first().json.video_size }}"},
            ]
        },
        "sendBody": True,
        "contentType": "binaryData",
        "inputDataFieldName": "data",
        "options": {"timeout": 120000},
    },
    7608, Y_MAIN + 480,
    type_version=4.4,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "TikTok: Check Status",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
        "sendHeaders": True,
        "headerParameters": {
            "parameters": [
                {"name": "Authorization", "value": "=Bearer {{ $('TikTok: Save New Tokens').first().json.access_token }}"},
                {"name": "Content-Type", "value": "application/json; charset=UTF-8"},
            ]
        },
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ publish_id: $('TikTok: Init Upload').first().json.data.publish_id }) }}",
        "options": {"timeout": 20000},
    },
    7832, Y_MAIN + 480,
    type_version=4.4,
    extra={"onError": "continueRegularOutput"},
)

wf.node(
    "Merge Social Uploads",
    "n8n-nodes-base.merge",
    {"mode": "combine", "combineBy": "combineByPosition", "numberInputs": 3, "options": {}},
    8056, Y_MAIN, type_version=3,
)

wf.link("Research Agent", "Build Thumbnail Image Query")
wf.link("Build Thumbnail Image Query", "Tavily Image Search (Thumbnail)")
wf.link("Tavily Image Search (Thumbnail)", "Check Tavily Images (Thumbnail)")
wf.link("Check Tavily Images (Thumbnail)", "Has Tavily Image? (Thumbnail)")
wf.link("Has Tavily Image? (Thumbnail)", "Download Thumbnail (Tavily)", src_index=0)
wf.link("Has Tavily Image? (Thumbnail)", "Pexels Image Search (Thumbnail)", src_index=1)
wf.link("Download Thumbnail (Tavily)", "Validate Tavily Thumbnail")
wf.link("Validate Tavily Thumbnail", "Is Tavily Thumbnail Valid?")
wf.link("Is Tavily Thumbnail Valid?", "Write Thumbnail Background", src_index=0)
wf.link("Is Tavily Thumbnail Valid?", "Pexels Image Search (Thumbnail)", src_index=1)
wf.link("Pexels Image Search (Thumbnail)", "Extract Pexels Image URL (Thumbnail)")
wf.link("Extract Pexels Image URL (Thumbnail)", "Download Thumbnail (Pexels)")
wf.link("Download Thumbnail (Pexels)", "Write Thumbnail Background")
wf.link("Write Thumbnail Background", "Merge Video + Thumbnail", dst_index=1)
wf.link("Execute Render Script (ffmpeg)", "Merge Video + Thumbnail", dst_index=0)
wf.link("Merge Video + Thumbnail", "Prepare YouTube Metadata")
wf.link("Prepare YouTube Metadata", "Read Final Video File")
wf.link("Read Final Video File", "Upload Video To YouTube")
wf.link("Upload Video To YouTube", "Read Thumbnail File")
wf.link("Read Thumbnail File", "Set YouTube Thumbnail")

wf.link("Prepare YouTube Metadata", "FB: Start Upload")
wf.link("FB: Start Upload", "FB: Read Video File")
wf.link("FB: Read Video File", "FB: Upload Video")
wf.link("FB: Upload Video", "FB: Publish Reel")

wf.link("Prepare YouTube Metadata", "TikTok: Load Tokens")
wf.link("TikTok: Load Tokens", "TikTok: Refresh Token")
wf.link("TikTok: Refresh Token", "TikTok: Save New Tokens")
wf.link("TikTok: Save New Tokens", "TikTok: Prepare Upload Info")
wf.link("TikTok: Prepare Upload Info", "TikTok: Init Upload")
wf.link("TikTok: Init Upload", "TikTok: Read Video File")
wf.link("TikTok: Read Video File", "TikTok: Upload Video")
wf.link("TikTok: Upload Video", "TikTok: Check Status")

wf.link("Set YouTube Thumbnail", "Merge Social Uploads", dst_index=0)
wf.link("FB: Publish Reel", "Merge Social Uploads", dst_index=1)
wf.link("TikTok: Check Status", "Merge Social Uploads", dst_index=2)
wf.link("Merge Social Uploads", "Loop Over Headlines")

print("TOTAL nodes:", len(wf.nodes))

with open("n8n_workflow_shorts.json", "w", encoding="utf-8") as f:
    json.dump(wf.export(), f, ensure_ascii=False, indent=2)
print("wrote n8n_workflow_shorts.json")





