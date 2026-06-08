#!/bin/bash
#
# Remove the Voice Studio KH always-on service (launchd LaunchAgent).
# Leaves the app itself untouched — Pinokio's "Start" button works as before.
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
UID_NUM="$(id -u)"
LA="$HOME/Library/LaunchAgents"
SRV="com.kh.voicestudio.server"
WD="com.kh.voicestudio.watchdog"

launchctl bootout "gui/$UID_NUM/$SRV" 2>/dev/null || true
launchctl bootout "gui/$UID_NUM/$WD"  2>/dev/null || true
rm -f "$LA/$SRV.plist" "$LA/$WD.plist" "$ROOT/service/.installed"

echo "🧹 Voice Studio KH startup service removed."
echo "   The Mac will no longer auto-start it. Pinokio's Start button still works."
echo "   (System settings like auto-login / pmset are untouched — change those"
echo "    yourself if you no longer want the Mac to power on after a power cut.)"
