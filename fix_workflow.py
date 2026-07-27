import json
import re

PATH = "n8n_workflow_full.json"

with open(PATH, "r", encoding="utf-8") as f:
    text = f.read()

save_video_metadata_code = r"""const BACKSLASH = String.fromCharCode(92);
const NEWLINE = String.fromCharCode(10);
const CARRIAGE_RETURN = String.fromCharCode(13);

function repairJsonQuotes(text) {
  let result = '';
  let inString = false;
  let escapeNext = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (!inString) {
      result += ch;
      if (ch === '"') inString = true;
      continue;
    }
    if (escapeNext) {
      result += ch;
      escapeNext = false;
      continue;
    }
    if (ch === BACKSLASH) {
      result += ch;
      escapeNext = true;
      continue;
    }
    if (ch === '"') {
      let j = i + 1;
      while (j < text.length && /\s/.test(text[j])) j++;
      const next = text[j];
      if (next === undefined || next === ',' || next === '}' || next === ']' || next === ':') {
        result += ch;
        inString = false;
      } else {
        result += BACKSLASH + '"';
      }
      continue;
    }
    if (ch === NEWLINE) {
      result += BACKSLASH + 'n';
      continue;
    }
    if (ch === CARRIAGE_RETURN) {
      continue;
    }
    result += ch;
  }
  return result;
}

function safeJsonParse(text, sourceName) {
  try {
    return JSON.parse(text);
  } catch (e1) {
    try {
      return JSON.parse(repairJsonQuotes(text));
    } catch (e2) {
      throw new Error(`${sourceName} output không phải JSON hợp lệ (đã thử tự sửa nhưng vẫn lỗi): ${e2.message}`);
    }
  }
}

let raw = $input.first().json.output;
if (typeof raw === 'string') {
  raw = raw.trim();
  const fenceMatch = raw.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenceMatch) raw = fenceMatch[1];
}

const data = safeJsonParse(raw, 'Research Agent');

const staticData = $getWorkflowStaticData('global');
staticData.videoMeta = {
  title: data.title || '',
  description: data.description || '',
  hashtags: Array.isArray(data.hashtags) ? data.hashtags : [],
  tags: Array.isArray(data.tags) ? data.tags : [],
  cta: data.cta || ''
};

return [{ json: staticData.videoMeta }];"""

normalize_scene_data_code = r"""const BACKSLASH = String.fromCharCode(92);
const NEWLINE = String.fromCharCode(10);
const CARRIAGE_RETURN = String.fromCharCode(13);

function repairJsonQuotes(text) {
  let result = '';
  let inString = false;
  let escapeNext = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (!inString) {
      result += ch;
      if (ch === '"') inString = true;
      continue;
    }
    if (escapeNext) {
      result += ch;
      escapeNext = false;
      continue;
    }
    if (ch === BACKSLASH) {
      result += ch;
      escapeNext = true;
      continue;
    }
    if (ch === '"') {
      let j = i + 1;
      while (j < text.length && /\s/.test(text[j])) j++;
      const next = text[j];
      if (next === undefined || next === ',' || next === '}' || next === ']' || next === ':') {
        result += ch;
        inString = false;
      } else {
        result += BACKSLASH + '"';
      }
      continue;
    }
    if (ch === NEWLINE) {
      result += BACKSLASH + 'n';
      continue;
    }
    if (ch === CARRIAGE_RETURN) {
      continue;
    }
    result += ch;
  }
  return result;
}

function safeJsonParse(text, sourceName) {
  try {
    return JSON.parse(text);
  } catch (e1) {
    try {
      return JSON.parse(repairJsonQuotes(text));
    } catch (e2) {
      throw new Error(`${sourceName} output không phải JSON hợp lệ (đã thử tự sửa nhưng vẫn lỗi): ${e2.message}`);
    }
  }
}

return $input.all().flatMap(item => {
  let raw = item.json.output;
  if (typeof raw === 'string') {
    raw = raw.trim();
    const fenceMatch = raw.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
    if (fenceMatch) raw = fenceMatch[1];
  }

  const data = safeJsonParse(raw, 'Screen Planner');

  // Loại bỏ scene có narration rỗng/placeholder, tránh lỗi Piper TTS "text is empty"
  const cleanScenes = data.scenes.filter(scene => {
    const text = (scene.narration || '').trim();
    return text.length > 0 && !/^\(.*\)$/.test(text); // loại luôn các placeholder dạng "(...)"
  });

  return cleanScenes.map(scene => ({
    json: {
      video_style: data.video_style,
      theme: data.theme,
      aspect_ratio: data.aspect_ratio,
      fps: data.fps,
      ...scene
    }
  }));
});"""

replacements = [
    ("Save Video Metadata", save_video_metadata_code, '"a1b2c3d4-0001-4aaa-8aaa-000000000001"'),
    ("normalize scene data", normalize_scene_data_code, '"ba240150-b220-42e8-aafc-f217925492a6"'),
]

for name, code, id_marker in replacements:
    id_pos = text.find(id_marker)
    if id_pos == -1:
        raise SystemExit(f"Could not find id marker for {name}")
    # Find the start of this node object: walk backward to the nearest '{' that starts the node
    node_start = text.rfind('\n    {\n', 0, id_pos)
    if node_start == -1:
        raise SystemExit(f"Could not find node start for {name}")
    # Find the end of this node object: the matching '\n    },\n' or '\n    }\n  ],' after id_pos
    node_end_match = re.search(r'\n    \}(,)?\n', text[id_pos:])
    if not node_end_match:
        raise SystemExit(f"Could not find node end for {name}")
    node_end = id_pos + node_end_match.end()

    node_text = text[node_start:node_end]

    jscode_match = re.search(r'"jsCode":\s*"', node_text)
    if not jscode_match:
        raise SystemExit(f"Could not find jsCode field for {name}")

    # Find end of the jsCode string value by scanning for unescaped closing quote
    i = jscode_match.end()
    while True:
        if node_text[i] == '\\':
            i += 2
            continue
        if node_text[i] == '"':
            break
        i += 1
    jscode_value_end = i + 1  # include closing quote

    new_jscode_field = '"jsCode": ' + json.dumps(code)
    new_node_text = node_text[:jscode_match.start()] + new_jscode_field + node_text[jscode_value_end:]

    text = text[:node_start] + new_node_text + text[node_end:]
    print(f"Replaced jsCode for {name}: {len(code)} chars")

with open(PATH, "w", encoding="utf-8") as f:
    f.write(text)

# Validate
with open(PATH, "r", encoding="utf-8") as f:
    data = json.load(f)
print("JSON valid. nodes:", len(data["nodes"]))
