# GPUMode.py Changes Analysis

This is a summary of the changes made agains HEAD: `6b0523e`. In general, I wanted to clean up the UI to make it more intuitve. As part of that there were some state management changes that had to be made.

---

## Summary

**Version bump:** 1.01 → 1.02

**Overall scope:** Major refactor of state management to properly track pending GPU mode changes requiring reboot, plus UI improvements with power indicators and checkbox-style menu items.

---

## Changes Made

### 1. Added State Persistence System

**Files/Lines:** Lines 14, 21-22, 65-68, 125-192

**What changed:**
- Added `json` import
- Added `STATE_FILE = LOG_DIR / "state.json"` constant
- Replaced single `self.current_mode` with dual tracking:
  - `self.boot_mode` - actual GPU mode detected at startup (never changes until reboot)
  - `self.target_mode` - pending mode if different from boot_mode

**New methods:**
- `get_system_boot_time()` - reads btime from `/proc/stat`
- `load_state()` - loads persisted target_mode, clears if reboot detected
- `save_state()` - persists target_mode + boot_time to JSON
- `has_pending_change()` - returns True if target_mode differs from boot_mode
- `set_target_mode()` - sets target and saves state

**Why:** Previously, the UI would show the *configured* mode as active immediately after switching, even though the actual GPU doesn't change until reboot. This confused users into thinking the switch had taken effect.

**⚠️ POTENTIAL ISSUE:** JSON state file could become corrupt if write is interrupted. No error recovery beyond logging. Consider atomic write (write to temp, rename).

---

### 2. Added Power Consumption Indicators

**Files/Lines:** Lines 24-29

**What changed:**
```python
POWER_INDICATORS = {
    'integrated': '⚡',
    'hybrid': '⚡⚡',
    'nvidia': '⚡⚡⚡'
}
```

Menu labels now include these indicators (e.g., "Integrated ⚡").

**Why:** Visual hint about relative power consumption of each mode.

---

### 3. Added Mode Icons Dictionary

**Files/Lines:** Lines 31-36

**What changed:**
```python
MODE_ICONS = {
    'integrated': 'drive-harddisk-solidstate-symbolic',
    'hybrid': 'video-single-display-symbolic',
    'nvidia': 'video-display-symbolic'
}
```

Replaces inline icon selection in `update_icon()`.

**Why:** Centralizes icon mapping, easier to maintain.

---

### 4. Changed Menu Items to CheckMenuItems

**Files/Lines:** Lines 462-482 (build_menu)

**What changed:**
- GPU mode options changed from `Gtk.MenuItem` to `Gtk.CheckMenuItem`
- Uses `set_active()` to show checkmark on current/pending mode
- Removed `switch_integrated()` and `switch_hybrid()` wrapper methods
- Added `on_integrated_toggled()` and `on_hybrid_toggled()` handlers

**Why:** Checkbox UI is more intuitive for mutually exclusive mode selection.

**⚠️ POTENTIAL ISSUE:** `CheckMenuItem` `toggled` signal fires both when checking AND unchecking. The handlers must guard against recursive/unwanted toggles. Current code does handle this but it's fragile:
```python
def on_integrated_toggled(self, widget):
    if widget.get_active() and selected_mode != 'integrated':
        self.switch_gpu('integrated')
    elif not widget.get_active() and selected_mode == 'integrated':
        widget.set_active(True)  # Re-check if user tried to uncheck active
```

---

### 5. Added "(ON REBOOT)" Label Suffix

**Files/Lines:** Lines 463-466, 473-476

**What changed:**
```python
if selected_mode == 'integrated' and self.boot_mode != 'integrated':
    integrated_label += ' (ON REBOOT)'
```

**Why:** Makes it clear that the selected mode won't take effect until reboot.

---

### 6. Changed Menu Header Format

**Files/Lines:** Line 425

**What changed:**
- Old: `━━━ Current: {mode.upper()} ━━━`
- New: `ACTIVE MODE: {mode.upper()}`

**Why:** Cleaner, less decorative.

---

### 7. Changed RTD3 Parameter Value

**Files/Lines:** Lines 298, 558

**What changed:**
- Old: `cmd.extend(['--rtd3', '2'])`
- New: `cmd.extend(['--rtd3', '3'])`

**Why:** RTD3 level 3 is more aggressive power saving for the NVIDIA GPU in hybrid mode. Framework laptops with discrete GPUs are modern hardware that fully supports RTD3 level 3, so this is the appropriate setting for better battery life in hybrid mode.

---

### 8. Changed Reboot Command to Use pkexec

**Files/Lines:** Lines 310-315

**What changed:**
- Old: `subprocess.run(['systemctl', 'reboot'], timeout=5)`
- New: `subprocess.run(['pkexec', 'systemctl', 'reboot'], timeout=60)`

Also added handling for reboot cancellation:
```python
if reboot_result.returncode != 0:
    logging.info("Reboot cancelled or failed, showing pending state")
    GLib.idle_add(self.switch_complete, mode, True, None)
```

**Why:** `systemctl reboot` requires root. Using pkexec prompts for authentication. If user cancels, UI now correctly shows pending state instead of hanging.

**⚠️ POTENTIAL ISSUE:** User now gets TWO pkexec prompts when using switch_and_reboot: one for envycontrol, one for reboot. This is slightly annoying UX but necessary for security.

---

### 9. Updated switch_complete() Logic

**Files/Lines:** Lines 600-638

**What changed:**
- Now calls `self.set_target_mode(mode)` to persist state
- Different notification based on `has_pending_change()`:
  - Pending change: "Reboot to finish the switch to MODE mode."
  - No pending (restored to boot mode): "Restored to MODE mode. No reboot required."

**Why:** Better user feedback. If user switches back to boot mode, no reboot is needed.

---

### 10. Gutted refresh_mode() Method

**Files/Lines:** Lines 407-412

**What changed:**
```python
def refresh_mode(self):
    """Refresh menu state (boot_mode is fixed at startup...)"""
    # boot_mode is intentionally NOT refreshed here...
    pass
```

Also removed from menu's 'show' signal connection.

**Why:** boot_mode should NEVER change during runtime - it represents actual GPU state at boot. Refreshing it would defeat the purpose of the new state tracking.

**⚠️ POTENTIAL ISSUE:** Method is now a no-op but still exists. Could confuse future maintainers. Consider removing entirely or renaming to clarify intent.

---

### 11. Changed CheckMenuItem Signal for Power Prompts

**Files/Lines:** Line 499

**What changed:**
- Old: `power_prompts_item.connect('activate', self.toggle_power_prompts)`
- New: `power_prompts_item.connect('toggled', self.toggle_power_prompts)`

**Why:** `toggled` is the correct signal for CheckMenuItem state changes.

---

### 12. Menu Structure Changes (NVIDIA mode)

**Files/Lines:** Lines 432-456

**What changed:**
- Removed "⚠ NVIDIA Mode Active" warning line (redundant with header)
- Moved "Set BIOS to Hybrid (F2)..." message to after Integrated/Hybrid options
- NVIDIA CheckMenuItem kept sensitive (white text) but no handler connected
- Uses CheckMenuItem with `set_active(True)` for NVIDIA when in NVIDIA mode

**Why:** Less redundant, cleaner visual hierarchy.

---

### 13. Removed Separator Before About

**Files/Lines:** Line 504

**What changed:**
- Old: Had `Gtk.SeparatorMenuItem()` before Quit only
- New: Has `Gtk.SeparatorMenuItem()` before Power Prompts and before About

**Why:** Better visual grouping.

---

## Potential Issues Summary

| Issue | Severity | Description |
|-------|----------|-------------|
| JSON state corruption | Low | No atomic write for state.json |
| Double pkexec prompt | Low | UX annoyance in switch_and_reboot flow |
| Empty refresh_mode() | Low | Dead code, could confuse maintainers |
| CheckMenuItem toggle guards | Low | Fragile re-check logic if user unchecks active mode |

---

## Files Changed

- `GPUMode.py` - All changes above

## New Dependencies

- None (json is stdlib)

## New Files Created at Runtime

- `~/.local/share/gpumode/state.json` - Persists target_mode and boot_time
