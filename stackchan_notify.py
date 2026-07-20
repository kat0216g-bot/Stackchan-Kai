#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スタックチャン通知スクリプト（Claude Code hooks 用 / WiFi版）

Claude Code のイベント種別を ASCII フラグ(--event)で受け取り、
対応する表情・日本語セリフをJSONでCore2へ送る。

設計上のポイント（STEP 0-1/4/5(B) の調査結果を反映）:
  - サーボ用電源はスタックチャン本体の電源Type-Cからのみ供給され、
    その場合本体USB-C（データ）は使えない（給電専用ポートのため）。
    → PCとの通信はUSBシリアルではなくWiFi(TCP)で行う。
  - 日本語セリフはこのファイル(UTF-8)内に埋め込む。
    → コマンドライン引数で日本語を渡すとWindowsで文字化けするため、
      hookからは --event done/ask/error のASCIIのみ渡す。
  - 既定の接続先は mDNS ホスト名 stackchan.local:3300。
    Windowsの名前解決でmDNSが引けない環境向けに --host でIP直指定も可能。
  - 旧シリアル版は --transport serial で引き続き利用可能（デバッグ用に残置）。
"""
import argparse
import json
import socket
import sys
import time

DEFAULT_HOST = "stackchan.local"
DEFAULT_TCP_PORT = 3300
DEFAULT_SERIAL_PORT = "COM3"
DEFAULT_BAUD = 115200
ACK_TIMEOUT = 3.0   # OK/ERR を待つ秒数（WiFi経由は初回接続に時間がかかることがあるため長め）
FACE_STACKCHAN = 2  # setupで初期化済みの唯一の顔(faces[2]) / palette 0,1 は未初期化なので使わない

# イベント種別 -> (表情, セリフ, 表示時間ms)
# 表情は .ino の parseExpression が解釈できる6種のみ:
#   Happy / Angry / Sad / Doubt / Sleepy / Neutral
EVENTS = {
    "done":  ("Happy", "終わったよ！見て見て！！", 8000),    # 完了 (Stop)
    "ask":   ("Doubt", "質問があります！",        12000),    # 確認待ち (Notification) 気づくまで長めに
    "error": ("Sad",   "失敗しちゃった、、、",     10000),    # エラー
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


def send_via_wifi(host, port, payload, timeout):
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload)
        sock.settimeout(timeout)
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = sock.recv(256)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                break
        resp = buf.decode("utf-8", errors="replace").strip()
        if resp.startswith("OK"):
            return True, resp
        if resp.startswith("ERR"):
            return False, resp
        return False, resp or "timeout waiting for ACK"


def send_via_serial(port, baud, payload, timeout):
    import serial  # 遅延importでWiFi専用運用時にpyserial必須にしない

    ser = serial.Serial()
    ser.port = port
    ser.baudrate = baud
    ser.timeout = 0.2
    ser.rts = False   # 開く時にENを叩かない（CH9102のリセット保持を防ぐ）
    ser.dtr = False
    ser.open()
    ser.rts = False
    ser.dtr = False
    try:
        time.sleep(0.2)
        ser.reset_input_buffer()
        ser.write(payload)
        ser.flush()
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
    finally:
        ser.close()


def main():
    parser = argparse.ArgumentParser(description="StackChan notifier for Claude Code hooks")
    parser.add_argument("--event", choices=sorted(EVENTS.keys()), required=True,
                        help="通知イベント種別: done(完了)/ask(確認待ち)/error(エラー)")
    parser.add_argument("--transport", choices=["wifi", "serial"], default="wifi",
                        help="通信経路 (既定: %(default)s)。serialはサーボ電源が来ないデバッグ専用。")
    parser.add_argument("--host", default=DEFAULT_HOST, help="WiFi接続先ホスト名/IP (既定: %(default)s)")
    parser.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT, help="WiFi接続先TCPポート (既定: %(default)d)")
    parser.add_argument("--port", default=DEFAULT_SERIAL_PORT, help="シリアルポート (既定: %(default)s)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="ボーレート (既定: %(default)d)")
    args = parser.parse_args()

    expression, speech, duration = EVENTS[args.event]
    payload = build_payload(expression, speech, duration)

    try:
        if args.transport == "wifi":
            ok, resp = send_via_wifi(args.host, args.tcp_port, payload, ACK_TIMEOUT)
        else:
            ok, resp = send_via_serial(args.port, args.baud, payload, ACK_TIMEOUT)
        print(f"[{args.event}] {expression} \"{speech}\" -> {resp}")
        sys.exit(0 if ok else 1)
    except OSError as exc:
        print(f"Connection error ({args.transport}): {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
