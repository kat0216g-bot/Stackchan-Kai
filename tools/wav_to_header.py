#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
assets/voices/*.wav を Arduino スケッチ用の C ヘッダ(voices.h)に変換する。

なぜ埋め込み方式か（2026-07-29時点の判断）:
  - Claude Code通知の3フレーズで合計約158KBと小さく、スケッチ領域(6.5MB中1.34MB使用)に
    十分収まる。LittleFSのイメージ作成・パーティションオフセット指定といった
    失敗リスクのある手順を回避できる。
  - 将来フレーズが数MB規模に増えたらLittleFSやSDカードへ移行する。
    その際は「WiFi経由で音声ファイルを追加する仕組み」も入れると、
    フレーズ追加のたびにUSBを差し替える必要がなくなる。

使い方:
  python tools/wav_to_header.py
  -> base_firmware/.../voices.h と firmware/.../voices.h に出力
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
VOICE_DIR = ROOT / "assets" / "voices"
OUTPUTS = [
    ROOT / "base_firmware" / "M5Core2_SG90_StackChan_VoiceText_Ataru" / "voices.h",
    ROOT / "firmware" / "M5Core2_SG90_StackChan_VoiceText_Ataru" / "voices.h",
]

BYTES_PER_LINE = 16


def to_c_array(name, data):
    lines = [f"const uint8_t {name}[] = {{"]
    for i in range(0, len(data), BYTES_PER_LINE):
        chunk = data[i:i + BYTES_PER_LINE]
        lines.append("  " + "".join(f"0x{b:02x}, " for b in chunk).rstrip())
    lines.append("};")
    return "\n".join(lines)


def main():
    wavs = sorted(VOICE_DIR.glob("*.wav"))
    if not wavs:
        print(f"WAVが見つかりません: {VOICE_DIR}")
        print("先に python tools/generate_voices.py を実行してください。")
        return

    parts = [
        "// 自動生成ファイル - 直接編集しないこと。",
        "// 生成元: tools/wav_to_header.py (素材は assets/voices/*.wav)",
        "// フレーズを変更する場合は tools/generate_voices.py で再生成してから本スクリプトを実行する。",
        "#pragma once",
        "#include <stdint.h>",
        "",
    ]

    names = []
    total = 0
    for wav in wavs:
        data = wav.read_bytes()
        var = f"voice_{wav.stem}"
        parts.append(to_c_array(var, data))
        parts.append("")
        names.append((wav.stem, var))
        total += len(data)
        print(f"  {wav.name}: {len(data):,} bytes -> {var}")

    # 名前から音声データを引くためのテーブル
    parts.append("struct VoiceEntry {")
    parts.append("  const char *name;")
    parts.append("  const uint8_t *data;")
    parts.append("  size_t length;")
    parts.append("};")
    parts.append("")
    parts.append("const VoiceEntry kVoiceTable[] = {")
    for stem, var in names:
        parts.append(f'  {{"{stem}", {var}, sizeof({var})}},')
    parts.append("};")
    parts.append(f"const size_t kVoiceCount = {len(names)};")
    parts.append("")

    content = "\n".join(parts)
    for out in OUTPUTS:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
        print(f"出力: {out}")
    print(f"合計 {total:,} bytes / {len(names)} ファイル")


if __name__ == "__main__":
    main()
