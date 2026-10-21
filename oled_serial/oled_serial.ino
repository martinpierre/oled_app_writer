/*
  oled_serial.ino - Affichage en direct sur OLED SSD1306 128x64 (I2C)

  Bibliothèques (Gestionnaire de bibliothèques) :
    - Adafruit SSD1306
    - Adafruit GFX Library

  Câblage Uno/Nano : SDA -> A4, SCL -> A5, VCC -> 5V (ou 3.3V), GND -> GND
  Adresse I2C : 0x3C (parfois 0x3D selon le module)

  Protocole (115200 bauds), 2 octets par pixel :
    octet 1 : 1 C yyyyyy   (bit7 = 1, C = couleur 1=blanc / 0=noir, y = 0..63)
    octet 2 : 0 xxxxxxx    (x = 0..127)
    octet seul 0x7F        : efface l'écran
  Après chaque rafraîchissement, l'Arduino envoie 'K' (accusé pour le PC).
*/
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#define SCREEN_W 128
#define SCREEN_H 64
#define OLED_ADDR 0x3C

Adafruit_SSD1306 display(SCREEN_W, SCREEN_H, &Wire, -1);

bool dirty = false;
bool haveHi = false;
uint8_t hiByte = 0;
unsigned long lastRx = 0;

void setup() {
  Serial.begin(115200);
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) {
    for (;;) ;                       // écran non trouvé : on bloque
  }
  Wire.setClock(400000);             // I2C rapide
  display.clearDisplay();
  display.display();
  Serial.write('R');                 // "ready"
}

void loop() {
  // 1) Lire tout ce qui arrive et dessiner dans le buffer (RAM)
  while (Serial.available()) {
    uint8_t b = Serial.read();
    lastRx = micros();

    if (b & 0x80) {                  // premier octet d'un pixel
      hiByte = b;
      haveHi = true;
    } else if (haveHi) {             // second octet : on dessine
      haveHi = false;
      uint8_t y = hiByte & 0x3F;
      uint8_t color = (hiByte & 0x40) ? SSD1306_WHITE : SSD1306_BLACK;
      display.drawPixel(b, y, color);
      dirty = true;
    } else if (b == 0x7F) {          // commande d'effacement
      display.clearDisplay();
      dirty = true;
    }
  }

  // 2) Quand la rafale est terminée (silence > 1,5 ms), on rafraîchit l'écran.
  //    On envoie l'accusé AVANT display() pour que le PC prépare déjà le paquet
  //    suivant pendant le transfert I2C (le buffer série de l'Uno fait 63 octets).
  if (dirty && (micros() - lastRx) > 1500) {
    Serial.write('K');
    display.display();
    dirty = false;
  }
}
