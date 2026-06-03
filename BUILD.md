# Building GPUMode

Instructions for building the GPUMode .deb package locally.

---

## Prerequisites

- Debian/Ubuntu-based system
- `dpkg-deb` (usually pre-installed)

---

## Build Steps

### 1. Create package structure

```bash
rm -rf debian
mkdir -p debian/gpumode/usr/bin
mkdir -p debian/gpumode/lib/systemd/system
mkdir -p debian/gpumode/etc/udev/rules.d
mkdir -p debian/gpumode/usr/share/doc/gpumode
mkdir -p debian/gpumode/DEBIAN
```

### 2. Copy application files

```bash
cp GPUMode.py debian/gpumode/usr/bin/gpumode
chmod +x debian/gpumode/usr/bin/gpumode

cp power-profile-manager.py debian/gpumode/usr/bin/power-profile-manager
chmod +x debian/gpumode/usr/bin/power-profile-manager

cp power-profile-manager.service debian/gpumode/lib/systemd/system/
cp 99-power-profile-manager.rules debian/gpumode/etc/udev/rules.d/
```

### 3. Create control file

```bash
cat > debian/gpumode/DEBIAN/control << 'EOF'
Package: gpumode
Version: 1.02
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-gi, python3-dbus, gir1.2-gtk-3.0, gir1.2-appindicator3-0.1, gir1.2-notify-0.7, gir1.2-upowerglib-1.0, polkitd, udev, mesa-utils
Maintainer: Matt Hartley <mrh@frame.work>
Description: Manual GPU switching and automatic power profile management
 System tray application for manual GPU mode switching on NVIDIA Optimus
 laptops, with automatic power profile adjustment.
EOF
```

### 4. Create postinst script

```bash
cat > debian/gpumode/DEBIAN/postinst << 'EOF'
#!/bin/bash
set -e

for user_home in /home/*; do
    if [ -d "$user_home" ]; then
        user=$(basename "$user_home")
        autostart_dir="$user_home/.config/autostart"
        autostart_file="$autostart_dir/gpumode.desktop"

        sudo -u "$user" mkdir -p "$autostart_dir" 2>/dev/null || mkdir -p "$autostart_dir"

        cat > "$autostart_file" << 'DESKTOPEOF'
[Desktop Entry]
Type=Application
Name=GPUMode
Comment=Manual GPU mode switching for laptops
Exec=/usr/bin/gpumode
Icon=video-display
Terminal=false
Categories=System;
X-GNOME-Autostart-enabled=true
DESKTOPEOF

        chown "$user":"$user" "$autostart_file" 2>/dev/null || true
        chmod 644 "$autostart_file"
    fi
done

udevadm control --reload-rules
udevadm trigger --subsystem-match=power_supply

systemctl daemon-reload
systemctl enable power-profile-manager.service
systemctl start power-profile-manager.service

exit 0
EOF
chmod +x debian/gpumode/DEBIAN/postinst
```

### 5. Create prerm script

```bash
cat > debian/gpumode/DEBIAN/prerm << 'EOF'
#!/bin/bash
set -e

systemctl stop power-profile-manager.service 2>/dev/null || true
systemctl disable power-profile-manager.service 2>/dev/null || true

pkill -f "python3.*gpumode" 2>/dev/null || true

for user_home in /home/*; do
    if [ -d "$user_home" ]; then
        rm -f "$user_home/.config/autostart/gpumode.desktop" 2>/dev/null || true
    fi
done

exit 0
EOF
chmod +x debian/gpumode/DEBIAN/prerm
```

### 6. Build the package

```bash
dpkg-deb --build debian/gpumode
mv debian/gpumode.deb gpumode_1.02_all.deb
```

---

## Installation

```bash
# Remove old version (if installed)
sudo dpkg -r gpumode

# Install new package
sudo dpkg -i gpumode_1.02_all.deb
```

---

## Verify Installation

```bash
# Check package is installed
dpkg -s gpumode

# Check version
gpumode --version 2>/dev/null || grep VERSION /usr/bin/gpumode
```

---

## Clean Up Build Artifacts

```bash
rm -rf debian/
rm -f gpumode_*.deb
```
