#!/bin/bash
SCRIPT="$HOME/ssd_health.py"
if [ ! -f "$SCRIPT" ]; then
  echo "Липсва $SCRIPT"
  echo "Копирай ssd_health.py в домашната папка."
  read -r -p "Натисни Enter..."
  exit 1
fi
sudo python3 "$SCRIPT"
echo
read -r -p "Натисни Enter за затваряне..."
