# Filament Manager

[![Validate](https://github.com/ludgerbeckmann/ha_filament_manager/actions/workflows/validate.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/ludgerbeckmann/ha_filament_manager.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/releases/)
[![GitHub license](https://img.shields.io/github/license/ludgerbeckmann/ha_filament_manager.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/blob/main/LICENSE)

HA Integration zur Verwaltung des eigenen 3D-Druck-Filamentbestandes –
inspiriert von [Spoolman](https://github.com/Donkie/Spoolman), aber als
schlanke, native Home-Assistant-Integration ohne externen Server.

## Funktionen

- Ein **Hub** (Eintrag unter *Einstellungen → Geräte & Dienste*) ist **eine
  Filamentbox oder ein Regal**. Du legst beliebig viele Hubs an, z. B. einen
  pro Filamentbox; die Spulen werden darin als Unterobjekte verwaltet
  (hinzufügen/bearbeiten/löschen über den Eintrag selbst).
- Jede Filamentspule wird als eigenes Gerät angelegt, mit **Name, Material,
  Farbe, Hersteller, Durchmesser** und **Gesamt-/Restgewicht**.
- Die Restmenge lässt sich direkt im Dashboard anpassen (editierbare
  `number`-Entität) oder per Service aktualisieren.
- Ein Sensor zeigt den **Füllstand in Prozent** – ideal für
  Balken-/Glance-Karten auf dem Dashboard.
- Optional kann pro Hub (Filamentbox) ein vorhandener
  **Luftfeuchtigkeitssensor** hinterlegt werden (z. B. ein Hygrometer in der
  Trockenbox). Überschreitet die gemessene Luftfeuchtigkeit den Grenzwert,
  schaltet ein `binary_sensor` auf "Warnung" – Grenzwert und Verzögerung
  richten sich automatisch nach dem empfindlichsten Material in der Box
  (siehe "Luftfeuchtigkeits-Grenzwerte" unten).
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

### Hub (Filamentbox) anlegen

*Einstellungen → Geräte & Dienste → Integration hinzufügen* → nach "Filament
Manager" suchen. Im Dialog **Filamentbox hinzufügen** legst du fest:

- den **Namen** (z. B. "Filamentbox 1"),
- optional einen **Luftfeuchtigkeitssensor** der Box,
- optional **Grenzwert** und **Verzögerung** der Luftfeuchtigkeitswarnung –
  leer lassen für die Automatik nach dem empfindlichsten Material in der Box,
- optional **Notify-Ziele** und ob eine dauerhafte
  Benachrichtigung angezeigt werden soll (siehe "Benachrichtigungen"),
- optional die **maximale Spulenanzahl** – leer lassen für keine Begrenzung.

Du kannst **beliebig viele Hubs** anlegen, z. B. einen pro Filamentbox oder
ein "Regal" ohne Sensor für lose Spulen. Die Dashboard-Karte zeigt die
Inhalte aller Hubs gemeinsam an. Die Einstellungen eines Hubs änderst du
über das Drei-Punkte-Menü des Eintrags → **Neu konfigurieren**. Dabei wird
auch die automatisch angelegte Box umbenannt: Unter jedem Hub steht ein
Unterobjekt **Filamentbox** mit dem Namen des Hubs, dem eine Raute mit
Leerzeichen vorangestellt ist ("# Filamentbox 3"). Home Assistant sortiert
Unterobjekte alphabetisch; so steht die Box ganz oben, vor den Spulen. Die
Raute wird automatisch wieder ergänzt, falls sie fehlt – der Name der Box
folgt immer dem des Hubs. Es trägt das
Gerät und die Entitäten der Box (Luftfeuchtigkeitswarnung, Spulenanzahl) und
lässt sich nicht separat bearbeiten oder löschen (es wird bei Bedarf neu
angelegt).

> **Hinweis (ab v0.10.0):** Der Hub *ist* die Filamentbox – es gibt keine
> separaten Box-Unterobjekte mehr. Hubs, Boxen und Spulen aus älteren
> Versionen müssen neu angelegt werden (alten Eintrag löschen, neuen Hub
> anlegen).

### Spule anlegen

Im gewünschten Hub "+ Spule hinzufügen". Die Spule gehört automatisch zur
Filamentbox ihres Hubs:

1. Material (vorbelegt: PETG) und Farbe (beides Dropdowns mit gängigen
   Werten, alphabetisch sortiert, aber frei überschreibbar) sowie optional
   Hersteller (ebenfalls Dropdown mit bekannten Marken) auswählen.
2. Durchmesser, Gesamtgewicht und (falls schon angebrochen) aktuelle
   Restmenge eintragen. Das Gesamtgewicht ist bereits vorbelegt: mit einem
   bekannten Realwert, falls für die Kombination aus Hersteller und Material
   einer hinterlegt ist, sonst mit einem branchenüblichen Standardwert (z. B.
   500 g für TPU/PVA, sonst 1000 g) – in jedem Fall frei überschreibbar.
3. Optional einen Schwellwert für die Bestandswarnung (z. B. 15 %) sowie ein
   oder mehrere Notify-Ziele und ob eine dauerhafte
   Benachrichtigung angezeigt werden soll (siehe "Benachrichtigungen").
4. Im letzten Schritt einen Namen vergeben – vorbelegt mit einem Vorschlag
   aus Hersteller, Material und Farbe (z. B. "Prusament PETG Rot"), kann
   aber beliebig angepasst werden.
5. Für eine weitere Spule den Vorgang wiederholen.

Bekannte Gesamtgewichte für bestimmte Hersteller/Material-Kombinationen
sind in `custom_components/ha_filament_manager/const.py`
(`MANUFACTURER_MATERIAL_WEIGHTS`) hinterlegt und lassen sich dort beliebig
ergänzen, sobald reale Werte bekannt sind.

Bestehende Spulen lassen sich über das Zahnrad-Symbol der jeweiligen Spule
in ihrem Hub bearbeiten (Material, Farbe, Gesamtgewicht usw.). Die Restmenge
wird dort bewusst nicht verändert – dafür gibt es die `number`-Entität und
die Dienste unten.

Hat der Hub eine maximale Spulenanzahl und ist sie erreicht, lässt sich keine
weitere Spule anlegen. Auf dem Dashboard werden die Spulen eines Hubs
gruppiert unter einer gemeinsamen Kopfzeile mit Boxname und Luftfeuchtigkeit
angezeigt (siehe "Dashboard-Karte" unten).

### Spule in eine andere Box verschieben

Gibt es mehr als eine Filamentbox, erscheint beim Bearbeiten einer Spule
(Zahnrad-Symbol) zusätzlich das Feld **Filamentbox**. Wählst du dort eine
andere Box, wird die Spule dorthin verschoben. Entitäten (inkl. Entity-IDs),
Verlauf, Restmenge, Bereich und die gemerkte AMS-RFID bleiben dabei erhalten –
es ist dieselbe Spule, nur in einer anderen Box. Eine volle Box (maximale
Spulenanzahl) nimmt keine Spule mehr auf.

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| `number.<spule>_remaining_weight` | Restmenge in Gramm, direkt editierbar |
| `sensor.<spule>_remaining_percentage` | Füllstand in % |
| `sensor.<spule>_material` | Materialtyp (z. B. PLA, PETG) |
| `sensor.<spule>_color` | Farbe |
| `binary_sensor.<spule>_low_stock_alert` | Nur vorhanden, wenn ein Bestandsschwellwert hinterlegt wurde |
| `binary_sensor.<spule>_in_printer` | "Im Drucker", nur vorhanden, wenn der Spule ein AMS-Slot zugeordnet ist (siehe unten) |
| `sensor.<box>_spools` | Anzahl der Spulen in der Filamentbox (dem Hub) |
| `binary_sensor.<box>_humidity_alert` | Luftfeuchtigkeitswarnung der Filamentbox, nur vorhanden, wenn die Box einen Sensor hat |

## Kopplung mit Bambu Lab (AMS)

Läuft die Integration [ha-bambulab](https://github.com/greghesp/ha-bambulab),
erscheint in den Spulen-Einstellungen das Feld **AMS-Slot** (Auswahl der
Slot-Sensoren, z. B. `sensor.p1s_ams_1_tray_1`). Das Feld wird nur angeboten,
wenn solche Sensoren existieren; ohne ha-bambulab ändert sich nichts.

- **Im Drucker**: Die Spule erhält die Entität `binary_sensor.<spule>_in_printer`.
  Sie ist "an", solange der Slot belegt ist. Bei Spulen mit RFID (original
  Bambu-Spulen) merkt sich der Filament Manager die RFID beim ersten Sehen;
  wechselt eine andere Spule in den Slot, gilt die Spule als nicht mehr im
  Drucker. Spulen ohne RFID zählen als im Drucker, solange der Slot belegt ist.
- **Restmenge aus dem AMS übernehmen** (optional, Standard an): Für RFID-Spulen
  folgt die Restmenge dem AMS-Wert, aber nur bei einer Änderung – beim Start
  und bei manuell gesetzten Werten wird nichts überschrieben.
- Beim Auffüllen (`refill_spool` bzw. Auffüll-Aktion) wird die gemerkte RFID
  vergessen, sodass eine neue Spule im selben Slot sauber erkannt wird.

Die Idee, AMS-Slots auszulesen, stammt aus
[Bambu Filaments](https://github.com/Timmes123/ha-bambu-filaments) (MIT,
© 2026 Timmes123). Es werden keine Cloud-Zugangsdaten benötigt – alle Daten
kommen aus den Entitäten von ha-bambulab.

## Abgleich mit der Bambu-Cloud (optional)

Bambu Studio und Bambu Handy führen eine Filamentbibliothek in der Bambu-Cloud.
Der Filament Manager kann sie **nur lesend** abfragen, damit Spulen deren
Restmenge übernehmen. Die Schnittstelle ist inoffiziell: Funktioniert sie
nicht (Cloud nicht erreichbar, von Bambu blockiert, Token abgelaufen), bleiben
alle Werte wie sie sind und alles läuft wie bisher weiter – es wird nie etwas
in die Cloud geschrieben.

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Filament
   Manager → **Bambu-Cloud-Konto verbinden*** (Region, E-Mail, Passwort; ggf.
   Bestätigungscode oder Zwei-Faktor-Code). Das Passwort wird nicht gespeichert,
   nur das Login-Token. Es läuft nach ca. 90 Tagen ab – Home Assistant bittet
   dann um eine erneute Anmeldung.
2. Pro Spule erscheinen im Bearbeiten-Dialog das Feld **Bambu-Cloud-Spule** und
   die Option **Restmenge aus der Cloud übernehmen** (Standard an):
   - Eine gewählte Cloud-Spule wird fest zugeordnet.
   - Bleibt das Feld auf „–“, wird automatisch zugeordnet: über die RFID, die
     der Filament Manager vom AMS gelernt hat (siehe oben).
3. Die Restmenge wird beim ersten Zuordnen übernommen und danach immer, wenn
   die Cloud einen neuen Wert meldet (Abfrage alle 30 Minuten) – nicht bei
   jedem Start, ein von Hand gesetzter Wert bleibt also bis zur nächsten
   Änderung in der Cloud stehen. Die zugeordnete Cloud-Spule steht als Attribut
   `cloud_spool` an der Restmengen-Entität.

Hinweise: Die Cloud antwortet nur browserähnlichen Clients, deshalb braucht die
Integration das Paket `curl_cffi` (wird von Home Assistant automatisch
installiert). Login und Endpunkte folgen
[Bambu Filaments](https://github.com/Timmes123/ha-bambu-filaments) (MIT,
© 2026 Timmes123).

## Spulen in der Karte verwalten

Das Stift-Symbol rechts im Kartenkopf schaltet den Bearbeiten-Modus ein (nur
für Administratoren sichtbar). Dann erscheinen:

- pro Spule drei Aktionen: **in den Drucker laden** bzw. herausnehmen (AMS-Slot
  zuordnen – ein Slot hat nur eine Spule, die bisherige wird herausgenommen; das
  ist vor allem für Spulen ohne RFID nützlich), **in eine andere Box
  verschieben** und **löschen** (mit Rückfrage),
- ein **+** an jeder Box und ein Knopf **Spule anlegen** (Box, Material, Farbe,
  Hersteller, Durchmesser, optional Name und Gewichte; Name und Gesamtgewicht
  werden sonst wie im Einrichtungsdialog vorgeschlagen).

Dahinter stehen Dienste, die du auch in Automationen nutzen kannst:
`load_spool`, `unload_spool`, `move_spool`, `add_spool` und `remove_spool`.
Jede Änderung lädt die betroffene Box kurz neu (ca. eine Sekunde), Restmengen
bleiben erhalten.

## Dienste

- `ha_filament_manager.consume_filament` – reduziert die Restmenge einer Spule
  (Feld `amount` in Gramm). Praktisch für Automationen, die nach jedem Druck
  automatisch die verbrauchte Menge abziehen.
- `ha_filament_manager.refill_spool` – setzt die Restmenge zurück (Feld
  `amount`, ohne Angabe wird auf das Gesamtgewicht zurückgesetzt) – z. B.
  beim Einlegen einer neuen Spule.

## Luftfeuchtigkeits-Grenzwerte

Filamente reagieren unterschiedlich empfindlich auf Feuchtigkeit. Der
Grenzwert der Filamentbox richtet sich daher nach dem empfindlichsten
darin gelagerten Material (Warnung, sobald die gemessene relative
Luftfeuchtigkeit darüber liegt):

| Material | Grenzwert |
|---|---|
| PLA, ABS, ASA, HIPS | 50 % |
| PETG | 40 % |
| TPU, PC | 30 % |
| Nylon, PVA | 20 % |
| Sonstiges | 40 % |

Zusätzlich gibt es eine **Verzögerung** (Feld „Warnung erst nach … Minuten"):
Die Warnung schaltet erst, wenn die Luftfeuchtigkeit so lange am Stück über
dem Grenzwert lag. Kurze Ausreißer (Box öffnen, Spulenwechsel) lösen so
keinen Alarm aus – Filament nimmt Feuchtigkeit erst über Stunden auf. Fällt
der Wert zwischendurch unter den Grenzwert, beginnt die Wartezeit von vorn;
die Warnung endet weiterhin sofort. Auch sie richtet sich nach dem Material:

| Material | Verzögerung |
|---|---|
| PLA, ABS, ASA, HIPS | 60 min |
| PETG | 30 min |
| TPU, PC | 20 min |
| Nylon, PVA | 10 min |
| Sonstiges | 30 min |

`0` warnt sofort.

Das sind Faustwerte, keine Normen – der Wert bleibt frei änderbar, und die
Angaben deines Filamentherstellers haben Vorrang.

### Automatik oder eigene Werte

Lässt du beim Hub (der Filamentbox) Grenzwert und/oder Verzögerung **leer**,
gelten automatisch die strengsten Werte der darin gelagerten Spulen: der
niedrigste Grenzwert und die kürzeste Verzögerung. Bei Nylon (20 %, 10 min)
und PLA (50 %, 60 min) in derselben Box gilt also 20 % / 10 min. Wird eine
Spule angelegt, entfernt oder ihr Material geändert, passen sich die Werte
automatisch an. Ein leerer Hub nutzt 40 % / 30 min. Trägst du einen Wert
ein, hat er immer Vorrang; durch Leeren des Feldes ("Neu konfigurieren")
kehrst du zur Automatik zurück.

## Benachrichtigungen

Sowohl die Luftfeuchtigkeitswarnung (pro Filamentbox) als auch die
Bestandswarnung (pro Spule) können automatisch benachrichtigen, sobald der jeweilige `binary_sensor` von "aus"
auf "an" wechselt (keine eigene Automation nötig):

- **Push-Benachrichtigung**: ein oder mehrere Notify-Ziele auswählbar (z. B.
  `notify.mobile_app_dein_handy`).
- **Dauerhafte Benachrichtigung**: als Karte im Dashboard
  (*Einstellungen → Benachrichtigungen*), wird automatisch wieder entfernt,
  sobald der Warnzustand endet (z. B. Luftfeuchtigkeit wieder unter dem
  Grenzwert, oder Spule aufgefüllt).

Beide Kanäle sind optional und unabhängig voneinander zuschaltbar, über das
Zahnrad-Symbol der jeweiligen Spule bzw. über "Neu konfigurieren" der Box nachträglich änderbar.

## Dashboard-Karte

### Eingebaute Übersichtskarte (empfohlen)

Die Integration liefert eine eigene Lovelace-Karte mit, die **automatisch
alle Spulen** anzeigt und sich selbst beim Frontend registriert – keine
zusätzliche Ressource unter *Einstellungen → Dashboards → Ressourcen*
nötig. Die Spulen eines Hubs werden darin unter einer gemeinsamen
Kopfzeile (Boxname + Luftfeuchtigkeit) gruppiert dargestellt. Per Klick auf die Kopfzeile (Boxname) lässt sich eine Box
ein-/ausklappen: eingeklappt werden die einzelnen Spulen ausgeblendet und
stattdessen nur ein kleiner Farbpunkt je enthaltener Spule angezeigt
(der per Klick gesetzte Zustand gilt nur, bis die Seite neu geladen wird;
ob Boxen beim Laden standardmäßig ein- oder ausgeklappt starten, stellst du
in der Karte ein, siehe unten). Pro Spule
zweizeilig aufgebaut: Name/Material/Farbe, darunter der
Fortschrittsbalken mit Füllstand in % und Restgewicht in Gramm; bei Spulen
ohne Box zusätzlich rechts (falls ein eigener Luftfeuchtigkeitssensor
hinterlegt ist) das Feuchtigkeits-Symbol mit dem aktuellen Messwert in %
darunter. Einfach eine neue Karte hinzufügen und "Filament Manager"
auswählen, oder per YAML:

```yaml
type: custom:filament-manager-card
title: Meine Spulen   # optional
group_by: box         # optional: box (Standard) | material | none
only_in_printer: true # optional: nur Spulen anzeigen, die im Drucker (AMS) stecken
collapse_boxes: true  # optional: Gruppen starten eingeklappt (Standard: false)
dark_background: true # optional: schwarzer Kartenhintergrund wie bei den Bambu-Lab-Karten
```

- `group_by: box` gruppiert nach Filamentbox, `material` nach Materialtyp
  (die Spulenzeile zeigt dann zusätzlich die Box), `none` zeigt eine flache
  Liste.
- Spulen, die laut Kopplung mit Bambu Lab (siehe oben) gerade im Drucker
  stecken, tragen ein Drucker-Symbol. Mit `only_in_printer` werden nur diese
  angezeigt.

Alle Optionen lassen sich auch über den visuellen Karten-Editor setzen
(Stift-Symbol auf der Karte), ohne YAML zu bearbeiten.

Ein Klick auf eine Zeile öffnet die Detailansicht der **Restmenge** (dort
direkt editierbar); ein Klick auf das Luftfeuchtigkeits-Symbol (auch in der
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
