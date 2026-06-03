# GPUMode Roadmap

## Completed

### Add mesa-utils dependency
- **Status:** Done
- **File:** `.github/workflows/build-packages.yml`
- **Change:** Added `mesa-utils` to package dependencies (provides `glxinfo` for GPU detection)

---

### Fix misleading "ACTIVE" indicator after GPU switch
- **Status:** Done (v1.10)
- **File:** `GPUMode.py`

**Problem solved:**
When a user switches GPU modes, the UI now correctly shows the actual running mode (boot_mode) as checked, and appends "(ON REBOOT)" to the pending mode when a reboot is required.

**Implementation:**
- Added `boot_mode` and `target_mode` state tracking
- State persisted to `~/.local/share/gpumode/state.json`
- Reboot detection using system boot time from `/proc/stat`
- Switching back to boot mode clears pending state (no reboot needed)
- Uses `Gtk.CheckMenuItem` for GPU modes

**Decision:** Use "(ON REBOOT)" for pending label text.

---

### Add power consumption indicators to menu options
- **Status:** Done (v1.10)
- **File:** `GPUMode.py`

**Implementation:**
- Added lightning bolt indicators to menu labels:
  - Integrated: ⚡ (lowest power)
  - Hybrid: ⚡⚡ (balanced)
  - NVIDIA: ⚡⚡⚡ (highest power)

**Decisions:**
- Use ⚡ symbol
- Do not include in tray tooltip

---

### Add status icons to menu items
- **Status:** Partially done (v1.10)
- **File:** `GPUMode.py`

**Implementation:**
- Corrected tray icon mapping to match intended design:
  - Integrated: `drive-harddisk-solidstate-symbolic`
  - Hybrid: `video-display-symbolic`
  - NVIDIA: `video-single-display-symbolic`
- Menu icons not added (would require deprecated ImageMenuItem or complex custom widgets)

---

## Planned

### UI refinements for NVIDIA mode menu

**Goal:** Clean up redundancy and improve visual consistency when in NVIDIA mode.

**Current behavior (NVIDIA mode):**
```
━━━ Current: NVIDIA ━━━
─────────────────────────
⚠ NVIDIA Mode Active              <- Redundant
Set BIOS to Hybrid (F2)...        <- Should move down
─────────────────────────
Integrated ⚡                      <- No icon
Hybrid ⚡⚡                         <- No icon
─────────────────────────
✓ NVIDIA ⚡⚡⚡ (gray text)         <- Should be white
    Set in BIOS (F2)              <- Redundant when active
─────────────────────────
```

**Proposed behavior (NVIDIA mode):**
```
━━━ Current: NVIDIA ━━━
─────────────────────────
💾 Integrated ⚡
🖵 Hybrid ⚡⚡
    Set BIOS to Hybrid (F2) to enable switching
─────────────────────────
🖥 ✓ NVIDIA ⚡⚡⚡ (white text)
─────────────────────────
```

**Changes:**
1. Remove "⚠ NVIDIA Mode Active" warning - redundant with "Current: NVIDIA" header
2. Move "Set BIOS to Hybrid (F2) to enable switching" to bottom of Integrated/Hybrid section
3. Make NVIDIA menu item white text (sensitive) when in NVIDIA mode, not gray
4. Remove "Set in BIOS (F2)" sub-label when NVIDIA is active (already obvious)
5. Add tray icons next to each GPU mode option:
   - Integrated: `drive-harddisk-solidstate-symbolic`
   - Hybrid: `video-display-symbolic`
   - NVIDIA: `video-single-display-symbolic`

**Implementation:**
- Modify `build_menu()` in `GPUMode.py`
- Use `Gtk.Box` with `Gtk.Image` + `Gtk.Label` for icon+text menu items
- Or use Unicode symbols as icon placeholders if GTK icons prove difficult

**Files to modify:**
- `GPUMode.py`

---

### Add reboot action buttons to mode switch notification

**Goal:** When user switches GPU mode and gets the reboot notification, provide "Reboot Now" and "Later" buttons instead of just a passive notification.

**Current behavior:**
```
┌─────────────────────────────────────┐
│ ✓ GPU Mode Changed                  │
│ ⚠️ Reboot to finish the switch to   │
│ HYBRID mode.                        │
└─────────────────────────────────────┘
```

**Proposed behavior:**
```
┌─────────────────────────────────────┐
│ ✓ GPU Mode Changed                  │
│ ⚠️ Reboot to finish the switch to   │
│ HYBRID mode.                        │
│                                     │
│ [Reboot Now]  [Later]               │
└─────────────────────────────────────┘
```

**Approach:**
Use libnotify's `add_action()` method to attach interactive buttons to the notification:

```python
notification.add_action("reboot_now", "Reboot Now", self.on_reboot_action, None)
notification.add_action("reboot_later", "Later", self.on_later_action, None)
```

**Caveats:**
1. Not all notification daemons support action buttons (GNOME's does, some minimal daemons don't)
2. Notification object must be kept alive while displayed - store as `self.pending_notification`
3. Must connect to `closed` signal to clean up reference when dismissed
4. Actions run in GLib main loop context

**Implementation plan:**
1. Add `self.pending_notification = None` instance variable in `__init__`
2. Create callback methods:
   - `on_reboot_action(notification, action, user_data)` - triggers `pkexec systemctl reboot`
   - `on_later_action(notification, action, user_data)` - just dismisses notification
   - `on_notification_closed(notification)` - cleans up `self.pending_notification`
3. Modify `switch_complete()` to:
   - Store notification in `self.pending_notification`
   - Add actions via `add_action()`
   - Connect `closed` signal
4. Handle case where notification daemon doesn't support actions (graceful fallback)

**Files to modify:**
- `GPUMode.py`

---

### Integrate envycontrol functionality directly

**Goal:** Bundle envycontrol functionality into GPUMode so users don't need to install it separately. This simplifies installation to a single package.

**Current situation:**
- GPUMode depends on envycontrol as an external tool
- Users must install envycontrol separately from https://github.com/bayasdev/envycontrol
- GPU switching calls `pkexec envycontrol -s <mode>`

**Investigation needed:**
1. Review envycontrol source to understand what it does:
   - Modifies kernel module blacklists
   - Configures udev rules for NVIDIA
   - Sets up Xorg/Wayland configuration
   - Manages RTD3 power management
2. Determine licensing compatibility (envycontrol is MIT licensed)
3. Evaluate whether to:
   - Vendor envycontrol source directly into GPUMode
   - Reimplement the core functionality in GPUMode.py
   - Bundle envycontrol as a package dependency (current approach)

**Potential benefits:**
- Single package install
- No external dependency management
- Tighter integration and error handling
- Could customize behavior for Framework laptops specifically

**Potential risks:**
- Maintenance burden of tracking envycontrol updates
- GPU switching is complex and hardware-specific
- May break on future kernel/driver updates

**Files to modify:**
- `GPUMode.py`
- `.github/workflows/build-packages.yml` (remove envycontrol dependency)
- `debian/control` template