# Close Call – Installation und erster Start

Close Call ist ein Trainingsprogramm für Verkaufsgespräche: Du wählst ein Szenario, sprichst mit einem KI-Kunden und bekommst danach ein kurzes Coaching-Feedback.

## Was du brauchst

- **Mac mit Apple-Chip** (M1 oder neuer) **oder Windows-PC** (Windows 10/11, 64 Bit)
- Ein **Headset** – das ist Pflicht (siehe unten)
- Eine **Internetverbindung**
- Die **Installationsdatei** und deinen **Zugangsschlüssel** – beides bekommst du separat zugeschickt

**Warum ein Headset?** Ohne Headset nimmt das Mikrofon die Stimme des KI-Kunden aus den Lautsprechern wieder auf. Er hört sich dann selbst und das Gespräch gerät durcheinander.

Den Zugangsschlüssel bitte nicht weitergeben, er ist wie ein Passwort.

## Installation auf dem Mac

1. Öffne die zugeschickte Zip-Datei mit einem Doppelklick. Darin liegt eine `.dmg`-Datei – öffne auch diese mit einem Doppelklick.
2. Ziehe **Close Call** in den Ordner **Programme**.
3. Starte Close Call aus dem Programme-Ordner.
4. Beim ersten Start meldet macOS: *„Apple konnte nicht überprüfen, ob ‚Close Call' frei von Schadsoftware ist …"*. Das ist bei internen Programmen normal.
   - Klicke auf **Fertig** (nicht auf „In den Papierkorb legen").
   - Öffne **Systemeinstellungen → Datenschutz & Sicherheit** und scrolle nach unten.
   - Neben dem Hinweis zu Close Call auf **Dennoch öffnen** klicken und mit Passwort oder Touch ID bestätigen.
   - Im nächsten Fenster noch einmal **Dennoch öffnen** wählen.

   Das ist nur beim allerersten Start nötig.
5. Wenn Close Call nach dem Mikrofon fragt: **Erlauben**.

## Installation unter Windows

1. Entpacke die zugeschickte Zip-Datei (Rechtsklick → **Alle extrahieren**).
2. Starte **Close Call Setup** mit einem Doppelklick. Administratorrechte sind nicht nötig.
3. Erscheint *„Der Computer wurde durch Windows geschützt"*: Klicke auf **Weitere Informationen** und dann auf **Trotzdem ausführen**.
4. Close Call wird installiert und startet danach automatisch. Später findest du es im Startmenü.
5. Wenn nach dem Mikrofon gefragt wird: **Zulassen**.

Lässt dein Firmenrechner die Installation gar nicht zu, melde dich bitte – dann muss die IT freischalten.

## Erster Start: Zugang einrichten

Beim ersten Start erscheint **Zugang einrichten**.

1. Füge deinen Zugangsschlüssel in das Feld ein.
2. Klicke auf **Prüfen und speichern**.

Close Call prüft den Schlüssel sofort. Stimmt er, geht es direkt zu den Szenarien – ab jetzt bei jedem Start. Erscheint *„Der Schlüssel wurde nicht akzeptiert"*, kopiere ihn bitte noch einmal vollständig (ohne Leerzeichen am Anfang oder Ende).

## Üben

1. Klicke auf **Training starten**, wähle ein Szenario und dann **Gespräch starten**.
2. Der Kunde meldet sich zuerst. Sprich ganz normal, du kannst ihn auch unterbrechen.
3. Klicke auf **Gespräch beenden**. Nach einigen Sekunden erscheint dein Feedback.

**Wichtig in der Testphase:** Verwende in Übungsgesprächen **keine echten Kundennamen, Preise oder Projektdaten**. Die Gespräche werden von einem KI-Dienst verarbeitet.

## Wenn etwas nicht klappt

| Problem | Lösung |
|---|---|
| Der Kunde sagt nichts | Internetverbindung prüfen. Wurde ein neuer Zugangsschlüssel verschickt, auf der Startseite **Zugang ändern** wählen und ihn eintragen. |
| Der Kunde hört mich nicht | Mikrofonzugriff erlauben: Mac unter *Systemeinstellungen → Datenschutz & Sicherheit → Mikrofon*, Windows unter *Einstellungen → Datenschutz → Mikrofon*. Headset vor dem Start von Close Call anschließen. |
| Der Kunde unterbricht sich oder antwortet auf sich selbst | Er hört seine eigene Stimme über die Lautsprecher. Headset verwenden und vor dem Start von Close Call anschließen. |
| Neuer Zugangsschlüssel bekommen | Auf der Startseite **Zugang ändern** wählen, den neuen Schlüssel einfügen, **Prüfen und speichern**. |
| Etwas anderes | Melde dich mit einer kurzen Beschreibung. Hilfreich ist die Protokolldatei: auf dem Mac `~/Library/Application Support/Close Call/logs/server.log` (Finder → *Gehe zu → Gehe zum Ordner …*), unter Windows `%APPDATA%\Close Call\logs\server.log` (in die Adresszeile des Explorers einfügen). |
