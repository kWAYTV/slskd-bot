#!/usr/bin/env python3
"""Write es/de/gl gettext catalogs from the extracted POT and compile .mo files."""

from __future__ import annotations

from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "src" / "music_downloader" / "locales"
POT = LOCALES / "messages.pot"

# msgid -> (es, de, gl). Tuples are (singular, plural) for ngettext.
TRANSLATIONS: dict[str | tuple[str, str], tuple[str | tuple[str, str], ...]] = {
    "You are not authorized to use this bot.": (
        "No estás autorizado para usar este bot.",
        "Du bist nicht berechtigt, diesen Bot zu verwenden.",
        "Non estás autorizado para usar este bot.",
    ),
    "You can search and download files, but only library users can save to the music library or import playlists.": (
        "Puedes buscar y descargar archivos, pero solo los usuarios de la biblioteca pueden guardar en la biblioteca o importar playlists.",
        "Du kannst suchen und Dateien herunterladen, aber nur Bibliotheksnutzer können in die Musikbibliothek speichern oder Playlists importieren.",
        "Podes buscar e descargar ficheiros, pero só os usuarios da biblioteca poden gardar na biblioteca ou importar playlists.",
    ),
    "ON": ("ACTIVADO", "AN", "ACTIVADO"),
    "OFF": ("DESACTIVADO", "AUS", "DESACTIVADO"),
    "Auto-download mode: *{mode}*": (
        "Modo de descarga automática: *{mode}*",
        "Automatischer Download: *{mode}*",
        "Modo de descarga automática: *{mode}*",
    ),
    "Auto-download mode is currently: *{mode}*\n\nWhen ON, the best FLAC match is downloaded automatically without asking you to pick.": (
        "El modo de descarga automática está: *{mode}*\n\nSi está ACTIVADO, se descarga automáticamente la mejor coincidencia FLAC sin pedirte que elijas.",
        "Der automatische Download ist aktuell: *{mode}*\n\nWenn AN, wird die beste FLAC-Übereinstimmung automatisch heruntergeladen, ohne dass du auswählen musst.",
        "O modo de descarga automática está: *{mode}*\n\nSe está ACTIVADO, descárgase automaticamente a mellor coincidencia FLAC sen pedirche que elixas.",
    ),
    "*Active searches:*": ("*Búsquedas activas:*", "*Aktive Suchen:*", "*Buscas activas:*"),
    "*Active downloads:*": ("*Descargas activas:*", "*Aktive Downloads:*", "*Descargas activas:*"),
    "No downloads yet.": (
        "Aún no hay descargas.",
        "Noch keine Downloads.",
        "Aínda non hai descargas.",
    ),
    "*Recent downloads:*": ("*Descargas recientes:*", "*Letzte Downloads:*", "*Descargas recentes:*"),
    "Search expired. Send a new query.": (
        "La búsqueda ha caducado. Envía una nueva consulta.",
        "Die Suche ist abgelaufen. Sende eine neue Anfrage.",
        "A busca caducou. Envía unha nova consulta.",
    ),
    "Cancelled.": ("Cancelado.", "Abgebrochen.", "Cancelado."),
    "⬇️ *Downloading #{n}...*\n{artist} - {title}\nFrom: `{user}`\nFile: `{file}`": (
        "⬇️ *Descargando #{n}...*\n{artist} - {title}\nDe: `{user}`\nArchivo: `{file}`",
        "⬇️ *Lade #{n} herunter...*\n{artist} - {title}\nVon: `{user}`\nDatei: `{file}`",
        "⬇️ *Descargando #{n}...*\n{artist} - {title}\nDe: `{user}`\nFicheiro: `{file}`",
    ),
    "❌ Failed to enqueue download from `{user}`.\nThe user might be offline.": (
        "❌ No se pudo encolar la descarga de `{user}`.\nEs posible que el usuario esté desconectado.",
        "❌ Download von `{user}` konnte nicht eingereiht werden.\nDer Benutzer ist möglicherweise offline.",
        "❌ Non se puido encolar a descarga de `{user}`.\nPode que o usuario estea desconectado.",
    ),
    "Timeout": ("Tiempo agotado", "Zeitüberschreitung", "Tempo esgotado"),
    "❌ Download failed: {state}\nFile: `{file}`": (
        "❌ Error de descarga: {state}\nArchivo: `{file}`",
        "❌ Download fehlgeschlagen: {state}\nDatei: `{file}`",
        "❌ Erro de descarga: {state}\nFicheiro: `{file}`",
    ),
    "❌ Downloaded file not found on disk.\nCheck DOWNLOAD_DIR configuration.": (
        "❌ No se encontró el archivo descargado en disco.\nComprueba la configuración de DOWNLOAD_DIR.",
        "❌ Heruntergeladene Datei nicht auf der Festplatte gefunden.\nPrüfe die DOWNLOAD_DIR-Konfiguration.",
        "❌ Non se atopou o ficheiro descargado no disco.\nComproba a configuración de DOWNLOAD_DIR.",
    ),
    "Quality: {quality} | {duration}": (
        "Calidad: {quality} | {duration}",
        "Qualität: {quality} | {duration}",
        "Calidade: {quality} | {duration}",
    ),
    "✅ *{label} Downloaded!* Sending preview...\n`{file}`\n{quality}": (
        "✅ *{label} ¡Descargado!* Enviando vista previa...\n`{file}`\n{quality}",
        "✅ *{label} Heruntergeladen!* Sende Vorschau...\n`{file}`\n{quality}",
        "✅ *{label} Descargado!* Enviando vista previa...\n`{file}`\n{quality}",
    ),
    "{label} {quality}\nSave to library?": (
        "{label} {quality}\n¿Guardar en la biblioteca?",
        "{label} {quality}\nIn die Bibliothek speichern?",
        "{label} {quality}\nGardar na biblioteca?",
    ),
    "{label} {quality}\nSent to you — not saved to the library.": (
        "{label} {quality}\nEnviado a ti — no se guardó en la biblioteca.",
        "{label} {quality}\nAn dich gesendet — nicht in der Bibliothek gespeichert.",
        "{label} {quality}\nEnviado a ti — non se gardou na biblioteca.",
    ),
    "❌ Error downloading `{file}`. Check logs.": (
        "❌ Error al descargar `{file}`. Revisa los logs.",
        "❌ Fehler beim Herunterladen von `{file}`. Prüfe die Logs.",
        "❌ Erro ao descargar `{file}`. Revisa os logs.",
    ),
    "🎧 {label} Converted to OGG (original: {size:.0f}MB {fmt})\n{quality}\n": (
        "🎧 {label} Convertido a OGG (original: {size:.0f}MB {fmt})\n{quality}\n",
        "🎧 {label} Nach OGG konvertiert (Original: {size:.0f}MB {fmt})\n{quality}\n",
        "🎧 {label} Convertido a OGG (orixinal: {size:.0f}MB {fmt})\n{quality}\n",
    ),
    "Save to library?": (
        "¿Guardar en la biblioteca?",
        "In die Bibliothek speichern?",
        "Gardar na biblioteca?",
    ),
    "Sent to you — not saved to the library.": (
        "Enviado a ti — no se guardó en la biblioteca.",
        "An dich gesendet — nicht in der Bibliothek gespeichert.",
        "Enviado a ti — non se gardou na biblioteca.",
    ),
    "❌ {label} Could not create preview for {size:.0f}MB file.\n{quality}\n\n": (
        "❌ {label} No se pudo crear la vista previa del archivo de {size:.0f}MB.\n{quality}\n\n",
        "❌ {label} Vorschau für die {size:.0f}MB-Datei konnte nicht erstellt werden.\n{quality}\n\n",
        "❌ {label} Non se puido crear a vista previa do ficheiro de {size:.0f}MB.\n{quality}\n\n",
    ),
    "Save to library anyway?": (
        "¿Guardar en la biblioteca de todos modos?",
        "Trotzdem in die Bibliothek speichern?",
        "Gardar na biblioteca de todos os xeitos?",
    ),
    "Could not create a preview.": (
        "No se pudo crear una vista previa.",
        "Vorschau konnte nicht erstellt werden.",
        "Non se puido crear unha vista previa.",
    ),
    "🎧 {label} ~1 min preview (full file: {size:.0f}MB)\n{quality}\n": (
        "🎧 {label} Vista previa de ~1 min (archivo completo: {size:.0f}MB)\n{quality}\n",
        "🎧 {label} ~1 Min. Vorschau (volle Datei: {size:.0f}MB)\n{quality}\n",
        "🎧 {label} Vista previa de ~1 min (ficheiro completo: {size:.0f}MB)\n{quality}\n",
    ),
    "⏹ Cancelled": ("⏹ Cancelado", "⏹ Abgebrochen", "⏹ Cancelado"),
    "🚫 You are not allowed to save to the library.": (
        "🚫 No tienes permiso para guardar en la biblioteca.",
        "🚫 Du darfst nicht in die Bibliothek speichern.",
        "🚫 Non tes permiso para gardar na biblioteca.",
    ),
    "✅ Saved: `{name}`": ("✅ Guardado: `{name}`", "✅ Gespeichert: `{name}`", "✅ Gardado: `{name}`"),
    "❌ Failed to save file. Check logs.": (
        "❌ No se pudo guardar el archivo. Revisa los logs.",
        "❌ Datei konnte nicht gespeichert werden. Prüfe die Logs.",
        "❌ Non se puido gardar o ficheiro. Revisa os logs.",
    ),
    "❌ Source file not found.": (
        "❌ No se encontró el archivo de origen.",
        "❌ Quelldatei nicht gefunden.",
        "❌ Non se atopou o ficheiro de orixe.",
    ),
    "🗑 Discarded: {artist} - {title}": (
        "🗑 Descartado: {artist} - {title}",
        "🗑 Verworfen: {artist} - {title}",
        "🗑 Descartado: {artist} - {title}",
    ),
    "⏹ Download expired. Send a new search.": (
        "⏹ La descarga ha caducado. Envía una nueva búsqueda.",
        "⏹ Download abgelaufen. Starte eine neue Suche.",
        "⏹ A descarga caducou. Envía unha nova busca.",
    ),
    "🔄 Retrying: `{file}`...": (
        "🔄 Reintentando: `{file}`...",
        "🔄 Erneuter Versuch: `{file}`...",
        "🔄 Reintentando: `{file}`...",
    ),
    "⬇️ Re-downloading from `{user}`...": (
        "⬇️ Volviendo a descargar de `{user}`...",
        "⬇️ Lade erneut von `{user}` herunter...",
        "⬇️ Volvendo a descargar de `{user}`...",
    ),
    "⏹ No more results available. Try a new search.": (
        "⏹ No hay más resultados. Prueba una nueva búsqueda.",
        "⏹ Keine weiteren Ergebnisse. Starte eine neue Suche.",
        "⏹ Non hai máis resultados. Proba unha nova busca.",
    ),
    "⏹ No more results to try.": (
        "⏹ No hay más resultados que probar.",
        "⏹ Keine weiteren Ergebnisse zum Ausprobieren.",
        "⏹ Non hai máis resultados que probar.",
    ),
    "You have an unfinished import: *{name}* ({done}/{total}).\nSend `/import resume` to continue, or /cancel to stop it.": (
        "Tienes una importación sin terminar: *{name}* ({done}/{total}).\nEnvía `/import resume` para continuar, o /cancel para detenerla.",
        "Du hast einen unfertigen Import: *{name}* ({done}/{total}).\nSende `/import resume` zum Fortsetzen oder /cancel zum Abbrechen.",
        "Tes unha importación sen rematar: *{name}* ({done}/{total}).\nEnvía `/import resume` para continuar, ou /cancel para detela.",
    ),
    "Usage: `/import <spotify_playlist_or_album_url>` or `/import resume`": (
        "Uso: `/import <url_de_playlist_o_álbum_de_spotify>` o `/import resume`",
        "Verwendung: `/import <spotify_playlist_oder_album_url>` oder `/import resume`",
        "Uso: `/import <url_de_playlist_ou_álbum_de_spotify>` ou `/import resume`",
    ),
    "Please provide a valid Spotify playlist or album URL.": (
        "Proporciona una URL válida de playlist o álbum de Spotify.",
        "Bitte eine gültige Spotify-Playlist- oder Album-URL angeben.",
        "Proporciona un URL válido de playlist ou álbum de Spotify.",
    ),
    "You already have an active import: *{name}* ({done}/{total})\nSend `/import resume` to continue, or /cancel to stop it first.": (
        "Ya tienes una importación activa: *{name}* ({done}/{total})\nEnvía `/import resume` para continuar, o /cancel para detenerla primero.",
        "Du hast bereits einen aktiven Import: *{name}* ({done}/{total})\nSende `/import resume` zum Fortsetzen oder brich zuerst mit /cancel ab.",
        "Xa tes unha importación activa: *{name}* ({done}/{total})\nEnvía `/import resume` para continuar, ou /cancel para detela primeiro.",
    ),
    "🔍 Resolving playlist...": (
        "🔍 Resolviendo la playlist...",
        "🔍 Playlist wird aufgelöst...",
        "🔍 Resolvendo a playlist...",
    ),
    "Failed to resolve playlist. Check the URL and try again.": (
        "No se pudo resolver la playlist. Comprueba la URL e inténtalo de nuevo.",
        "Playlist konnte nicht aufgelöst werden. Prüfe die URL und versuche es erneut.",
        "Non se puido resolver a playlist. Comproba o URL e téntao de novo.",
    ),
    "album": ("álbum", "Album", "álbum"),
    "playlist": ("playlist", "Playlist", "playlist"),
    "📋 Found {kind}: *{name}*\nBy: {owner}\nTracks: {total}\n\nImport all tracks one by one?": (
        "📋 Se encontró {kind}: *{name}*\nDe: {owner}\nPistas: {total}\n\n¿Importar todas las pistas una a una?",
        "📋 {kind} gefunden: *{name}*\nVon: {owner}\nTitel: {total}\n\nAlle Titel nacheinander importieren?",
        "📋 Atopouse {kind}: *{name}*\nDe: {owner}\nPistas: {total}\n\nImportar todas as pistas unha a unha?",
    ),
    "❌ Import cancelled.": (
        "❌ Importación cancelada.",
        "❌ Import abgebrochen.",
        "❌ Importación cancelada.",
    ),
    "❌ Cancelled.": ("❌ Cancelado.", "❌ Abgebrochen.", "❌ Cancelado."),
    "Nothing to cancel.": (
        "No hay nada que cancelar.",
        "Nichts zum Abbrechen.",
        "Non hai nada que cancelar.",
    ),
    "⏹ Import not found.": (
        "⏹ Importación no encontrada.",
        "⏹ Import nicht gefunden.",
        "⏹ Importación non atopada.",
    ),
    "✅ Import started! Processing tracks one by one...": (
        "✅ ¡Importación iniciada! Procesando las pistas una a una...",
        "✅ Import gestartet! Titel werden nacheinander verarbeitet...",
        "✅ Importación iniciada! Procesando as pistas unha a unha...",
    ),
    "🗑 Track discarded.": ("🗑 Pista descartada.", "🗑 Titel verworfen.", "🗑 Pista descartada."),
    "⏭ Track skipped.": ("⏭ Pista omitida.", "⏭ Titel übersprungen.", "⏭ Pista omitida."),
    "⏹ Download expired. Use Skip or Mark failed to continue the import.": (
        "⏹ La descarga ha caducado. Usa Omitir o Marcar fallida para continuar la importación.",
        "⏹ Download abgelaufen. Nutze Überspringen oder Als fehlgeschlagen markieren, um den Import fortzusetzen.",
        "⏹ A descarga caducou. Usa Omitir ou Marcar fallida para continuar a importación.",
    ),
    "⏹ Download expired": ("⏹ Descarga caducada", "⏹ Download abgelaufen", "⏹ Descarga caducada"),
    "❌ Source file not ready. Download may still be in progress.": (
        "❌ El archivo de origen no está listo. La descarga puede seguir en curso.",
        "❌ Quelldatei noch nicht bereit. Der Download läuft möglicherweise noch.",
        "❌ O ficheiro de orixe non está listo. A descarga pode seguir en curso.",
    ),
    "❌ Failed to save file.": (
        "❌ No se pudo guardar el archivo.",
        "❌ Datei konnte nicht gespeichert werden.",
        "❌ Non se puido gardar o ficheiro.",
    ),
    "🏁 *Import complete!*": (
        "🏁 *¡Importación completa!*",
        "🏁 *Import abgeschlossen!*",
        "🏁 *Importación completa!*",
    ),
    "✅ Saved: {saved}\n❌ Failed: {failed}\n⏭ Skipped: {skipped}\n📊 Total: {total}": (
        "✅ Guardadas: {saved}\n❌ Fallidas: {failed}\n⏭ Omitidas: {skipped}\n📊 Total: {total}",
        "✅ Gespeichert: {saved}\n❌ Fehlgeschlagen: {failed}\n⏭ Übersprungen: {skipped}\n📊 Gesamt: {total}",
        "✅ Gardadas: {saved}\n❌ Fallidas: {failed}\n⏭ Omitidas: {skipped}\n📊 Total: {total}",
    ),
    "*Failed tracks:*": (
        "*Pistas fallidas:*",
        "*Fehlgeschlagene Titel:*",
        "*Pistas fallidas:*",
    ),
    "…and {n} more": ("…y {n} más", "…und {n} weitere", "…e {n} máis"),
    "Nothing to retry — no failed tracks left.": (
        "Nada que reintentar: no quedan pistas fallidas.",
        "Nichts zu wiederholen — keine fehlgeschlagenen Titel übrig.",
        "Nada que reintentar: non quedan pistas fallidas.",
    ),
    "🔄 Retrying {n} failed track(s)...": (
        "🔄 Reintentando {n} pista(s) fallida(s)...",
        "🔄 {n} fehlgeschlagene(r) Titel werden wiederholt...",
        "🔄 Reintentando {n} pista(s) fallida(s)...",
    ),
    ("🔄 Retry {n} failed track", "🔄 Retry {n} failed tracks"): (
        ("🔄 Reintentar {n} pista fallida", "🔄 Reintentar {n} pistas fallidas"),
        ("🔄 {n} fehlgeschlagenen Titel wiederholen", "🔄 {n} fehlgeschlagene Titel wiederholen"),
        ("🔄 Reintentar {n} pista fallida", "🔄 Reintentar {n} pistas fallidas"),
    ),
    "📋 *Import [{position}/{total}]*\n🔍 Searching: *{artist} - {title}*\nAlbum: {album} ({year})": (
        "📋 *Importación [{position}/{total}]*\n🔍 Buscando: *{artist} - {title}*\nÁlbum: {album} ({year})",
        "📋 *Import [{position}/{total}]*\n🔍 Suche: *{artist} - {title}*\nAlbum: {album} ({year})",
        "📋 *Importación [{position}/{total}]*\n🔍 Buscando: *{artist} - {title}*\nÁlbum: {album} ({year})",
    ),
    "📋 *Import track:* {artist} - {title}\n\nNo results found on Soulseek.": (
        "📋 *Pista de importación:* {artist} - {title}\n\nNo se encontraron resultados en Soulseek.",
        "📋 *Import-Titel:* {artist} - {title}\n\nKeine Ergebnisse auf Soulseek gefunden.",
        "📋 *Pista de importación:* {artist} - {title}\n\nNon se atoparon resultados en Soulseek.",
    ),
    "📋 *Import track:* {artist} - {title}\n⬇️ Downloading: `{file}`\nFrom: `{user}` | {quality}": (
        "📋 *Pista de importación:* {artist} - {title}\n⬇️ Descargando: `{file}`\nDe: `{user}` | {quality}",
        "📋 *Import-Titel:* {artist} - {title}\n⬇️ Lade herunter: `{file}`\nVon: `{user}` | {quality}",
        "📋 *Pista de importación:* {artist} - {title}\n⬇️ Descargando: `{file}`\nDe: `{user}` | {quality}",
    ),
    "Cannot reach slskd. Check `SLSKD_HOST` and the API key.": (
        "No se puede conectar con slskd. Comprueba `SLSKD_HOST` y la clave API.",
        "slskd ist nicht erreichbar. Prüfe `SLSKD_HOST` und den API-Schlüssel.",
        "Non se pode conectar con slskd. Comproba `SLSKD_HOST` e a clave API.",
    ),
    "❌ Search failed for {artist} - {title}": (
        "❌ La búsqueda falló para {artist} - {title}",
        "❌ Suche fehlgeschlagen für {artist} - {title}",
        "❌ A busca fallou para {artist} - {title}",
    ),
    "❌ Failed to enqueue from `{user}`": (
        "❌ No se pudo encolar desde `{user}`",
        "❌ Einreihen von `{user}` fehlgeschlagen",
        "❌ Non se puido encolar desde `{user}`",
    ),
    "❌ Download failed: {state}\n`{file}`": (
        "❌ Error de descarga: {state}\n`{file}`",
        "❌ Download fehlgeschlagen: {state}\n`{file}`",
        "❌ Erro de descarga: {state}\n`{file}`",
    ),
    "❌ Downloaded file not found on disk.": (
        "❌ No se encontró el archivo descargado en disco.",
        "❌ Heruntergeladene Datei nicht auf der Festplatte gefunden.",
        "❌ Non se atopou o ficheiro descargado no disco.",
    ),
    "📋 Import: {artist} - {title}\n{quality}": (
        "📋 Importación: {artist} - {title}\n{quality}",
        "📋 Import: {artist} - {title}\n{quality}",
        "📋 Importación: {artist} - {title}\n{quality}",
    ),
    "✅ Downloaded: `{file}` ({size:.0f}MB)\n{quality}\n\nFile too large to preview. Save to library?": (
        "✅ Descargado: `{file}` ({size:.0f}MB)\n{quality}\n\nEl archivo es demasiado grande para previsualizar. ¿Guardar en la biblioteca?",
        "✅ Heruntergeladen: `{file}` ({size:.0f}MB)\n{quality}\n\nDatei zu groß für die Vorschau. In die Bibliothek speichern?",
        "✅ Descargado: `{file}` ({size:.0f}MB)\n{quality}\n\nO ficheiro é demasiado grande para previsualizar. Gardar na biblioteca?",
    ),
    "❌ Error downloading `{file}`": (
        "❌ Error al descargar `{file}`",
        "❌ Fehler beim Herunterladen von `{file}`",
        "❌ Erro ao descargar `{file}`",
    ),
    "Nothing to resume.": (
        "No hay nada que reanudar.",
        "Nichts zum Fortsetzen.",
        "Non hai nada que retomar.",
    ),
    "Import of *{name}* is already running.": (
        "La importación de *{name}* ya está en curso.",
        "Der Import von *{name}* läuft bereits.",
        "A importación de *{name}* xa está en curso.",
    ),
    "Resuming import of *{name}* ({remaining} remaining, {done} done).": (
        "Reanudando la importación de *{name}* ({remaining} restantes, {done} hechas).",
        "Setze Import von *{name}* fort ({remaining} übrig, {done} erledigt).",
        "Retomando a importación de *{name}* ({remaining} restantes, {done} feitas).",
    ),
    "◀️ Prev": ("◀️ Ant", "◀️ Zurück", "◀️ Ant"),
    "Next ▶️": ("Sig ▶️", "Weiter ▶️", "Seg ▶️"),
    "Auto-pick best": ("Elegir la mejor", "Beste automatisch", "Elixir a mellor"),
    "Cancel": ("Cancelar", "Abbrechen", "Cancelar"),
    "💾 Save to library": ("💾 Guardar en la biblioteca", "💾 In Bibliothek speichern", "💾 Gardar na biblioteca"),
    "🗑 Discard": ("🗑 Descartar", "🗑 Verwerfen", "🗑 Descartar"),
    "⏭ Try next result": ("⏭ Probar el siguiente", "⏭ Nächstes Ergebnis", "⏭ Probar o seguinte"),
    "Continue anyway": ("Continuar de todos modos", "Trotzdem fortfahren", "Continuar de todos os xeitos"),
    "🔍 Search Soulseek directly": (
        "🔍 Buscar en Soulseek directamente",
        "🔍 Direkt auf Soulseek suchen",
        "🔍 Buscar en Soulseek directamente",
    ),
    "Disable auto-mode": ("Desactivar auto-modo", "Auto-Modus aus", "Desactivar auto-modo"),
    "Enable auto-mode": ("Activar auto-modo", "Auto-Modus an", "Activar auto-modo"),
    "✅ Start import": ("✅ Iniciar importación", "✅ Import starten", "✅ Iniciar importación"),
    "❌ Cancel": ("❌ Cancelar", "❌ Abbrechen", "❌ Cancelar"),
    "⏭ Skip track": ("⏭ Omitir pista", "⏭ Titel überspringen", "⏭ Omitir pista"),
    "Prefer Hi-Res (24-bit)": (
        "Preferir Hi-Res (24 bits)",
        "Hi-Res bevorzugen (24 Bit)",
        "Preferir Hi-Res (24 bits)",
    ),
    "Prefer CD quality (16/44.1)": (
        "Preferir calidad CD (16/44.1)",
        "CD-Qualität bevorzugen (16/44.1)",
        "Preferir calidade CD (16/44.1)",
    ),
    "CD quality (16/44.1)": ("Calidad CD (16/44.1)", "CD-Qualität (16/44.1)", "Calidade CD (16/44.1)"),
    "Hi-Res (24-bit)": ("Hi-Res (24 bits)", "Hi-Res (24 Bit)", "Hi-Res (24 bits)"),
    "Audio quality preference: *{label}*": (
        "Preferencia de calidad de audio: *{label}*",
        "Audioqualitäts-Präferenz: *{label}*",
        "Preferencia de calidade de audio: *{label}*",
    ),
    "Audio quality preference: *{label}*\n\nThis changes how search results are ranked — the preferred format scores higher.": (
        "Preferencia de calidad de audio: *{label}*\n\nEsto cambia cómo se ordenan los resultados de búsqueda: el formato preferido puntúa más alto.",
        "Audioqualitäts-Präferenz: *{label}*\n\nDies ändert die Sortierung der Suchergebnisse — das bevorzugte Format erhält eine höhere Punktzahl.",
        "Preferencia de calidade de audio: *{label}*\n\nIsto cambia como se ordenan os resultados da busca: o formato preferido puntúa máis alto.",
    ),
    "Nothing to undo — no library saves in this chat.": (
        "Nada que deshacer: no hay guardados en la biblioteca en este chat.",
        "Nichts rückgängig zu machen — keine gespeicherten Titel in diesem Chat.",
        "Nada que desfacer: non hai gardados na biblioteca neste chat.",
    ),
    "↩️ Removed from library: {name}": (
        "↩️ Eliminado de la biblioteca: {name}",
        "↩️ Aus der Bibliothek entfernt: {name}",
        "↩️ Eliminado da biblioteca: {name}",
    ),
    "Could not find {name} in the library — maybe it was already removed.": (
        "No se encontró {name} en la biblioteca; quizá ya se eliminó.",
        "{name} wurde nicht in der Bibliothek gefunden — vielleicht wurde es bereits entfernt.",
        "Non se atopou {name} na biblioteca; quizais xa se eliminou.",
    ),
    "⏱ exact duration": ("⏱ duración exacta", "⏱ exakte Dauer", "⏱ duración exacta"),
    "⏱ ±{secs}s": ("⏱ ±{secs}s", "⏱ ±{secs}s", "⏱ ±{secs}s"),
    "🟢 free slot": ("🟢 hueco libre", "🟢 freier Slot", "🟢 oco libre"),
    "🔴 queue of {n}": ("🔴 cola de {n}", "🔴 Warteschlange von {n}", "🔴 cola de {n}"),
    "⭐ {score}/100": ("⭐ {score}/100", "⭐ {score}/100", "⭐ {score}/100"),
    "That looks like a playlist or album link.\nUse `/import {url}` to import it.": (
        "Eso parece un enlace de playlist o álbum.\nUsa `/import {url}` para importarlo.",
        "Das sieht nach einem Playlist- oder Album-Link aus.\nVerwende `/import {url}`, um ihn zu importieren.",
        "Iso parece unha ligazón de playlist ou álbum.\nUsa `/import {url}` para importalo.",
    ),
    "🔗 Resolving Spotify track link...": (
        "🔗 Resolviendo el enlace de pista de Spotify...",
        "🔗 Spotify-Track-Link wird aufgelöst...",
        "🔗 Resolvendo a ligazón de pista de Spotify...",
    ),
    "Could not resolve that Spotify track link. Try the song name instead.": (
        "No se pudo resolver ese enlace de pista de Spotify. Prueba con el nombre de la canción.",
        "Dieser Spotify-Track-Link konnte nicht aufgelöst werden. Versuche es mit dem Songnamen.",
        "Non se puido resolver esa ligazón de pista de Spotify. Proba co nome da canción.",
    ),
    "🔗 Resolving SoundCloud link...": (
        "🔗 Resolviendo el enlace de SoundCloud...",
        "🔗 SoundCloud-Link wird aufgelöst...",
        "🔗 Resolvendo a ligazón de SoundCloud...",
    ),
    "Could not resolve that SoundCloud link. Try the song name instead.": (
        "No se pudo resolver ese enlace de SoundCloud. Prueba con el nombre de la canción.",
        "Dieser SoundCloud-Link konnte nicht aufgelöst werden. Versuche es mit dem Songnamen.",
        "Non se puido resolver esa ligazón de SoundCloud. Proba co nome da canción.",
    ),
    "🎧 SoundCloud: *{artist} - {title}*\nLooking it up...": (
        "🎧 SoundCloud: *{artist} - {title}*\nBuscándolo...",
        "🎧 SoundCloud: *{artist} - {title}*\nWird gesucht...",
        "🎧 SoundCloud: *{artist} - {title}*\nBuscándoo...",
    ),
    "🚫 Mark failed": ("🚫 Marcar fallida", "🚫 Als fehlgeschlagen", "🚫 Marcar fallida"),
    "🔄 Retry": ("🔄 Reintentar", "🔄 Erneut versuchen", "🔄 Reintentar"),
    "Choose a language:": ("Elige un idioma:", "Wähle eine Sprache:", "Escolle un idioma:"),
    "Language set to {name}.": (
        "Idioma establecido: {name}.",
        "Sprache gesetzt: {name}.",
        "Idioma estabelecido: {name}.",
    ),
    "Send me a song name (e.g., `Nancy Sinatra Bang Bang`), a Spotify track link, or a SoundCloud track link and I'll find and download it in FLAC.\n\nCommands:\n/auto — Toggle auto-download mode\n/quality — Prefer CD or Hi-Res audio\n/import <url> — Import a Spotify playlist or album\n/import resume — Continue a paused import after restart\n/status — Show active searches, downloads, and imports\n/history — Recent downloads\n/undo — Remove the last track saved to the library\n/cancel — Cancel the current search, download, or import\n/lang — Change language\n/help — Show this message": (
        "Envíame el nombre de una canción (p. ej., `Nancy Sinatra Bang Bang`), un enlace de pista de Spotify o un enlace de pista de SoundCloud y la buscaré y descargaré en FLAC.\n\nComandos:\n/auto — Alternar el modo de descarga automática\n/quality — Preferir audio CD o Hi-Res\n/import <url> — Importar una playlist o álbum de Spotify\n/import resume — Continuar una importación pausada tras un reinicio\n/status — Mostrar búsquedas, descargas e importaciones activas\n/history — Descargas recientes\n/undo — Eliminar la última pista guardada en la biblioteca\n/cancel — Cancelar la búsqueda, descarga o importación actual\n/lang — Cambiar idioma\n/help — Mostrar este mensaje",
        "Schick mir einen Songnamen (z. B. `Nancy Sinatra Bang Bang`), einen Spotify-Track-Link oder einen SoundCloud-Track-Link und ich finde und lade ihn als FLAC herunter.\n\nBefehle:\n/auto — Automatischen Download umschalten\n/quality — CD- oder Hi-Res-Audio bevorzugen\n/import <url> — Spotify-Playlist oder -Album importieren\n/import resume — Pausierten Import nach einem Neustart fortsetzen\n/status — Aktive Suchen, Downloads und Importe anzeigen\n/history — Letzte Downloads\n/undo — Zuletzt in der Bibliothek gespeicherten Titel entfernen\n/cancel — Aktuelle Suche, Download oder Import abbrechen\n/lang — Sprache ändern\n/help — Diese Nachricht anzeigen",
        "Envíame o nome dunha canción (p. ex., `Nancy Sinatra Bang Bang`), unha ligazón de pista de Spotify ou unha ligazón de pista de SoundCloud e buscareina e descargareina en FLAC.\n\nComandos:\n/auto — Alternar o modo de descarga automática\n/quality — Preferir audio CD ou Hi-Res\n/import <url> — Importar unha playlist ou álbum de Spotify\n/import resume — Continuar unha importación pausada tras un reinicio\n/status — Amosar buscas, descargas e importacións activas\n/history — Descargas recentes\n/undo — Eliminar a última pista gardada na biblioteca\n/cancel — Cancelar a busca, descarga ou importación actual\n/lang — Cambiar o idioma\n/help — Amosar esta mensaxe",
    ),
    "{emoji} Lossless OK (spectrum to {khz:.1f}kHz)": (
        "{emoji} Lossless OK (espectro hasta {khz:.1f}kHz)",
        "{emoji} Lossless OK (Spektrum bis {khz:.1f}kHz)",
        "{emoji} Lossless OK (espectro ata {khz:.1f}kHz)",
    ),
    "Possible transcode": ("Posible transcodificación", "Mögliche Transkodierung", "Posible transcodificación"),
    "Likely transcode": ("Probable transcodificación", "Vermutlich transkodiert", "Probable transcodificación"),
    "Fake lossless": ("Falso lossless", "Gefälschtes Lossless", "Falso lossless"),
    "{emoji} {label} (cutoff {khz:.1f}kHz)": (
        "{emoji} {label} (corte {khz:.1f}kHz)",
        "{emoji} {label} (Cutoff {khz:.1f}kHz)",
        "{emoji} {label} (corte {khz:.1f}kHz)",
    ),
    "🔍 *Multiple matches found on Spotify:*": (
        "🔍 *Varias coincidencias en Spotify:*",
        "🔍 *Mehrere Treffer auf Spotify:*",
        "🔍 *Varias coincidencias en Spotify:*",
    ),
    " (page {page}/{total})": (
        " (página {page}/{total})",
        " (Seite {page}/{total})",
        " (páxina {page}/{total})",
    ),
    "*#{n} {artist} - {title}*\n    Album: {album} ({year}) | {duration}\n    [Listen on Spotify]({url})": (
        "*#{n} {artist} - {title}*\n    Álbum: {album} ({year}) | {duration}\n    [Escuchar en Spotify]({url})",
        "*#{n} {artist} - {title}*\n    Album: {album} ({year}) | {duration}\n    [Auf Spotify anhören]({url})",
        "*#{n} {artist} - {title}*\n    Álbum: {album} ({year}) | {duration}\n    [Escoitar en Spotify]({url})",
    ),
    "Pick the correct version:": (
        "Elige la versión correcta:",
        "Wähle die richtige Version:",
        "Escolle a versión correcta:",
    ),
    ("Found {n} FLAC match:", "Found {n} FLAC matches:"): (
        ("Se encontró {n} coincidencia FLAC:", "Se encontraron {n} coincidencias FLAC:"),
        ("{n} FLAC-Treffer gefunden:", "{n} FLAC-Treffer gefunden:"),
        ("Atopouse {n} coincidencia FLAC:", "Atopáronse {n} coincidencias FLAC:"),
    ),
    "🔍 *Direct search:* `{query}`": (
        "🔍 *Búsqueda directa:* `{query}`",
        "🔍 *Direktsuche:* `{query}`",
        "🔍 *Busca directa:* `{query}`",
    ),
    "Duration: {duration} | Album: {album}": (
        "Duración: {duration} | Álbum: {album}",
        "Dauer: {duration} | Album: {album}",
        "Duración: {duration} | Álbum: {album}",
    ),
    ("⚠️ No FLAC found — showing all formats ({n} match):", "⚠️ No FLAC found — showing all formats ({n} matches):"): (
        (
            "⚠️ No se encontró FLAC — mostrando todos los formatos ({n} coincidencia):",
            "⚠️ No se encontró FLAC — mostrando todos los formatos ({n} coincidencias):",
        ),
        (
            "⚠️ Kein FLAC gefunden — zeige alle Formate ({n} Treffer):",
            "⚠️ Kein FLAC gefunden — zeige alle Formate ({n} Treffer):",
        ),
        (
            "⚠️ Non se atopou FLAC — amosando todos os formatos ({n} coincidencia):",
            "⚠️ Non se atopou FLAC — amosando todos os formatos ({n} coincidencias):",
        ),
    ),
    "📄 Page {page}/{total}": (
        "📄 Página {page}/{total}",
        "📄 Seite {page}/{total}",
        "📄 Páxina {page}/{total}",
    ),
    "🔍 Searching slskd for: `{query}`\nSaving as: *{artist} - {title}*": (
        "🔍 Buscando en slskd: `{query}`\nSe guardará como: *{artist} - {title}*",
        "🔍 Suche auf slskd nach: `{query}`\nSpeichern als: *{artist} - {title}*",
        "🔍 Buscando en slskd: `{query}`\nGardarase como: *{artist} - {title}*",
    ),
    "⚠️ *Similar files already in library:*\n\n{files}\n\nContinue searching anyway?": (
        "⚠️ *Ya hay archivos similares en la biblioteca:*\n\n{files}\n\n¿Continuar la búsqueda de todos modos?",
        "⚠️ *Ähnliche Dateien bereits in der Bibliothek:*\n\n{files}\n\nTrotzdem weitersuchen?",
        "⚠️ *Xa hai ficheiros semellantes na biblioteca:*\n\n{files}\n\nContinuar a busca de todos os xeitos?",
    ),
    "🔍 Looking up: `{query}`": (
        "🔍 Buscando: `{query}`",
        "🔍 Suche: `{query}`",
        "🔍 Buscando: `{query}`",
    ),
    "Could not find `{query}` on Spotify.\nYou can search Soulseek directly instead.": (
        "No se encontró `{query}` en Spotify.\nPuedes buscar en Soulseek directamente.",
        "`{query}` wurde auf Spotify nicht gefunden.\nDu kannst stattdessen direkt auf Soulseek suchen.",
        "Non se atopou `{query}` en Spotify.\nPodes buscar en Soulseek directamente.",
    ),
    "Something went wrong. Please try again.": (
        "Algo salió mal. Inténtalo de nuevo.",
        "Etwas ist schiefgelaufen. Bitte versuche es erneut.",
        "Algo saíu mal. Téntao de novo.",
    ),
    "🎵 {track}\nAlbum: {album} ({year})\nDuration: {duration}\n\nSearching slskd...": (
        "🎵 {track}\nÁlbum: {album} ({year})\nDuración: {duration}\n\nBuscando en slskd...",
        "🎵 {track}\nAlbum: {album} ({year})\nDauer: {duration}\n\nSuche auf slskd...",
        "🎵 {track}\nÁlbum: {album} ({year})\nDuración: {duration}\n\nBuscando en slskd...",
    ),
    "🎵 {track}\n\nNo results with full query — retrying with song title only…": (
        "🎵 {track}\n\nSin resultados con la consulta completa — reintentando solo con el título…",
        "🎵 {track}\n\nKeine Treffer mit voller Suche — versuche nur den Songtitel…",
        "🎵 {track}\n\nSen resultados coa consulta completa — reintentando só co título…",
    ),
    "🎵 {track}\n\nStill no results — trying keyword variations with year…": (
        "🎵 {track}\n\nSigue sin haber resultados — probando variaciones de palabras clave con el año…",
        "🎵 {track}\n\nImmer noch keine Treffer — versuche Keyword-Varianten mit Jahr…",
        "🎵 {track}\n\nSegue sen haber resultados — probando variacións de palabras clave co ano…",
    ),
    "🎵 {track}\n\nStill no results — trying artist + keyword search…": (
        "🎵 {track}\n\nSigue sin haber resultados — buscando artista + palabras clave…",
        "🎵 {track}\n\nImmer noch keine Treffer — versuche Künstler + Keywords…",
        "🎵 {track}\n\nSegue sen haber resultados — buscando artista + palabras clave…",
    ),
    "🎵 {track} ({duration})\n\nNo results found on Soulseek matching this track.\nTry a different search query.": (
        "🎵 {track} ({duration})\n\nNo se encontraron resultados en Soulseek para esta pista.\nPrueba con otra búsqueda.",
        "🎵 {track} ({duration})\n\nKeine passenden Ergebnisse auf Soulseek.\nVersuche eine andere Suche.",
        "🎵 {track} ({duration})\n\nNon se atoparon resultados en Soulseek para esta pista.\nProba con outra busca.",
    ),
    "Something went wrong during the search. Please try again.": (
        "Algo salió mal durante la búsqueda. Inténtalo de nuevo.",
        "Bei der Suche ist etwas schiefgelaufen. Bitte versuche es erneut.",
        "Algo saíu mal durante a busca. Téntao de novo.",
    ),
    "Continuing with search: `{query}`": (
        "Continuando la búsqueda: `{query}`",
        "Suche wird fortgesetzt: `{query}`",
        "Continuando a busca: `{query}`",
    ),
    "🔍 Searching slskd for FLAC...": (
        "🔍 Buscando FLAC en slskd...",
        "🔍 Suche FLAC auf slskd...",
        "🔍 Buscando FLAC en slskd...",
    ),
    "Selected: {track} ({duration})": (
        "Seleccionado: {track} ({duration})",
        "Ausgewählt: {track} ({duration})",
        "Seleccionado: {track} ({duration})",
    ),
    "🎵 How should this track be saved?\n\nSend the name as: `Artist - Title`\n(This will be used for the filename and tags)": (
        "🎵 ¿Cómo se debe guardar esta pista?\n\nEnvía el nombre así: `Artista - Título`\n(Se usará para el nombre de archivo y las etiquetas)",
        "🎵 Wie soll dieser Titel gespeichert werden?\n\nSende den Namen als: `Interpret - Titel`\n(Wird für Dateiname und Tags verwendet)",
        "🎵 Como se debe gardar esta pista?\n\nEnvía o nome así: `Artista - Título`\n(Usarase para o nome de ficheiro e as etiquetas)",
    ),
    "🔍 Direct search: `{query}`\n\nNo results found on Soulseek.": (
        "🔍 Búsqueda directa: `{query}`\n\nNo se encontraron resultados en Soulseek.",
        "🔍 Direktsuche: `{query}`\n\nKeine Ergebnisse auf Soulseek.",
        "🔍 Busca directa: `{query}`\n\nNon se atoparon resultados en Soulseek.",
    ),
    "⚠️ *Already in the library:* {track}": (
        "⚠️ *Ya está en la biblioteca:* {track}",
        "⚠️ *Bereits in der Bibliothek:* {track}",
        "⚠️ *Xa está na biblioteca:* {track}",
    ),
    "On disk:": ("En disco:", "Auf der Festplatte:", "No disco:"),
    "Previously saved as `{filename}`": (
        "Guardado anteriormente como `{filename}`",
        "Bereits gespeichert als `{filename}`",
        "Gardado anteriormente como `{filename}`",
    ),
    "Search Soulseek anyway?": (
        "¿Buscar en Soulseek de todos modos?",
        "Trotzdem auf Soulseek suchen?",
        "Buscar en Soulseek de todos os xeitos?",
    ),
    "⚡ Auto-downloading best match for {track}...": (
        "⚡ Descargando automáticamente la mejor coincidencia de {track}...",
        "⚡ Lade beste Übereinstimmung für {track} automatisch herunter...",
        "⚡ Descargando automaticamente a mellor coincidencia de {track}...",
    ),
    "⬇️ *Downloading #{n}...*\n{track}\nFrom: `{user}`\nFile: `{file}`": (
        "⬇️ *Descargando #{n}...*\n{track}\nDe: `{user}`\nArchivo: `{file}`",
        "⬇️ *Lade #{n} herunter...*\n{track}\nVon: `{user}`\nDatei: `{file}`",
        "⬇️ *Descargando #{n}...*\n{track}\nDe: `{user}`\nFicheiro: `{file}`",
    ),
    "awaiting approval": (
        "esperando aprobación",
        "wartet auf Freigabe",
        "agardando aprobación",
    ),
    "starting...": (
        "iniciando...",
        "startet...",
        "iniciando...",
    ),
    "*Active import:*": (
        "*Importación activa:*",
        "*Aktiver Import:*",
        "*Importación activa:*",
    ),
    "• {name} — {done}/{total} processed ({ok} saved, {failed} failed, {skipped} skipped)": (
        "• {name} — {done}/{total} procesadas ({ok} guardadas, {failed} fallidas, {skipped} omitidas)",
        "• {name} — {done}/{total} verarbeitet ({ok} gespeichert, {failed} fehlgeschlagen, {skipped} übersprungen)",
        "• {name} — {done}/{total} procesadas ({ok} gardadas, {failed} fallidas, {skipped} omitidas)",
    ),
    "No active searches, downloads, or imports.": (
        "No hay búsquedas, descargas ni importaciones activas.",
        "Keine aktiven Suchen, Downloads oder Importe.",
        "Non hai buscas, descargas nin importacións activas.",
    ),
    "⬇️ *Downloading {label}...* {pct}%\n{bar}\n{artist} - {title}\nFile: `{file}`": (
        "⬇️ *Descargando {label}...* {pct}%\n{bar}\n{artist} - {title}\nArchivo: `{file}`",
        "⬇️ *Lade {label} herunter...* {pct}%\n{bar}\n{artist} - {title}\nDatei: `{file}`",
        "⬇️ *Descargando {label}...* {pct}%\n{bar}\n{artist} - {title}\nFicheiro: `{file}`",
    ),
    "🔄 Retrying {label}: `{file}`...": (
        "🔄 Reintentando {label}: `{file}`...",
        "🔄 Erneuter Versuch {label}: `{file}`...",
        "🔄 Reintentando {label}: `{file}`...",
    ),
    "⬇️ Re-downloading {label} from `{user}`...": (
        "⬇️ Volviendo a descargar {label} de `{user}`...",
        "⬇️ Lade {label} erneut von `{user}` herunter...",
        "⬇️ Volvendo a descargar {label} de `{user}`...",
    ),
    "⏭ Trying next result {label}: `{file}`": (
        "⏭ Probando el siguiente resultado {label}: `{file}`",
        "⏭ Nächstes Ergebnis {label}: `{file}`",
        "⏭ Probando o seguinte resultado {label}: `{file}`",
    ),
    "⬇️ Downloading {label} from `{user}`...": (
        "⬇️ Descargando {label} de `{user}`...",
        "⬇️ Lade {label} von `{user}` herunter...",
        "⬇️ Descargando {label} de `{user}`...",
    ),
    "📋 *Import track:* {artist} - {title}\n⬇️ Downloading {pct}%\n{bar}\n`{file}`": (
        "📋 *Pista de importación:* {artist} - {title}\n⬇️ Descargando {pct}%\n{bar}\n`{file}`",
        "📋 *Import-Titel:* {artist} - {title}\n⬇️ Download {pct}%\n{bar}\n`{file}`",
        "📋 *Pista de importación:* {artist} - {title}\n⬇️ Descargando {pct}%\n{bar}\n`{file}`",
    ),
}


def _as_key(msgid) -> str | tuple[str, str]:
    if isinstance(msgid, (list, tuple)) and len(msgid) == 2:
        return (str(msgid[0]), str(msgid[1]))
    return msgid


def main() -> None:
    with POT.open("rb") as fh:
        pot = read_po(fh)

    missing: list[str] = []
    for message in pot:
        if not message.id:
            continue
        if _as_key(message.id) not in TRANSLATIONS:
            missing.append(repr(message.id))
    if missing:
        raise SystemExit("Missing translations:\n" + "\n".join(missing))

    extra = set(TRANSLATIONS) - {_as_key(m.id) for m in pot if m.id}
    if extra:
        raise SystemExit("Unused translation keys:\n" + "\n".join(repr(k) for k in extra))

    locales = (
        ("es", "es", "Spanish"),
        ("de", "de", "German"),
        ("gl", "gl", "Galician"),
    )
    for index, (code, locale, name) in enumerate(locales):
        catalog = Catalog(
            locale=locale,
            domain="messages",
            header_comment=f"# {name} translations for telegram-slskd-local-bot\n",
        )
        for message in pot:
            if not message.id:
                continue
            translated = TRANSLATIONS[_as_key(message.id)][index]
            catalog.add(
                message.id,
                string=translated,
                locations=message.locations,
                flags=message.flags,
                user_comments=message.user_comments,
                auto_comments=message.auto_comments,
            )
        dest = LOCALES / code / "LC_MESSAGES"
        dest.mkdir(parents=True, exist_ok=True)
        po_path = dest / "messages.po"
        mo_path = dest / "messages.mo"
        with po_path.open("wb") as fh:
            write_po(fh, catalog, ignore_obsolete=True)
        with mo_path.open("wb") as fh:
            write_mo(fh, catalog)
        print(f"wrote {po_path} and {mo_path}")


if __name__ == "__main__":
    main()
