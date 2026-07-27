#!/usr/bin/env python3
"""
Generator for the "AI/Tech Premium Shorts" n8n pipeline.

Why a generator script (instead of hand-written JSON)?
- The workflow has 60+ nodes across 11 modules; generating it programmatically
  guarantees valid JSON, unique ids, and consistent wiring.
- Mirrors the repo convention already established by fix_workflow.py (script
  owns the JSON, not a human hand-editing giant files).
- To change a module later: edit the relevant section below and re-run:
      .venv/bin/python generate_premium_workflow.py

Outputs:
  n8n_workflow_premium.json    -> main daily content pipeline (modules 1-10)
  n8n_workflow_analytics.json  -> independent analytics + learnings feedback (module 11)
"""
import json
import uuid


def nid():
    return str(uuid.uuid4())


class Workflow:
    def __init__(self):
        self.nodes = []
        self.connections = {}
        self.by_name = {}

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
        self.by_name[name] = n
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

    def model(self, modelName, agentName):
        self.link(modelName, agentName, otype="ai_languageModel")

    def tool(self, toolName, agentName):
        self.link(toolName, agentName, otype="ai_tool")

    def memory(self, memName, agentName):
        self.link(memName, agentName, otype="ai_memory")

    def export(self):
        return {"nodes": self.nodes, "connections": self.connections, "pinData": {}, "meta": {"instanceId": "premium-ai-shorts-pipeline"}}


wf = Workflow()

# credential placeholders - user MUST reselect these in n8n UI after import
OLLAMA_CRED = {"ollamaApi": {"id": "REPLACE_ME", "name": "Ollama account"}}
TAVILY_HEADER_CRED = {"httpHeaderAuth": {"id": "REPLACE_ME", "name": "Tavily API Key (Bearer)"}}
YOUTUBE_CRED = {"youTubeOAuth2Api": {"id": "REPLACE_ME", "name": "YouTube account"}}
TIKTOK_HEADER_CRED = {"httpHeaderAuth": {"id": "REPLACE_ME", "name": "TikTok Content Posting API"}}
FACEBOOK_HEADER_CRED = {"httpHeaderAuth": {"id": "REPLACE_ME", "name": "Facebook Graph API"}}

Y_MAIN = 1000
Y_MODEL = 1260
Y_LOOP = 1560
Y_LOOP2 = 1680

# ============================================================================
# MODULE 1 - TREND RESEARCH
# ============================================================================
wf.sticky(
    "## MODULE 1 - TREND RESEARCH\n\n"
    "Sources: Google Trends, Google News, YouTube, Reddit, GitHub Trending,\n"
    "Product Hunt, OpenAI blog, Anthropic blog, Google AI blog (all via Tavily).\n\n"
    "Ranks candidates by Virality / Search Interest / Novelty / Educational\n"
    "Value / Long-term Search Potential. Selects exactly ONE topic.",
    -6200, 760, w=520, h=280,
)

wf.node(
    "Schedule Trigger",
    "n8n-nodes-base.scheduleTrigger",
    {"rule": {"interval": [{"triggerAtHour": 6}]}},
    -6200, Y_MAIN,
)

wf.node(
    "Load Config & Learnings",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const fs = require('fs');\n"
            "const path = require('path');\n\n"
            "// ==== EDIT THESE FOR YOUR MACHINE ====\n"
            "const BASE_DIR = process.env.AI_SHORTS_BASE_DIR || '/Users/tuht1/ai-shorts-videos';\n"
            "const VIETTTS_URL = process.env.VIETTTS_URL || 'http://127.0.0.1:8002/tts';\n"
            "const NICHE = ['Artificial Intelligence','Automation','Software','Programming',\n"
            "  'AI Tools','Productivity','Tech News','LLMs','Open Source AI'];\n"
            "const PLATFORMS = ['tiktok','youtube_shorts','facebook_reels'];\n"
            "// =======================================\n\n"
            "fs.mkdirSync(BASE_DIR, { recursive: true });\n"
            "fs.mkdirSync(path.join(BASE_DIR, 'assets', 'bgm'), { recursive: true });\n"
            "fs.mkdirSync(path.join(BASE_DIR, 'assets', 'sfx'), { recursive: true });\n"
            "fs.mkdirSync(path.join(BASE_DIR, 'analytics'), { recursive: true });\n\n"
            "// Module 11 (Analytics) writes this file; Module 1 reads it so today's\n"
            "// research is informed by what actually performed well recently.\n"
            "const learningsPath = path.join(BASE_DIR, 'analytics', 'learnings.json');\n"
            "let learnings = { topPerformingTopics: [], topPerformingHooks: [], avoid: [] };\n"
            "try {\n"
            "  if (fs.existsSync(learningsPath)) learnings = JSON.parse(fs.readFileSync(learningsPath, 'utf8'));\n"
            "} catch (e) { /* first run, no learnings yet */ }\n\n"
            "const now = new Date();\n"
            "return [{\n"
            "  json: {\n"
            "    BASE_DIR, VIETTTS_URL, NICHE, PLATFORMS, learnings,\n"
            "    today: now.toISOString().slice(0, 10)\n"
            "  }\n"
            "}];"
        )
    },
    -5950, Y_MAIN, type_version=2,
)

wf.sticky(
    "## RELIABILITY NOTE\n\n"
    "Modules 1-2 used to run Tavily as an AI-tool inside an autonomous agent\n"
    "(ReAct loop). With small local Ollama models that loop was unreliable -\n"
    "it repeatedly hit 'Max iterations reached' instead of answering, even\n"
    "after raising maxIterations and tuning the prompt. Redesigned to be\n"
    "DETERMINISTIC instead: a Code node builds the query, a plain HTTP Request\n"
    "node calls the Tavily REST API directly (no agent, no tool, no loop),\n"
    "then a tool-free LLM call (same pattern already proven reliable for the\n"
    "Script/Storyboard/Visual Director/SEO steps) synthesizes the JSON.",
    -5750, 700, w=520, h=300,
)

wf.node(
    "Build Trend Search Query",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "// One well-scoped Tavily query covering every requested source, rather than\n"
            "// letting an agent decide (unreliable with small local models - see sticky note).\n"
            "const niche = ($json.NICHE || []).join(', ');\n"
            "const query = 'Trending in the last 3 days about ' + niche + ': '\n"
            "  + 'Google Trends breakout topics, Google News headlines, popular YouTube videos, '\n"
            "  + 'top Reddit discussions, GitHub Trending repositories, Product Hunt launches, '\n"
            "  + 'and official OpenAI, Anthropic, Google AI blog announcements.';\n"
            "return [{ json: { ...$json, trendQuery: query } }];"
        )
    },
    -5700, Y_MAIN, type_version=2,
)

wf.node(
    "Tavily Search (Trend)",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://api.tavily.com/search",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ query: $json.trendQuery, topic: 'news', search_depth: 'advanced', "
            "days: 3, max_results: 10, include_answer: false }) }}"
        ),
        "options": {"timeout": 30000},
    },
    -5500, Y_MAIN,
    type_version=4.4,
    extra={"credentials": TAVILY_HEADER_CRED},
)

wf.node(
    "Parse Trend Search Results",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const prev = $('Build Trend Search Query').first().json;\n"
            "const results = $json.results || [];\n"
            "const digest = results.slice(0, 10).map((r, i) =>\n"
            "  (i + 1) + '. ' + r.title + '\\n   URL: ' + r.url + '\\n   ' + (r.content || '').slice(0, 300)\n"
            ").join('\\n\\n');\n\n"
            "return [{ json: { ...prev, trendSearchDigest: digest || 'Khong co ket qua tim kiem.' } }];"
        )
    },
    -5300, Y_MAIN, type_version=2,
)

wf.node(
    "Ollama Chat Model (Trend Synthesis)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": "qwen2.5:14b", "options": {"format": "json"}},
    -5100, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Trend Synthesis Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Bạn là Trend Researcher cho kênh Shorts công nghệ (AI, Automation, "
            "Software, Programming, AI Tools, Productivity, Tech News, LLMs, Open Source AI), "
            "đăng trên TikTok / YouTube Shorts / Facebook Reels.\n\n"
            "Ngày hôm nay: {{ $json.today }}\n"
            "Chủ đề đã dùng gần đây (TRÁNH lặp lại): {{ JSON.stringify($json.learnings.avoid) }}\n"
            "Chủ đề/hook từng hiệu quả tốt (tham khảo phong cách, KHÔNG copy nguyên): "
            "{{ JSON.stringify($json.learnings.topPerformingTopics) }}\n\n"
            "Kết quả tìm kiếm Tavily (Google Trends/News/YouTube/Reddit/GitHub Trending/"
            "Product Hunt/OpenAI/Anthropic/Google AI blogs) trong 72 giờ qua:\n"
            "{{ $json.trendSearchDigest }}\n\n"
            "Dựa CHỈ vào kết quả tìm kiếm trên (không bịa thêm), chọn ra ĐÚNG 5 chủ đề tiềm "
            "năng nhất, mỗi chủ đề chấm điểm 1-10 trên 5 tiêu chí: virality, search_interest, "
            "novelty, educational_value, long_term_search_potential. Tính tổng điểm và SẮP XẾP "
            "giảm dần. Chọn ứng viên có tổng điểm cao nhất làm selected_topic. source_urls PHẢI "
            "là URL thật lấy từ kết quả tìm kiếm ở trên.\n\n"
            "Output CHỈ JSON, không markdown, không giải thích, đúng schema:\n"
            "{\n"
            '  "candidates": [\n'
            "    {\n"
            '      "topic": "",\n'
            '      "why_now": "",\n'
            '      "source_urls": [""],\n'
            '      "scores": {"virality":0,"search_interest":0,"novelty":0,"educational_value":0,"long_term_search_potential":0},\n'
            '      "total_score": 0\n'
            "    }\n"
            "  ],\n"
            '  "selected_topic": {\n'
            '    "topic": "",\n'
            '    "why_now": "",\n'
            '    "source_urls": [""]\n'
            "  }\n"
            "}"
        ),
        "options": {},
    },
    -4900, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (Trend Synthesis)", "Trend Synthesis Agent")

wf.node(
    "Select Top Topic",
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
            "  throw new Error('Trend Synthesis Agent khong tra ve JSON hop le: ' + String($json.output).slice(0, 300));\n"
            "}\n\n"
            "if (!data.candidates || !Array.isArray(data.candidates) || data.candidates.length === 0) {\n"
            "  throw new Error('Trend Synthesis Agent thieu field candidates[]');\n"
            "}\n"
            "if (data.candidates.length > 5) data.candidates = data.candidates.slice(0, 5);\n\n"
            "const ranked = data.candidates.slice().sort((a, b) => (b.total_score || 0) - (a.total_score || 0));\n"
            "const top = data.selected_topic && data.selected_topic.topic ? data.selected_topic : ranked[0];\n\n"
            "const cfg = $('Load Config & Learnings').first().json;\n"
            "return [{\n"
            "  json: {\n"
            "    ...cfg,\n"
            "    candidates: ranked,\n"
            "    topic: top.topic,\n"
            "    whyNow: top.why_now,\n"
            "    topicSourceUrls: top.source_urls || []\n"
            "  }\n"
            "}];"
        )
    },
    -4700, Y_MAIN, type_version=2,
)

# ============================================================================
# MODULE 2 - DEEP RESEARCH
# ============================================================================
wf.sticky(
    "## MODULE 2 - DEEP RESEARCH\n\n"
    "Collects facts, stats, official docs and real announcements for the\n"
    "selected topic. Every fact must carry a source URL. No invented info.\n"
    "Fails the run if fewer than 3 sourced facts are found. Same deterministic\n"
    "search-then-synthesize pattern as Module 1 (no agent/tool loop).",
    -4500, 760, w=480, h=280,
)

wf.node(
    "Build Deep Research Query",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const query = 'Facts, statistics, official announcements, documentation and best "
            "practices about: ' + $json.topic + '. Context: ' + $json.whyNow;\n"
            "return [{ json: { ...$json, deepQuery: query } }];"
        )
    },
    -4450, Y_MAIN, type_version=2,
)

wf.node(
    "Tavily Search (Deep Research)",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://api.tavily.com/search",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ query: $json.deepQuery, search_depth: 'advanced', "
            "max_results: 10, include_answer: false }) }}"
        ),
        "options": {"timeout": 30000},
    },
    -4250, Y_MAIN,
    type_version=4.4,
    extra={"credentials": TAVILY_HEADER_CRED},
)

wf.node(
    "Parse Deep Research Results",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const prev = $('Build Deep Research Query').first().json;\n"
            "const results = $json.results || [];\n"
            "const digest = results.slice(0, 10).map((r, i) =>\n"
            "  (i + 1) + '. ' + r.title + '\\n   URL: ' + r.url + '\\n   ' + (r.content || '').slice(0, 400)\n"
            ").join('\\n\\n');\n\n"
            "return [{ json: { ...prev, deepSearchDigest: digest || 'Khong co ket qua tim kiem.' } }];"
        )
    },
    -4050, Y_MAIN, type_version=2,
)

wf.node(
    "Ollama Chat Model (Deep Synthesis)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": "qwen2.5:14b", "options": {"format": "json"}},
    -3850, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Deep Research Synthesis Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Bạn là Fact Researcher nghiêm ngặt. Chủ đề: {{ $json.topic }}\n"
            "Bối cảnh: {{ $json.whyNow }}\n\n"
            "Kết quả tìm kiếm Tavily (số liệu, ví dụ, thông báo, tài liệu chính thức):\n"
            "{{ $json.deepSearchDigest }}\n\n"
            "Dựa CHỈ vào kết quả tìm kiếm ở trên để trích xuất: số liệu thật, ví dụ thật, phát "
            "biểu/thông báo chính thức, tài liệu kỹ thuật chính thức, best practice được công "
            "nhận. TUYỆT ĐỐI không suy diễn, không bịa số liệu, không dùng tin giật gân/chưa xác "
            "thực. Mỗi fact PHẢI có source_url thật lấy từ kết quả tìm kiếm ở trên (không bịa URL).\n\n"
            "Output CHỈ JSON, đúng schema:\n"
            "{\n"
            '  "facts": [ {"fact": "", "source_url": "", "source_name": ""} ],\n'
            '  "official_docs": [ {"title": "", "url": ""} ],\n'
            '  "real_example": {"description": "", "source_url": ""},\n'
            '  "best_practices": [""],\n'
            '  "key_takeaway": ""\n'
            "}"
        ),
        "options": {},
    },
    -3650, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (Deep Synthesis)", "Deep Research Synthesis Agent")

wf.node(
    "Validate Facts",
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
            "  throw new Error('Deep Research Agent khong tra ve JSON hop le.');\n"
            "}\n\n"
            "const facts = (data.facts || []).filter(f => f.fact && f.source_url);\n"
            "if (facts.length < 3) {\n"
            "  throw new Error('Deep Research: chi tim duoc ' + facts.length + ' fact co nguon (can >= 3). Dung, khong bia so lieu.');\n"
            "}\n\n"
            "const prev = $('Select Top Topic').first().json;\n"
            "return [{\n"
            "  json: {\n"
            "    ...prev,\n"
            "    facts,\n"
            "    officialDocs: data.official_docs || [],\n"
            "    realExample: data.real_example || {},\n"
            "    bestPractices: data.best_practices || [],\n"
            "    keyTakeaway: data.key_takeaway || ''\n"
            "  }\n"
            "}];"
        )
    },
    -4450, Y_MAIN, type_version=2,
)

# ============================================================================
# MODULE 3 - SCRIPT WRITER
# ============================================================================
wf.sticky(
    "## MODULE 3 - SCRIPT WRITER\n\n"
    "Hook / Problem / Explanation / Real Example / Key Takeaway / CTA.\n"
    "Max 170 words. Conversational Vietnamese. No repeated ideas.\n"
    "Validated for word count + required structure before continuing.",
    -4250, 760, w=480, h=260,
)

wf.node(
    "Ollama Chat Model (Script)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": "qwen2.5:14b", "options": {"format": "json"}},
    -4200, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Script Writer Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Bạn là Senior Scriptwriter cho kênh Shorts công nghệ premium (không mass-produced). "
            "Văn phong tự nhiên, đời thường, tiếng Việt hội thoại - như một creator am hiểu đang "
            "nói chuyện với bạn, KHÔNG phải giọng đọc báo cáo hay AI máy móc.\n\n"
            "Chủ đề: {{ $json.topic }}\n"
            "Facts (PHẢI dùng, không bịa thêm): {{ JSON.stringify($json.facts) }}\n"
            "Ví dụ thật: {{ JSON.stringify($json.realExample) }}\n"
            "Best practices: {{ JSON.stringify($json.bestPractices) }}\n"
            "Key takeaway gợi ý: {{ $json.keyTakeaway }}\n\n"
            "Viết script theo ĐÚNG cấu trúc 6 phần, liền mạch, không lặp ý:\n"
            "1. Hook (3 giây đầu - phải tạo tò mò NGAY LẬP TỨC, có thể là câu hỏi gây sốc, "
            "số liệu bất ngờ, hoặc mâu thuẫn nhận thức)\n"
            "2. Problem (vấn đề khán giả đang gặp liên quan đến chủ đề)\n"
            "3. Explanation (giải thích ngắn gọn, dễ hiểu)\n"
            "4. Real Example (dẫn ví dụ/case thật từ facts đã research)\n"
            "5. Key Takeaway (bài học/insight đúc kết)\n"
            "6. CTA (kêu gọi hành động tự nhiên: theo dõi/thử/bình luận - không sáo rỗng)\n\n"
            "RÀNG BUỘC BẮT BUỘC: toàn bộ full_script tối đa 170 từ. Mỗi câu phải có giá trị, "
            "không câu nào thừa hay lặp ý câu khác.\n\n"
            "Output CHỈ JSON, đúng schema:\n"
            "{\n"
            '  "hook": "", "problem": "", "explanation": "", "real_example": "",\n'
            '  "key_takeaway": "", "cta": "",\n'
            '  "full_script": "",\n'
            '  "word_count": 0\n'
            "}"
        ),
        "options": {},
    },
    -3950, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (Script)", "Script Writer Agent")

wf.node(
    "Validate Script",
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
            "  throw new Error('Script Writer Agent khong tra ve JSON hop le.');\n"
            "}\n\n"
            "const required = ['hook','problem','explanation','real_example','key_takeaway','cta','full_script'];\n"
            "for (const k of required) {\n"
            "  if (!data[k] || !String(data[k]).trim()) throw new Error('Script thieu phan: ' + k);\n"
            "}\n\n"
            "const words = String(data.full_script).trim().split(/\\s+/).filter(Boolean);\n"
            "if (words.length > 170) {\n"
            "  throw new Error('Script vuot qua 170 tu (dang co ' + words.length + ' tu). Yeu cau Script Writer Agent rut gon.');\n"
            "}\n\n"
            "const prev = $('Validate Facts').first().json;\n"
            "return [{\n"
            "  json: {\n"
            "    ...prev,\n"
            "    script: { ...data, word_count: words.length }\n"
            "  }\n"
            "}];"
        )
    },
    -3700, Y_MAIN, type_version=2,
)

# ============================================================================
# MODULE 4 - STORYBOARD PLANNING
# ============================================================================
wf.sticky(
    "## MODULE 4 - STORYBOARD\n\n"
    "Splits the script into 5-8 dynamic scenes (45-70s total). Each scene:\n"
    "duration, narration, subtitle, visual_description, camera_motion,\n"
    "transition, emotion, text_overlay, animation_suggestion.",
    -3500, 760, w=480, h=260,
)

wf.node(
    "Ollama Chat Model (Storyboard)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": "qwen2.5:14b", "options": {"format": "json"}},
    -3450, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Storyboard Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Bạn là Senior Storyboard Director cho video dọc 9:16, 1080x1920, dài 45-70 giây, "
            "đăng TikTok / YouTube Shorts / Facebook Reels. Nhịp độ phải NĂNG ĐỘNG nhưng KHÔNG hỗn loạn.\n\n"
            "Full script: {{ $json.script.full_script }}\n"
            "Hook: {{ $json.script.hook }}\n"
            "CTA: {{ $json.script.cta }}\n\n"
            "Chia thành 5-8 scene. TỔNG duration các scene phải nằm trong khoảng 45-70 giây. "
            "Scene 1 PHẢI chứa hook và xuất hiện trong 3 giây đầu.\n\n"
            "Với MỖI scene, cung cấp đủ các field sau:\n"
            "- duration (giây, số thực)\n"
            "- narration (câu thoại đúng phần này của script, tiếng Việt)\n"
            "- subtitle (bản rút gọn dễ đọc của narration, dùng để hiển thị phụ đề - ngắn hơn narration)\n"
            "- visual_description (mô tả cảnh sẽ thấy, tiếng Anh, súc tích)\n"
            "- camera_motion (một trong: slow-zoom, push-in, pull-out, pan-left, pan-right, parallax, static, handheld-drift)\n"
            "- transition (transition dẫn ĐẾN scene tiếp theo: cut, whip-pan, zoom-blur, glitch, match-cut, fade)\n"
            "- emotion (cảm xúc chủ đạo của scene: curiosity, tension, excitement, relief, awe, humor)\n"
            "- text_overlay (từ khóa ngắn hiển thị nổi bật trên màn hình, có thể rỗng nếu không cần)\n"
            "- animation_suggestion (cách chữ/overlay xuất hiện: pop-in, slide-up, typewriter, bounce, fade)\n\n"
            "Output CHỈ JSON, đúng schema:\n"
            "{\n"
            '  "scenes": [\n'
            "    {\n"
            '      "duration": 8, "narration": "", "subtitle": "", "visual_description": "",\n'
            '      "camera_motion": "", "transition": "", "emotion": "", "text_overlay": "",\n'
            '      "animation_suggestion": ""\n'
            "    }\n"
            "  ]\n"
            "}"
        ),
        "options": {},
    },
    -3200, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (Storyboard)", "Storyboard Agent")

wf.node(
    "Normalize Storyboard",
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
            "  throw new Error('Storyboard Agent khong tra ve JSON hop le.');\n"
            "}\n\n"
            "if (!data.scenes || !Array.isArray(data.scenes) || data.scenes.length === 0) {\n"
            "  throw new Error('Storyboard thieu scenes[]');\n"
            "}\n\n"
            "const total = data.scenes.reduce((s, sc) => s + (Number(sc.duration) || 0), 0);\n"
            "if (total < 45 || total > 70) {\n"
            "  throw new Error('Tong duration scenes = ' + total.toFixed(1) + 's, phai nam trong 45-70s. Yeu cau Storyboard Agent dieu chinh.');\n"
            "}\n\n"
            "const prev = $('Validate Script').first().json;\n"
            "const scenes = data.scenes.map((sc, i) => ({ sceneId: i + 1, ...sc }));\n"
            "return scenes.map(sc => ({ json: { ...prev, totalDuration: total, scene: sc } }));"
        )
    },
    -2950, Y_MAIN, type_version=2,
)

# ============================================================================
# MODULE 5 - VISUAL DIRECTION (most important module)
# ============================================================================
wf.sticky(
    "## MODULE 5 - VISUAL DIRECTION (most important)\n\n"
    "Runs once per scene (after Normalize Storyboard splits into items).\n"
    "No Sora / AI video generation - this is a REAL PHOTO slideshow format.\n"
    "Produces two search queries per scene: event_query (specific real-world\n"
    "photo of the actual event/company/person, for Tavily image search) and\n"
    "stock_query (generic English description, Pexels fallback).",
    -2750, 760, w=520, h=280,
)

wf.node(
    "Ollama Chat Model (Visual Director)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": "qwen2.5:14b", "options": {"format": "json"}},
    -2700, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "Visual Director Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Bạn là Visual Director cho video dạng SLIDESHOW ẢNH THẬT (không dùng AI tạo "
            "video, không Sora) - mỗi scene là MỘT ảnh thật với hiệu ứng zoom nhẹ (Ken Burns).\n\n"
            "Scene #{{ $json.scene.sceneId }} / duration {{ $json.scene.duration }}s\n"
            "Narration: {{ $json.scene.narration }}\n"
            "Subtitle: {{ $json.scene.subtitle }}\n"
            "Visual description gốc: {{ $json.scene.visual_description }}\n\n"
            "Nhiệm vụ: tạo 2 câu truy vấn tìm ảnh cho scene này:\n"
            "1. event_query: từ khóa tìm ẢNH THẬT gắn với sự kiện/công ty/sản phẩm/nhân vật cụ "
            "thể được nhắc trong narration (dùng tên riêng, tiếng Việt hoặc tiếng Anh tùy ngữ "
            "cảnh). Nếu scene nói về một công ty/sản phẩm/người cụ thể, PHẢI nêu rõ tên trong "
            "query này. Dùng cho Tavily image search.\n"
            "2. stock_query: mô tả tiếng Anh chung chung kiểu ảnh stock chuyên nghiệp (ví dụ: "
            "'modern data center server room', 'developer coding on laptop close up') để làm "
            "phương án dự phòng trên Pexels khi không tìm được ảnh sự kiện cụ thể.\n\n"
            "Output CHỈ JSON, đúng schema:\n"
            "{\n"
            '  "event_query": "",\n'
            '  "stock_query": ""\n'
            "}"
        ),
        "options": {},
    },
    -2450, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (Visual Director)", "Visual Director Agent")

wf.node(
    "Attach Image Queries",
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
            "  throw new Error('Visual Director Agent khong tra ve JSON hop le.');\n"
            "}\n\n"
            "return [{\n"
            "  json: {\n"
            "    ...$json,\n"
            "    scene: {\n"
            "      ...$json.scene,\n"
            "      eventQuery: data.event_query || $json.scene.visual_description,\n"
            "      stockQuery: data.stock_query || 'technology abstract background'\n"
            "    }\n"
            "  }\n"
            "}];"
        )
    },
    -2200, Y_MAIN, type_version=2,
)

wf.node(
    "Init Video Paths",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const path = require('path');\n"
            "const fs = require('fs');\n\n"
            "const BASE_DIR = $json.BASE_DIR;\n"
            "const now = new Date();\n"
            "const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');\n"
            "const slug = String($json.topic || 'video')\n"
            "  .toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')\n"
            "  .replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '').slice(0, 40);\n\n"
            "// videoId is stable across all items of the same execution (based on execution id)\n"
            "const videoId = $json.videoId || (dateStr + '-' + slug + '-' + $execution.id);\n"
            "const videoDir = path.join(BASE_DIR, videoId);\n"
            "const scenesDir = path.join(videoDir, 'scenes');\n"
            "fs.mkdirSync(scenesDir, { recursive: true });\n\n"
            "return { json: { ...$json, videoId, videoDir, scenesDir } };"
        ),
    },
    -1950, Y_MAIN, type_version=2,
)

print("modules 1-5 nodes so far:", len(wf.nodes))

# ============================================================================
# MODULE 6/7/8 (per-scene loop) - VOICE GENERATION, SUBTITLE CUES, VISUAL CLIP
# ============================================================================
wf.sticky(
    "## LOOP OVER SCENES\n\n"
    "Runs modules 6 (Voice), 7-partial (subtitle cue timing) and 8-partial\n"
    "(real photo per scene via Tavily image search, Pexels stock-photo\n"
    "fallback) once per scene. Final assembly (Ken Burns zoom + subtitle burn\n"
    "+ ffmpeg edit) happens once after the loop completes.",
    -1750, 760, w=520, h=260,
)

wf.node(
    "Loop Over Scenes",
    "n8n-nodes-base.splitInBatches",
    {"options": {}},
    -1700, Y_MAIN, type_version=3,
)

# --- MODULE 6: VOICE GENERATION (VietTTS) ---
wf.node(
    "Generate Scene Voice (VietTTS)",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "={{ $json.VIETTTS_URL }}",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ text: $json.scene.narration, voice: 'infore', "
            "silence_duration: 0.15, speech_rate: 1.05 }) }}"
        ),
        "options": {"response": {"response": {"responseFormat": "file"}}, "timeout": 60000},
    },
    -1450, Y_LOOP,
    type_version=4.4,
)

wf.node(
    "Write Scene Voice File",
    "n8n-nodes-base.readWriteFile",
    {
        "operation": "write",
        "fileName": "={{ $json.scenesDir }}/scene_{{ String($json.scene.sceneId).padStart(2,'0') }}.wav",
        "dataPropertyName": "data",
        "options": {},
    },
    -1200, Y_LOOP,
)

wf.node(
    "Probe Voice Duration (ffprobe)",
    "n8n-nodes-base.executeCommand",
    {
        "command": (
            "=ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "
            "\"{{ $json.fileName }}\""
        )
    },
    -950, Y_LOOP,
)

# --- MODULE 7 (partial): subtitle cues for this scene, timed to the real audio duration ---
wf.node(
    "Build Scene Subtitle Cues",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "// Splits this scene's subtitle text into short, readable phrases (max 2 lines\n"
            "// worth each), spread proportionally across the REAL measured audio duration\n"
            "// (from ffprobe), and flags 1-2 'keywords' per phrase to highlight later.\n"
            "const ctx = $json; // this item already carries scene + paths from the loop\n\n"
            "const durationSec = parseFloat($('Probe Voice Duration (ffprobe)').first().json.stdout.trim()) || ctx.scene.duration;\n\n"
            "const text = String(ctx.scene.subtitle || ctx.scene.narration || '').trim();\n"
            "// Split into clause-like chunks on punctuation, then re-group into <= 6-word phrases.\n"
            "const rawParts = text.split(/(?<=[.,!?;:])\\s+|\\s{2,}/).filter(Boolean);\n"
            "let words = [];\n"
            "(rawParts.length ? rawParts : [text]).forEach(p => words.push(...p.split(/\\s+/).filter(Boolean)));\n\n"
            "const phrases = [];\n"
            "let cur = [];\n"
            "for (const w of words) {\n"
            "  cur.push(w);\n"
            "  if (cur.length >= 5) { phrases.push(cur.join(' ')); cur = []; }\n"
            "}\n"
            "if (cur.length) phrases.push(cur.join(' '));\n"
            "if (phrases.length === 0) phrases.push(text || '...');\n\n"
            "const perCue = durationSec / phrases.length;\n"
            "const STOPWORDS = new Set(['la','va','cua','o','trong','mot','nhung','de','cho','khi','the','nay','voi','tu','duoc']);\n\n"
            "function stripDiacritics(s) {\n"
            "  return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\u0111/g, 'd').replace(/\\u0110/g, 'D').toLowerCase();\n"
            "}\n\n"
            "const cues = phrases.map((p, i) => {\n"
            "  const tokens = p.split(/\\s+/);\n"
            "  const keyword = tokens\n"
            "    .filter(t => !STOPWORDS.has(stripDiacritics(t.replace(/[^\\p{L}\\p{N}]/gu, ''))))\n"
            "    .sort((a, b) => b.length - a.length)[0] || tokens[0];\n"
            "  return {\n"
            "    start: +(i * perCue).toFixed(2),\n"
            "    end: +((i + 1) * perCue).toFixed(2),\n"
            "    text: p,\n"
            "    keyword\n"
            "  };\n"
            "});\n\n"
            "return [{\n"
            "  json: {\n"
            "    ...ctx,\n"
            "    scene: { ...ctx.scene, measuredDuration: durationSec, subtitleCues: cues },\n"
            "    audioPath: $('Write Scene Voice File').first().json.fileName\n"
            "  }\n"
            "}];"
        )
    },
    -700, Y_LOOP, type_version=2,
)

# --- MODULE 8 (partial): real photo per scene via Tavily (event photo) with
# Pexels stock-photo fallback - proven pattern reused from n8n_workflow_shorts.json ---
wf.node(
    "Tavily Image Search",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://api.tavily.com/search",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({ query: $json.scene.eventQuery, search_depth: 'basic', "
            "include_images: true, include_image_descriptions: false, max_results: 3 }) }}"
        ),
        "options": {"timeout": 30000},
    },
    -450, Y_LOOP,
    type_version=4.4,
    extra={"credentials": TAVILY_HEADER_CRED},
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
            "    url.endsWith('.svg') || url.includes('.svg?') || url.includes('logo') ||\n"
            "    url.includes('icon') || url.includes('favicon') ||\n"
            "    url.includes('lookaside.instagram') || url.includes('instagram.com')\n"
            "  );\n"
            "};\n\n"
            "let imageUrl = null;\n"
            "if (Array.isArray($json.results)) {\n"
            "  for (const result of $json.results) {\n"
            "    if (!Array.isArray(result.images)) continue;\n"
            "    imageUrl = result.images.find(u => !bad(u));\n"
            "    if (imageUrl) break;\n"
            "  }\n"
            "}\n"
            "if (!imageUrl && Array.isArray($json.images)) {\n"
            "  imageUrl = $json.images.find(u => !bad(u));\n"
            "}\n\n"
            "const ctx = $('Build Scene Subtitle Cues').first().json;\n"
            "return [{ json: { ...ctx, hasTavilyImage: !!imageUrl, tavilyImageUrl: imageUrl } }];"
        )
    },
    -200, Y_LOOP, type_version=2,
)

wf.node(
    "Has Tavily Image?",
    "n8n-nodes-base.if",
    {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
            "conditions": [
                {
                    "leftValue": "={{ $json.hasTavilyImage }}",
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }
            ],
            "combinator": "and",
        }
    },
    50, Y_LOOP, type_version=2.3,
)

wf.node(
    "Download Image (Tavily)",
    "n8n-nodes-base.httpRequest",
    {
        "url": "={{ $json.tavilyImageUrl }}",
        "options": {"response": {"response": {"neverError": True, "responseFormat": "file"}}, "timeout": 30000},
    },
    300, Y_LOOP - 100,
    type_version=4.4,
)

wf.node(
    "Validate Tavily Image",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const scene = $input.item.json;\n"
            "const binary = $input.item.binary && $input.item.binary.data;\n"
            "let isValid = false;\n\n"
            "if (binary) {\n"
            "  const buffer = await this.helpers.getBinaryDataBuffer(0, 'data');\n"
            "  const isJpeg = buffer.length > 4 && buffer[0] === 0xFF && buffer[1] === 0xD8;\n"
            "  const isPng = buffer.length > 8 && buffer[0] === 0x89 && buffer[1] === 0x50;\n"
            "  const isWebp = buffer.length > 12 && buffer.slice(8, 12).toString() === 'WEBP';\n"
            "  isValid = buffer.length > 2000 && (isJpeg || isPng || isWebp);\n"
            "}\n\n"
            "return { json: { ...scene, tavilyImageValid: isValid }, binary: $input.item.binary };"
        )
    },
    550, Y_LOOP - 100, type_version=2,
)

wf.node(
    "Is Tavily Image Valid?",
    "n8n-nodes-base.if",
    {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
            "conditions": [
                {
                    "leftValue": "={{ $json.tavilyImageValid }}",
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }
            ],
            "combinator": "and",
        }
    },
    800, Y_LOOP - 100, type_version=2.3,
)

# Fallback path when Tavily has no usable event photo (or it fails validation): Pexels stock photo
wf.node(
    "Pexels Image Search",
    "n8n-nodes-base.httpRequest",
    {
        "url": "=https://api.pexels.com/v1/search?query={{ encodeURIComponent($json.scene.stockQuery) }}&orientation=portrait&per_page=1&size=large",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "options": {"timeout": 30000},
    },
    300, Y_LOOP + 200,
    type_version=4.4,
    extra={"credentials": {"httpHeaderAuth": {"id": "REPLACE_ME", "name": "Pexels API Key"}}, "continueOnFail": True},
)

wf.node(
    "Extract Pexels Image URL",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForEachItem",
        "jsCode": (
            "const photos = $json.photos || [];\n"
            "const photo = photos[0];\n"
            "const imageUrl = photo && photo.src && (photo.src.large2x || photo.src.large || photo.src.original);\n\n"
            "const ctx = $('Check Tavily Images').first().json;\n"
            "if (!imageUrl) {\n"
            "  throw new Error('Pexels khong tra ve anh phu hop cho query: ' + (ctx.scene.stockQuery || ''));\n"
            "}\n\n"
            "return { json: { ...ctx, pexelsImageUrl: imageUrl } };"
        )
    },
    550, Y_LOOP + 200, type_version=2,
)

wf.node(
    "Download Image (Pexels)",
    "n8n-nodes-base.httpRequest",
    {
        "url": "={{ $json.pexelsImageUrl }}",
        "options": {"response": {"response": {"responseFormat": "file"}}, "timeout": 30000},
    },
    800, Y_LOOP + 200,
    type_version=4.4,
)

wf.node(
    "Write Scene Image File",
    "n8n-nodes-base.readWriteFile",
    {
        "operation": "write",
        "fileName": "={{ $('Build Scene Subtitle Cues').first().json.scenesDir }}/scene_{{ String($('Build Scene Subtitle Cues').first().json.scene.sceneId).padStart(2,'0') }}_image.jpg",
        "dataPropertyName": "data",
        "options": {},
    },
    1050, Y_LOOP,
)

wf.node(
    "Finalize Scene",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const ctx = $('Build Scene Subtitle Cues').first().json;\n"
            "const imagePath = $json.fileName;\n"
            "const staticData = $getWorkflowStaticData('global');\n"
            "staticData.scenes = staticData.scenes || [];\n"
            "staticData.scenes.push({\n"
            "  ...ctx.scene,\n"
            "  audioPath: ctx.audioPath,\n"
            "  imagePath\n"
            "});\n"
            "return [{ json: { ...ctx, imagePath } }];"
        )
    },
    1300, Y_LOOP, type_version=2,
)

# wiring for the loop
wf.link("Schedule Trigger", "Load Config & Learnings")
wf.link("Load Config & Learnings", "Build Trend Search Query")
wf.link("Build Trend Search Query", "Tavily Search (Trend)")
wf.link("Tavily Search (Trend)", "Parse Trend Search Results")
wf.link("Parse Trend Search Results", "Trend Synthesis Agent")
wf.link("Trend Synthesis Agent", "Select Top Topic")
wf.link("Select Top Topic", "Build Deep Research Query")
wf.link("Build Deep Research Query", "Tavily Search (Deep Research)")
wf.link("Tavily Search (Deep Research)", "Parse Deep Research Results")
wf.link("Parse Deep Research Results", "Deep Research Synthesis Agent")
wf.link("Deep Research Synthesis Agent", "Validate Facts")
wf.link("Validate Facts", "Script Writer Agent")
wf.link("Script Writer Agent", "Validate Script")
wf.link("Validate Script", "Storyboard Agent")
wf.link("Storyboard Agent", "Normalize Storyboard")
wf.link("Normalize Storyboard", "Visual Director Agent")
wf.link("Visual Director Agent", "Attach Image Queries")
wf.link("Attach Image Queries", "Init Video Paths")
wf.link("Init Video Paths", "Loop Over Scenes")

# splitInBatches: output 0 = done (handled later, after module 9 nodes exist),
# output 1 = loop body
wf.link("Loop Over Scenes", "Generate Scene Voice (VietTTS)", src_index=1)
wf.link("Generate Scene Voice (VietTTS)", "Write Scene Voice File")
wf.link("Write Scene Voice File", "Probe Voice Duration (ffprobe)")
wf.link("Probe Voice Duration (ffprobe)", "Build Scene Subtitle Cues")
wf.link("Build Scene Subtitle Cues", "Tavily Image Search")
wf.link("Tavily Image Search", "Check Tavily Images")
wf.link("Check Tavily Images", "Has Tavily Image?")
wf.link("Has Tavily Image?", "Download Image (Tavily)", src_index=0)
wf.link("Has Tavily Image?", "Pexels Image Search", src_index=1)
wf.link("Download Image (Tavily)", "Validate Tavily Image")
wf.link("Validate Tavily Image", "Is Tavily Image Valid?")
wf.link("Is Tavily Image Valid?", "Write Scene Image File", src_index=0)
wf.link("Is Tavily Image Valid?", "Pexels Image Search", src_index=1)
wf.link("Pexels Image Search", "Extract Pexels Image URL")
wf.link("Extract Pexels Image URL", "Download Image (Pexels)")
wf.link("Download Image (Pexels)", "Write Scene Image File")
wf.link("Write Scene Image File", "Finalize Scene")
wf.link("Finalize Scene", "Loop Over Scenes")

print("modules 1-8(loop) nodes so far:", len(wf.nodes))

# ============================================================================
# MODULE 7 (final) - SUBTITLE ASSEMBLY  /  MODULE 8 (final) - VIDEO EDITING
# ============================================================================
wf.sticky(
    "## MODULE 7 (assembly) - SUBTITLES\n"
    "## MODULE 8 (assembly) - VIDEO EDITING\n\n"
    "Runs once, after the scene loop finishes (done branch, index 0).\n"
    "Builds a karaoke-style .ass subtitle file (MrBeast-style keyword pop),\n"
    "then an ffmpeg script: each scene image gets scale+crop to fill 1080x1920\n"
    "plus a Ken Burns zoompan (per the storyboard's camera_motion), scenes are\n"
    "joined with xfade transitions, bgm+sfx mixed with sidechain ducking,\n"
    "loudnorm, subtitle burn-in.",
    -1700, 1900, w=560, h=280,
)

wf.node(
    "Write storyboard.json",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const fs = require('fs');\n"
            "const path = require('path');\n"
            "const staticData = $getWorkflowStaticData('global');\n"
            "const scenes = (staticData.scenes || []).slice().sort((a, b) => a.sceneId - b.sceneId);\n"
            "const ctx = $('Init Video Paths').first().json;\n\n"
            "const storyboardPath = path.join(ctx.videoDir, 'storyboard.json');\n"
            "fs.writeFileSync(storyboardPath, JSON.stringify({\n"
            "  videoId: ctx.videoId,\n"
            "  topic: ctx.topic,\n"
            "  script: ctx.script,\n"
            "  totalDuration: ctx.totalDuration,\n"
            "  scenes\n"
            "}, null, 2));\n\n"
            "return [{ json: { ...ctx, storyboardPath, scenes } }];"
        )
    },
    -1450, Y_MAIN, type_version=2,
)

wf.node(
    "Build Subtitles (ASS)",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "// Builds an .ass file with 2 styles: base text + a 'Key' style used only for\n"
            "// the highlighted keyword in each cue (bold, accent color, scale-pop-in),\n"
            "// which is what gives the MrBeast-style 'pop on keyword' subtitle feel.\n"
            "const fs = require('fs');\n"
            "const path = require('path');\n"
            "const ctx = $json;\n"
            "const scenes = ctx.scenes;\n\n"
            "function fmtTime(t) {\n"
            "  const h = Math.floor(t / 3600);\n"
            "  const m = Math.floor((t % 3600) / 60);\n"
            "  const s = t % 60;\n"
            "  return h + ':' + String(m).padStart(2, '0') + ':' + s.toFixed(2).padStart(5, '0');\n"
            "}\n\n"
            "const header = '[Script Info]\\nScriptType: v4.00+\\nPlayResX: 1080\\nPlayResY: 1920\\n\\n' +\n"
            "  '[V4+ Styles]\\n' +\n"
            "  'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\\n' +\n"
            "  'Style: Base,Montserrat ExtraBold,64,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,1,3,2,2,60,60,260,1\\n' +\n"
            "  'Style: Key,Montserrat ExtraBold,64,&H0000E5FF,&H0000E5FF,&H00101010,&H80000000,1,0,1,3,2,2,60,60,260,1\\n\\n' +\n"
            "  '[Events]\\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\\n';\n\n"
            "let offset = 0;\n"
            "const lines = [];\n"
            "for (const scene of scenes) {\n"
            "  for (const cue of (scene.subtitleCues || [])) {\n"
            "    const start = offset + cue.start;\n"
            "    const end = offset + cue.end;\n"
            "    // wrap to max 2 lines, highlight the keyword with a quick pop-in scale animation\n"
            "    const words = cue.text.split(/\\s+/);\n"
            "    const mid = Math.ceil(words.length / 2);\n"
            "    const line1 = words.slice(0, mid).join(' ');\n"
            "    const line2 = words.slice(mid).join(' ');\n"
            "    const highlight = (w) => w.toLowerCase() === String(cue.keyword).toLowerCase()\n"
            "      ? '{\\\\t(0,120,\\\\fscx120\\\\fscy120)}{\\\\c&H00E5FF&}' + w + '{\\\\c&HFFFFFF&}{\\\\fscx100\\\\fscy100}'\n"
            "      : w;\n"
            "    const styled1 = line1.split(/\\s+/).map(highlight).join(' ');\n"
            "    const styled2 = line2.split(/\\s+/).map(highlight).join(' ');\n"
            "    const text = [styled1, styled2].filter(Boolean).join('\\\\N');\n"
            "    lines.push('Dialogue: 0,' + fmtTime(start) + ',' + fmtTime(end) + ',Base,,0,0,0,,{\\\\fad(80,80)}' + text);\n"
            "  }\n"
            "  offset += scene.measuredDuration || scene.duration;\n"
            "}\n\n"
            "const assContent = header + lines.join('\\n') + '\\n';\n"
            "const subtitlesPath = path.join(ctx.videoDir, 'subtitles.ass');\n"
            "fs.writeFileSync(subtitlesPath, assContent);\n\n"
            "return [{ json: { ...ctx, subtitlesPath } }];"
        )
    },
    -1200, Y_MAIN, type_version=2,
)

wf.node(
    "Build Render Script",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "// Generates a bash script that: (1) turns each scene's still image into a clip\n"
            "// with scale+crop to fill the frame plus a Ken Burns zoompan (per the storyboard's\n"
            "// camera_motion), synced to the real narration duration, (2) concatenates scenes\n"
            "// with short crossfade (xfade) transitions, (3) mixes background music + sfx under\n"
            "// the narration with sidechain ducking, (4) applies loudnorm, (5) burns in\n"
            "// subtitles.ass, all at 1080x1920@30fps.\n"
            "const path = require('path');\n"
            "const ctx = $json;\n"
            "const W = 1080, H = 1920, FPS = 30;\n"
            "const dir = ctx.videoDir;\n"
            "const scenes = ctx.scenes;\n"
            "const bgm = path.join(ctx.BASE_DIR, 'assets', 'bgm', 'default.mp3');\n"
            "const sfxWhoosh = path.join(ctx.BASE_DIR, 'assets', 'sfx', 'whoosh.wav');\n\n"
            "function zoompan(camera, frames) {\n"
            "  const base = `zoompan=d=${frames}:s=${W}x${H}:fps=${FPS}`;\n"
            "  switch (camera) {\n"
            "    case 'push-in': return `zoompan=z='min(1+0.18*on/${frames},1.18)':d=${frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=${W}x${H}:fps=${FPS}`;\n"
            "    case 'pull-out': return `zoompan=z='max(1.18-0.18*on/${frames},1.0)':d=${frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=${W}x${H}:fps=${FPS}`;\n"
            "    case 'pan-left': return `zoompan=z=1.12:d=${frames}:x='(iw-iw/zoom)*(1-on/${frames})':y='ih/2-(ih/zoom/2)':s=${W}x${H}:fps=${FPS}`;\n"
            "    case 'pan-right': return `zoompan=z=1.12:d=${frames}:x='(iw-iw/zoom)*(on/${frames})':y='ih/2-(ih/zoom/2)':s=${W}x${H}:fps=${FPS}`;\n"
            "    case 'slow-zoom':\n"
            "    case 'parallax':\n"
            "    case 'handheld-drift':\n"
            "    case 'static':\n"
            "    default: return `zoompan=z='min(zoom+0.0006,1.12)':d=${frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=${W}x${H}:fps=${FPS}`;\n"
            "  }\n"
            "}\n\n"
            "let script = '#!/bin/bash\\nset -e\\ncd \"' + dir + '\"\\nexec 2>> \"' + dir + '/ffmpeg.log\"\\n\\n';\n"
            "const processed = [];\n"
            "scenes.forEach((sc, i) => {\n"
            "  const idx = String(sc.sceneId).padStart(2, '0');\n"
            "  const dur = sc.measuredDuration || sc.duration;\n"
            "  const frames = Math.round(dur * FPS);\n"
            "  const img = 'scenes/scene_' + idx + '_image.jpg';\n"
            "  const audio = 'scenes/scene_' + idx + '.wav';\n"
            "  const out = 'scenes/scene_' + idx + '_final.mp4';\n"
            "  processed.push(out);\n"
            "  // still photo -> video: scale+crop to fill 1080x1920 (no bars), Ken Burns zoompan\n"
            "  // sized to this scene's real narration duration, muxed with the narration audio at\n"
            "  // a fixed 44100/stereo so concat never desyncs.\n"
            "  script += 'ffmpeg -y -loop 1 -i \"' + img + '\" -i \"' + audio + '\" ' +\n"
            "    '-filter_complex \"[0:v]scale=' + W + ':' + H + ':force_original_aspect_ratio=increase,crop=' + W + ':' + H + ',setsar=1,' + zoompan(sc.camera_motion, frames) + ',format=yuv420p[v]\" ' +\n"
            "    '-map \"[v]\" -map 1:a -c:v libx264 -preset veryfast -crf 18 -r ' + FPS + ' ' +\n"
            "    '-ar 44100 -ac 2 -c:a aac -t ' + dur.toFixed(2) + ' \"' + out + '\"\\n';\n"
            "});\n\n"
            "// crossfade-concat all processed scenes (xfade + acrossfade), 0.35s transitions\n"
            "const XF = 0.35;\n"
            "let filterChain = '';\n"
            "let vLabel = '0:v'; let aLabel = '0:a'; let acc = 0;\n"
            "const inputs = processed.map(p => '-i \"' + p + '\"').join(' ');\n"
            "processed.forEach((p, i) => {\n"
            "  if (i === 0) return;\n"
            "  const dur = (scenes[i - 1].measuredDuration || scenes[i - 1].duration);\n"
            "  acc += dur - XF;\n"
            "  const vOut = 'v' + i; const aOut = 'a' + i;\n"
            "  filterChain += '[' + vLabel + '][' + i + ':v]xfade=transition=fade:duration=' + XF + ':offset=' + acc.toFixed(2) + '[' + vOut + '];';\n"
            "  filterChain += '[' + aLabel + '][' + i + ':a]acrossfade=d=' + XF + '[' + aOut + '];';\n"
            "  vLabel = vOut; aLabel = aOut;\n"
            "});\n\n"
            "const narrationMix = 'concat_video.mp4';\n"
            "script += 'ffmpeg -y ' + inputs + ' -filter_complex \"' + filterChain +\n"
            "  '[' + vLabel + ']null[vout];[' + aLabel + ']anull[aout]\" ' +\n"
            "  '-map \"[vout]\" -map \"[aout]\" -c:v libx264 -preset veryfast -crf 18 -r ' + FPS + ' -c:a aac \"' + narrationMix + '\"\\n';\n\n"
            "// bgm + sfx under narration, ducked via sidechaincompress so music drops when voice speaks,\n"
            "// then loudnorm for consistent platform loudness, then burn subtitles.ass\n"
            "script += 'if [ -f \"' + bgm + '\" ]; then\\n' +\n"
            "  '  ffmpeg -y -i \"' + narrationMix + '\" -stream_loop -1 -i \"' + bgm + '\" -filter_complex \"' +\n"
            "  '[1:a]volume=0.18[bgm];[0:a][bgm]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300[bgmduck];' +\n"
            "  '[0:a][bgmduck]amix=inputs=2:duration=first:dropout_transition=2,loudnorm=I=-14:TP=-1.5:LRA=11[aout]\" ' +\n"
            "  '-map 0:v -map \"[aout]\" -c:v copy -c:a aac mixed.mp4\\n' +\n"
            "  'else\\n' +\n"
            "  '  ffmpeg -y -i \"' + narrationMix + '\" -af loudnorm=I=-14:TP=-1.5:LRA=11 -c:v copy -c:a aac mixed.mp4\\n' +\n"
            "  'fi\\n\\n';\n\n"
            "script += 'ffmpeg -y -i mixed.mp4 -vf \"ass=subtitles.ass\" -c:v libx264 -preset veryfast -crf 17 ' +\n"
            "  '-c:a copy final_video.mp4\\n';\n\n"
            "const renderScriptPath = path.join(dir, 'render_video.sh');\n"
            "require('fs').writeFileSync(renderScriptPath, script, { mode: 0o755 });\n\n"
            "return [{ json: { ...ctx, renderScriptPath, finalVideoPath: path.join(dir, 'final_video.mp4') } }];"
        )
    },
    -950, Y_MAIN, type_version=2,
)

wf.node(
    "Execute Render Script (ffmpeg)",
    "n8n-nodes-base.executeCommand",
    {"command": "=bash \"{{ $json.renderScriptPath }}\""},
    -700, Y_MAIN,
)

wf.link("Loop Over Scenes", "Write storyboard.json", src_index=0)
wf.link("Write storyboard.json", "Build Subtitles (ASS)")
wf.link("Build Subtitles (ASS)", "Build Render Script")
wf.link("Build Render Script", "Execute Render Script (ffmpeg)")

# ============================================================================
# MODULE 9 - SEO
# ============================================================================
wf.sticky(
    "## MODULE 9 - SEO\n\n"
    "Title, description, keywords, hashtags + platform-specific captions.\n"
    "Optimized for search/CTR - explicitly NOT clickbait.",
    -500, 760, w=440, h=220,
)

wf.node(
    "Ollama Chat Model (SEO)",
    "@n8n/n8n-nodes-langchain.lmChatOllama",
    {"model": "qwen2.5:14b", "options": {"format": "json"}},
    -450, Y_MODEL,
    extra={"credentials": OLLAMA_CRED},
)
wf.node(
    "SEO Agent",
    "@n8n/n8n-nodes-langchain.agent",
    {
        "promptType": "define",
        "text": (
            "=Bạn là chuyên gia SEO cho video ngắn công nghệ, đăng TikTok / YouTube Shorts / "
            "Facebook Reels.\n\n"
            "Chủ đề: {{ $json.topic }}\n"
            "Script: {{ $json.script.full_script }}\n\n"
            "Tạo nội dung SEO tối ưu tìm kiếm và CTR thật, KHÔNG giật gân/clickbait sai sự thật. "
            "Caption cho từng nền tảng cần khác nhau về giọng điệu/hashtag phù hợp platform đó.\n\n"
            "Output CHỈ JSON, đúng schema:\n"
            "{\n"
            '  "title": "", "description": "", "keywords": [""], "hashtags": [""],\n'
            '  "tiktok_caption": "", "facebook_caption": "", "youtube_shorts_description": ""\n'
            "}"
        ),
        "options": {},
    },
    -200, Y_MAIN, type_version=3.1,
)
wf.model("Ollama Chat Model (SEO)", "SEO Agent")

wf.node(
    "Prepare SEO Metadata",
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
            "let seo;\n"
            "try {\n"
            "  seo = parseAgentJson($json.output);\n"
            "} catch (e) {\n"
            "  throw new Error('SEO Agent khong tra ve JSON hop le.');\n"
            "}\n\n"
            "const ctx = $('Build Render Script').first().json;\n"
            "return [{ json: { ...ctx, seo } }];"
        )
    },
    50, Y_MAIN, type_version=2,
)

wf.link("Execute Render Script (ffmpeg)", "SEO Agent")
wf.link("SEO Agent", "Prepare SEO Metadata")

# ============================================================================
# MODULE 10 - PUBLISHING
# ============================================================================
wf.sticky(
    "## MODULE 10 - PUBLISHING\n\n"
    "Uploads final_video.mp4 to YouTube (native node) and publishes to\n"
    "TikTok (Content Posting API) + Facebook (Graph API Reels flow) via\n"
    "HTTP Request. TikTok/Facebook calls require an approved developer app;\n"
    "see PREMIUM_WORKFLOW.md for the exact onboarding steps.",
    250, 760, w=520, h=260,
)

wf.node(
    "Read Final Video File",
    "n8n-nodes-base.readWriteFile",
    {"operation": "read", "fileSelector": "={{ $json.finalVideoPath }}", "options": {}},
    300, Y_MAIN,
)

wf.node(
    "Upload To YouTube",
    "n8n-nodes-base.youTube",
    {
        "resource": "video",
        "operation": "upload",
        "title": "={{ $('Prepare SEO Metadata').first().json.seo.title }}",
        "regionCode": "VN",
        "categoryId": "28",
        "options": {
            "description": "={{ $('Prepare SEO Metadata').first().json.seo.youtube_shorts_description }}",
            "privacyStatus": "private",
            "tags": "={{ ($('Prepare SEO Metadata').first().json.seo.keywords || []).join(',') }}",
        },
    },
    550, Y_MAIN - 150,
    extra={"credentials": YOUTUBE_CRED},
)

wf.node(
    "Publish To TikTok",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "https://open.tiktokapis.com/v2/post/publish/video/init/",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({\n"
            "  post_info: {\n"
            "    title: $('Prepare SEO Metadata').first().json.seo.tiktok_caption,\n"
            "    privacy_level: 'SELF_ONLY',\n"
            "    disable_duet: false, disable_comment: false, disable_stitch: false\n"
            "  },\n"
            "  source_info: { source: 'FILE_UPLOAD', video_size: $binary.data.fileSize, chunk_size: $binary.data.fileSize, total_chunk_count: 1 }\n"
            "}) }}"
        ),
        "options": {"timeout": 60000},
    },
    550, Y_MAIN,
    extra={"credentials": TIKTOK_HEADER_CRED, "continueOnFail": True},
)

wf.node(
    "Publish To Facebook Reels",
    "n8n-nodes-base.httpRequest",
    {
        "method": "POST",
        "url": "=https://graph.facebook.com/v19.0/{{ $json.facebookPageId || 'REPLACE_ME_PAGE_ID' }}/video_reels",
        "authentication": "genericCredentialType",
        "genericAuthType": "httpHeaderAuth",
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": (
            "={{ JSON.stringify({\n"
            "  upload_phase: 'start'\n"
            "}) }}"
        ),
        "options": {"timeout": 60000},
    },
    550, Y_MAIN + 150,
    extra={"credentials": FACEBOOK_HEADER_CRED, "continueOnFail": True},
)

wf.node(
    "Log Publish Results",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "// Appends one JSON line per published video to publish_log.jsonl so that the\n"
            "// independent Analytics workflow (module 11) knows what to pull metrics for.\n"
            "const fs = require('fs');\n"
            "const path = require('path');\n"
            "const ctx = $('Prepare SEO Metadata').first().json;\n\n"
            "let youtubeId = null;\n"
            "try { youtubeId = $('Upload To YouTube').first().json.id; } catch (e) {}\n\n"
            "const logPath = path.join(ctx.BASE_DIR, 'analytics', 'publish_log.jsonl');\n"
            "const entry = {\n"
            "  videoId: ctx.videoId,\n"
            "  topic: ctx.topic,\n"
            "  publishedAt: new Date().toISOString(),\n"
            "  finalVideoPath: ctx.finalVideoPath,\n"
            "  youtubeVideoId: youtubeId,\n"
            "  title: ctx.seo.title,\n"
            "  hashtags: ctx.seo.hashtags\n"
            "};\n"
            "fs.appendFileSync(logPath, JSON.stringify(entry) + '\\n');\n\n"
            "return [{ json: entry }];"
        )
    },
    800, Y_MAIN, type_version=2,
)

wf.link("Read Final Video File", "Upload To YouTube")
wf.link("Read Final Video File", "Publish To TikTok")
wf.link("Read Final Video File", "Publish To Facebook Reels")
wf.link("Prepare SEO Metadata", "Read Final Video File")
wf.link("Upload To YouTube", "Log Publish Results")
wf.link("Publish To TikTok", "Log Publish Results")
wf.link("Publish To Facebook Reels", "Log Publish Results")

print("TOTAL main workflow nodes:", len(wf.nodes))

with open("n8n_workflow_premium.json", "w", encoding="utf-8") as f:
    json.dump(wf.export(), f, ensure_ascii=False, indent=2)
print("wrote n8n_workflow_premium.json")

# ============================================================================
# MODULE 11 - ANALYTICS (independent workflow, own schedule)
# ============================================================================
wf2 = Workflow()

wf2.sticky(
    "## MODULE 11 - ANALYTICS (independent workflow)\n\n"
    "Runs on its own daily schedule (separate from the content pipeline).\n"
    "Pulls YouTube stats for every video in publish_log.jsonl, appends to\n"
    "analytics_store.jsonl, then aggregates results into learnings.json,\n"
    "which Module 1 (Trend Research) of the main pipeline reads to steer\n"
    "future topic selection toward what actually performs.",
    -1200, 700, w=560, h=280,
)

wf2.node(
    "Schedule Trigger (Analytics)",
    "n8n-nodes-base.scheduleTrigger",
    {"rule": {"interval": [{"triggerAtHour": 22}]}},
    -1200, 1000,
)

wf2.node(
    "Load Publish Log",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const fs = require('fs');\n"
            "const path = require('path');\n\n"
            "const BASE_DIR = process.env.AI_SHORTS_BASE_DIR || '/Users/tuht1/ai-shorts-videos';\n"
            "const logPath = path.join(BASE_DIR, 'analytics', 'publish_log.jsonl');\n"
            "if (!fs.existsSync(logPath)) return [];\n\n"
            "const lines = fs.readFileSync(logPath, 'utf8').split('\\n').filter(Boolean);\n"
            "const cutoff = Date.now() - 30 * 24 * 3600 * 1000;\n"
            "const videos = lines\n"
            "  .map(l => { try { return JSON.parse(l); } catch (e) { return null; } })\n"
            "  .filter(v => v && v.youtubeVideoId && new Date(v.publishedAt).getTime() >= cutoff);\n\n"
            "return videos.map(v => ({ json: { ...v, BASE_DIR } }));"
        )
    },
    -950, 1000, type_version=2,
)

wf2.node(
    "Loop Over Videos",
    "n8n-nodes-base.splitInBatches",
    {"options": {}},
    -700, 1000, type_version=3,
)

wf2.node(
    "Get YouTube Video Stats",
    "n8n-nodes-base.httpRequest",
    {
        "method": "GET",
        "url": "https://www.googleapis.com/youtube/v3/videos",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "youTubeOAuth2Api",
        "sendQuery": True,
        "queryParameters": {
            "parameters": [
                {"name": "part", "value": "statistics"},
                {"name": "id", "value": "={{ $json.youtubeVideoId }}"},
            ]
        },
        "options": {"timeout": 30000},
    },
    -450, 900,
    type_version=4.4,
    extra={"credentials": YOUTUBE_CRED, "continueOnFail": True},
)

wf2.node(
    "Get YouTube Analytics Report",
    "n8n-nodes-base.httpRequest",
    {
        "method": "GET",
        "url": "https://youtubeanalytics.googleapis.com/v2/reports",
        "authentication": "predefinedCredentialType",
        "nodeCredentialType": "youTubeOAuth2Api",
        "sendQuery": True,
        "queryParameters": {
            "parameters": [
                {"name": "ids", "value": "channel==MINE"},
                {"name": "startDate", "value": "={{ $json.publishedAt.slice(0,10) }}"},
                {"name": "endDate", "value": "={{ $now.toISODate() }}"},
                {"name": "metrics", "value": "views,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained"},
                {"name": "filters", "value": "=video=={{ $json.youtubeVideoId }}"},
            ]
        },
        "options": {"timeout": 30000},
    },
    -450, 1100,
    type_version=4.4,
    extra={"credentials": YOUTUBE_CRED, "continueOnFail": True},
)

wf2.node(
    "Normalize Metrics",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const video = $('Loop Over Videos').first().json;\n"
            "const stats = ($('Get YouTube Video Stats').first().json.items || [])[0]?.statistics || {};\n"
            "const report = $('Get YouTube Analytics Report').first().json;\n"
            "const row = (report.rows || [])[0] || [];\n"
            "const cols = (report.columnHeaders || []).map(c => c.name);\n\n"
            "function col(name) {\n"
            "  const i = cols.indexOf(name);\n"
            "  return i >= 0 ? row[i] : null;\n"
            "}\n\n"
            "return [{\n"
            "  json: {\n"
            "    videoId: video.videoId,\n"
            "    youtubeVideoId: video.youtubeVideoId,\n"
            "    topic: video.topic,\n"
            "    title: video.title,\n"
            "    hashtags: video.hashtags,\n"
            "    pulledAt: new Date().toISOString(),\n"
            "    views: Number(stats.viewCount || col('views') || 0),\n"
            "    likes: Number(stats.likeCount || col('likes') || 0),\n"
            "    comments: Number(stats.commentCount || col('comments') || 0),\n"
            "    shares: Number(col('shares') || 0),\n"
            "    avgViewDurationSec: Number(col('averageViewDuration') || 0),\n"
            "    retentionPct: Number(col('averageViewPercentage') || 0),\n"
            "    subscribersGained: Number(col('subscribersGained') || 0)\n"
            "  }\n"
            "}];"
        )
    },
    -200, 1000, type_version=2,
)

wf2.node(
    "Append Analytics Store",
    "n8n-nodes-base.code",
    {
        "jsCode": (
            "const fs = require('fs');\n"
            "const path = require('path');\n"
            "const BASE_DIR = $('Load Publish Log').first().json.BASE_DIR;\n"
            "const storePath = path.join(BASE_DIR, 'analytics', 'analytics_store.jsonl');\n"
            "fs.appendFileSync(storePath, JSON.stringify($json) + '\\n');\n"
            "return [{ json: $json }];"
        )
    },
    50, 1000, type_version=2,
)

wf2.node(
    "Compute Learnings",
    "n8n-nodes-base.code",
    {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "// Aggregates analytics_store.jsonl into learnings.json consumed by the main\n"
            "// pipeline's 'Load Config & Learnings' node (Module 1).\n"
            "const fs = require('fs');\n"
            "const path = require('path');\n"
            "const BASE_DIR = process.env.AI_SHORTS_BASE_DIR || '/Users/tuht1/ai-shorts-videos';\n"
            "const storePath = path.join(BASE_DIR, 'analytics', 'analytics_store.jsonl');\n"
            "if (!fs.existsSync(storePath)) return [{ json: { skipped: true } }];\n\n"
            "const rows = fs.readFileSync(storePath, 'utf8').split('\\n').filter(Boolean)\n"
            "  .map(l => { try { return JSON.parse(l); } catch (e) { return null; } })\n"
            "  .filter(Boolean);\n\n"
            "// keep only the most recent pull per video\n"
            "const latestByVideo = {};\n"
            "for (const r of rows) latestByVideo[r.videoId] = r;\n"
            "const latest = Object.values(latestByVideo);\n\n"
            "function score(r) {\n"
            "  // retention + shares/comments weighted higher than raw views (proxy for\n"
            "  // 'people who WANT to finish watching', matching the stated priority)\n"
            "  return (r.retentionPct || 0) * 2 + (r.shares || 0) * 3 + (r.comments || 0) * 2 + (r.likes || 0) * 0.5 + (r.views || 0) * 0.01;\n"
            "}\n\n"
            "const ranked = latest.slice().sort((a, b) => score(b) - score(a));\n"
            "const topPerformingTopics = ranked.slice(0, 5).map(r => r.topic);\n"
            "const topPerformingHooks = ranked.slice(0, 5).map(r => r.title);\n"
            "const avoid = ranked.slice(-5).filter(r => score(r) < score(ranked[0]) * 0.2).map(r => r.topic);\n\n"
            "const learnings = { topPerformingTopics, topPerformingHooks, avoid, updatedAt: new Date().toISOString() };\n"
            "fs.writeFileSync(path.join(BASE_DIR, 'analytics', 'learnings.json'), JSON.stringify(learnings, null, 2));\n\n"
            "return [{ json: learnings }];"
        )
    },
    300, 1000, type_version=2,
)

wf2.link("Schedule Trigger (Analytics)", "Load Publish Log")
wf2.link("Load Publish Log", "Loop Over Videos")
wf2.link("Loop Over Videos", "Compute Learnings", src_index=0)
wf2.link("Loop Over Videos", "Get YouTube Video Stats", src_index=1)
wf2.link("Loop Over Videos", "Get YouTube Analytics Report", src_index=1)
wf2.link("Get YouTube Video Stats", "Normalize Metrics")
wf2.link("Get YouTube Analytics Report", "Normalize Metrics")
wf2.link("Normalize Metrics", "Append Analytics Store")
wf2.link("Append Analytics Store", "Loop Over Videos")

with open("n8n_workflow_analytics.json", "w", encoding="utf-8") as f:
    json.dump(wf2.export(), f, ensure_ascii=False, indent=2)
print("wrote n8n_workflow_analytics.json (", len(wf2.nodes), "nodes)")
