#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スタックチャン通知スクリプト（Claude Code hooks 用 / Windows・CH9102対応）

Claude Code のイベント種別を ASCII フラグ(--event)で受け取り、
対応する表情・日本語セリフをシリアルJSONでCore2へ送る。

設計上のポイント（STEP 0-1 / STEP 4 の調査結果を反映）:
  - 日本語セリフはこのファイル(UTF-8)内に埋め込む。
    → コマンドライン引数で日本語を渡すとWindowsで文字化けするため、
      hookからは --event done/ask/error のASCIIのみ渡す。
  - ポートは rts=False / dtr=False で開く。
    → CH9102の自動リセット回路でCore2がリセット保持され無応答になるのを防ぐ。
      無リセットで開くと動作中のCore2へ即座に送れる（ACK約0.01秒）。
  - 送信のたびにボードをリセットしないので、通知は瞬時・画面のちらつきなし。
  - 初回ACKが返らない場合のみ、明示的なリセット→再送でフォールバック。
"""
import argparse
import json
import sys
import time

import serial

DEFAULT_PORT = "COM3"
DEFAULT_BAUD = 115200
ACK_TIMEOUT = 1.5   # OK/ERR を待つ秒数
FACE_STACKCHAN = 2  # setupで初期化済みの唯一の顔(faces[2]) / palette 0,1 は未初期化なので使わない

# イベント種別 -> (表情, セリフ, 表示時間ms)
# 表情は .ino の parseExpression が解釈できる6種のみ:
#   Happy / Angry / Sad / Doubt / Sleepy / Neutral
EVENTS = {
    "done":  ("Happy", "終わったよ！見て見て！！", 5000),   # 完了 (Stop)
    "ask":   ("Doubt", "質問があります！",         6000),   # 確認待ち (Notification)
    "error": ("Sad",   "失敗しちゃった、、、",       6000),   # エラー
}


def build_payload(expression, speech, duration):
    # ensure_ascii=True(既定)で非ASCIIは\uXXXXにエスケープされ、
    # ワイヤ上はASCIIのみ。Core2側(ArduinoJson)がUTF-8へ復元する。
    return json.dumps({
        "expression": expression,
        "speech": speech,
        "face": FACE_STACKCHAN,
        "duration": duration,
    }).encode("ascii") + b"\n"


def read_ack(ser, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if not line:
            continue
        if line.startswith("OK"):
            return True, line
        if line.startswith("ERR"):
            return False, line
    return False, "timeout waiting for ACK"


def reset_to_run(ser):
    """ESP32を通常起動でリセット（EN=RTS, IO0=DTR）。フォールバック用。"""
    ser.setDTR(False)   # IO0 high -> 通常ブート
    ser.setRTS(True)    # EN low -> リセット保持
    time.sleep(0.15)
    ser.reset_input_buffer()
    ser.setRTS(False)   # EN high -> 解除して起動
    # "Ready" が来るまで最大3秒待つ
    deadline = time.time() + 3.0
    while time.time() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line.startswith("Ready"):
            return True
    return False


def open_port(port, baud):
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.2
    ser.rts = False     # 開く時にENを叩かない（リセットさせない）
    ser.dtr = False
    ser.open()
    ser.rts = False
    ser.dtr = False
    return ser


def main():
    parser = argparse.ArgumentParser(description="StackChan notifier for Claude Code hooks")
    parser.add_argument("--event", choices=sorted(EVENTS.keys()), required=True,
                        help="通知イベント種別: done(完了)/ask(確認待ち)/error(エラー)")
    parser.add_argument("--port", default=DEFAULT_PORT, help="シリアルポート (既定: %(default)s)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="ボーレート (既定: %(default)d)")
    args = parser.parse_args()

    expression, speech, duration = EVENTS[args.event]
    payload = build_payload(expression, speech, duration)

    try:
        with open_port(args.port, args.baud) as ser:
            time.sleep(0.2)
            ser.reset_input_buffer()
            ser.write(payload)
            ser.flush()
            ok, resp = read_ack(ser, ACK_TIMEOUT)

            if not ok:
                # 無応答ならボードがリセット保持等の可能性。明示リセットして再送。
                if reset_to_run(ser):
                    ser.reset_input_buffer()
                    ser.write(payload)
                    ser.flush()
                    ok, resp = read_ack(ser, ACK_TIMEOUT)

            print(f"[{args.event}] {expression} \"{speech}\" -> {resp}")
            sys.exit(0 if ok else 1)
    except serial.SerialException as exc:
        print(f"Serial error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
