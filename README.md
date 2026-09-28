# Filament Manager

[![Validate](https://github.com/ludgerbeckmann/ha_filament_manager/actions/workflows/validate.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/ludgerbeckmann/ha_filament_manager.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/releases/)
[![GitHub license](https://img.shields.io/github/license/ludgerbeckmann/ha_filament_manager.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/blob/main/LICENSE)

HA Integration zur Verwaltung des eigenen 3D-Druck-Filamentbestandes –
inspiriert von [Spoolman](https://github.com/Donkie/Spoolman), aber als
schlanke, native Home-Assistant-Integration ohne externen Server.

## Funktionen

- Jede Filamentspule wird als eigenes Gerät angelegt, mit **Name, Material,
  Farbe, Hersteller, Durchmesser** und **Gesamt-/Restgewicht**.
- Die Restmenge lässt sich direkt im Dashboard anpassen (editierbare
  `number`-Entität) oder per Service aktualisieren.
- Ein Sensor zeigt den **Füllstand in Prozent** – ideal für
  Balken-/Glance-Karten auf dem Dashboard.
- Optional kann pro Spule ein vorhandener **Luftfeuchtigkeitssensor**
  hinterlegt werden (z. B. ein Hygrometer in der Trockenbox). Überschreitet
  die gemessene Luftfeuchtigkeit den konfigurierten Grenzwert, schaltet ein
  `binary_sensor` auf "Warnung".
- **Filamentboxen**: bis zu 4 Spulen lassen sich zu einer physischen
  Trockenbox gruppieren, die einen einzigen gemeinsamen
  Luftfeuchtigkeitssensor für alle zugeordneten Spulen trägt (siehe
  "Filamentboxen" unten).
- Optional außerdem eine **Warnung bei niedrigem Bestand** (Schwellwert in %
  frei wählbar).
- Beide Warnungen können automatisch **Push-Benachrichtigungen** verschicken
  und/oder eine **dauerhafte Benachrichtigung** im Dashboard anzeigen –
  keine eigene Automation nötig (siehe "Benachrichtigungen" unten).
- Bringt eine eigene **Lovelace-Übersichtskarte** mit, die automatisch alle
  Spulen anzeigt – keine YAML-Konfiguration oder zusätzliche Ressource
  nötig, siehe unten.

## Installation

### Über HACS (empfohlen)

1. HACS öffnen → *Integrationen* → Menü (⋮) → *Benutzerdefinierte
   Repositories*.
2. Dieses Repository (`ludgerbeckmann/ha_filament_manager`) als Kategorie
   *Integration* hinzufügen.
3. "Filament Manager" installieren und Home Assistant neu starten.

### Manuell

Den Ordner `custom_components/ha_filament_manager` in das
`custom_components`-Verzeichnis deiner Home-Assistant-Installation kopieren
und Home Assistant neu starten.

## Einrichtung

Über *Einstellungen → Geräte & Dienste → Integration hinzufügen* → nach
"Filament Manager" suchen erscheint zunächst eine Auswahl, ob eine
**Filamentspule** oder eine **Filamentbox** angelegt werden soll.

### Spule anlegen

1. Material und Farbe (beides Dropdowns mit gängigen Werten, aber frei
   überschreibbar) sowie optional Hersteller (ebenfalls Dropdown mit
   bekannten Marken) auswählen.
2. Durchmesser, Gesamtgewicht und (falls schon angebrochen) aktuelle
   Restmenge eintragen. Das Gesamtgewicht ist bereits vorbelegt: mit einem
   bekannten Realwert, falls für die Kombination aus Hersteller und Material
   einer hinterlegt ist, sonst mit einem branchenüblichen Standardwert (z. B.
   500 g für TPU/PVA, sonst 1000 g) – in jedem Fall frei überschreibbar.
3. Optional eine bereits angelegte **Filamentbox** auswählen, um die Spule
   ihr zuzuordnen (siehe "Filamentboxen" unten). Falls zugeordnet, übernimmt
   die Box die Luftfeuchtigkeitsüberwachung für diese Spule – ein eigener
   Luftfeuchtigkeitssensor der Spule wird dann ignoriert.
4. Optional (falls keine Box zugeordnet ist) einen eigenen
   Luftfeuchtigkeitssensor und einen Grenzwert (Standard 40 %) hinterlegen,
   optional einen Schwellwert für die Bestandswarnung (z. B. 15 %), und
   optional ein oder mehrere Notify-Ziele sowie ob zusätzlich eine
   dauerhafte Benachrichtigung angezeigt werden soll (siehe
   "Benachrichtigungen" unten).
5. Im letzten Schritt einen Namen vergeben – vorbelegt mit einem Vorschlag
   aus Hersteller, Material und Farbe (z. B. "Prusament PETG Rot"), kann
   aber beliebig angepasst werden.
6. Für eine weitere Spule den Vorgang wiederholen ("+ Integration
   hinzufügen" → erneut "Filament Manager" wählen).

Bekannte Gesamtgewichte für bestimmte Hersteller/Material-Kombinationen
sind in `custom_components/ha_filament_manager/const.py`
(`MANUFACTURER_MATERIAL_WEIGHTS`) hinterlegt und lassen sich dort beliebig
ergänzen, sobald reale Werte bekannt sind.

Bestehende Spulen lassen sich über das Zahnrad-Symbol des jeweiligen
Eintrags bearbeiten (Material, Farbe, Gesamtgewicht, Filamentbox,
Luftfeuchtigkeitssensor usw.). Die Restmenge wird dort bewusst nicht
verändert – dafür gibt es die `number`-Entität und die Dienste unten.

## Filamentboxen

Eine **Filamentbox** bildet eine physische Trockenbox ab, in die bis zu
**4 Spulen** passen und die mit einem einzigen Luftfeuchtigkeitssensor
ausgestattet ist. Statt den Sensor mehrfach je Spule zu hinterlegen, wird er
einmal an der Box konfiguriert:

1. Bei "Integration hinzufügen" → "Filament Manager" → **Filamentbox**
   wählen.
2. Namen (z. B. "Trockenbox 1") sowie optional Luftfeuchtigkeitssensor,
   Grenzwert und Benachrichtigungseinstellungen hinterlegen (siehe
   "Benachrichtigungen" unten – funktioniert für Boxen genauso wie für
   Spulen).
3. Beim Anlegen oder Bearbeiten einer Spule die Box im Feld "Filamentbox"
   auswählen.

Eine Box, die bereits 4 zugeordnete Spulen hat, kann keiner weiteren Spule
mehr zugewiesen werden. Auf dem Dashboard werden Spulen einer Box
gruppiert unter einer gemeinsamen Kopfzeile mit Boxname und
Luftfeuchtigkeit angezeigt (siehe "Dashboard-Karte" unten).

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| `number.<spule>_remaining_weight` | Restmenge in Gramm, direkt editierbar |
| `sensor.<spule>_remaining_percentage` | Füllstand in % |
| `sensor.<spule>_material` | Materialtyp (z. B. PLA, PETG) |
| `sensor.<spule>_color` | Farbe |
| `binary_sensor.<spule>_humidity_alert` | Nur vorhanden, wenn die Spule (ohne Filamentbox) einen eigenen Luftfeuchtigkeitssensor hat |
| `binary_sensor.<spule>_low_stock_alert` | Nur vorhanden, wenn ein Bestandsschwellwert hinterlegt wurde |
| `binary_sensor.<box>_humidity_alert` | Gemeinsame Luftfeuchtigkeitswarnung einer Filamentbox, nur vorhanden, wenn die Box einen Sensor hat |

## Dienste

- `ha_filament_manager.consume_filament` – reduziert die Restmenge einer Spule
  (Feld `amount` in Gramm). Praktisch für Automationen, die nach jedem Druck
  automatisch die verbrauchte Menge abziehen.
- `ha_filament_manager.refill_spool` – setzt die Restmenge zurück (Feld
  `amount`, ohne Angabe wird auf das Gesamtgewicht zurückgesetzt) – z. B.
  beim Einlegen einer neuen Spule.

## Benachrichtigungen

Sowohl die Luftfeuchtigkeits- als auch die Bestandswarnung können pro Spule
automatisch benachrichtigen, sobald der jeweilige `binary_sensor` von "aus"
auf "an" wechselt (keine eigene Automation nötig):

- **Push-Benachrichtigung**: ein oder mehrere Notify-Ziele auswählbar (z. B.
  `notify.mobile_app_dein_handy`).
- **Dauerhafte Benachrichtigung**: zusätzlich als Karte im Dashboard
  (*Einstellungen → Benachrichtigungen*), wird automatisch wieder entfernt,
  sobald der Warnzustand endet (z. B. Luftfeuchtigkeit wieder unter dem
  Grenzwert, oder Spule aufgefüllt).

Beide Kanäle sind optional und unabhängig voneinander zuschaltbar, über das
Zahnrad-Symbol der jeweiligen Spule bzw. Box nachträglich änderbar.

## Dashboard-Karte

### Eingebaute Übersichtskarte (empfohlen)

Die Integration liefert eine eigene Lovelace-Karte mit, die **automatisch
alle Spulen** anzeigt und sich selbst beim Frontend registriert – keine
zusätzliche Ressource unter *Einstellungen → Dashboards → Ressourcen*
nötig. Spulen, die einer Filamentbox zugeordnet sind, werden darin unter
einer gemeinsamen Kopfzeile (Boxname + Luftfeuchtigkeit) gruppiert
dargestellt; nicht zugeordnete Spulen erscheinen wie bisher einzeln
darunter. Über das Pfeil-Symbol in der Kopfzeile lässt sich eine Box
ein-/ausklappen: eingeklappt werden die einzelnen Spulen ausgeblendet und
stattdessen nur ein kleiner Farbpunkt je enthaltener Spule angezeigt
(Klapp-Zustand gilt nur für die aktuelle Browser-Sitzung). Pro Spule
zweizeilig aufgebaut: Name/Material/Farbe, darunter der
Fortschrittsbalken mit Füllstand in % und Restgewicht in Gramm; bei Spulen
ohne Box zusätzlich rechts (falls ein eigener Luftfeuchtigkeitssensor
hinterlegt ist) das Feuchtigkeits-Symbol mit dem aktuellen Messwert in %
darunter. Einfach eine neue Karte hinzufügen und "Filament Manager"
auswählen, oder per YAML:

```yaml
type: custom:filament-manager-card
title: Meine Spulen  # optional, per UI-Editor (Stift-Symbol) änderbar
```

Der Titel lässt sich auch über den visuellen Karten-Editor setzen (Stift-Symbol
auf der Karte), ohne YAML zu bearbeiten.

Ein Klick auf eine Zeile öffnet die Detailansicht der **Restmenge** (dort
direkt editierbar); ein Klick auf das Luftfeuchtigkeits-Symbol (bzw. auf die
Kopfzeile einer Box) öffnet stattdessen die Detailansicht des verknüpften
**Luftfeuchtigkeitssensors**. Nach einem Update der Integration ggf. einmal
den Browser-Cache leeren (Strg/Cmd+Shift+R), falls die Karte optisch nicht
aktualisiert wirkt.

### Manuelle Einzel-Karte

Alternativ lässt sich jede Spule auch als gewöhnliche Entitäten-Karte
anzeigen:

```yaml
type: entities
title: PLA Galaxy Black
entities:
  - entity: number.pla_galaxy_black_remaining_weight
  - entity: sensor.pla_galaxy_black_remaining_percentage
  - entity: sensor.pla_galaxy_black_material
  - entity: sensor.pla_galaxy_black_color
  - entity: binary_sensor.pla_galaxy_black_humidity_alert
```
