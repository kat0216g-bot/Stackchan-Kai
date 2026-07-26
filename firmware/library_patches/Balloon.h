// Copyright (c) Shinya Ishikawa. All rights reserved.
// Licensed under the MIT license. See LICENSE file in the project root for full
// license information.

#ifndef BALLOON_H_
#define BALLOON_H_
#define LGFX_USE_V1
#include <M5Unified.h>
#include "DrawContext.h"
#include "Drawable.h"

#ifndef ARDUINO
#include <string>
typedef std::string String;
#endif  // ARDUINO

const int16_t TEXT_HEIGHT = 8;
const int16_t TEXT_SIZE = 2;
const int16_t MIN_WIDTH = 40;
const int cx = 240;
const int cy = 220;

namespace m5avatar {
class Balloon final : public Drawable {
 public:
  // constructor
  Balloon() = default;
  ~Balloon() = default;
  Balloon(const Balloon &other) = default;
  Balloon &operator=(const Balloon &other) = default;
  void draw(M5Canvas *spi, BoundingRect rect,
            DrawContext *drawContext) override {
    String text = drawContext->getspeechText();
    const lgfx::IFont *font = drawContext->getSpeechFont();
    if (text.length() == 0) {
      return;
    }
    ColorPalette* cp = drawContext->getColorPalette();
    uint16_t primaryColor = cp->get(COLOR_BALLOON_FOREGROUND);
    uint16_t backgroundColor = cp->get(COLOR_BALLOON_BACKGROUND);
    M5.Lcd.setTextSize(TEXT_SIZE);
    M5.Lcd.setTextDatum(MC_DATUM);
    spi->setTextSize(TEXT_SIZE);
    spi->setTextColor(primaryColor, backgroundColor);
    spi->setTextDatum(MC_DATUM);
    M5.Lcd.setFont(font);

    // 長文対応: "\n" で区切られた複数行を吹き出しに描画する（元は1行決め打ちだった）。
    // 改行の判断（どこで折り返すか）は呼び出し側（.ino / stackchan_notify.py）で行う想定。
    const int kMaxLines = 4;
    String lines[kMaxLines];
    int lineCount = 0;
    int start = 0;
    while (lineCount < kMaxLines) {
      int nl = text.indexOf('\n', start);
      if (nl < 0) {
        lines[lineCount++] = text.substring(start);
        break;
      }
      lines[lineCount++] = text.substring(start, nl);
      start = nl + 1;
    }

    int textHeight = TEXT_HEIGHT * TEXT_SIZE;  // 楕円サイズ計算用（従来通り）
    // 行間はTEXT_HEIGHTの決め打ちではなく実際のフォント高さを使う
    // （決め打ち値だと実フォントより小さく、複数行が重なって見えなくなっていた）。
    int lineHeight = M5.Lcd.fontHeight();
    if (lineHeight <= 0) lineHeight = textHeight;
    int maxWidth = 0;
    for (int i = 0; i < lineCount; i++) {
      int w = M5.Lcd.textWidth(lines[i].c_str());
      if (w > maxWidth) maxWidth = w;
    }
    // 元の1行用サイズ式(textHeight*2+2)を行数・実フォント高さに応じて拡張する。
    int innerRy = lineHeight * lineCount + textHeight;
    int outerRy = innerRy + 2;

    // 行が増えた分は下ではなく上に広げる（cyは画面下寄りのため、下に伸ばすと
    // 3行目以降が画面外にはみ出してしまう）。最終行の位置は1行時と同じcyに固定し、
    // それより前の行を上へ積み上げる。楕円の中心だけテキストブロックに合わせて上にずらす。
    int blockHeight = lineHeight * (lineCount - 1);
    int ellipseCy = cy - blockHeight / 2;
    int firstLineY = cy - blockHeight;

    spi->fillEllipse(cx - 20, ellipseCy, maxWidth + 2, outerRy,
                     primaryColor);
    spi->fillTriangle(cx - 62, cy - 42, cx - 8, cy - 10, cx - 41, cy - 8,
                      primaryColor);
    spi->fillEllipse(cx - 20, ellipseCy, maxWidth, innerRy,
                     backgroundColor);
    spi->fillTriangle(cx - 60, cy - 40, cx - 10, cy - 10, cx - 40, cy - 10,
                      backgroundColor);

    for (int i = 0; i < lineCount; i++) {
      int w = M5.Lcd.textWidth(lines[i].c_str());
      spi->drawString(lines[i].c_str(), cx - w / 6 - 15, firstLineY + i * lineHeight, font);
    }
  }
};

}  // namespace m5avatar

#endif  // BALLOON_H_
