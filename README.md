# oled_app_writer
Minitools to write on oled screen between web app and arduino uno.

Full vibe coded with CLAUDE


# OLED Draw – dessin en direct sur écran OLED 128×64

Dessinez au doigt (ou à la souris) dans le navigateur : le dessin s'affiche en temps réel sur un écran OLED SSD1306 branché à un Arduino.

```
Navigateur (téléphone/PC) ──WebSocket──▶ oled_server.py ──USB série──▶ Arduino ▶ OLED
```

**Fonctions** : crayon, ligne, cercle, carré, triangle · pixel blanc ou noir (gomme) · effacement de toute la matrice · choix du port COM depuis l'interface · plusieurs appareils connectés en même temps.

## Contenu

| Fichier | Rôle |
| --- | --- |
| `oled_serial/oled_serial.ino` | Sketch Arduino : reçoit les pixels et rafraîchit l'OLED |
| `oled_server.py` | Serveur Python : sert le front et relaie vers le port série |
| `oled_front.html` | Interface web (conçue pour smartphone en paysage, Firefox) |
| `requirements.txt` | Dépendances Python |
| `oled_draw.py` | *(optionnel)* version autonome en tkinter, sans navigateur |

## Matériel

- Arduino Uno / Nano (ou compatible) + câble USB de données
- Écran OLED **SSD1306 128×64 en I2C**

| OLED | Arduino Uno/Nano |
| --- | --- |
| VCC | 5V (ou 3,3V) |
| GND | GND |
| SDA | A4 |
| SCL | A5 |

## Installation

### 1. Arduino

1. Dans l'IDE Arduino, installer les bibliothèques **Adafruit SSD1306** et **Adafruit GFX Library**.
2. Ouvrir `oled_serial/oled_serial.ino` (adresse I2C `0x3C`, à passer en `0x3D` si l'écran reste noir).
3. Téléverser, puis **fermer le moniteur série** (il bloque le port).

### 2. Serveur Python

Python 3.9+ requis.

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate      Linux/macOS : source .venv/bin/activate
pip install -r requirements.txt
```

## Utilisation

```bash
python oled_server.py                  # choix du port dans l'interface
python oled_server.py --serial COM3    # ouverture automatique du port
```

Le serveur affiche deux adresses :

```
Sur ce PC       : http://localhost:8000
Sur le téléphone: http://192.168.1.20:8000  (même Wi-Fi)
```

1. Ouvrir l'adresse dans Firefox (téléphone en **mode paysage**).
2. Choisir le port de l'Arduino dans la liste, puis **Connecter** (≈ 2 s : l'Arduino redémarre).
3. Dessiner. **Effacer la matrice** vide l'écran OLED.

> Ne pas ouvrir `oled_front.html` en double-cliquant : la page serait en mode démo, sans serveur.

Options : `--http-port 8080` (autre port), `--host 127.0.0.1` (accès limité à ce PC).

## Accès depuis le téléphone (Windows)

Si le téléphone n'atteint pas le serveur :

1. Passer le Wi-Fi du PC en réseau **Privé** (Paramètres › Réseau et Internet › Wi-Fi › propriétés).
2. Autoriser le port dans le pare-feu (PowerShell **administrateur**) :

   ```powershell
   New-NetFirewallRule -DisplayName "OLED server" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Private
   ```

3. Téléphone et PC sur le **même Wi-Fi** (pas de réseau invité, pas de VPN).

Alternative Android sans Wi-Fi : câble USB + débogage USB, puis `adb reverse tcp:8000 tcp:8000` et ouvrir `http://localhost:8000` sur le téléphone.

## Dépannage

| Problème | Piste |
| --- | --- |
| « Serveur injoignable » | Serveur arrêté, mauvaise adresse IP, pare-feu (voir ci-dessus) |
| Liste de ports vide | Câble USB « charge seulement », pilote manquant |
| Port occupé / accès refusé | Fermer le moniteur série Arduino et l'app tkinter ; Linux : `sudo usermod -aG dialout $USER` |
| Écran OLED noir | Vérifier le câblage, l'adresse `0x3C`/`0x3D`, le type d'écran (SH1106 ≠ SSD1306) |
| `ModuleNotFoundError: serial` | `pip uninstall serial` puis `pip install pyserial` |
| `tkinter` introuvable (Linux) | `sudo apt install python3-tk` (uniquement pour `oled_draw.py`) |

## Protocole série (115200 bauds)

Binaire, 2 octets par pixel :

| Octet | Format | Détail |
| --- | --- | --- |
| 1 | `1 C yyyyyy` | `C` = couleur (1 blanc, 0 noir), `y` = 0..63 |
| 2 | `0 xxxxxxx` | `x` = 0..127 |
| seul | `0x7F` | Efface tout l'écran |

L'Arduino répond `K` avant chaque rafraîchissement : le serveur n'envoie que 60 octets entre deux accusés (le buffer série de l'Uno fait 63 octets).

Côté WebSocket (`/ws`), le navigateur envoie les mêmes octets en messages binaires, et des commandes JSON : `{"cmd":"open","port":"COM3"}` / `{"cmd":"close"}`.

## Sécurité

Le serveur n'a **pas d'authentification** et écoute sur tout le réseau local par défaut. À utiliser sur un réseau de confiance (Wi-Fi privé), sinon lancer avec `--host 127.0.0.1`.
