#include <Arduino.h>
#include <M5Unified.h>
#include "esp_system.h"     // esp_random() 用

// サーボモーターの接続ピン番号
// 公式stack-chan-arduinoライブラリのM5StackCore2向けデフォルト(Port.A)に合わせる。
// 旧値(13/14)はStack-chan_Takao_Baseの実配線と一致せず無反応の原因だった。
#define SERVO_PIN_X 33
#define SERVO_PIN_Y 32

#include <Avatar.h>         // M5Stack用のアバターライブラリ：https://github.com/meganetaaan/m5stack-avatar
#include <ServoEasing.hpp>   // サーボのイージング動作用ライブラリ：https://github.com/ArminJo/ServoEasing
#include "AtaruFace.h"       // あたるの顔データ
#include "RamFace.h"         // ラムちゃんの顔データ
#include <ArduinoJson.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include "wifi_config.h"    // WIFI_SSID / WIFI_PASSWORD を定義（gitignore対象）

// サーボ用電源はスタックチャン本体の電源Type-Cからのみ供給される（本体USB-Cは非対応）。
// そのためPCとの通信はUSBシリアルではなくWiFi(TCP)で行う。
constexpr uint16_t kControlPort = 3300;
constexpr char kMdnsHostname[] = "stackchan"; // http://stackchan.local 相当でアクセス可能にする
WiFiServer controlServer(kControlPort);

// 長時間稼働中にWiFiが切断された場合の自動再接続用（2026-07-20 追加）。
// 起動しっぱなしにしていたらWiFiが途絶えて通知が届かなくなった事象への対応。
constexpr unsigned long kWifiCheckIntervalMs = 5000;   // 5秒おきに接続状態を確認
constexpr unsigned long kWifiReconnectTimeoutMs = 10000; // 再接続試行の最大待ち時間
unsigned long lastWifiCheckMs = 0;

constexpr size_t kJsonDocSize = 512;

// 通知モーション（2026-07-20 実機キャリブレーション結果を反映・第2回で再調整）。
// センターはX=80°, Y=75°（ホーン取付角のズレにより当初の85°よりさらに調整が必要だった）。
// 確認済み安全範囲: X 65〜105°(±20), Y 75〜95°(+20、ただし95°付近は当たっている感覚があり要注意)。
// この範囲外は未検証のため使わない。
enum class Motion { None, Nod, Tilt, Shake };

bool parseMotion(const char *value, Motion &out) {
  if (!value) return false;
  if (strcmp(value, "nod") == 0)   { out = Motion::Nod;   return true; }
  if (strcmp(value, "tilt") == 0)  { out = Motion::Tilt;  return true; }
  if (strcmp(value, "shake") == 0) { out = Motion::Shake; return true; }
  return false;
}

struct StackChanCommand {
  bool expressionSet = false;
  m5avatar::Expression expression;
  bool speechSet = false;
  String speech;
  bool faceSet = false;
  int faceIndex = 0;
  bool paletteSet = false;
  int paletteIndex = 0;
  bool durationSet = false;
  unsigned long durationMs = 0;
  bool clear = false;
  // 安全な可動域を実機で見極めるための暫定コマンド（1度単位の絶対角度指定）。デバッグ用に残置。
  bool servoXSet = false;
  int servoXDeg = 0;
  bool servoYSet = false;
  int servoYDeg = 0;
  // 本番のモーション（うなずき/首かしげ/ブンブン）
  bool motionSet = false;
  Motion motion = Motion::None;
};

// ハード上限（安全マージン込みの絶対クランプ）。実機で65〜105(X)/75〜95(Y)まで確認済み。
constexpr int SERVO_X_MIN = 65;
constexpr int SERVO_X_MAX = 105;
constexpr int SERVO_Y_MIN = 75;
constexpr int SERVO_Y_MAX = 95;

// モーション用の基準角度（すべて実機確認済みの安全範囲内。テスト済み最大値より少し内側を使用）。
constexpr int CENTER_X = 80;
constexpr int CENTER_Y = 75;
constexpr int NOD_Y_DOWN = 90;    // うなずき: Y方向 75→90→75 (95°付近は避ける)
constexpr int TILT_X_SIDE = 95;   // 首かしげ: X方向 80→95 で少し保持
constexpr int SHAKE_X_RIGHT = 95; // ブンブン: X方向 65⇔95 の真の左右往復
constexpr int SHAKE_X_LEFT = 65;

bool parseExpression(const char *value, m5avatar::Expression &out);
bool parseCommand(const String &line, StackChanCommand &out, String &error);
void applyCommand(const StackChanCommand &cmd);
void playMotion(Motion motion);
void clearSpeechText();
void ensureWifiConnected();

unsigned long speechClearTime = 0;
bool speechPending = false;

// 音声合成機能（VoiceText）の使用を有効化
//#define USE_VOICE_TEXT //for M5STACK_Core2 Only

//ランダムセリフ生成
// 1. ランダムに選択する文字列を配列で定義
const char* messages[] = {
  "今日は何して遊んだの？",
  "おなかがすいたよ～",
  "眠くなってきちゃった・・・",
  "一緒にゲームしよう",
  "明日ははれるといいね",
  "お散歩行こう"
};
const int MESSAGE_COUNT = sizeof(messages) / sizeof(messages[0]);

#ifdef USE_VOICE_TEXT
#include "AudioFileSourceBuffer.h"
#include "AudioGeneratorMP3.h"
#include "AudioOutputI2SLipSync.h"
#include "AudioFileSourceVoiceTextStream.h"

// Wi-Fi接続用の情報（実際のSSIDとPASSWORDに置き換えてください）
const char *SSID = "YOUR_WIFI_SSID";
const char *PASSWORD = "YOUR_WIFI_PASSWORD";

// 音声再生用オブジェクトの宣言
AudioGeneratorMP3 *mp3;
AudioFileSourceVoiceTextStream *file;
AudioFileSourceBuffer *buff;
AudioOutputI2SLipSync *out;
const int preallocateBufferSize = 40 * 1024;  // 音声バッファサイズの定義
uint8_t *preallocateBuffer;
#endif

using namespace m5avatar;

// アバターオブジェクトと各顔、カラーパレットのインスタンス
Avatar avatar;
Face* faces[3];
ColorPalette* cps[3];

// サーボの初期角度設定（X軸, Y軸）
// 実機キャリブレーション結果（2026-07-20、第2回で再調整）: X=80°, Y=75°が実際の正面（センター）。
#define START_DEGREE_VALUE_X 80
#define START_DEGREE_VALUE_Y 75

// サーボイージングを使用してなめらかに動作させるためのオブジェクト
ServoEasing servo_x;
ServoEasing servo_y;

// setup()でのattach()戻り値。WiFi応答での診断表示に使う。
int servoXAttachResult = -99;
int servoYAttachResult = -99;

// ----------------------------------------------
// タスク関数：アバターの行動制御（主に口の動きの調整）
// ----------------------------------------------
void behavior(void *args)
{
  float gazeX, gazeY;
  DriveContext *ctx = (DriveContext *)args;
  Avatar *avatar = ctx->getAvatar();
  for (;;)
  {
#ifdef USE_VOICE_TEXT
    // スピーカー出力のレベルを取得し、音量に応じた口の開閉具合を計算
    int level = out->getLevel();
    level = abs(level);
    if(level > 10000)
    {
      level = 10000;
    }
    float open = (float)level / 10000.0;
    // 口の開き具合を設定（0.0～1.0の値）
    avatar->setMouthOpenRatio(open);
#endif
    // タスクループ内で短時間待機
    vTaskDelay(1 / portTICK_PERIOD_MS);
    // delay(50);  // 以前は50ms待機していたが、現在は1msに変更
  }
}

// ----------------------------------------------
// タスク関数：サーボ制御（アバターの視線に合わせてサーボ動作を実現）
// ----------------------------------------------
void servoloop(void *args)
{
  //仮でサーボ停止
  return;
  float gazeX, gazeY;
  DriveContext *ctx = (DriveContext *)args;
  for (;;)
  {
    Avatar *avatar = ctx->getAvatar();
    // アバターの視線(gaze)を取得。gazeXとgazeYは通常-1～1の範囲を取る
    avatar->getGaze(&gazeY, &gazeX);
    // X軸サーボの角度を視線に合わせて調整（+-20度の範囲）
    servo_x.setEaseTo(START_DEGREE_VALUE_X + (int)(20.0 * gazeX));
    // Y軸サーボは視線が下方向の場合は+-20度、上方向の場合は+-10度で調整
    if (gazeY < 0) {
      servo_y.setEaseTo(START_DEGREE_VALUE_Y + (int)(20.0 * gazeY));
    } else {
      servo_y.setEaseTo(START_DEGREE_VALUE_Y + (int)(10.0 * gazeY));
    }
    // 全サーボの動作を同期し、全動作完了まで待機
    synchronizeAllServosStartAndWaitForAllServosToStop();
    // 約33ms待機（約30fpsの更新レート）
    vTaskDelay(33 / portTICK_PERIOD_MS);
  }
}

// ----------------------------------------------
// setup関数：初期化処理
// ----------------------------------------------
void setup() {
#ifdef USE_VOICE_TEXT
  // 音声再生用バッファの確保
  preallocateBuffer = (uint8_t*)ps_malloc(preallocateBufferSize);
#endif
  // M5Stackの基本設定の取得と初期化
  auto cfg = M5.config();
  cfg.serial_baudrate = 115200;
  M5.begin(cfg);
  Serial.begin(115200);
  Serial.println("Ready");

  // Stack-chan_Takao_Base: バッテリー(本体電源)駆動時、ExtOutputをtrueにしないと
  // サーボに電源が回らない（公式stack-chan-arduinoのStackchan_Takao_Base.hpp参照）。
  M5.Power.setExtOutput(true);

  // スピーカー設定（サンプルレートとモノラル設定）
  auto spk_config = M5.Speaker.config();
  spk_config.sample_rate = 88200;
  spk_config.stereo = false;
  M5.Speaker.config(spk_config);
  // M5.Speaker.begin();  // 必要に応じてアンコメント

  // サーボの初期設定：指定ピン、初期角度、PWMパルス幅の設定
  // 戻り値をservoXAttachResult/servoYAttachResultに保存し、WiFi応答経由でも診断できるようにする
  // （サーボ電源投入時はUSBシリアルが使えずSerial.printのログが見えないため）。
  servoXAttachResult = servo_x.attach(SERVO_PIN_X, START_DEGREE_VALUE_X, DEFAULT_MICROSECONDS_FOR_0_DEGREE, DEFAULT_MICROSECONDS_FOR_180_DEGREE);
  if (servoXAttachResult) {
    Serial.print("Error attaching servo x");
  }
  servoYAttachResult = servo_y.attach(SERVO_PIN_Y, START_DEGREE_VALUE_Y, DEFAULT_MICROSECONDS_FOR_0_DEGREE, DEFAULT_MICROSECONDS_FOR_180_DEGREE);
  if (servoYAttachResult) {
    Serial.print("Error attaching servo y");
  }
  // イージングタイプの設定（滑らかな動作のための補間）
  servo_x.setEasingType(EASE_QUADRATIC_IN_OUT);
  servo_y.setEasingType(EASE_QUADRATIC_IN_OUT);
  // サーボ動作速度の設定
  setSpeedForAllServos(60);

  //ふきだしに関する表示設定
  avatar.setSpeechFont(&fonts::lgfxJapanGothic_12);

#ifdef USE_VOICE_TEXT
  // ディスプレイの初期設定：明るさ、クリア、文字サイズ設定
  M5.Lcd.setBrightness(100);
  M5.Lcd.clear();
  M5.Lcd.setTextSize(2);
  delay(1000);

  // Wi-Fi接続処理
  Serial.println("Connecting to WiFi");
  M5.Lcd.print("Connecting to WiFi");
  WiFi.disconnect();
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  WiFi.begin(SSID, PASSWORD);
  // Wi-Fiが接続されるまで待機
  while (WiFi.status() != WL_CONNECTED) {
    delay(250);
    Serial.print(".");
    M5.Lcd.print(".");
  }
  Serial.println("\nConnected");
  M5.Lcd.println("\nConnected");
  // 接続確認後、スピーカーでトーン再生
  M5.Speaker.tone(2000, 500);
  delay(500);
  M5.Speaker.tone(1000, 500);
  delay(1000);
  
  // 音声再生用の初期設定
  audioLogger = &Serial;
  out = new AudioOutputI2SLipSync(0, 0);
  out->SetPinout(12, 0, 2);  // I2Sのピン設定（BCK, LRCK, DATA）
  out->SetOutputModeMono(false);
  mp3 = new AudioGeneratorMP3();
#endif

  // 顔データとカラーパレットの初期化
  //faces[0] = new AtaruFace();
  //faces[1] = new RamFace();
  faces[2] = avatar.getFace();
  //cps[0] = new ColorPalette();
  //cps[1] = new ColorPalette();
  cps[2] = new ColorPalette();

  // カラーパレットの設定（各顔の配色）
  //cps[0]->set(COLOR_PRIMARY, TFT_BLACK);
  //cps[0]->set(COLOR_BACKGROUND, TFT_WHITE);
  //cps[0]->set(COLOR_SECONDARY, TFT_WHITE);
  
  //cps[1]->set(COLOR_PRIMARY, TFT_BLACK);
  //cps[1]->set(COLOR_BACKGROUND, TFT_WHITE);
  //cps[1]->set(COLOR_SECONDARY, TFT_WHITE);
  
  cps[2]->set(COLOR_PRIMARY, TFT_WHITE);
  cps[2]->set(COLOR_BACKGROUND, TFT_BLACK);
  cps[2]->set(COLOR_SECONDARY, TFT_WHITE);

  // アバターの初期化と初期設定（顔とパレットの割り当て）
  avatar.init(8);
  avatar.setFace(faces[2]);
  avatar.setColorPalette(*cps[2]);
  // タスクとして行動制御とサーボ制御をアバターへ追加
  avatar.addTask(behavior, "behavior");
  //avatar.addTask(servoloop, "servoloop");

  // ランダムシードの初期化
  // 未接続のアナログピン（A0）を読み取ることで擬似的な乱数シードを生成
  randomSeed( esp_random() );

  // WiFi接続（サーボ電源はスタックチャン本体電源からのみ供給されUSBシリアルが使えないため、
  // PCとの通信はWiFi(TCP)で行う）。
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  unsigned long wifiStart = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - wifiStart < 20000) {
    delay(250);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected. IP: " + WiFi.localIP().toString());
    if (MDNS.begin(kMdnsHostname)) {
      Serial.printf("mDNS started: http://%s.local\n", kMdnsHostname);
    } else {
      Serial.println("mDNS start failed");
    }
    controlServer.begin();
    Serial.printf("Control server listening on port %u\n", kControlPort);
  } else {
    Serial.println("\nWiFi connect failed (continuing without network control)");
  }
}

#ifdef USE_VOICE_TEXT
// 各種テキストおよびTTS用パラメータの定義
char *text1 = "こんにちは、僕の名前はあたるです。よろしくね！";
char *text2 = "こんにちは、私の名前はラムちゃんです。よろしくね！";
char *text3 = "こんにちは、私の名前はスタックちゃんです。よろしくね！";
char *tts_parms1 = "&emotion_level=2&emotion=happiness&format=mp3&speaker=takeru&volume=200&speed=100&pitch=130";
char *tts_parms2 = "&emotion_level=2&emotion=happiness&format=mp3&speaker=hikari&volume=200&speed=120&pitch=130";
char *tts_parms3 = "&emotion_level=4&emotion=anger&format=mp3&speaker=bear&volume=200&speed=120&pitch=100";

// 音声合成（Text-to-Speech）を開始するための関数
void VoiceText_tts(char *text, char *tts_parms) {
    // 指定されたテキストとパラメータから音声ストリームを生成
    file = new AudioFileSourceVoiceTextStream(text, tts_parms);
    // 生成したストリームをバッファリング
    buff = new AudioFileSourceBuffer(file, preallocateBuffer, preallocateBufferSize);
    delay(100);
    // mp3再生を開始
    mp3->begin(buff, out);
}
#endif

//表情に応じてメッセージを生成
char* GenText(int expression){

}

bool parseExpression(const char *value, m5avatar::Expression &out) {
  if (!value) return false;
  if (strcmp(value, "Happy") == 0) { out = Expression::Happy; return true; }
  if (strcmp(value, "Angry") == 0) { out = Expression::Angry; return true; }
  if (strcmp(value, "Sad") == 0) { out = Expression::Sad; return true; }
  if (strcmp(value, "Doubt") == 0) { out = Expression::Doubt; return true; }
  if (strcmp(value, "Sleepy") == 0) { out = Expression::Sleepy; return true; }
  if (strcmp(value, "Neutral") == 0) { out = Expression::Neutral; return true; }
  return false;
}

bool parseCommand(const String &line, StackChanCommand &out, String &error) {
  StaticJsonDocument<kJsonDocSize> doc;
  DeserializationError err = deserializeJson(doc, line);
  if (err) {
    error = String(err.c_str());
    return false;
  }
  if (doc.containsKey("expression")) {
    const char *expr = doc["expression"];
    if (parseExpression(expr, out.expression)) {
      out.expressionSet = true;
    } else {
      error = "invalid expression";
      return false;
    }
  }
  if (doc.containsKey("speech")) {
    out.speech = String((const char *)doc["speech"]);
    out.speechSet = true;
  }
  if (doc.containsKey("face")) {
    out.faceIndex = doc["face"].as<int>();
    out.faceSet = true;
  }
  if (doc.containsKey("palette")) {
    out.paletteIndex = doc["palette"].as<int>();
    out.paletteSet = true;
  }
  if (doc.containsKey("duration")) {
    out.durationMs = doc["duration"].as<unsigned long>();
    out.durationSet = true;
  }
  if (doc.containsKey("clear")) {
    out.clear = doc["clear"].as<bool>();
  }
  if (doc.containsKey("servoX")) {
    out.servoXDeg = doc["servoX"].as<int>();
    out.servoXSet = true;
  }
  if (doc.containsKey("servoY")) {
    out.servoYDeg = doc["servoY"].as<int>();
    out.servoYSet = true;
  }
  if (doc.containsKey("motion")) {
    const char *motion = doc["motion"];
    if (parseMotion(motion, out.motion)) {
      out.motionSet = true;
    } else {
      error = "invalid motion";
      return false;
    }
  }
  return true;
}

void clearSpeechText() {
  avatar.setSpeechText("");
  // セリフが消えたら表情も標準（Neutral）へ戻す。
  // 通知の余韻で感情顔が残り続けると不自然なため、待機顔に復帰させる。
  avatar.setExpression(Expression::Neutral);
  speechPending = false;
  speechClearTime = 0;
}

void applyCommand(const StackChanCommand &cmd) {
  if (cmd.faceSet && cmd.faceIndex >= 0 && cmd.faceIndex < 3) {
    avatar.setFace(faces[cmd.faceIndex]);
  }
  if (cmd.paletteSet && cmd.paletteIndex >= 0 && cmd.paletteIndex < 3) {
    avatar.setColorPalette(*cps[cmd.paletteIndex]);
  }
  if (cmd.expressionSet) {
    avatar.setExpression(cmd.expression);
  }
  if (cmd.speechSet) {
    avatar.setSpeechText(cmd.speech.c_str());
    speechPending = false;
  }
  if (cmd.durationSet && cmd.durationMs > 0) {
    speechPending = true;
    speechClearTime = millis() + cmd.durationMs;
  }
  if (cmd.clear) {
    clearSpeechText();
  }
  // 安全確認フェーズ用の暫定サーボ制御。ハード上限でクランプした上でゆっくり(setSpeedForAllServosの設定速度)動かす。
  if (cmd.servoXSet) {
    int deg = constrain(cmd.servoXDeg, SERVO_X_MIN, SERVO_X_MAX);
    servo_x.setEaseTo(deg);
  }
  if (cmd.servoYSet) {
    int deg = constrain(cmd.servoYDeg, SERVO_Y_MIN, SERVO_Y_MAX);
    servo_y.setEaseTo(deg);
  }
  if (cmd.servoXSet || cmd.servoYSet) {
    synchronizeAllServosStartAndWaitForAllServosToStop();
  }
  if (cmd.motionSet) {
    playMotion(cmd.motion);
  }
}

// 通知モーション本体。すべて実機確認済みの安全範囲(CENTER_X/Y ±確認済み量)のみを使う。
// ブロッキング（完了までOK応答を返さない）。各モーションとも1秒前後で完了する。
void playMotion(Motion motion) {
  switch (motion) {
    case Motion::Nod:
      // うなずき: Y軸を中心から少し下げて戻す、を2回。
      for (int i = 0; i < 2; i++) {
        servo_y.setEaseTo(NOD_Y_DOWN);
        synchronizeAllServosStartAndWaitForAllServosToStop();
        delay(120);
        servo_y.setEaseTo(CENTER_Y);
        synchronizeAllServosStartAndWaitForAllServosToStop();
        delay(120);
      }
      break;
    case Motion::Tilt:
      // 首かしげ: X軸を少し傾けてしばらく保持してから戻す。
      servo_x.setEaseTo(TILT_X_SIDE);
      synchronizeAllServosStartAndWaitForAllServosToStop();
      delay(500);
      servo_x.setEaseTo(CENTER_X);
      synchronizeAllServosStartAndWaitForAllServosToStop();
      break;
    case Motion::Shake:
      // ブンブン: X軸を左右(SHAKE_X_LEFT/RIGHT)で素早く往復させ、最後に中心へ戻す。
      for (int i = 0; i < 2; i++) {
        servo_x.setEaseTo(SHAKE_X_RIGHT);
        synchronizeAllServosStartAndWaitForAllServosToStop();
        servo_x.setEaseTo(SHAKE_X_LEFT);
        synchronizeAllServosStartAndWaitForAllServosToStop();
      }
      servo_x.setEaseTo(CENTER_X);
      synchronizeAllServosStartAndWaitForAllServosToStop();
      break;
    case Motion::None:
    default:
      break;
  }
}

// 1行分のコマンド文字列を解釈して実行し、応答文字列("OK"または"ERR ...")を返す。
// Serial経由・WiFi(TCP)経由の両方から共通で使う。
String handleCommandLine(const String &rawLine) {
  String line = rawLine;
  line.trim();
  if (line.length() == 0) {
    return "";
  }
  StackChanCommand cmd;
  String error;
  if (parseCommand(line, cmd, error)) {
    applyCommand(cmd);
    String resp = "OK";
    if (cmd.servoXSet || cmd.servoYSet) {
      // サーボ電源投入時はSerialログが見えないため、診断情報をWiFi応答に埋め込む。
      resp += " diag attachX=" + String(servoXAttachResult)
            + " attachY=" + String(servoYAttachResult)
            + " curX=" + String(servo_x.getCurrentAngle())
            + " curY=" + String(servo_y.getCurrentAngle());
    }
    return resp;
  }
  return "ERR " + error;
}

// WiFiが切断されていたら再接続を試みる（長時間稼働中の切断対策）。
// 呼び出しごとに毎回チェックすると重いので、kWifiCheckIntervalMsおきに間引く。
void ensureWifiConnected() {
  if (millis() - lastWifiCheckMs < kWifiCheckIntervalMs) return;
  lastWifiCheckMs = millis();
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.println("WiFi disconnected. Reconnecting...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < kWifiReconnectTimeoutMs) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("WiFi reconnected. IP: " + WiFi.localIP().toString());
    // 切断・再接続でmDNSの内部状態が古くなる場合があるため念のため再登録する。
    MDNS.end();
    if (MDNS.begin(kMdnsHostname)) {
      Serial.printf("mDNS restarted: http://%s.local\n", kMdnsHostname);
    }
  } else {
    Serial.println("WiFi reconnect failed. Will retry later.");
  }
}

// サーボ用の電源はスタックチャン本体電源Type-C接続時のみ供給され、
// その場合USBシリアルでの通信ができない（本体USB-Cはデータ非対応の給電専用ポートのため）。
// そのためWiFi経由のTCP接続でも同じJSONコマンドを受け付ける。
void handleWifiClients() {
  if (WiFi.status() != WL_CONNECTED) return;
  WiFiClient client = controlServer.available();
  if (!client) return;

  unsigned long start = millis();
  while (client.connected() && client.available() == 0 && millis() - start < 2000) {
    delay(1);
  }
  if (client.available()) {
    String line = client.readStringUntil('\n');
    Serial.print("RX(wifi): ");
    Serial.println(line);
    String response = handleCommandLine(line);
    if (response.length() > 0) {
      client.println(response);
    }
  }
  client.stop();
}

// ----------------------------------------------
// メインループ：シリアル/WiFi両方からコマンドを受け取り、表情を更新
// ----------------------------------------------
void loop() {
  M5.update();
  ensureWifiConnected();
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      Serial.print("RX: ");
      Serial.println(line);
      Serial.println(handleCommandLine(line));
    }
  }
  handleWifiClients();
  if (speechPending && speechClearTime != 0 && millis() >= speechClearTime) {
    clearSpeechText();
  }
}
