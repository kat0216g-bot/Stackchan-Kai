#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スタックチャン用の固定フレーズ音声をVOICEVOXで一括生成するツール。

設計方針（2026-07-29）:
  - 喋らせるフレーズは限定的（Claude Code通知 / 株取引 / 多肉植物モニター）なので、
    実行時にリアルタイム合成せず、**事前に生成したWAVをCore2に保存して再生**する。
    → 実行時のPC/Raspberry Pi側の負荷はゼロ（小さなJSONコマンドを送るだけ）。
  - 数値を含むフレーズも「取りうる値の全パターンを事前生成」すれば同じ仕組みで扱える
    （気温0〜40℃なら41ファイル等）。ファームの変更は不要でファイルを足すだけ。

使い方:
  1. VOICEVOXエンジンを起動（GUIでも可。headlessなら下記）:
       "C:\\Program Files\\VOICEVOX\\vv-engine\\run.exe" --port 9021 --host 127.0.0.1
     ※ポートは49152以上（Windowsの動的ポート範囲）だと他アプリに奪われることがあるため、
       それ未満の値を明示指定するのが安全。
  2. python tools/generate_voices.py
  3. 生成されたWAVが assets/voices/ に出力される。

Core2側はRAM節約のため 16kHz モノラル で出力する（通知用途には十分な音質）。
"""
import json
import pathlib
import sys
import urllib.parse
import urllib.request

VOICEVOX_HOST = "127.0.0.1"
VOICEVOX_PORT = 9021
SPEAKER_ID = 3          # ずんだもん(ノーマル)。/speakers で一覧取得可能
OUTPUT_SAMPLING_RATE = 16000
OUTPUT_STEREO = False

OUTPUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "assets" / "voices"

# ファイル名 -> 読み上げるテキスト
# Claude Code通知の3イベントに限定して開始（stackchan_notify.py の EVENTS と対応）。
PHRASES = {
    "done":  "終わったよ！見て見て！",
    "ask":   "質問があります！",
    "error": "失敗しちゃった",
}


def base_url():
    return f"http://{VOICEVOX_HOST}:{VOICEVOX_PORT}"


def synthesize(text, speaker=SPEAKER_ID):
    """VOICEVOXでテキストを音声合成し、WAVバイト列を返す。"""
    # 1) audio_query: テキストから合成用パラメータを作る
    query_url = f"{base_url()}/audio_query?speaker={speaker}&text={urllib.parse.quote(text)}"
    req = urllib.request.Request(query_url, method="POST")
    with urllib.request.urlopen(req) as res:
        query = json.load(res)

    # Core2のRAM節約のためサンプリングレートを落とす
    query["outputSamplingRate"] = OUTPUT_SAMPLING_RATE
    query["outputStereo"] = OUTPUT_STEREO

    # 2) synthesis: パラメータからWAVを生成
    syn_url = f"{base_url()}/synthesis?speaker={speaker}"
    req2 = urllib.request.Request(
        syn_url,
        data=json.dumps(query).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req2) as res:
        return res.read()


def main():
    try:
        with urllib.request.urlopen(f"{base_url()}/version", timeout=5) as res:
            version = res.read().decode("utf-8").strip()
    except OSError as exc:
        print(f"VOICEVOXエンジンに接続できません ({base_url()}): {exc}")
        print("エンジンを起動してから再実行してください。")
        sys.exit(1)

    print(f"VOICEVOX {version} に接続 (speaker={SPEAKER_ID}, {OUTPUT_SAMPLING_RATE}Hz mono)")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    total = 0
    for name, text in PHRASES.items():
        wav = synthesize(text)
        out_path = OUTPUT_DIR / f"{name}.wav"
        out_path.write_bytes(wav)
        total += len(wav)
        print(f"  {name}.wav  {len(wav):>7,} bytes  \"{text}\"")

    print(f"合計 {total:,} bytes -> {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
