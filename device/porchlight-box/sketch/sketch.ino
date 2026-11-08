// Porchlight UNO Q: physical inputs stay on the MCU; Linux owns networking.
// Verified wiring: PIR D2, button D3 to GND (INPUT_PULLUP), green D8, red D9.
// D5 drives a 3-pin vibration motor module (VCC 5V, GND, IN on D5): HIGH=ON, LOW=OFF.
// Tested on the module: D5 HIGH runs the motor, LOW stops it.
#include "Arduino_RouterBridge.h"
#include <Arduino_LED_Matrix.h>

#ifndef PORCHLIGHT_MOTOR_ENABLED
#define PORCHLIGHT_MOTOR_ENABLED 1
#endif
const int PIN_PIR = 2, PIN_BUTTON = 3, PIN_MOTOR = 5;
const int PIN_GREEN = 8, PIN_RED = 9;
const unsigned long DEBOUNCE_MS = 30, DOUBLE_PRESS_MS = 600;
const unsigned long GREEN_MS = 5000, MOTION_INTERVAL_MS = 2000;

// Same frames, same order as web/patterns.js: idle, ok, ask, help, visitor.
uint8_t FRAMES[5][104] = {
  { // idle
    0,0,0,0,0,0,1,0,0,0,0,0,0,
    0,0,0,0,0,1,1,1,0,0,0,0,0,
    0,0,0,0,1,1,1,1,1,0,0,0,0,
    0,0,0,1,1,1,1,1,1,1,0,0,0,
    0,0,0,0,1,0,0,0,1,0,0,0,0,
    0,0,0,0,1,0,1,0,1,0,0,0,0,
    0,0,0,0,1,0,0,0,1,0,0,0,0,
    0,0,0,0,1,1,1,1,1,0,0,0,0,
  },
  { // ok
    0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,0,1,0,
    0,0,0,0,0,0,0,0,0,0,1,1,0,
    0,1,0,0,0,0,0,0,0,1,1,0,0,
    0,1,1,0,0,0,0,0,1,1,0,0,0,
    0,0,1,1,0,0,0,1,1,0,0,0,0,
    0,0,0,1,1,0,1,1,0,0,0,0,0,
    0,0,0,0,1,1,1,0,0,0,0,0,0,
  },
  { // ask
    0,0,0,0,0,1,1,1,0,0,0,0,0,
    0,0,0,0,1,0,0,0,1,0,0,0,0,
    0,0,0,0,0,0,0,0,1,0,0,0,0,
    0,0,0,0,0,0,0,1,0,0,0,0,0,
    0,0,0,0,0,0,1,0,0,0,0,0,0,
    0,0,0,0,0,0,1,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,1,0,0,0,0,0,0,
  },
  { // help
    0,0,0,0,0,0,1,0,0,0,0,0,0,
    0,0,0,0,0,1,1,1,0,0,0,0,0,
    0,0,0,0,0,1,1,1,0,0,0,0,0,
    0,0,0,0,0,1,1,1,0,0,0,0,0,
    0,0,0,0,0,0,1,0,0,0,0,0,0,
    0,0,0,0,0,0,1,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,1,0,0,0,0,0,0,
  },
  { // visitor
    0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,1,1,0,0,0,0,0,1,1,0,0,
    0,1,1,1,1,0,0,0,1,1,1,1,0,
    0,1,1,1,1,1,1,1,1,1,1,1,0,
    0,0,1,1,1,1,1,1,1,1,1,0,0,
    0,0,0,1,1,1,1,1,1,1,0,0,0,
    0,0,0,0,1,1,1,1,1,0,0,0,0,
    0,0,0,0,0,0,1,0,0,0,0,0,0,
  }
};
const int IDLE = 0, OK = 1, HELP = 3;
Arduino_LED_Matrix matrix;
int pending = 0;                  // unchanged bits: OK=1, Help=2, motion=4
int helpFrame = HELP;
int rawButton = HIGH, stableButton = HIGH, lastPir = LOW;
bool waitingSecond = false, helpActive = false, helpPending = false;
bool greenActive = false, motionReported = false;
unsigned long buttonChangedAt = 0, firstPressAt = 0, greenAt = 0, lastMotionAt = 0;

// Pattern 1: short-short-long wellness prompt. Pattern 2: two short acknowledgment pulses.
const unsigned int WELLNESS[] = {200, 150, 200, 150, 600};
const unsigned int ACKNOWLEDGED[] = {200, 150, 200};
const unsigned int *vibration = nullptr;
int vibrationLength = 0, vibrationStep = 0, queuedPattern = 0;
unsigned long vibrationAt = 0, vibrationDuration = 0;

void motor_output(bool on) {
#if PORCHLIGHT_MOTOR_ENABLED
  digitalWrite(PIN_MOTOR, on ? HIGH : LOW);
#endif
}

void show(int frame) {
  if (helpPending) frame = HELP;   // a stale poll must not imply acknowledgment
  else if (helpActive) frame = helpFrame;
  if (frame >= 0 && frame < 5) matrix.draw(FRAMES[frame]);
}

void buzz(int ms) {              // retain the original Bridge command
  vibration = nullptr;
  vibrationLength = 1;
  vibrationStep = 0;
  vibrationAt = millis();
  vibrationDuration = ms > 0 ? (unsigned long)ms : 0;
  motor_output(vibrationDuration > 0);
}

void buzz_pattern(int pattern) {
  if (pattern != 1 && pattern != 2) { buzz(700); return; }
  if (vibrationLength) { queuedPattern = pattern; return; }
  vibration = pattern == 1 ? WELLNESS : ACKNOWLEDGED;
  vibrationLength = pattern == 1 ? 5 : 3;
  vibrationStep = 0;
  vibrationAt = millis();
  vibrationDuration = vibration[0];
  motor_output(true);
}

// 0=no server Help, 1=requested, 2=acknowledged, 3=resolved.
// Bit 2 (4) is set ONLY after a Help POST succeeds, releasing the local latch.
void help_state(int command) {
  if (command & 4) helpPending = false;
  int state = command & 3;
  if (state == 1 || state == 2) {
    helpActive = true;
    helpFrame = state == 2 ? 4 : HELP;
    show(helpFrame);
  }
  if (state == 3 && !helpPending) helpActive = false;
  digitalWrite(PIN_RED, (helpActive || helpPending) ? HIGH : LOW);
  if (helpActive || helpPending) digitalWrite(PIN_GREEN, LOW);
}

int read_inputs() {
  int v = pending;
  pending = 0;
  return v;
}

void request_help() {
  pending |= 2;
  helpActive = helpPending = true;
  show(HELP);
}

void activity(unsigned long now) {
  greenActive = true;
  greenAt = now;
}

void setup() {
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_RED, OUTPUT);
  digitalWrite(PIN_GREEN, LOW);
  digitalWrite(PIN_RED, LOW);
#if PORCHLIGHT_MOTOR_ENABLED
  pinMode(PIN_MOTOR, OUTPUT);
  digitalWrite(PIN_MOTOR, LOW);
#endif
  matrix.begin();
  matrix.setGrayscaleBits(1);
  show(IDLE);
  Bridge.begin();
  Bridge.provide_safe("read_inputs", read_inputs);
  Bridge.provide_safe("show", show);
  Bridge.provide_safe("buzz", buzz);
  Bridge.provide_safe("buzz_pattern", buzz_pattern);
  Bridge.provide_safe("help_state", help_state);
}

void loop() {
  unsigned long now = millis();
  int button = digitalRead(PIN_BUTTON);
  if (button != rawButton) { rawButton = button; buttonChangedAt = now; }
  if (button != stableButton && now - buttonChangedAt >= DEBOUNCE_MS) {
    stableButton = button;
    if (button == LOW) {
      if (waitingSecond && now - firstPressAt <= DOUBLE_PRESS_MS) {
        waitingSecond = false;
        pending |= 1;           // double press produces OK only
        activity(now);
        show(OK);
      } else {
        if (waitingSecond) request_help();
        waitingSecond = true;
        firstPressAt = now;
      }
    }
  }
  if (waitingSecond && now - firstPressAt >= DOUBLE_PRESS_MS) {
    waitingSecond = false;
    request_help();              // single press waits for the double-press window
  }

  int pir = digitalRead(PIN_PIR);
  if (pir == HIGH && lastPir == LOW && (!motionReported || now - lastMotionAt >= MOTION_INTERVAL_MS)) {
    pending |= 4;                // motion never becomes a manual OK
    motionReported = true;
    lastMotionAt = now;
    activity(now);
  }
  lastPir = pir;
  if (greenActive && now - greenAt >= GREEN_MS) greenActive = false;
  digitalWrite(PIN_RED, (helpActive || helpPending) ? HIGH : LOW);
  digitalWrite(PIN_GREEN, greenActive && !helpActive && !helpPending ? HIGH : LOW);

  if (vibrationLength && now - vibrationAt >= vibrationDuration) {
    vibrationStep++;
    if (vibrationStep >= vibrationLength) {
      vibrationLength = 0;
      motor_output(false);
      if (queuedPattern) {
        int next = queuedPattern;
        queuedPattern = 0;
        buzz_pattern(next);
      }
    } else {
      vibrationAt = now;
      vibrationDuration = vibration[vibrationStep];
      motor_output(vibrationStep % 2 == 0);
    }
  }
}
