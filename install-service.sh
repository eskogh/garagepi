#!/bin/bash
SERVICE=garagepi.service
SYSTEMD_DIR=/etc/systemd/system

echo "Copying $SERVICE to $SYSTEMD_DIR..."
sudo cp src/garagepi/systemd/$SERVICE $SYSTEMD_DIR

echo "Reloading systemd..."
sudo systemctl daemon-reload

echo "Enabling service..."
sudo systemctl enable --now $SERVICE

echo "Done. Check status with: systemctl status $SERVICE"
