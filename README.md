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
  **Luftfeuchtigkeitssensor** (z. B. ein Hygrometer in der Trockenbox), einen
  **Temperatursensor** (nur zur Anzeige) und eine maximale Spulenanzahl haben.
- Der **Vorrat** nimmt **verschlossene Rollen** auf (jede einzeln erfasst).
  Mit „Spule öffnen" wandert eine Rolle in eine Box und bekommt ihre
  Entitäten.
- Jede Spule hat **Name, Material, Variante, Farbe, Hersteller, Durchmesser** sowie
  **Gesamt- und Restgewicht**. Die Restmenge ist direkt anpassbar (editierbare
  `number`-Entität) oder per Dienst; Material, Farbe, Füllstand u. a. stehen
  als Attribute daran.
- Optionale **Warnungen**: Luftfeuchtigkeit (pro Box, Grenzwert und
  Verzögerung automatisch nach dem empfindlichsten Material) und niedriger
  Bestand (pro Spule), jeweils mit Push- und/oder dauerhafter Benachrichtigung.
- Optional eine **Druck-Benachrichtigung** als Live Activity (iPhone/iPad) auf
  Basis der Bambu-Lab-Sensoren und eine **Druck-Karte** mit dem aktuellen
  Auftrag.
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

### Material und Variante

Das **Material** ist die Grundsorte (PLA, PETG, ABS, ASA, TPU, PC, Nylon, PVA,
HIPS, Sonstiges), die **Variante** die Ausprägung: z. B. Matte, Silk, Plus,
Pro, HF, Tough, CF (Kohlefaser), GF (Glasfaser), Galaxy, Sparkle, Marble,
Metallic, Glow, Wood – oder ein eigener Eintrag. So bleibt „PETG-CF“ ein PETG:
Feuchtegrenzwerte, Gewichtsvorschläge und die Gruppierung nach Material richten
sich nach der Grundsorte, die Variante steht im Namen (`Elegoo PLA Matte
Schwarz`), in der Zeile (`PLA Matte · Schwarz`) und als Attribut `variant`.

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
- pro Box: **bearbeiten** (Name, Luftfeuchtigkeits- und Temperatursensor,
  Grenzwerte, maximale Spulenanzahl) und – wenn sie leer ist – **löschen**,
- pro verschlossener Spule im Vorrat: **öffnen** (in eine Box legen),
  bearbeiten und löschen. **Gleiche Rollen** (Name, Hersteller, Material,
  Farbe, Durchmesser und Gewicht stimmen überein) stehen als eine Zeile
  `3 × …` da; mit **+** kommt eine weitere Rolle dazu, mit **−** wird eine
  entfernt, **öffnen** nimmt eine heraus,
- pro AMS-Slot (wenn die AMS-Anzeige eingeschaltet ist, siehe unten): eine
  Spule aus den Boxen **zuordnen** bzw. die Zuordnung **aufheben**,
- die Knöpfe **Spule anlegen**, **Box anlegen**, **Warnungen** und **Druck-Benachrichtigung** (siehe unten).
  Beim **Anlegen** Beim Anlegen einer Spule
  wählst du die Ablage: eine Box oder **Vorrat (verschlossen)**. Material,
  Variante (optional), Farbe und Hersteller (Pflicht) sind Dropdowns wie gewohnt, auf Wunsch mit
  „Eigene Eingabe …"; Name, Gesamtgewicht und Restgewicht sind mit den
  Vorschlägen vorbelegt und folgen den Auswahlen, bis du sie änderst. Beim
  **Bearbeiten** einer Spule folgt der Name Änderungen von Hersteller,
  Material, Variante und Farbe, solange er noch dem Vorschlag entspricht (ein
  eigener Name bleibt unangetastet). Volle
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

Einordnung: Eine allgemeingültige Norm gibt es nicht, die Hersteller sind sich
nicht einig. Das [Bambu-Lab-Wiki](https://wiki.bambulab.com/en/filament-acc/acc/sealed-box)
nennt für die Lagerung in der Dichtbox „unter 20 % rF“,
[UltiMaker](https://support.ultimaker.com/articles/Knowledge/1667410781492) hält
feuchteempfindliche Materialien (Nylon, TPU 95A, PVA) unter 50 % und die meisten
anderen am besten bei 10–30 %, [Snapmaker](https://support.snapmaker.com/hc/en-us/articles/4417380565911-3-Filament-Library)
nennt 40 %; in der Community gilt PLA oft schon bei etwa 40 % als unkritisch. Die
Werte oben sind bewusst eher großzügig – wer strenger lagern will, trägt in der
Box einen eigenen (niedrigeren) Grenzwert ein.

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
`binary_sensor` von "aus" auf "an" wechselt (keine eigene Automation nötig).
Wohin, legst du **einmal für alles** fest: Karte → Stift-Symbol →
**Warnungen** (oder Dienst `set_alert_notifications`):

- **Push-Benachrichtigung**: ein oder mehrere Notify-Entitäten auswählbar
  (z. B. `notify.mobile_app_dein_handy`).
- **Dauerhafte Benachrichtigung**: als Karte im Dashboard
  (*Einstellungen → Benachrichtigungen*), wird automatisch wieder entfernt,
  sobald der Warnzustand endet (z. B. Luftfeuchtigkeit wieder unter dem
  Grenzwert, oder Spule aufgefüllt).

Beide Kanäle sind optional und unabhängig voneinander zuschaltbar. Welche Box
oder Spule überhaupt warnt, bestimmen ihr Feuchtesensor bzw. ihre
Bestandswarnung. (Bis Version 1.2 hatte jede Box und Spule eigene Ziele; sie
werden beim Update zu den gemeinsamen zusammengeführt.)

## Druck-Benachrichtigung (Live Activity)

Auf Basis der Sensoren der Bambu-Lab-Integration (Druckstatus,
Druckfortschritt, verbleibende Zeit, Name der Aufgabe) zeigt der Filament
Manager den Fortschritt eines Drucks als **Live Activity auf iPhone und iPad**
(bei Android als Live-Update) – eine eigene Automation ist nicht mehr nötig:

- Während der Vorbereitung, des Drucks und der Pause bleibt **eine**
  Benachrichtigung aktuell: Titel (der **Anzeigename**), Fortschrittsbalken mit
  Prozent, darunter z. B. `Druckt · fertig ca. 15:04 · Auftrag`, bei Pause
  `⏸ Pausiert · Auftrag`, grünes bzw. orangefarbenes Symbol. Wie in der
  Bambu-App läuft die **Restzeit als Countdown** auf dem Gerät mit (er tickt
  von allein, es sind keine Updates pro Minute nötig); ohne Countdown steht
  `noch 1 h 5 min` im Text. Auf Wunsch steht dahinter die **verwendete
  Spule** (aus dem aktiven AMS-Slot, wenn die Spule dort eingetragen ist),
  z. B. `· PETG Rot (82 %)`.
- Der Fortschritt beginnt bei **0 %**: Behält der Drucker nach dem letzten
  Druck noch die „100 %“ im Sensor, werden sie nicht in die erste
  Benachrichtigung übernommen.
- Am Ende wird die Live Activity entfernt und durch `✅ … Druck fertig` bzw.
  `❌ … Druck fehlgeschlagen` ersetzt. Geht der Drucker auf Leerlauf oder
  offline, verschwindet sie ebenfalls.
- **Ziele** sind die Companion-Apps (`notify.mobile_app_…`), beliebig viele:
  nur sie nehmen die Zusatzdaten einer Live Activity an. In den Einstellungen
  der App müssen Live Activities erlaubt sein.

Einrichten: Karte → Stift-Symbol → **Druck-Benachrichtigung** (Drucker, Ziele,
Anzeigename, Countdown, optional eine Seite, die beim Antippen geöffnet wird).
Ohne eigenen **Anzeigename** nimmt der Filament Manager den Namen des Druckers
ohne Seriennummer: aus `P1S_01P09C482100602` wird `Bambu Lab P1S`. Mit **Speichern und
testen** erscheint eine Beispiel-Live-Activity, die nach 30 Sekunden wieder
verschwindet. Aussehen: Die Live Activity zeichnet die Home-Assistant-App
selbst (Titel, Text, Fortschrittsbalken, Prozent, Symbol, Countdown); das
schwarze Layout der Bambu-App mit „Time Left“ und „ETA“ lässt sich damit nicht
nachbauen, aber Inhalt und Countdown kommen ihm nah. Dieselben Einstellungen
gibt es als Dienste
`set_print_notification` und `test_print_notification`.

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
appearance: dark      # optional: theme (Standard: wie Home Assistant) | light | dark | system
show_ams: true        # optional: AMS-Einheiten mit ihren Slots anzeigen (Standard: aus)
```

Die Spulen einer Box stehen unter einer Kopfzeile mit Boxname und
Luftfeuchtigkeit und – wenn für die Box ein Temperatursensor eingetragen ist –
Temperatur; ein Klick auf die Kopfzeile klappt die Gruppe ein (dann
zeigt ein Farbpunkt je Spule den Inhalt). Pro Spule siehst du Name,
Material/Farbe, Füllstandsbalken mit Prozent und Gramm und – wenn sie laut
Kopplung mit Bambu Lab im Drucker steckt – ein Drucker-Symbol. Verschlossene
Spulen stehen im Bereich **Vorrat**.

- `group_by: box` gruppiert nach Box, `material` nach Materialtyp (die Zeile
  zeigt dann zusätzlich Box und Luftfeuchtigkeit), `none` zeigt eine flache
  Liste.
- `only_in_printer` zeigt nur Spulen im Drucker (und blendet den Vorrat aus).
- `show_ams: true` zeigt jede **AMS-Einheit** der Bambu-Lab-Integration als
  eigene Gruppe (z. B. „AMS 2 Pro“) mit Temperatur und Luftfeuchtigkeit des
  AMS in der Kopfzeile und einer Zeile je Slot: Farbe, Name, Füllstand, ein
  Symbol für den gerade druckenden Slot und „Leer“ für leere Slots. Ist dem
  Slot eine Spule aus deinen Boxen zugeordnet, erscheinen deren Name und
  Restgewicht, sonst die Angaben des AMS.

`appearance` legt die Darstellung fest: `theme` folgt dem Theme von Home
Assistant (Standard), `light` ist immer hell, `dark` immer dunkel (wie die
Bambu-Lab-Karten), `system` folgt der Hell/Dunkel-Einstellung des Geräts. Die
ältere Option `dark_background: true` gilt weiter wie `appearance: dark`.

Alle Optionen lassen sich auch im visuellen Karten-Editor setzen. Ein Klick
auf eine Zeile öffnet die Restmenge (dort direkt editierbar), ein Klick auf das
Luftfeuchtigkeits-Symbol den Feuchtigkeitssensor. Nach einem Update der
Integration ggf. einmal den Browser-Cache leeren (Strg/Cmd+Shift+R).

### Druck-Karte

Die zweite mitgelieferte Karte **Filament Manager – Druck** zeigt, was ein
Bambu-Lab-Drucker gerade tut – ähnlich wie die Auftragsansicht der Bambu-App:

```yaml
type: custom:filament-manager-print-card
printer: 01P09C482100602   # optional: Seriennummer, sonst der erste Drucker
title: Mein P1S            # optional, sonst der Name des Druckers
show_cover: true           # optional: Vorschaubild des Auftrags (Standard: an)
show_filament: true        # optional: verwendetes Filament (Standard: an)
show_temperatures: true    # optional: Düse, Bett, Kammer (Standard: an)
appearance: dark           # optional: theme | light | dark | system
```

Oben stehen der Druckername und ein **Status** (Druckt, Pausiert, Vorbereitung,
Fertig, Fehlgeschlagen, Bereit, Offline). Während eines Drucks folgen
Auftragsname mit Vorschaubild und Fortschrittsbalken, **Verbleibend**, **Fertig
um**, **Gestartet**, **Schicht** (aktuell/gesamt) und **Gewicht**, das gerade
verwendete **Filament** (bei einer zugeordneten Spule mit Name und Restmenge
aus dem Bestand) sowie die **Temperaturen**. Ein Klick auf den Kopf öffnet den
Status-Sensor, ein Klick auf das Filament den AMS-Slot. Die Karte braucht die
Bambu-Lab-Integration (ha-bambulab) und liest deren Sensoren; alle Optionen
gibt es auch im visuellen Editor.

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
