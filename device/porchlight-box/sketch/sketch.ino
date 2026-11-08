// Porchlight box, MCU side (STM32 on the UNO Q).
// Reads the two buttons and the motion sensor, drives the vibration motor and
// the LED matrix. The Linux side calls these functions over the Bridge.
//
// Wiring: I'm OK button D2 to GND, Help button D4 to GND (internal pull-ups),
// vibration module IN on D5, PIR OUT on D7. All logic is 3.3 V.
#include "Arduino_RouterBridge.h"
#include <Arduino_LED_Matrix.h>

const int PIN_OK = 2;
const int PIN_HELP = 4;
const int PIN_MOTOR = 5;
const int PIN_PIR = 7;

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
int pending = 0;                  // bit 0: OK pressed, bit 1: help pressed, bit 2: motion
int lastOk = HIGH, lastHelp = HIGH, lastPir = LOW;
unsigned long lastPress = 0, motorOffAt = 0;

void show(int frame) {
  if (frame >= 0 && frame < 5) matrix.draw(FRAMES[frame]);
}

void buzz(int ms) {
  digitalWrite(PIN_MOTOR, HIGH);
  motorOffAt = millis() + ms;
}

// Returns what happened since the last call and clears it, so a press is
// reported exactly once even if the network is slow.
int read_inputs() {
  int v = pending;
  pending = 0;
  return v;
}

void setup() {
  pinMode(PIN_OK, INPUT_PULLUP);
  pinMode(PIN_HELP, INPUT_PULLUP);
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_MOTOR, OUTPUT);
  matrix.begin();
  matrix.setGrayscaleBits(1);
  show(IDLE);
  Bridge.begin();
  // provide_safe runs these inside loop(), so they never race with it.
  Bridge.provide_safe("read_inputs", read_inputs);
  Bridge.provide_safe("show", show);
  Bridge.provide_safe("buzz", buzz);
}

void loop() {
  int ok = digitalRead(PIN_OK), help = digitalRead(PIN_HELP), pir = digitalRead(PIN_PIR);
  bool settled = millis() - lastPress > 250;       // debounce
  if (ok == LOW && lastOk == HIGH && settled) {
    pending |= 1; lastPress = millis();
    show(OK); buzz(120);                           // answer the press even if Wi-Fi is down
  }
  if (help == LOW && lastHelp == HIGH && settled) {
    pending |= 2; lastPress = millis();
    show(HELP); buzz(400);
  }
  if (pir == HIGH && lastPir == LOW) pending |= 4;
  lastOk = ok; lastHelp = help; lastPir = pir;
  if (motorOffAt && (long)(millis() - motorOffAt) >= 0) {
    digitalWrite(PIN_MOTOR, LOW);
    motorOffAt = 0;
  }
}
