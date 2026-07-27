#!/usr/bin/env python3
"""
HTTP server bọc LightSpeed (giọng NAM tiếng Việt, kế thừa từ vietTTS,
tác giả NTT123 - https://github.com/NTT123/light-speed), tương thích với
hợp đồng /tts mà n8n workflow đang gọi (giống piper_tts_server.py /
viettts_server.py).

Khác với vietTTS (dùng jax/haiku, phải vá 4 chỗ mới chạy được trên máy này),
LightSpeed là mô hình VITS thuần PyTorch, không cần jax/phonemizer/espeak,
nên setup đơn giản hơn nhiều.

Model + checkpoint được tải sẵn về từ HF Space "Vietnam-male-voice-TTS"
(cùng tác giả NTT123) vào thư mục lightspeed_assets/ cạnh file này:
  - models.py / modules.py / attentions.py / commons.py / flow.py  (kiến trúc VITS)
  - config.json                                                    (hyperparameters)
  - vbx_phone_set.json                                              (bảng phoneme)
  - vbx_duration_model.pth                                          (model dự đoán duration)
  - gen_619k.pth                                                    (generator, checkpoint 619k step - xịn nhất trong 4 checkpoint có sẵn)

Load model MỘT LẦN khi khởi động và giữ trong RAM để phục vụ nhiều request
liên tục, giống viettts_server.py.

Usage:
    python lightspeed_server.py
    # hoặc tùy biến qua biến môi trường:
    LIGHTSPEED_PORT=8003 python lightspeed_server.py
"""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf
import torch
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

ASSETS_DIR = Path(os.environ.get("LIGHTSPEED_ASSETS_DIR", Path(__file__).parent / "lightspeed_assets")).expanduser()
PORT = int(os.environ.get("LIGHTSPEED_PORT", "8003"))
DEFAULT_SILENCE_DURATION = float(os.environ.get("LIGHTSPEED_SILENCE_DURATION", "0.2"))
DEFAULT_SPEECH_RATE = float(os.environ.get("LIGHTSPEED_SPEECH_RATE", "1.0"))
VOICE = "male"  # server này chỉ phục vụ đúng 1 giọng (nam), giống ràng buộc của viettts_server.py

# models.py trong lightspeed_assets import "attentions"/"commons"/"modules"/"flow"
# theo kiểu top-level (không phải package), nên phải thêm thư mục này vào sys.path
# TRƯỚC KHI import, giống cách viettts_server.py phải chdir trước khi import vietTTS.
sys.path.insert(0, str(ASSETS_DIR))
from models import DurationNet, SynthesizerTrn  # noqa: E402

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

with open(ASSETS_DIR / "config.json", "rb") as f:
    HPS = json.load(f, object_hook=lambda x: SimpleNamespace(**x))

with open(ASSETS_DIR / "vbx_phone_set.json", "r", encoding="utf-8") as f:
    PHONE_SET = json.load(f)

assert PHONE_SET[0][1:-1] == "SEP"
assert "sil" in PHONE_SET
SIL_IDX = PHONE_SET.index("sil")
SAMPLE_RATE = HPS.data.sampling_rate

# Chuyển số -> chữ tiếng Việt (giữ nguyên logic gốc của LightSpeed).
DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
NUM_RE = re.compile(r"([0-9.,]*[0-9])")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+")


def _read_number(num: str) -> str:
    if len(num) == 1:
        return DIGITS[int(num)]
    elif len(num) == 2 and num.isdigit():
        n = int(num)
        end = DIGITS[n % 10]
        if n == 10:
            return "mười"
        if n % 10 == 5:
            end = "lăm"
        if n % 10 == 0:
            return DIGITS[n // 10] + " mươi"
        elif n < 20:
            return "mười " + end
        else:
            if n % 10 == 1:
                end = "mốt"
            return DIGITS[n // 10] + " mươi " + end
    elif len(num) == 3 and num.isdigit():
        n = int(num)
        if n % 100 == 0:
            return DIGITS[n // 100] + " trăm"
        elif num[1] == "0":
            return DIGITS[n // 100] + " trăm lẻ " + DIGITS[n % 100]
        else:
            return DIGITS[n // 100] + " trăm " + _read_number(num[1:])
    elif 4 <= len(num) <= 6 and num.isdigit():
        n = int(num)
        n1 = n // 1000
        return _read_number(str(n1)) + " ngàn " + _read_number(num[-3:])
    elif "," in num:
        n1, n2 = num.split(",")
        return _read_number(n1) + " phẩy " + _read_number(n2)
    elif "." in num:
        parts = num.split(".")
        if len(parts) == 2:
            if parts[1] == "000":
                return _read_number(parts[0]) + " ngàn"
            elif parts[1].startswith("00"):
                end = DIGITS[int(parts[1][2:])]
                return _read_number(parts[0]) + " ngàn lẻ " + end
            else:
                return _read_number(parts[0]) + " ngàn " + _read_number(parts[1])
        elif len(parts) == 3:
            return (
                _read_number(parts[0]) + " triệu " + _read_number(parts[1]) + " ngàn " + _read_number(parts[2])
            )
    return num


def _text_to_phone_idx(text: str):
    text = text.lower()
    text = unicodedata.normalize("NFKC", text)
    for ch in ".,;:!?(":
        text = text.replace(ch, f" {ch} ")

    text = NUM_RE.sub(r" \1 ", text)
    words = text.split()
    words = [_read_number(w) if NUM_RE.fullmatch(w) else w for w in words]
    text = " ".join(words)

    text = re.sub(r"\s+", " ", text).strip()

    tokens = []
    for c in text:
        if c in ":,.!?;(":
            tokens.append(SIL_IDX)
        elif c in PHONE_SET:
            tokens.append(PHONE_SET.index(c))
        elif c == " ":
            tokens.append(0)  # <SEP> phone

    if not tokens:
        tokens = [SIL_IDX, 0, SIL_IDX]
    if tokens[0] != SIL_IDX:
        tokens = [SIL_IDX, 0] + tokens
    if tokens[-1] != SIL_IDX:
        tokens = tokens + [0, SIL_IDX]
    return tokens


def _load_models():
    duration_net = DurationNet(HPS.data.vocab_size, 64, 4).to(DEVICE)
    duration_net.load_state_dict(torch.load(ASSETS_DIR / "vbx_duration_model.pth", map_location=DEVICE))
    duration_net = duration_net.eval()

    generator = SynthesizerTrn(
        HPS.data.vocab_size,
        HPS.data.filter_length // 2 + 1,
        HPS.train.segment_size // HPS.data.hop_length,
        **vars(HPS.model),
    ).to(DEVICE)
    del generator.enc_q
    ckpt = torch.load(ASSETS_DIR / "gen_619k.pth", map_location=DEVICE)
    params = {}
    for k, v in ckpt["net_g"].items():
        k = k[7:] if k.startswith("module.") else k
        params[k] = v
    generator.load_state_dict(params, strict=False)
    generator = generator.eval()
    return duration_net, generator


print(f"[lightspeed_server] loading models from {ASSETS_DIR} on device={DEVICE} ...", flush=True)
DURATION_NET, GENERATOR = _load_models()
print("[lightspeed_server] models loaded, ready to serve.", flush=True)


def _synthesize_sentence(text: str, silence_ms: float, speech_rate: float) -> np.ndarray:
    phone_idx = _text_to_phone_idx(text)
    phone_idx_t = torch.tensor([phone_idx], dtype=torch.long, device=DEVICE)
    phone_length_t = torch.tensor([len(phone_idx)], dtype=torch.long, device=DEVICE)

    with torch.inference_mode():
        phone_duration = DURATION_NET(phone_idx_t, phone_length_t)[:, :, 0] * 1000

    # >1 nói nhanh hơn, <1 nói chậm hơn (cùng quy ước với viettts_server.py / piper_tts_server.py)
    phone_duration = phone_duration / speech_rate
    phone_duration = torch.where(
        phone_idx_t == SIL_IDX, torch.clamp_min(phone_duration, silence_ms), phone_duration
    )
    phone_duration = torch.where(phone_idx_t == 0, torch.zeros_like(phone_duration), phone_duration)

    end_time = torch.cumsum(phone_duration, dim=-1)
    start_time = end_time - phone_duration
    start_frame = start_time / 1000 * HPS.data.sampling_rate / HPS.data.hop_length
    end_frame = end_time / 1000 * HPS.data.sampling_rate / HPS.data.hop_length
    spec_length = end_frame.max(dim=-1).values
    pos = torch.arange(0, int(spec_length.item()), device=DEVICE)
    attn = torch.logical_and(
        pos[None, :, None] >= start_frame[:, None, :],
        pos[None, :, None] < end_frame[:, None, :],
    ).float()

    with torch.inference_mode():
        y_hat = GENERATOR.infer(
            phone_idx_t, phone_length_t, spec_length, attn, max_len=None, noise_scale=0.667
        )[0]
    return y_hat[0, 0].data.cpu().numpy()


def _synthesize(text: str, silence_duration: float, speech_rate: float) -> np.ndarray:
    silence_ms = max(1.0, silence_duration * 1000)
    # Chia theo câu (thay vì cắt cứng ở 500 ký tự như app.py gốc) để không mất
    # nội dung với narration dài; mỗi câu synth riêng rồi nối lại.
    chunks = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(para) if s.strip()]
        for sentence in sentences or [para]:
            chunks.append(_synthesize_sentence(sentence, silence_ms, speech_rate))

    if not chunks:
        raise ValueError("text is empty after normalization")
    return np.concatenate(chunks)


app = FastAPI()


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None  # chỉ để tương thích jsonBody hiện có, server này chỉ có 1 giọng nam
    silence_duration: float | None = None
    speech_rate: float | None = None  # >1 nhanh hơn, <1 chậm hơn
    length_scale: float | None = None  # tương thích jsonBody cũ: >1 chậm hơn, <1 nhanh hơn


@app.post("/tts")
def tts(req: TTSRequest, background_tasks: BackgroundTasks):
    if not req.text.strip():
        raise HTTPException(400, "text is empty")

    if req.voice and req.voice not in (VOICE, "infore", "male"):
        raise HTTPException(
            400,
            f"Server này chỉ phục vụ giọng nam duy nhất ('{VOICE}'). "
            f"Không hỗ trợ đổi giọng '{req.voice}' trên server này.",
        )

    silence_duration = req.silence_duration if req.silence_duration is not None else DEFAULT_SILENCE_DURATION

    if req.speech_rate is not None:
        speech_rate = req.speech_rate
    elif req.length_scale is not None:
        if req.length_scale <= 0:
            raise HTTPException(400, "length_scale must be > 0")
        speech_rate = 1.0 / req.length_scale
    else:
        speech_rate = DEFAULT_SPEECH_RATE

    if speech_rate <= 0:
        raise HTTPException(400, "speech_rate must be > 0")
    speech_rate = max(0.6, min(1.8, float(speech_rate)))

    import tempfile

    out_fd, out_path_str = tempfile.mkstemp(suffix=".wav")
    os.close(out_fd)
    out_path = Path(out_path_str)

    try:
        wave = _synthesize(req.text, silence_duration, speech_rate)
        sf.write(str(out_path), wave, samplerate=SAMPLE_RATE, subtype="PCM_16")
    except Exception as e:
        if out_path.exists():
            out_path.unlink()
        raise HTTPException(500, f"LightSpeed synth error: {e}")

    background_tasks.add_task(lambda p: p.exists() and p.unlink(), out_path)
    return FileResponse(str(out_path), media_type="audio/wav", filename="narration.wav")


if __name__ == "__main__":
    import uvicorn

    print(f"[lightspeed_server] voice={VOICE} assets_dir={ASSETS_DIR} port={PORT}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
