# Filament Manager

[![Validate](https://github.com/ludgerbeckmann/ha_filament_manager/actions/workflows/validate.yml/badge.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)
[![GitHub release](https://img.shields.io/github/release/ludgerbeckmann/ha_filament_manager.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/releases/)
[![GitHub license](https://img.shields.io/github/license/ludgerbeckmann/ha_filament_manager.svg)](https://github.com/ludgerbeckmann/ha_filament_manager/blob/main/LICENSE)

HA Integration zur Verwaltung des eigenen 3D-Druck-Filamentbestandes –
inspiriert von [Spoolman](https://github.com/Donkie/Spoolman), aber als
schlanke, native Home-Assistant-Integration ohne externen Server.

## Funktionen

- **Boxen, Spulen und ein Vorrat**, alles in **einem** Eintrag und bequem in
  der mitgelieferten **Dashboard-Karte** verwaltet: Spulen anlegen, bearbeiten,
  in eine andere Box verschieben, in den Drucker laden, löschen.
- Eine **Box** ist eine Filamentbox oder ein Regal. Sie kann einen
  **Luftfeuchtigkeitssensor** (z. B. ein Hygrometer in der Trockenbox), eine
  maximale Spulenanzahl und Benachrichtigungen haben.
- Der **Vorrat** nimmt **verschlossene Rollen** auf (jede einzeln erfasst).
  Mit „Spule öffnen" wandert eine Rolle in eine Box und bekommt ihre
  Entitäten.
- Jede Spule hat **Name, Material, Farbe, Hersteller, Durchmesser** sowie
  **Gesamt- und Restgewicht**. Die Restmenge ist direkt anpassbar (editierbare
  `number`-Entität) oder per Dienst; Material, Farbe, Füllstand u. a. stehen
  als Attribute daran.
- Optionale **Warnungen**: Luftfeuchtigkeit (pro Box, Grenzwert und
  Verzögerung automatisch nach dem empfindlichsten Material) und niedriger
  Bestand (pro Spule), jeweils mit Push- und/oder dauerhafter Benachrichtigung.
- Optional **Kopplung mit Bambu Lab** (AMS-Slots, „Im Drucker") und **Abgleich
  der Restmengen mit der Bambu-Cloud** (nur lesend).

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

*Einstellungen → Geräte & Dienste → Integration hinzufügen* → "Filament
Manager" → **Filament Manager** (der Eintrag für Boxen, Spulen und Vorrat; es
gibt nur einen). Danach eine Karte **Filament Manager** zu einem Dashboard
hinzufügen: Mit dem Stift-Symbol oben rechts legst du Boxen und Spulen an.

Boxen und Spulen haben keine eigenen Einrichtungsdialoge in den
Einstellungen mehr – sie werden in der Karte verwaltet (siehe „Verwalten in
der Karte") oder über die Dienste.

### Update von Version 0.x

Bis Version 0.15 war jede Box ein eigener Eintrag und jede Spule ein
Unter-Eintrag. Beim ersten Start von 1.0 wird das **automatisch** übernommen:
Alle Boxen und Spulen landen im neuen Eintrag, Restmengen, AMS-Zuordnungen und
Cloud-Einstellungen bleiben erhalten. Auch **Entity-IDs, Namen, Verlauf und
Bereiche** der Restmengen, Warnungen und Geräte bleiben bestehen. Entfallen
sind nur die Sensoren *Füllstand*, *Material* und *Farbe* je Spule: ihre Werte
stehen jetzt als Attribute (`remaining_percentage`, `material`, `color`, …) an
der Restmengen-Entität. Wer sie in Karten oder Automationen nutzt, stellt auf
die Attribute um.

## Entitäten

| Entität | Beschreibung |
| --- | --- |
| `number.<spule>_remaining_weight` | Restmenge in Gramm, direkt editierbar; Attribute: Material, Farbe, Hersteller, Durchmesser, Gesamtgewicht, Füllstand in %, Box, AMS-Slot, Cloud-Spule |
| `binary_sensor.<spule>_low_stock_alert` | Nur vorhanden, wenn eine Bestandswarnung eingestellt ist |
| `binary_sensor.<spule>_in_printer` | "Im Drucker", nur vorhanden, wenn der Spule ein AMS-Slot zugeordnet ist |
| `sensor.<box>_spools` | Anzahl der Spulen in der Box (Attribut `spool_limit`) |
| `binary_sensor.<box>_humidity_alert` | Luftfeuchtigkeitswarnung der Box, nur vorhanden, wenn die Box einen Sensor hat |
| `sensor.vorrat_sealed_spools` | Anzahl verschlossener Spulen im Vorrat (Attribut `by_material`) |

Verschlossene Spulen im Vorrat haben keine eigenen Entitäten.

## Verwalten in der Karte

Das Stift-Symbol rechts im Kartenkopf schaltet den **Bearbeiten-Modus** ein
(nur für Administratoren sichtbar). Dann erscheinen:

- pro Spule in einer Box: **in den Drucker laden** bzw. herausnehmen (AMS-Slot
  zuordnen – ein Slot hat nur eine Spule, die bisherige wird herausgenommen),
  **in eine andere Box verschieben**, **bearbeiten** und **löschen**,
- pro Box: **bearbeiten** (Name, Luftfeuchtigkeitssensor, Grenzwerte, maximale
  Spulenanzahl, Benachrichtigungen) und – wenn sie leer ist – **löschen**,
- pro verschlossener Spule im Vorrat: **öffnen** (in eine Box legen),
  bearbeiten und löschen,
- die Knöpfe **Spule anlegen** und **Box anlegen**. Beim Anlegen einer Spule
  wählst du die Ablage: eine Box oder **Vorrat (verschlossen)**. Material,
  Farbe und Hersteller (Pflicht) sind Dropdowns wie gewohnt, auf Wunsch mit
  „Eigene Eingabe …"; Name, Gesamtgewicht und Restgewicht sind mit den
  Vorschlägen vorbelegt und folgen den Auswahlen, bis du sie änderst. Volle
  Boxen werden nicht zur Auswahl angeboten.

## Dienste

Die Karte nutzt diese Dienste; du kannst sie genauso in Automationen und
Skripten verwenden. Spulen und Boxen werden über ihre ID (so kennt sie die
Karte) **oder** über ihr Gerät angegeben (so bietet es der Dialog von Home
Assistant an).

- `consume_filament` / `refill_spool` – Restmenge einer Spule verringern bzw.
  zurücksetzen (Ziel: die Restmengen-Entität; Feld `amount` in Gramm).
- `add_spool`, `update_spool`, `remove_spool` – Spulen verwalten (`add_spool`
  ohne `box` legt eine verschlossene Spule im Vorrat an; der Hersteller ist
  Pflicht).
- `move_spool`, `open_spool` – Spule in eine andere Box legen bzw. eine
  verschlossene Spule aus dem Vorrat in eine Box öffnen.
- `load_spool`, `unload_spool` – Spule einem AMS-Slot zuordnen bzw.
  herausnehmen.
- `add_box`, `update_box`, `remove_box` – Boxen verwalten.

## Kopplung mit Bambu Lab (AMS)

Läuft die Integration [ha-bambulab](https://github.com/greghesp/ha-bambulab),
kannst du eine Spule einem **AMS-Slot** zuordnen (Slot-Sensoren wie
`sensor.p1s_ams_1_tray_1`): in der Karte im Bearbeiten-Modus über das
Drucker-Symbol der Spule. Ohne ha-bambulab ändert sich nichts.

- **Im Drucker**: Die Spule erhält die Entität `binary_sensor.<spule>_in_printer`.
  Sie ist "an", solange der Slot belegt ist. Bei Spulen mit RFID (original
  Bambu-Spulen) merkt sich der Filament Manager die RFID beim ersten Sehen;
  wechselt eine andere Spule in den Slot, gilt die Spule als nicht mehr im
  Drucker. Spulen ohne RFID zählen als im Drucker, solange der Slot belegt ist.
- **Restmenge aus dem AMS übernehmen** (optional, Standard an): Für RFID-Spulen
  folgt die Restmenge dem AMS-Wert, aber nur bei einer Änderung – beim Start
  und bei manuell gesetzten Werten wird nichts überschrieben.
- Beim Auffüllen (`refill_spool`) wird die gemerkte RFID
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
2. Pro Spule erscheinen im Bearbeiten-Dialog der Karte das Feld
   **Bambu-Cloud-Spule** und die Option **Restmenge aus der Cloud übernehmen**
   (Standard an):
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

Lässt du bei einer Box Grenzwert und/oder Verzögerung **leer**, gelten
automatisch die strengsten Werte der darin gelagerten Spulen: der niedrigste
Grenzwert und die kürzeste Verzögerung. Bei Nylon (20 %, 10 min) und PLA
(50 %, 60 min) in derselben Box gilt also 20 % / 10 min. Wird eine Spule
angelegt, entfernt oder ihr Material geändert, passen sich die Werte
automatisch an. Eine leere Box nutzt 40 % / 30 min. Trägst du einen Wert ein,
hat er immer Vorrang; durch Leeren des Feldes kehrst du zur Automatik zurück.

## Benachrichtigungen

Sowohl die Luftfeuchtigkeitswarnung (pro Box) als auch die Bestandswarnung
(pro Spule) können automatisch benachrichtigen, sobald der jeweilige
`binary_sensor` von "aus" auf "an" wechselt (keine eigene Automation nötig):

- **Push-Benachrichtigung**: ein oder mehrere Notify-Ziele auswählbar (z. B.
  `notify.mobile_app_dein_handy`).
- **Dauerhafte Benachrichtigung**: als Karte im Dashboard
  (*Einstellungen → Benachrichtigungen*), wird automatisch wieder entfernt,
  sobald der Warnzustand endet (z. B. Luftfeuchtigkeit wieder unter dem
  Grenzwert, oder Spule aufgefüllt).

Beide Kanäle sind optional und unabhängig voneinander zuschaltbar, im
Bearbeiten-Dialog der Box bzw. der Spule in der Karte.

## Dashboard-Karte

Die Integration liefert die Lovelace-Karte **Filament Manager** mit; sie
registriert sich selbst beim Frontend – keine zusätzliche Ressource unter
*Einstellungen → Dashboards → Ressourcen* nötig. Einfach eine neue Karte
hinzufügen und "Filament Manager" auswählen, oder per YAML:

```yaml
type: custom:filament-manager-card
title: Meine Spulen   # optional
group_by: box         # optional: box (Standard) | material | none
only_in_printer: true # optional: nur Spulen anzeigen, die im Drucker (AMS) stecken
show_stock: false     # optional: Vorrat ausblenden (Standard: sichtbar)
collapse_boxes: true  # optional: Gruppen starten eingeklappt (Standard: false)
dark_background: true # optional: schwarzer Kartenhintergrund wie bei den Bambu-Lab-Karten
```

Die Spulen einer Box stehen unter einer Kopfzeile mit Boxname und
Luftfeuchtigkeit; ein Klick auf die Kopfzeile klappt die Gruppe ein (dann
zeigt ein Farbpunkt je Spule den Inhalt). Pro Spule siehst du Name,
Material/Farbe, Füllstandsbalken mit Prozent und Gramm und – wenn sie laut
Kopplung mit Bambu Lab im Drucker steckt – ein Drucker-Symbol. Verschlossene
Spulen stehen im Bereich **Vorrat**.

- `group_by: box` gruppiert nach Box, `material` nach Materialtyp (die Zeile
  zeigt dann zusätzlich Box und Luftfeuchtigkeit), `none` zeigt eine flache
  Liste.
- `only_in_printer` zeigt nur Spulen im Drucker (und blendet den Vorrat aus).

Alle Optionen lassen sich auch im visuellen Karten-Editor setzen. Ein Klick
auf eine Zeile öffnet die Restmenge (dort direkt editierbar), ein Klick auf das
Luftfeuchtigkeits-Symbol den Feuchtigkeitssensor. Nach einem Update der
Integration ggf. einmal den Browser-Cache leeren (Strg/Cmd+Shift+R).

### Einzelne Spule als Entitäten-Karte

```yaml
type: entities
title: PLA Galaxy Black
entities:
  - entity: number.pla_galaxy_black_remaining_weight
  - type: attribute
    entity: number.pla_galaxy_black_remaining_weight
    attribute: remaining_percentage
    suffix: "%"
    name: Füllstand
```
