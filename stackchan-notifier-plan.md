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

> **【実機で判明・2026-07-20】このキット（もんごんた版タカオ版ケースセット）に限っては、
> ベース側USB-Cポートは給電専用でデータ線が通っていなかった**（画面点灯するがPCにCH9102/シリアルデバイスが一切現れない、
> ドライバ未認識エラーも無し＝物理的に未結線と推定）。
> 上記の「ベース側推奨」はM5公式の一般論であり、**このサードパーティ製ベースには当てはまらない**。
> → **通信には本体側ポート（COM3, CH9102）を使うほかない**。
> サーボ動作時のケーブル巻きつきリスクは、運用（うなずき等の小角度動作を先に検証・目視監視・大振りは最小限に設計）で軽減する方針とした。

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

## サーボ動作の実現：WiFi化 + 根本原因の特定（2026-07-20）

「首の動き」着手にあたり、サーボ電源が本体側USB-Cでは供給されない（給電経路が排他）という
ハード制約が判明し、通信経路をUSBシリアルからWiFiへ全面移行。さらに複数回の実機切り分けで
サーボ無反応の根本原因（配線ミス）を特定・修正した。

### 発端：電源とデータ通信の排他性
- **Core2本体側USB-C**: データ通信（COM3/CH9102）は使えるが、**サーボに電源が来ない**
- **スタックチャン本体の電源Type-C**（Takao Baseのバッテリー経路）: サーボに電源は来るが、
  **USBデータ線がない**（ベース側ポートは前回判明の通り給電専用）
- この排他性はハード設計上のものでファームでは解決不能。
  → **通信をWiFi(TCP)化し、USB接続自体を不要にする**方針に転換。

### WiFi化の実装
- `wifi_config.h`（gitignore対象、SSID/パスワード）を新設し `.ino` へ `#include`
- `.ino` に `WiFi.h` / `ESPmDNS.h` を追加。起動時にWiFi接続 → mDNSホスト名
  `stackchan.local` → TCPサーバ(ポート3300)を起動
- 受信JSONコマンドの処理をSerial/WiFi共通の `handleCommandLine()` に統一（1コマンド1接続、
  応答後に `client.stop()`）
- `stackchan_notify.py` を全面書き換え。既定トランスポートは `--transport wifi`
  （`stackchan.local:3300`へTCP接続、JSON送信、OK/ERR受信）。
  `--transport serial` は書き込み後のデバッグ用に残置。
- `.claude/settings.json` のhooksコマンドから `--port COM3` を削除（既定でWiFi経由になるため不要）

### サーボ無反応の根本原因（3つ複合）
実際にサーボ電源側で通電しても無反応だった問題を、公式 `stack-chan/stackchan-arduino`
リポジトリのソースを直接調査して特定：

1. **GPIOピン番号の誤り**: 旧ファーム（Murasan201/robo8080系）は `SERVO_PIN_X=13` /
   `SERVO_PIN_Y=14` を使用していたが、公式ライブラリの `Stackchan_system_config.cpp` によれば
   **M5Stack Core2 + Port.A(Stack-chan_Takao_Base)の正しいピンは X=33, Y=32**。
   このキットの実配線と一致しておらず、コマンドは正常処理されても物理的に無反応だった。
2. **`ExtOutput`の設定漏れ**: 公式 `Stackchan_Takao_Base.hpp` の `checkTakaoBasePowerStatus()` に
   よれば、バッテリー（本体電源）駆動時は `power->setExtOutput(true)` を明示的に呼ばないと
   Takao Base側のサーボ電源が入らない。旧ファームにはこの呼び出しが無かった。
   → `setup()` に `M5.Power.setExtOutput(true);` を追加して解決。
3. **サーボホーンの取り付け角度のズレ**（物理）: ソフト上の90°が実際の正面と一致しておらず、
   角度によっては機構的なストール（「ジー」という保持力音）が発生。手動でホーンを再調整して解消。

参考ソース:
- [akita11/Stack-chan_Takao_Base](https://github.com/akita11/Stack-chan_Takao_Base)
- [stack-chan/stackchan-arduino](https://github.com/stack-chan/stackchan-arduino)
- [Power Management (Takao Base) | DeepWiki](https://deepwiki.com/stack-chan/stackchan-arduino/5.2-power-management-(takao-base))

### 診断の仕組み（開発時の工夫）
サーボ電源投入時（本体電源駆動時）はUSBシリアルが使えずSerialログが見えないため、
`handleCommandLine()` のOK応答に診断情報を埋め込む方式で対応：
```
OK diag attachX=<attach戻り値> attachY=<attach戻り値> curX=<現在角度> curY=<現在角度>
```
これによりWiFi経由でもファーム内部の状態を可視化できた。

### 実機キャリブレーション結果
本体90°/90°が両軸とも正面よりずれていたため、実際に少しずつ角度を振って正面を実測：

| 軸 | ソフト初期値(旧) | 実際の正面(センター) |
|---|---|---|
| X（左右） | 90° | **85°** |
| Y（上下） | 90° | **85°** |

→ `START_DEGREE_VALUE_X` / `START_DEGREE_VALUE_Y` を **85** に変更（起動時の待機姿勢が正面を向く）。
安全クランプは暫定で X: 60-120°, Y: 50-95°（Y上限は公式デフォルト90から実機確認のため95まで拡張、
ストールなしを確認済み）。**両軸ともこれより広い範囲は未検証**なので、本格的なモーション
（うなずき/首かしげ/ブンブン）を設計する際はさらに慎重に段階的検証すること。

### サーボ安全テストの教訓（今後のモーション設計に活用）
- ストール時の音は「ジー」という**継続する**保持力音。一瞬鳴ってすぐ止まるのは正常な作動音。
- ストールを確認したら**即座に電源を切る**（WiFiコマンドで戻すより物理的な電源断が速く確実）。
- 新しい角度は必ず**1〜5°の小刻みなステップ**で検証し、都度ユーザーが目視・音を確認してから次へ。
- サーボは180°仕様（中心から±90°の可動域を持つが、実際に安全に動かせる範囲は
  ケース・ブラケットの機構的な制約で大幅に狭まる）。

### ファイル構成の変更
- `base_firmware/` は引き続きgitignore対象（別リポジトリの作業用クローン）だが、
  今回の重要な改修が失われないよう、確定した `.ino` を `firmware/` 配下にコピーして
  リポジトリに保存（バックアップ・iPhone側との共有用）。
- `firmware/M5Core2_SG90_StackChan_VoiceText_Ataru/wifi_config.h.example` を追加
  （実際の認証情報は書かず、書式のみのテンプレート）。

### 次にやること
- `firmware/`配下の`.ino`はメインスケッチのみのバックアップ（AtaruFace.h等の付随ファイルは
  `base_firmware/`側のみ）。ビルドは引き続き`base_firmware/`から行うこと。
- 上記の安全クランプ範囲をさらに広げて、実際の「うなずき/首かしげ/ブンブン」モーションを設計・実装。
- STEP5(B)のTODO（エラー通知・A展開）も引き続き未着手。

---

## モーション本番実装（2026-07-20）

前回確認済みの安全範囲（センターX/Y=85°、確認済み X:85〜89°、Y:85〜95°）のみを使い、
JSONコマンドに `motion` キーを新設して3種のモーションを実装・実機確認済み。

### 実装内容
- `.ino`: `enum class Motion { None, Nod, Tilt, Shake }` を追加。`parseMotion()` で
  JSON文字列(`"nod"`/`"tilt"`/`"shake"`)をパースし、`applyCommand()` の末尾で `playMotion()` を呼ぶ。
  - **nod（うなずき）**: Y軸を `85→93→85` を2回往復（各ステップ後120ms待機）
  - **tilt（首かしげ）**: X軸を `85→89` に動かし500ms保持してから `85` に戻す
  - **shake（ブンブン）**: X軸を `85⇔89` で素早く3往復
  - いずれもブロッキング処理（完了後にOK応答）。所要時間は1秒未満〜1秒強で、
    既存のACK_TIMEOUT(3.0秒)内に収まる。
- `stackchan_notify.py`: `EVENTS` に4つ目の要素としてmotionを追加
  （done→nod, ask→tilt, error→shake）。`build_payload()` もmotionを含めるよう変更。

### 実機確認結果
- 3モーションとも単体テストで正常動作（異音なし、目視で動きを確認）
- `stackchan_notify.py --event done` の統合テストでも、Happy表情＋セリフ＋うなずきが同時に
  正しく発火することを確認。**通知ロボとして完成形**に到達。

### ハマりどころ（Arduino自動プロトタイプ生成の罠）
`enum class Motion` と `parseMotion()` を追加した際、既存の `parseExpression(const char*, Expression&)`
の定義（`using namespace m5avatar;` に依存した非修飾の`Expression`型を使用）がコンパイルエラーに
なった。原因はArduinoのビルドシステム（ctags）が関数プロトタイプを自動生成する際、
ファイル冒頭のinclude直後に一括挿入するため、`using namespace m5avatar;`（ファイル中盤で宣言）
より前の位置に非修飾`Expression`型を参照するコードが出現し解決できなくなったこと。
新しい関数を追加したことで自動生成の挙動が変化し顕在化した。
→ **対処**: 定義側も `m5avatar::Expression`（完全修飾名）に統一して解決。
　今後この種の型（他ライブラリのnamespace由来）を関数シグネチャに使う際は、
　`using namespace`に頼らず完全修飾名で書くのが安全。

### 今後の発展余地（2026-07-20 第2回で解消済み。以下は記録として残す）
- 当初の可動域はごく小さい（X:+4°, Y:+10°）ため、モーションはやや控えめだった。
- 特に`shake`は片側(85→89)のみの往復で、本来の左右往復（両方向）ではなかった。

---

## モーション拡大＆センター再調整（2026-07-20 第2回）

うなずきが「下に当たっている」ように見える／もっと大きい動きにしたいとの指摘を受け、
センター位置の再キャリブレーションと可動域拡張を実施。

### 再キャリブレーション結果
1回目のセンター確認（X/Y=85°）は不十分で、実際にはさらにズレていた：

| 軸 | 1回目のセンター | 再調整後のセンター | 確認済み安全範囲 |
|---|---|---|---|
| X（左右） | 85° | **80°** | **65°〜105°**（±20〜25°） |
| Y（上下） | 85° | **75°** | **75°〜95°**（95°付近は「当たっている」感覚があり要注意） |

判定方法は前回と同じ：候補角度に動かして正面らしさを比較→次の角度→…と1〜5°刻みで
段階的に進め、ユーザーが目視・体感で判断。X軸は初めて逆方向（85→80→75→70→65）も検証し、
±20°超の対称な範囲を確保できた（前回はプラス方向の+4°しか検証していなかった）。

### モーション再設計（`.ino`定数を更新）
テスト済み最大値ちょうどではなく、少し内側を安全マージンとして採用：
- `CENTER_X=80, CENTER_Y=75`（`START_DEGREE_VALUE_X/Y`も同期）
- `SERVO_X_MIN/MAX = 65/105`, `SERVO_Y_MIN/MAX = 75/95`（安全クランプも実測範囲に合わせて更新）
- **うなずき**: Y `75→90→75` を2回（振れ幅15°、旧8°から倍増。95°付近は使わない）
- **首かしげ**: X `80→95` で保持して戻る（振れ幅15°、旧4°から拡大）
- **ブンブン**: X `95⇔65` で**真の左右往復**を2セット→中心に戻る
  （旧は片側だけの往復だったが、今回X軸の逆方向も検証できたため実現）

### 実機確認結果
3モーション単体＋統合テスト（`--event done`/`--event error`で表情+セリフ+モーション同時発火）を
再確認。全て異音なく、より大きく自然な動きになったことを目視確認済み。

### 教訓
- 初回のセンター確認（他の角度と比較して「一番近い」を選ぶ方式）だけでは不十分な場合がある。
  実際にモーション（往復動作）を動かしてみて初めて「まだズレている」「当たっている感じがする」
  といった違和感に気づけることがある。**静止比較だけでなく、実際の動作パターンでの確認**が重要。
- 安全範囲の探索は、片方向だけでなく**両方向**を検証すること。今回X軸の逆方向を検証したことで
  真の左右往復（shake）が実現でき、表現の幅が大きく広がった。

---

## エラー通知（Sad+ブンブン）の自動発火を実装（2026-07-20）

TODO4「エラー系イベントをどのフックで拾うか」に対応。`PostToolUseFailure` フック
（ツール呼び出し失敗時に発火）を採用し、`error` イベントとして接続。

### 実装内容
- `stackchan_notify.py`: イベントごとの連続通知クールダウン機構を追加
  （`COOLDOWN_SECONDS = {"error": 5.0}`）。1ターン中にツール失敗が連発すると
  ブンブンが連発しうるため、`.stackchan_notify_state/<event>.last` の
  タイムスタンプで直近5秒以内の再発火を黙ってスキップする。
  スキップ時はexit 0（hookの失敗として扱われないように）。
- `.claude/settings.json` に `PostToolUseFailure` フックを追加
  （`stackchan_notify.py --event error` を実行）。
- `.gitignore` に `.stackchan_notify_state/`（クールダウン用の実行時生成ファイル）を追加。

### 検証方法の注意点
CLIを直列(`&&`)で2回実行するテストは、各回のWiFi/mDNS接続自体に数秒かかるため、
2回目が始まる時点で既に5秒以上経過してしまい正しく検証できなかった。
`&`で2プロセスをほぼ同時に起動して初めてクールダウンの動作（1回はスキップ、
1回は送信）を確認できた。実際のPostToolUseFailure連発（同一ターン内での複数ツール失敗）
はこの並列起動に近い挙動になるため、この検証方法で妥当と判断。

### 実機確認結果
意図的にBashコマンドを失敗させ（`exit 1`）、Sad表情＋「失敗しちゃった、、、」＋ブンブンの
自動発火を確認済み。これでSTEP5(B)の残タスク（TODO4）が解消。

### 残りの発展候補
- **A展開**: グローバル `~/.claude/settings.json` に同じhooks一式（Stop/Notification/
  PostToolUseFailure）を入れ、全プロジェクトで通知ロボが反応するようにする。

---

## A展開: グローバルhooks化（2026-07-20）

`~/.claude/settings.json`（グローバル設定、Gitリポジトリ外）に、このプロジェクトと同じ
Stop/Notification/PostToolUseFailureの3フックを追加。既存の設定（model/theme等）は保持し
`hooks`キーのみ追加した。

- プロジェクト側`.claude/settings.json`にも同じhooksが残っているが、**重複発火は起きない**ことを
  実機で確認済み（Stopフックで「うなずき」が1回だけ発火）。両方に同一hooksがあっても安全。
- これで**どのプロジェクトで作業していても通知ロボが反応する**ようになった。

### STEP5(B) 完了
Stop（完了）/ Notification（確認待ち）/ PostToolUseFailure（エラー）の3フックすべてが
実機で自動発火することを確認し、モーション（うなずき/首かしげ/ブンブン）付きの
通知ロボとして完成。TODO4（エラー系イベントの拾い方）・A展開ともに解消。

---

## 他プロジェクト向け汎用スピークAPI（2026-07-20）

「スタックチャンを他プロジェクトのダッシュボードも兼ねさせたい」という要望に対応。
例: `D:\Make\Tanniku_sensor`（多肉植物モニター、企画段階）でセンサー値を定期的に喋らせる、
`D:\Make\stock_trading_llm`（株取引自動化、企画段階）で売買シグナル検知時にアクションさせる、
といった用途を想定。両プロジェクトとも詳細仕様は未定のため、**今回はスタックチャン側の
汎用受け口だけを整備**し、各プロジェクト固有の統合コード（データ取得・シグナル検知等）は
それぞれの仕様が固まってから実装する方針。

### 実装内容（`stackchan_notify.py`）
- `speak(speech, expression="Happy", motion=None, duration=6000, host=..., port=...)` 関数を追加。
  **他プロジェクトからPythonで直接importして呼ぶのが推奨**:
  ```python
  import sys; sys.path.append(r"D:\Make\StackChan-kai")
  from stackchan_notify import speak
  speak("気温25度、湿度60%です", expression="Happy", motion="nod")
  ```
  CLI引数(argv)経由だとWindowsで日本語が文字化けする問題を、Python文字列として
  直接渡すことで回避できる（json.dumpsのensure_ascii=Trueで\uXXXXエスケープされるため）。
- CLIにも汎用モードを追加: `--event` の代わりに `--speech`/`--expression`/`--motion`/`--duration`
  を指定可能（ASCII文字列限定なら文字化けの心配なし）。`--event`と`--speech`は排他。
- `build_payload()` はmotion省略時にJSONの`motion`キー自体を送らないよう変更
  （`.ino`側は`motion:null`を想定しておらず、送るとparseMotion失敗でERRになるため）。
- 汎用呼び出し（`speak()`・CLI汎用モード）にはクールダウンを掛けない
  （呼び出し頻度は呼び出し側が自分で制御する想定）。

### 実機確認結果
`speak()`経由で日本語セリフ＋モーション（うなずき）が文字化けなく正常表示されることを確認。
既存の`--event done/ask/error`（Claude Code hooks用）も引き続き正常動作。

### 設計上の注意点（申し送り）
- スタックチャンの表示は1つしか出せないため、Claude Code通知と他プロジェクトの発話が
  タイミング的に重なると後着ち優先で上書きされる（キューイングは無い）。
  用途によっては簡単な排他制御が必要になるかもしれないが、現時点では未実装。
- 既存の3モーション（nod/tilt/shake）は流用可能で、Core2への再書き込み不要。
  新しいモーション種別を追加する場合のみ`.ino`の再書き込みが必要。

---

## WiFi自動再接続の実装（2026-07-20）

「セッションを閉じた後、他プロジェクトで通知が来ない」という報告を調査。

### 原因調査
- グローバル`~/.claude/settings.json`のhooks設定自体は正常だった。
- `stackchan.local:3300`へ接続不可。同一サブネット(192.168.10.0/24)を全ポートスキャンしても
  スタックチャンが見つからず、単なるIP変更ではなく**WiFi自体が繋がっていない**と判明。
- 電源を入れ直したら復旧 → 起動時のWiFi接続自体は正常に行えることを確認。
- `.ino`を確認したところ、**WiFi接続はsetup()で起動時に1回行うのみで、loop()側は
  「切断されていたら何もしない」だけ（再接続処理が皆無）**だった
  （`handleWifiClients()`冒頭の`if (WiFi.status() != WL_CONNECTED) return;`）。
- 長時間稼働中に何らかの理由（ルーターの瞬断等）でWiFiが切れると、そのまま二度と
  復旧せず、次回の電源入れ直しまで通知が届かなくなる、という設計上の欠陥だった。

### 実装内容
`.ino`に定期的な接続監視＋自動再接続を追加：
- `ensureWifiConnected()`関数を新設。`loop()`の冒頭で毎回呼ぶが、
  実際のチェックは`kWifiCheckIntervalMs`(5秒)おきに間引く。
- 5秒ごとに`WiFi.status()`を確認し、`WL_CONNECTED`でなければ`WiFi.begin()`で
  再接続を試行（最大`kWifiReconnectTimeoutMs`=10秒待つ）。
- 再接続成功時は`MDNS.end()`→`MDNS.begin()`でmDNSも登録し直す
  （切断・再接続でmDNSの内部状態が古くなる可能性への対処）。

### 検証状況
- 通常起動＋既存の通知（`--event done`）が壊れていないことは実機確認済み。
- **実際のWiFi切断からの自動復旧そのものは未検証**（家庭内ルーターに影響するテストを
  避けたため）。次に本当に通知が来なくなった場合、電源を入れ直さずにまず
  「5〜10秒待って自然に復旧するか」を確認することで検証できる。

---

## 段階的構築の全体像（再掲）

1. hooks が発火することを確認（まず echo 等で）
2. シリアルでイベント受信 → 画面表示だけ
3. 表情・セリフ・動作を足して通知ロボ完成
4. （発展）AI会話化、iPhoneからClaude Codeにリモート指示 → デスクのロボが進捗通知
