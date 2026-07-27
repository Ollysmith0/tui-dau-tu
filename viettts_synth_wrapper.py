#!/usr/bin/env python3
"""
Wrapper quanh vietTTS synthesizer, hỗ trợ chọn giọng bằng cách trỏ FLAGS
đến đúng thư mục model.

Mỗi giọng cần có cấu trúc thư mục:
  {viettts_dir}/assets/{voice}/
      nat/
          duration_latest_ckpt.pickle
          acoustic_latest_ckpt.pickle
      hifigan/
          hk_hifi.pickle
      lexicon.txt

Và file dùng chung (kiến trúc HiFiGAN):
  {viettts_dir}/assets/hifigan/config.json

Dùng trong quick_start.sh để tải model infore:
  bash scripts/quick_start.sh

Usage:
    python viettts_synth_wrapper.py \\
        --text "xin chào" \\
        --output /tmp/out.wav \\
        --voice infore \\
        --viettts-dir ~/vietTTS \\
        --silence-duration 0.2
"""
import argparse
import os
import re
import unicodedata
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--text", required=True)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--voice", default="infore")
parser.add_argument("--viettts-dir", required=True, type=Path)
parser.add_argument("--silence-duration", type=float, default=0.2)
args = parser.parse_args()

# Phải chuyển CWD về vietTTS trước khi import — nhiều path trong vietTTS là relative
os.chdir(args.viettts_dir)

# Patch cả hai FLAGS TRƯỚC KHI import bất kỳ module nào của vietTTS
import vietTTS.nat.config as nat_cfg
import vietTTS.hifigan.config as hifi_cfg

nat_cfg.FLAGS.ckpt_dir = args.viettts_dir / "assets" / args.voice / "nat"
hifi_cfg.FLAGS.ckpt_dir = args.viettts_dir / "assets" / args.voice / "hifigan"

import soundfile as sf
from vietTTS.hifigan.mel2wave import mel2wave
from vietTTS.nat.text2mel import text2mel


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().strip()
    sil = nat_cfg.FLAGS.special_phonemes[nat_cfg.FLAGS.sil_index]
    text = re.sub(r"[\n.,:;?!]+", f" {sil} ", text)
    text = text.replace('"', " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(f"( {sil}+)+ ", f" {sil} ", text)
    return text.strip()


normalized = _normalize(args.text)
print(f"[viettts] voice={args.voice}  text={normalized[:80]}", flush=True)

lexicon_file = args.viettts_dir / "assets" / args.voice / "lexicon.txt"
mel = text2mel(normalized, lexicon_file, args.silence_duration)
wave = mel2wave(mel)

sf.write(str(args.output), wave, samplerate=16000)
print(f"[viettts] saved → {args.output}", flush=True)
