#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
スタックチャン通知スクリプト（Claude Code hooks 用 / WiFi版）
他プロジェクトから汎用的に喋らせるための共有API（speak()）も兼ねる。

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
  - error イベントは PostToolUseFailure フックから発火する想定。1ターン中に複数回
    ツールが失敗するとブンブンが連発しうるため、イベントごとにクールダウンを設ける。

他プロジェクト（例: Tanniku_sensorのようなダッシュボード用途）からの汎用利用:
  - Pythonから直接importするのが推奨（--speechをCLI引数で渡すとWindowsで日本語が
    文字化けする問題を回避できる）:
      import sys; sys.path.append(r"D:\Make\StackChan-kai")
      from stackchan_notify import speak
      speak("気温25度、湿度60%です", expression="Happy")
  - CLIからも --event の代わりに --speech/--expression/--motion で呼び出せる
    （ASCII文字列限定なら文字化けの心配なし）。
  - スタックチャンの表示は1つしか出せないため、Claude Code通知と重なると
    後から届いた方が上書きする（キューイングは無い）。
"""
import argparse
import json
import pathlib
import socket
import sys
import time

DEFAULT_HOST = "stackchan.local"
DEFAULT_TCP_PORT = 3300
DEFAULT_SERIAL_PORT = "COM3"
DEFAULT_BAUD = 115200
ACK_TIMEOUT = 3.0   # OK/ERR を待つ秒数（WiFi経由は初回接続に時間がかかることがあるため長め）
FACE_STACKCHAN = 2  # setupで初期化済みの唯一の顔(faces[2]) / palette 0,1 は未初期化なので使わない

# イベントごとの連続通知クールダウン秒数（このイベントを最後に送ってからN秒未満なら黙ってスキップ）。
# 設定が無いイベントはクールダウン無し。
COOLDOWN_SECONDS = {
    "error": 5.0,  # PostToolUseFailureは短時間に連発しうるため
}
STATE_DIR = pathlib.Path(__file__).resolve().parent / ".stackchan_notify_state"


def check_and_update_cooldown(event):
    """クールダウン中ならFalse（送信スキップ）、そうでなければ記録してTrue（送信OK）を返す。"""
    cooldown = COOLDOWN_SECONDS.get(event)
    if not cooldown:
        return True
    STATE_DIR.mkdir(exist_ok=True)
    marker = STATE_DIR / f"{event}.last"
    now = time.time()
    if marker.exists() and (now - marker.stat().st_mtime) < cooldown:
        return False
    marker.touch()
    return True

# イベント種別 -> (表情, セリフ, 表示時間ms, モーション)
# 表情は .ino の parseExpression が解釈できる6種のみ:
#   Happy / Angry / Sad / Doubt / Sleepy / Neutral
# モーションは .ino の parseMotion が解釈できる3種のみ（すべて実機安全確認済み範囲内で動作）:
#   nod(うなずき) / tilt(首かしげ) / shake(ブンブン)
EVENTS = {
    "done":  ("Happy", "終わったよ！見て見て！！", 8000,  "nod"),    # 完了 (Stop)
    "ask":   ("Doubt", "質問があります！",        12000, "tilt"),   # 確認待ち (Notification) 気づくまで長めに
    "error": ("Sad",   "失敗しちゃった、、、",     10000, "shake"),  # エラー
}

VALID_EXPRESSIONS = ["Happy", "Angry", "Sad", "Doubt", "Sleepy", "Neutral"]
VALID_MOTIONS = ["nod", "tilt", "shake"]
# 再生できる音声はCore2に埋め込まれたもののみ（assets/voices/*.wav → voices.h）。
# フレーズを追加したら tools/generate_voices.py → tools/wav_to_header.py → 再書き込みが必要。
# なおCore2側はBtnAで音声ON/OFFを切り替えられ、既定はOFF（OFFなら送っても鳴らない）。
VALID_SOUNDS = ["done", "ask", "error"]
DEFAULT_CUSTOM_DURATION = 6000

# 吹き出しの見切れ対策（長文の自動折り返し）。
# フォントはlgfxJapanGothic_12・TEXT_SIZE=2固定なので、この単位数は実機で見ながら調整すること。
# 半角=1単位・全角=2単位のおおまかな目安で計算する（正確なフォント幅計測はしていない）。
WRAP_MAX_UNITS_PER_LINE = 24
WRAP_MAX_LINES = 3


def _char_width_units(ch):
    return 1 if ord(ch) < 0x3000 else 2


def wrap_speech(text, max_units_per_line=WRAP_MAX_UNITS_PER_LINE, max_lines=WRAP_MAX_LINES):
    """長いセリフを吹き出しに収まるよう複数行(\n区切り)に折り返す。
    行数を超える分は末尾を「…」で省略する。Balloon.h側は\nで分割して描画するだけなので、
    どこで折り返すかの判断はこちらで行う。
    """
    lines = []
    current = ""
    current_units = 0
    for ch in text:
        w = _char_width_units(ch)
        if current and current_units + w > max_units_per_line:
            lines.append(current)
            current, current_units = ch, w
        else:
            current += ch
            current_units += w
    if current:
        lines.append(current)

    truncated = len(lines) > max_lines
    lines = lines[:max_lines]
    if truncated and lines:
        last = lines[-1]
        lines[-1] = (last[:-1] + "…") if len(last) > 1 else "…"
    return "\n".join(lines)


def build_payload(expression, speech, duration, motion=None, sound=None):
    # ensure_ascii=True(既定)で非ASCIIは\uXXXXにエスケープされ、
    # ワイヤ上はASCIIのみ。Core2側(ArduinoJson)がUTF-8へ復元する。
    # motion/sound省略時はキー自体を送らない（.ino側はnullを想定していないため）。
    payload = {
        "expression": expression,
        "speech": wrap_speech(speech),
        "face": FACE_STACKCHAN,
        "duration": duration,
    }
    if motion:
        payload["motion"] = motion
    if sound:
        payload["sound"] = sound
    return json.dumps(payload).encode("ascii") + b"\n"


def speak(speech, expression="Happy", motion=None, duration=DEFAULT_CUSTOM_DURATION,
          sound=None, host=DEFAULT_HOST, port=DEFAULT_TCP_PORT, timeout=ACK_TIMEOUT):
    """他プロジェクトからimportして直接呼び出す汎用API。

    例: from stackchan_notify import speak
        speak("気温25度、湿度60%です", expression="Happy")

    soundにはCore2へ事前に埋め込んだ音声名(VALID_SOUNDS)を指定できる。
    任意のテキストを読み上げることはできない点に注意（フレーズは事前生成方式のため）。

    Claude Codeのdone/ask/errorイベントとは独立しており、クールダウンも掛からない
    （呼び出し頻度はこの関数の呼び出し側が自分で制御すること）。
    戻り値は send_via_wifi と同じ (bool ok, str resp)。
    """
    payload = build_payload(expression, speech, duration, motion, sound)
    return send_via_wifi(host, port, payload, timeout)


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
    parser = argparse.ArgumentParser(description="StackChan notifier for Claude Code hooks / 汎用スピークAPI")
    parser.add_argument("--event", choices=sorted(EVENTS.keys()), default=None,
                        help="Claude Codeプリセットイベント: done(完了)/ask(確認待ち)/error(エラー)")
    parser.add_argument("--speech", default=None,
                        help="汎用モード: 任意のセリフ。--eventの代わりに指定する（他プロジェクトからの利用向け）")
    parser.add_argument("--expression", choices=VALID_EXPRESSIONS, default="Happy",
                        help="汎用モード時の表情 (既定: %(default)s)")
    parser.add_argument("--motion", choices=VALID_MOTIONS, default=None,
                        help="汎用モード時のモーション（省略可）")
    parser.add_argument("--sound", choices=VALID_SOUNDS, default=None,
                        help="汎用モード時に再生する事前録音音声（省略可）")
    parser.add_argument("--duration", type=int, default=None,
                        help="汎用モード時のセリフ表示時間ms (既定: %d)" % DEFAULT_CUSTOM_DURATION)
    parser.add_argument("--transport", choices=["wifi", "serial"], default="wifi",
                        help="通信経路 (既定: %(default)s)。serialはサーボ電源が来ないデバッグ専用。")
    parser.add_argument("--host", default=DEFAULT_HOST, help="WiFi接続先ホスト名/IP (既定: %(default)s)")
    parser.add_argument("--tcp-port", type=int, default=DEFAULT_TCP_PORT, help="WiFi接続先TCPポート (既定: %(default)d)")
    parser.add_argument("--port", default=DEFAULT_SERIAL_PORT, help="シリアルポート (既定: %(default)s)")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="ボーレート (既定: %(default)d)")
    args = parser.parse_args()

    if args.event and args.speech:
        parser.error("--event と --speech は同時に指定できません")
    if not args.event and not args.speech:
        parser.error("--event か --speech のいずれかを指定してください")

    if args.event:
        if not check_and_update_cooldown(args.event):
            print(f"[{args.event}] skipped (cooldown active)")
            sys.exit(0)
        expression, speech, duration, motion = EVENTS[args.event]
        # 音声名はイベント名と同じにしてある（voices.h の kVoiceTable と対応）
        sound = args.event if args.event in VALID_SOUNDS else None
        label = args.event
    else:
        expression, speech, motion = args.expression, args.speech, args.motion
        sound = args.sound
        duration = args.duration if args.duration is not None else DEFAULT_CUSTOM_DURATION
        label = "custom"

    payload = build_payload(expression, speech, duration, motion, sound)

    try:
        if args.transport == "wifi":
            ok, resp = send_via_wifi(args.host, args.tcp_port, payload, ACK_TIMEOUT)
        else:
            ok, resp = send_via_serial(args.port, args.baud, payload, ACK_TIMEOUT)
        print(f"[{label}] {expression} \"{speech}\" -> {resp}")
        sys.exit(0 if ok else 1)
    except OSError as exc:
        print(f"Connection error ({args.transport}): {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
