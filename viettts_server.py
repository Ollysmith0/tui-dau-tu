#!/usr/bin/env python3
"""
HTTP server bọc vietTTS, tương thích với hợp đồng /tts mà n8n workflow
đang gọi (giống piper_tts_server.py), nhưng dùng vietTTS thay cho Piper.

Khác với viettts_synth_wrapper.py (CLI chạy 1 lần rồi thoát), server này
load model NAT + HiFiGAN MỘT LẦN khi khởi động và giữ trong RAM để phục vụ
nhiều request liên tục — tránh việc mỗi scene phải load lại model JAX
(rất tốn thời gian).

Giới hạn quan trọng: vietTTS patch đường dẫn model qua FLAGS TRƯỚC KHI
import module, nên server này chỉ phục vụ ĐÚNG MỘT giọng (voice) cố định
cho mỗi lần khởi động — khớp với cách workflow hiện tại luôn dùng 1 giọng
xuyên suốt 1 video. Muốn đổi giọng thì đổi biến VOICE bên dưới rồi khởi
động lại server (không đổi được giọng "nóng" giữa lúc server đang chạy).

Usage:
    python viettts_server.py
    # hoặc tùy biến qua biến môi trường:
    VIETTTS_DIR=/Users/tuht1/vietTTS VIETTTS_VOICE=infore VIETTTS_PORT=8002 \
        python viettts_server.py
"""
import os
import re
import tempfile
import unicodedata
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
import numpy as np
from pydantic import BaseModel

VIETTTS_DIR = Path(os.environ.get("VIETTTS_DIR", "/Users/tuht1/vietTTS")).expanduser()
VOICE = os.environ.get("VIETTTS_VOICE", "infore")
PORT = int(os.environ.get("VIETTTS_PORT", "8002"))
DEFAULT_SILENCE_DURATION = float(os.environ.get("VIETTTS_SILENCE_DURATION", "0.2"))
DEFAULT_SPEECH_RATE = float(os.environ.get("VIETTTS_SPEECH_RATE", "1.0"))
SAMPLE_RATE = 16000

# Phải chuyển CWD về vietTTS trước khi import — nhiều path trong vietTTS là relative
os.chdir(VIETTTS_DIR)

# vietTTS (không còn được bảo trì từ 2021) gọi jax.tree_map() trực tiếp —
# API này đã bị xoá khỏi các bản jax mới (chuyển hẳn sang jax.tree_util.tree_map).
# Vá lại bằng alias thay vì hạ cấp jax (jax quá cũ không có wheel cho macOS arm64).
import jax
import jax.numpy as jnp
import jax.tree_util

if not hasattr(jax, "tree_map"):
    jax.tree_map = jax.tree_util.tree_map
if not hasattr(jax, "tree_multimap"):
    jax.tree_multimap = jax.tree_util.tree_map

# vietTTS cũng gọi jnp.clip(x, a_min=..., a_max=...) — kwargs cũ đã bị đổi
# tên thành min/max trong các bản jax/numpy mới. Bọc lại cho tương thích ngược.
_orig_clip = jnp.clip


def _compat_clip(*args, a_min=None, a_max=None, **kwargs):
    if a_min is not None:
        kwargs.setdefault("min", a_min)
    if a_max is not None:
        kwargs.setdefault("max", a_max)
    return _orig_clip(*args, **kwargs)


jnp.clip = _compat_clip

# Patch FLAGS TRƯỚC KHI import bất kỳ module nào của vietTTS (chỉ 1 lần, chỉ 1 voice)
import vietTTS.nat.config as nat_cfg
import vietTTS.hifigan.config as hifi_cfg

nat_cfg.FLAGS.ckpt_dir = VIETTTS_DIR / "assets" / VOICE / "nat"
hifi_cfg.FLAGS.ckpt_dir = VIETTTS_DIR / "assets" / VOICE / "hifigan"

import soundfile as sf
from vietTTS.hifigan.mel2wave import mel2wave
import vietTTS.nat.text2mel as nat_text2mel

# FIX (loi lap lai "'f' is not in list" lam crash toan bo cau narration):
# vietTTS.nat.text2mel.text2tokens() tra cuu tung tu qua lexicon.txt, sau do
# tra cuu TUNG PHONEME cua tu do bang phonemes.index(pp) KHONG bat loi. Mot so
# entry trong lexicon.txt (file du lieu co san cua vietTTS, khong con bao tri
# tu 2021) dung ky hieu phoneme (vd 'f', dung cho tu muon nuoc ngoai) da KHONG
# con nam trong bo phoneme thuc su cua checkpoint model da train -> ValueError
# "'f' is not in list", lam crash CA CAU chi vi MOT tu bi le. Vá lai ham nay
# (monkeypatch, khong sua source vietTTS) de khi lexicon tra ve phoneme la
# duong voi bo phoneme cua model, fallback ve tokenize tung ky tu cho tu do
# (giong nhanh xu ly tu OOV co san) thay vi nem loi lam hong ca request.
_orig_load_lexicon = nat_text2mel.load_lexicon


def _safe_text2tokens(text, lexicon_fn):
    phonemes = nat_text2mel.load_phonemes_set()
    lexicon = _orig_load_lexicon(lexicon_fn)

    words = text.strip().lower().split()
    tokens = [nat_cfg.FLAGS.sil_index]
    for word in words:
        if word in nat_cfg.FLAGS.special_phonemes:
            tokens.append(phonemes.index(word))
            continue
        if word in lexicon:
            ps = lexicon[word].split()
            try:
                tokens.extend(phonemes.index(pp) for pp in ps)
                tokens.append(nat_cfg.FLAGS.word_end_index)
                continue
            except ValueError:
                pass  # roi xuong fallback tung ky tu ben duoi cho tu nay
        for ch in word:
            if ch in phonemes:
                tokens.append(phonemes.index(ch))
        tokens.append(nat_cfg.FLAGS.word_end_index)
    tokens.append(nat_cfg.FLAGS.sil_index)
    return tokens


nat_text2mel.text2tokens = _safe_text2tokens

LEXICON_FILE = VIETTTS_DIR / "assets" / VOICE / "lexicon.txt"


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    sil = nat_cfg.FLAGS.special_phonemes[nat_cfg.FLAGS.sil_index]
    text = re.sub(r"[\n.,:;?!]+", f" {sil} ", text)
    text = text.replace('"', " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(f"( {sil}+)+ ", f" {sil} ", text)
    return text.strip()


app = FastAPI()


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None  # chỉ để tương thích jsonBody hiện có, không dùng để đổi giọng nóng
    silence_duration: float | None = None
    speech_rate: float | None = None  # >1 nhanh hơn, <1 chậm hơn
    length_scale: float | None = None  # tương thích jsonBody cũ: >1 chậm hơn, <1 nhanh hơn


def _text2mel_with_rate(text: str, silence_duration: float, speech_rate: float):
    tokens = nat_text2mel.text2tokens(text, LEXICON_FILE)
    durations = nat_text2mel.predict_duration(tokens)

    # speed control: tăng speech_rate thì giảm durations để nói nhanh hơn.
    durations = durations / speech_rate
    durations = jnp.where(
        np.array(tokens)[None, :] == nat_cfg.FLAGS.sil_index,
        jnp.clip(durations, a_min=silence_duration, a_max=None),
        durations,
    )
    durations = jnp.where(
        np.array(tokens)[None, :] == nat_cfg.FLAGS.word_end_index, 0.0, durations
    )

    mels = nat_text2mel.predict_mel(tokens, durations)
    if tokens[-1] == nat_cfg.FLAGS.sil_index:
        end_silence = durations[0, -1].item()
        silence_frame = int(end_silence * nat_cfg.FLAGS.sample_rate / (nat_cfg.FLAGS.n_fft // 4))
        mels = mels[:, : (mels.shape[1] - silence_frame)]
    return mels


@app.post("/tts")
def tts(req: TTSRequest, background_tasks: BackgroundTasks):
    if not req.text.strip():
        raise HTTPException(400, "text is empty")

    if req.voice and req.voice != VOICE:
        raise HTTPException(
            400,
            f"Server này chỉ phục vụ giọng '{VOICE}' (đã load sẵn khi khởi động). "
            f"Muốn dùng giọng '{req.voice}', khởi động lại server với VIETTTS_VOICE={req.voice}.",
        )

    silence_duration = req.silence_duration if req.silence_duration is not None else DEFAULT_SILENCE_DURATION

    # Ưu tiên tham số mới speech_rate. Nếu không có, map từ length_scale cũ.
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

    # Giữ phạm vi an toàn để tránh artefacts nặng hoặc lỗi số học.
    speech_rate = max(0.6, min(1.8, float(speech_rate)))

    out_fd, out_path_str = tempfile.mkstemp(suffix=".wav")
    os.close(out_fd)
    out_path = Path(out_path_str)

    try:
        normalized = _normalize(req.text)
        mel = _text2mel_with_rate(normalized, silence_duration, speech_rate)
        wave = mel2wave(mel)
        sf.write(str(out_path), wave, samplerate=SAMPLE_RATE)
    except Exception as e:
        if out_path.exists():
            out_path.unlink()
        raise HTTPException(500, f"vietTTS synth error: {e}")

    background_tasks.add_task(lambda p: p.exists() and p.unlink(), out_path)
    return FileResponse(str(out_path), media_type="audio/wav", filename="narration.wav")


if __name__ == "__main__":
    import uvicorn

    print(f"[viettts_server] voice={VOICE} viettts_dir={VIETTTS_DIR} port={PORT}", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=PORT)