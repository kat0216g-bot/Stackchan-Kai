# スタックチャン Claude Code 通知ロボ化 — 設計メモ

PC作業の引き継ぎ用ドキュメント。iPhoneで詰めた設計判断をまとめてある。
PCではこの手順どおりに進めればよい。

---

## ゴール

PCで動いている Claude Code のタスク状況（完了・確認待ち・エラー）を、
デスク横のスタックチャンが **表情・首の動き・日本語のセリフ** で知らせる「通知ロボ」を作る。

---

## ハードウェア / 環境の前提

- キット: もんごんた（Arpeggio Factory）版「タカオ版ケースセット」
  - https://booth.pm/ja/items/7090763
  - M5Stack Core2 系 + SG90 サーボ2個（X=左右パン, Y=上下チルト）
- スタックチャンは **PCディスプレイ横に常設**
- **USB Type-C 1本でPCに直結**（給電＋シリアル通信を兼ねる）
  - ネットワーク・MQTT不要。最もシンプルな構成
- PC: **Windows**

### 接続・安全上の注意（M5公式ドキュメント由来）
- USB-Cは本体側・ベース側どちらもデータ通信対応だが、
  モーターの動きによる事故防止のため **ベース側ポート推奨**
- **Y軸（上下）サーボの可動域は 5〜85° に収める**。
  極端な角度はサーボのストール・永久故障の原因になる（うなずき自作時に注意）

---

## 採用するベースファーム（候補A）

**Murasan201/M5Core2_StackChan_AI_Extension**
- https://github.com/Murasan201/M5Core2_StackChan_AI_Extension
- robo8080版「M5Core2_SG90_StackChan_VoiceText_Ataru」のフォーク
- **@mongonta555 のM5GoBottom版キットに名指しで対応**
- Arduino IDE でビルド可能・日本語コメント付き

### なぜこれか（決め手）
このフォークは単なるAI会話ファームではなく、
**シリアル経由でJSONコマンドを送って表情・セリフを制御する仕組みに作り替え済み**。
通知ロボに必要な「コアの通信部分」がすでに実装されている。

- M5側（.ino）: 改行区切りJSONパーサを持ち、
  `expression` / `speech` / `palette` / `duration` / `clear` を解釈。
  常にデフォルト顔（`faces[2]`）を使用
- 母艦側（`control_stackchan.py`）: CLIフラグをJSONに変換し、
  115200bps でポートを開き、`OK` ハンドシェイクを待つ。
  `ERR` かタイムアウトで失敗を返す
- 使用例（元はRaspberry Pi前提）:
  ```
  python3 control_stackchan.py --expression Happy --speech "Hello StackChan" --palette 2 --duration 3000
  ```

> 元がRaspberry Pi前提なので、**Windowsに読み替えるだけ**でよい。

### （参考）不採用にした候補B
- robo8080/AI_StackChan2（本家・情報量最多）
- ただしVSCode + PlatformIO前提で環境構築のハードルが高く、
  通信部も自前追加が必要。将来AI会話に発展させる時の資産として温存

---

## 通知イベント対応表（確定版）

| Claude Codeイベント | 表情 | セリフ | 動作 |
|---|---|---|---|
| 完了 (Stop) | Happy | 終わったよ！見て見て！！ | うなずき |
| 確認待ち (Notification) | Doubt | 質問があります！ | 首かしげ |
| エラー | Sad | 失敗しちゃった、、、 | ブンブン |

---

## PCでの作業手順

### STEP 0. リポジトリ取得
```
git clone https://github.com/Murasan201/M5Core2_StackChan_AI_Extension.git
```

### STEP 1. 現物コードの確認（Windows対応ポイントの洗い出し）
- `control_stackchan.py` … ポートが `/dev/ttyUSB0` 決め打ちのはず。
  → Windowsの `COM?` に変更。理想は引数化する:
  ```python
  import argparse
  parser.add_argument("--port", default="COM3")  # 環境に合わせる
  # serial.Serial(...) の第一引数を args.port に
  ser = serial.Serial(args.port, 115200, timeout=5)
  ```
- `.ino` … 使える `expression` 値の一覧を確認
  （m5stack-avatar標準なら Neutral / Happy / Sad / Angry / Doubt / Sleepy など）
- エラー通知に使えるイベント種別（Stop/Notification以外）の確認

### STEP 2. Python準備
```
pip install pyserial
```

### STEP 3. Arduino IDE 環境構築 & 書き込み
- ESP32ボードパッケージを追加
- 必要ライブラリ: M5Unified / ServoEasing / ESP32Servo / ESP8266Audio / ArduinoJson
- m5stack-avatar のソースを配置
- FQBN: `esp32:esp32:m5stack_core2`
- デバイスマネージャーでCOMポート番号を確認
  （挿抜して現れる/消えるポートが目的のもの）
- ファーム書き込み

### STEP 4. 第一マイルストーン（手打ちで動作確認）
```
python control_stackchan.py --port COM3 --expression Happy --speech "終わったよ！見て見て！！" --duration 3000
```
→ スタックチャンが表情を変え、セリフを表示すればOK。

### STEP 5. Claude Code hooks 設定（通知ロボ完成）
`~/.claude/settings.json`（または プロジェクトの `.claude/settings.json`）:
```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command",
        "command": "python C:\\stackchan\\control_stackchan.py --port COM3 --expression Happy --speech \"終わったよ！見て見て！！\" --duration 3000" } ] }
    ],
    "Notification": [
      { "hooks": [ { "type": "command",
        "command": "python C:\\stackchan\\control_stackchan.py --port COM3 --expression Doubt --speech \"質問があります！\" --duration 3000" } ] }
    ]
  }
}
```
- パス・`--port`・`--expression` は現物合わせで確定させる
- エラー通知はイベント割り当てが完了/確認待ちと異なるため、
  現物のイベント仕様を見て確定

---

## 未確定・PCで確定させること（TODO）

- [x] `control_stackchan.py` の実際のポート指定箇所と引数仕様 → **`--port`で引数化済み。改変不要**（下記STEP 0-1調査結果を参照）
- [x] `.ino` で使える `expression` 値の正確な一覧 → **Happy/Angry/Sad/Doubt/Sleepy/Neutral の6種**
- [ ] Claude Code hooks の最新イベント仕様（stdinで渡るJSONの中身）
- [ ] エラー系イベントをどのフックで拾うか
- [x] うなずき/首かしげ/ブンブンの動作が既存実装にあるか、自作が必要か → **未実装。自作が必要**（サーボ制御は無効化されている）

---

## STEP 0-1 現物コード調査結果（2026-07-19 実施）

ベースファーム `Murasan201/M5Core2_StackChan_AI_Extension` をクローンし現物を精査した結果。
（対象: `control_stackchan.py` と `M5Core2_SG90_StackChan_VoiceText_Ataru.ino`）

### 確定できたこと

- **ポート指定**: `control_stackchan.py` は既に `--port` 引数化済み（デフォルト `/dev/ttyUSB0`）。
  Windowsでは実行時に `--port COM3` を渡すだけでよく、**コード改変は不要**。
- **expression の一覧**: `Happy` / `Angry` / `Sad` / `Doubt` / `Sleepy` / `Neutral` の6種。
  Python側（`EXPRESSION_CHOICES`）・.ino側（`parseExpression`）の両方で一致。
  → 通知イベント対応表の Happy / Doubt / Sad は**全て対応済み**。表情＋セリフ通知はファーム改変なしで実現可能。

### 首の動き（重要）

- サーボ制御タスク `servoloop()` は冒頭で `return;` により**無効化**されている。
  `addTask(servoloop, ...)` もコメントアウト済み。
- しかも既存の `servoloop` は「アバターの視線追従」用であって**通知動作ではない**。
- JSONコマンドに首を動かすキーは**存在しない**（`expression`/`speech`/`face`/`palette`/`duration`/`clear` のみ）。
- **結論**: うなずき/首かしげ/ブンブンは、.ino に**モーション用キー（例 `motion`）とサーボ動作関数を自作追加**する必要がある。
  → まず表情＋セリフで通知ロボを完成させ、首の動きは第2段階として後付けするのが妥当。

### 追加で判明した落とし穴（当初mdに無かった注意点）

- **face/palette は 2 以外を送るとクラッシュの恐れ**:
  setup内で `faces[0]/[1]`（Ataru/Ram）と `cps[0]/[1]` がコメントアウトされ未初期化。
  `--face 0/1` や `--palette 0/1` を送るとnullポインタ参照になる。
  → **face/palette は送らない、または 2 固定にする**（デフォルト顔=`faces[2]`のStackChan）。
  ※ hooks例の `--palette 2` は 2 なのでOKだが、不要なら省略が安全。
- **音は鳴らない**: `M5.Speaker.begin()` がコメントアウト＋`USE_VOICE_TEXT` 無効。
  「セリフ」＝**画面の吹き出しテキスト表示**であって音声ではない。
- **送信のたびに約3秒の遅延**: Pythonが送信前に `time.sleep(3)` を入れている
  （Core2がUSB接続時にDTRでリセットするため）。hook発火のたびに約3秒待つ。通知用途なら許容範囲。
  ACKタイムアウトは1秒（`OK`/`ERR` を待つ）。
- **Y軸サーボ角度の矛盾に注意**: 本メモは「Y軸5〜85°」としているが、コードの初期値は
  `START_DEGREE_VALUE_Y 90`。うなずき自作時にこの安全域と要すり合わせ（極端な角度はサーボ故障）。

### 次にやること

- TODO 3・4（Claude Code hooks の最新イベント仕様、エラーイベントの拾い方）はファーム側では確定不可。
  別途 hooks 仕様の調査が必要。
- 実機があれば STEP 2〜4（pyserial導入 → Arduino IDE書き込み → 手打ち動作確認）へ進める。

---

## STEP 2-4 実機セットアップ完了（2026-07-19 実施）

実機（M5Core2）をPCへ接続し、ファーム書き込み〜手打ち動作確認まで完了。**表情＋日本語セリフの通知が実機で動作**。

### 確定した環境情報
- **接続**: USB-シリアルチップは **CH9102（WCH社）**。ポートは **COM3**。
  （M5Core2は世代でチップが異なり、旧型のCP210x=Silicon Labsではなかった）
- **Python**: 3.11.9 / `pip install pyserial` 済み（pyserial 3.5）。
- **ビルド環境**: `arduino-cli` 1.5.1 を winget で導入（`C:\Program Files\Arduino CLI\`）。
  - ESP32コア: `esp32:esp32` 3.3.10
  - ライブラリ: M5Unified / **M5Stack_Avatar**（※検索名はアンダースコア。`Avatar.h`提供）/
    ServoEasing / ESP32Servo / ArduinoJson
  - **FQBN: `esp32:esp32:m5stack_core2`**
- **ビルド/書き込みコマンド**（arduino-cliのPATHを通した上で）:
  ```
  arduino-cli compile --fqbn esp32:esp32:m5stack_core2 base_firmware/M5Core2_SG90_StackChan_VoiceText_Ataru
  arduino-cli upload  --fqbn esp32:esp32:m5stack_core2 --port COM3 base_firmware/M5Core2_SG90_StackChan_VoiceText_Ataru
  ```

### 実機テストで判明した重要な2点（STEP 5に直結）
1. **ポートは rts=False / dtr=False で開くこと**:
   標準の `control_stackchan.py` は `rts=True`（pyserial既定）で開くため、
   CH9102の自動リセット回路が **Core2のEN端子をLowに保持＝リセット状態で固まり、無応答**になる。
   → 無リセットで開くと動作中のCore2へ**即応答（ACK約0.01秒）**。リセット不要で通知が瞬時・ちらつき無し。
2. **日本語はコマンドライン引数で渡さない**:
   Windowsではargvの日本語が文字化けする。
   → **日本語セリフはスクリプト内(UTF-8)に埋め込み**、外部からは `--event done/ask/error` のASCIIのみ渡す。
   ワイヤ上は `json.dumps(ensure_ascii=True)` で `\uXXXX` エスケープ→Core2(ArduinoJson)がUTF-8復元。

### 新規作成: `stackchan_notify.py`（通知ロボ本体・hooks用）
上記2点を反映した専用スクリプトをリポジトリ直下に作成。
- `--event done` → Happy「終わったよ！見て見て！！」
- `--event ask`  → Doubt「質問があります！」
- `--event error`→ Sad「失敗しちゃった、、、」
- 無リセットで開く／初回ACK失敗時のみ明示リセット→再送のフォールバック付き。
- **3種すべて実機で表情切替＋日本語セリフ表示を確認済み**（STEP 4クリア）。
- 補足: ファームは**セリフのみ`duration`後に自動クリア、表情は残る**（最後の通知の顔で待機）。
- 補足: 起動時の `Error attaching servo y` はServoEasingの戻り値解釈の些細なバグ（成功していても表示）。無害。

### STEP 5 での使い方（想定）
`~/.claude/settings.json`（または プロジェクトの `.claude/settings.json`）の hooks から:
```
python d:\Make\StackChan-kai\stackchan_notify.py --event done   --port COM3
python d:\Make\StackChan-kai\stackchan_notify.py --event ask    --port COM3
```
※ 日本語を settings.json に書かずに済むので文字化けの心配なし。

---

## STEP 5(B) 完了 & 次回の改善タスク（2026-07-19）

- プロジェクトの `.claude/settings.json` に hooks 設定（Stop→done / Notification→ask）。
  Claude Code再起動後、実機で自動通知の発火を確認 = **通知ロボ稼働**。

### 次回の改善要望（ユーザー指示・未着手）
1. **セリフの表示時間を延ばす**: `stackchan_notify.py` の `EVENTS` の `duration` を調整
   （現 done=5000ms → 8000〜10000ms 程度）。ファーム改修不要・すぐ可能。
2. **セリフが消えたら顔を標準(Neutral)に戻す**: 現状はセリフのみ `duration` 後に消え、表情は残る。
   `.ino` の速度クリア処理（`clearSpeechText()` 付近）で、クリア時に `avatar.setExpression(Expression::Neutral)`
   も呼ぶよう改修が必要（要 再コンパイル&書き込み）。

### その後の発展候補
- **A展開**: グローバル `~/.claude/settings.json` に同hookを入れ全プロジェクトで通知。
- **エラー通知(Sad)追加**: TODO4（どのイベントで拾うか）を調査して error を組み込む。
- **首の動き**: `.ino` にモーション追加（第2段階）。

---

## 段階的構築の全体像（再掲）

1. hooks が発火することを確認（まず echo 等で）
2. シリアルでイベント受信 → 画面表示だけ
3. 表情・セリフ・動作を足して通知ロボ完成
4. （発展）AI会話化、iPhoneからClaude Codeにリモート指示 → デスクのロボが進捗通知
