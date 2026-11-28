#!/bin/sh
# Instala el lector de WhatsApp en la Mac que se queda prendida.
# Uso: mac/whatsapp-lector/instalar.sh '<PROYECTO>' '<URL_CLOUD_RUN>'
# Requiere: Xcode Command Line Tools (swiftc), gcloud con sesión, WhatsApp para Mac con sesión.
set -eu

project="${1:-}"
url="${2:-}"
if [ -z "$project" ] || [ -z "$url" ]; then
    printf 'Uso: %s <PROYECTO> <URL_CLOUD_RUN>\n' "$0" >&2
    exit 2
fi

here="$(cd "$(dirname "$0")" && pwd)"
bin="$HOME/.jarvis/bin/whatsapp-lector"
mkdir -p "$HOME/.jarvis/bin" "$HOME/Library/LaunchAgents"

swiftc -O "$here/main.swift" -o "$bin"

if [ ! -f "$HOME/.jarvis/whatsapp.json" ]; then
    printf '{"url": "%s", "excluir": []}\n' "$url" > "$HOME/.jarvis/whatsapp.json"
fi

# El token va al Llavero, nunca a un archivo.
token="$(gcloud secrets versions access latest --secret=JARVIS_TOKEN --project="$project")"
security add-generic-password -U -s jarvis -a token -w "$token" >/dev/null
unset token

plist="$HOME/Library/LaunchAgents/com.jarvis.whatsapp.plist"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.jarvis.whatsapp</string>
    <key>ProgramArguments</key><array><string>$bin</string></array>
    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
    </array>
    <key>StandardOutPath</key><string>$HOME/.jarvis/whatsapp.log</string>
    <key>StandardErrorPath</key><string>$HOME/.jarvis/whatsapp.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/com.jarvis.whatsapp" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"

printf 'Listo. Falta darle Acceso total al disco a:\n  %s\n' "$bin"
printf 'Luego prueba con: %s --revisar\n' "$bin"
