"""
TTS server dùng vietTTS (https://github.com/NTT123/vietTTS).

Biến môi trường:
  VIETTTS_DIR  — thư mục repo vietTTS đã clone (mặc định ~/vietTTS)

Mỗi giọng là một thư mục con dưới {VIETTTS_DIR}/assets/:
  assets/{voice}/nat/duration_latest_ckpt.pickle
  assets/{voice}/nat/acoustic_latest_ckpt.pickle
  assets/{voice}/hifigan/hk_hifi.pickle
  assets/{voice}/lexicon.txt

Tải model mặc định (giọng infore):
  cd ~/vietTTS && bash scripts/quick_start.sh

Endpoints:
  GET  /voices          — liệt kê tất cả giọng khả dụng
  POST /tts             — tổng hợp giọng nói, trả về file WAV 16 kHz
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

VIETTTS_DIR = Path(os.environ.get("VIETTTS_DIR", Path.home() / "vietTTS"))
WRAPPER_SCRIPT = Path(__file__).parent / "viettts_synth_wrapper.py"
DEFAULT_VOICE = "infore"

app = FastAPI(title="vietTTS Server", version="2.0")


class TTSRequest(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    # Khoảng lặng (giây) sau dấu câu — giá trị âm = để mô hình tự quyết định
    silence_duration: float = 0.2


@app.get("/voices")
def list_voices():
    """Liệt kê các giọng đã cài đặt (mỗi giọng là một thư mục trong assets/)."""
    assets_dir = VIETTTS_DIR / "assets"
    voices = []
    if assets_dir.exists():
        for d in sorted(assets_dir.iterdir()):
            if (
                d.is_dir()
                and (d / "lexicon.txt").exists()
                and (d / "nat").is_dir()
                and (d / "hifigan").is_dir()
            ):
                voices.append(d.name)
    return {"voices": voices, "default": DEFAULT_VOICE}


@app.post("/tts")
def tts(req: TTSRequest, background_tasks: BackgroundTasks):
    if not req.text.strip():
        raise HTTPException(400, "text is empty")

    lexicon_file = VIETTTS_DIR / "assets" / req.voice / "lexicon.txt"
    if not lexicon_file.exists():
        available = list_voices()["voices"]
        raise HTTPException(
            400,
            f"Voice '{req.voice}' not found. "
            f"Available: {available}. "
            f"Run 'bash scripts/quick_start.sh' inside {VIETTTS_DIR} to download the default model.",
        )

    out_fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(out_fd)

    result = subprocess.run(
        [
            sys.executable,
            str(WRAPPER_SCRIPT),
            "--text", req.text,
            "--output", out_path,
            "--voice", req.voice,
            "--viettts-dir", str(VIETTTS_DIR),
            "--silence-duration", str(req.silence_duration),
        ],
        capture_output=True,
        timeout=180,
    )

    if result.returncode != 0:
        if os.path.exists(out_path):
            os.remove(out_path)
        raise HTTPException(
            500,
            result.stderr.decode("utf-8", "ignore")[:3000]
            or result.stdout.decode("utf-8", "ignore")[:1000],
        )

    background_tasks.add_task(lambda p: os.path.exists(p) and os.remove(p), out_path)
    return FileResponse(out_path, media_type="audio/wav", filename="narration.wav")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)