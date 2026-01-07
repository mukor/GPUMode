#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
gi.require_version('Notify', '0.7')
gi.require_version('UPowerGlib', '1.0')
from gi.repository import Gtk, AppIndicator3, Notify, GLib, UPowerGlib
import subprocess
import threading
import os
import sys
import fcntl
import logging
import json
from pathlib import Path

VERSION = "1.02"
LOCK_FILE = "/tmp/gpumode.lock"
LOG_DIR = Path.home() / ".local/share/gpumode"
LOG_FILE = LOG_DIR / "gpumode.log"
SETTINGS_FILE = LOG_DIR / "settings.conf"
STATE_FILE = LOG_DIR / "state.json"

# Power consumption indicators
POWER_INDICATORS = {
    'integrated': '⚡',
    'hybrid': '⚡⚡',
    'nvidia': '⚡⚡⚡'
}

# Icon names for each mode (used in tray)
MODE_ICONS = {
    'integrated': 'drive-harddisk-solidstate-symbolic',
    'hybrid': 'video-single-display-symbolic',
    'nvidia': 'video-display-symbolic'
}


class GPUIndicator:
    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=LOG_FILE,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        logging.info("GPUMode started")
        
        if not self.check_envycontrol():
            self.show_error_and_exit("envycontrol not found", 
                                    "Please install envycontrol:\ninstall envycontrol\nfrom https://github.com/bayasdev/envycontrol, releases/assets")
            return
        
        Notify.init("GPUMode")
        
        self.indicator = AppIndicator3.Indicator.new(
            "gpumode",
            "video-display",
            AppIndicator3.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        
        self.switching = False

        # State tracking for reboot indicator
        self.boot_mode = self.get_current_mode()  # Actual GPU from glxinfo
        self.target_mode = None  # Pending mode (differs from boot_mode if reboot needed)
        self.load_state()  # Load target_mode and check for reboot

        self.update_icon()

        self.power_prompts_enabled = self.load_power_prompts_setting()

        self.indicator.set_menu(self.build_menu())

        self.upower_client = UPowerGlib.Client.new()
        self.upower_client.connect('notify::on-battery', self.on_power_changed)
        self.last_power_state = self.upower_client.get_on_battery()

        logging.info(f"Boot GPU mode: {self.boot_mode}")
        logging.info(f"Target GPU mode: {self.target_mode}")
        logging.info(f"Initial power state: {'battery' if self.last_power_state else 'AC'}")
        logging.info(f"Power prompts enabled: {self.power_prompts_enabled}")
        
        GLib.timeout_add(2000, self.check_startup_mismatch)

    def check_startup_mismatch(self):
        """Check if GPU mode mismatches power state at startup"""
        if not self.power_prompts_enabled:
            logging.info("Power prompts disabled, skipping startup check")
            return False

        on_battery = self.upower_client.get_on_battery()

        if on_battery and self.boot_mode in ['nvidia', 'hybrid']:
            logging.info("Startup mismatch: On battery but using NVIDIA/Hybrid")
            self.prompt_switch_on_battery()
        elif not on_battery and self.boot_mode == 'integrated':
            logging.info("Startup mismatch: On AC but using Integrated")
            self.prompt_switch_on_ac()
        else:
            logging.info("No startup mismatch detected")

        return False

    def load_power_prompts_setting(self):
        """Load power prompts enabled setting from file"""
        if not SETTINGS_FILE.exists():
            return True
        
        try:
            content = SETTINGS_FILE.read_text().strip()
            return content == "enabled"
        except:
            return True

    def save_power_prompts_setting(self, enabled):
        """Save power prompts enabled setting to file"""
        try:
            SETTINGS_FILE.write_text("enabled" if enabled else "disabled")
            logging.info(f"Power prompts {'enabled' if enabled else 'disabled'}")
        except Exception as e:
            logging.error(f"Failed to save power prompts setting: {e}")

    def get_system_boot_time(self):
        """Get system boot time from /proc/stat"""
        try:
            with open('/proc/stat', 'r') as f:
                for line in f:
                    if line.startswith('btime'):
                        return int(line.split()[1])
        except Exception as e:
            logging.error(f"Failed to get boot time: {e}")
        return None

    def load_state(self):
        """Load target_mode from state file, clearing if reboot occurred"""
        if not STATE_FILE.exists():
            self.target_mode = None
            return

        try:
            state = json.loads(STATE_FILE.read_text())
            saved_boot_time = state.get('boot_time')
            saved_target_mode = state.get('target_mode')
            current_boot_time = self.get_system_boot_time()

            # If boot time changed, system rebooted - clear pending state
            if saved_boot_time != current_boot_time:
                logging.info("Reboot detected, clearing pending state")
                self.target_mode = None
                self.save_state()
                return

            # If target_mode matches boot_mode, no pending change
            if saved_target_mode == self.boot_mode:
                logging.info("Target mode matches boot mode, no pending change")
                self.target_mode = None
                self.save_state()
                return

            self.target_mode = saved_target_mode
            logging.info(f"Loaded pending target mode: {self.target_mode}")

        except Exception as e:
            logging.error(f"Failed to load state: {e}")
            self.target_mode = None

    def save_state(self):
        """Save target_mode and boot time to state file"""
        try:
            state = {
                'boot_time': self.get_system_boot_time(),
                'target_mode': self.target_mode
            }
            STATE_FILE.write_text(json.dumps(state))
            logging.info(f"Saved state: target_mode={self.target_mode}")
        except Exception as e:
            logging.error(f"Failed to save state: {e}")

    def has_pending_change(self):
        """Check if there's a pending GPU mode change requiring reboot"""
        return self.target_mode is not None and self.target_mode != self.boot_mode

    def set_target_mode(self, mode):
        """Set target mode and save state"""
        if mode == self.boot_mode:
            # Switching back to boot mode - no reboot needed
            self.target_mode = None
        else:
            self.target_mode = mode
        self.save_state()

    def toggle_power_prompts(self, widget):
        """Toggle power change prompts on/off"""
        self.power_prompts_enabled = widget.get_active()
        self.save_power_prompts_setting(self.power_prompts_enabled)
        
        notification = Notify.Notification.new(
            "Power Prompts " + ("Enabled" if self.power_prompts_enabled else "Disabled"),
            "You will " + ("now" if self.power_prompts_enabled else "no longer") + " be prompted to switch GPU when AC power changes.",
            "dialog-information"
        )
        notification.show()

    def on_power_changed(self, client, pspec):
        """Handle AC/battery power changes"""
        on_battery = client.get_on_battery()
        
        if on_battery == self.last_power_state:
            return
        
        logging.info(f"Power state changed: {'AC->Battery' if on_battery else 'Battery->AC'}")
        self.last_power_state = on_battery
        
        if not self.power_prompts_enabled:
            logging.info("Power prompts disabled, skipping")
            return
        
        if on_battery:
            self.prompt_switch_on_battery()
        else:
            self.prompt_switch_on_ac()

    def prompt_switch_on_battery(self):
        """Prompt to switch to integrated when on battery"""
        if self.boot_mode == "integrated":
            logging.info("Already on integrated, skipping battery prompt")
            return
        
        logging.info("Prompting switch to integrated on battery")
        
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Switch to Integrated GPU?"
        )
        dialog.format_secondary_text(
            "You're now on battery power.\n\n"
            "Would you like to switch to Integrated GPU mode for better battery life?\n\n"
            "This will require a reboot."
        )
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            logging.info("User accepted battery switch prompt")
            self.switch_and_reboot('integrated')
        else:
            logging.info("User declined battery switch prompt")

    def prompt_switch_on_ac(self):
        """Prompt to switch to Hybrid when on AC"""
        if self.boot_mode == "hybrid":
            logging.info("Already on Hybrid, skipping AC prompt")
            return
        
        logging.info("Prompting switch to Hybrid on AC")
        
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Switch to Hybrid Mode?"
        )
        dialog.format_secondary_text(
            "You're now on AC power.\n\n"
            "Would you like to switch to Hybrid mode for balanced performance?\n\n"
            "This will require a reboot."
        )
        
        response = dialog.run()
        dialog.destroy()
        
        if response == Gtk.ResponseType.YES:
            logging.info("User accepted AC switch prompt")
            self.switch_and_reboot('hybrid')
        else:
            logging.info("User declined AC switch prompt")

    def switch_and_reboot(self, mode):
        """Switch GPU mode and reboot"""
        self.switching = True
        self.update_icon()
        self.indicator.set_menu(self.build_menu())

        notification = Notify.Notification.new(
            "GPUMode",
            f"Switching to {mode} mode and rebooting...",
            "emblem-synchronizing"
        )
        notification.show()

        def switch_reboot_thread():
            try:
                cmd = ['pkexec', 'envycontrol', '-s', mode]
                if mode == 'hybrid':
                    cmd.extend(['--rtd3', '3'])

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )

                if result.returncode == 0:
                    logging.info(f"Switched to {mode}, initiating reboot")
                    GLib.idle_add(self.set_target_mode, mode)
                    # Reboot requires privileges - use pkexec
                    reboot_result = subprocess.run(['pkexec', 'systemctl', 'reboot'], timeout=60)
                    if reboot_result.returncode != 0:
                        # Reboot cancelled/failed - update UI to show pending state
                        logging.info("Reboot cancelled or failed, showing pending state")
                        GLib.idle_add(self.switch_complete, mode, True, None)
                else:
                    logging.error(f"Failed to switch: {result.stderr}")
                    GLib.idle_add(self.switch_complete, mode, False, result.stderr)

            except Exception as e:
                logging.error(f"Switch and reboot error: {e}")
                GLib.idle_add(self.switch_complete, mode, False, str(e))

        thread = threading.Thread(target=switch_reboot_thread)
        thread.daemon = True
        thread.start()

    def check_envycontrol(self):
        """Check if envycontrol is installed"""
        try:
            result = subprocess.run(['which', 'envycontrol'], 
                                  capture_output=True, timeout=2)
            return result.returncode == 0
        except:
            return False

    def show_error_and_exit(self, title, message):
        """Show error dialog and exit"""
        logging.error(f"{title}: {message}")
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
        sys.exit(1)

    def get_current_mode(self):
        """Query current GPU mode - checks glxinfo first to detect BIOS-set NVIDIA mode"""
        try:
            # Check glxinfo OpenGL renderer line specifically
            glx_result = subprocess.run(['sh', '-c', 'glxinfo | grep "OpenGL renderer"'], 
                                      capture_output=True, text=True, timeout=2)
            if glx_result.returncode == 0:
                renderer = glx_result.stdout.strip()
                logging.info(f"glxinfo renderer string: {renderer}")
                
                # Check the actual OpenGL renderer string
                if 'NVIDIA' in renderer and 'AMD' not in renderer:
                    logging.info("Detected NVIDIA-only mode via glxinfo (BIOS-set)")
                    return "nvidia"
                elif 'AMD' in renderer and 'NVIDIA' not in renderer:
                    # AMD only in glxinfo - query envycontrol for actual mode
                    # (hybrid mode uses AMD by default, NVIDIA on-demand)
                    try:
                        result = subprocess.run(['envycontrol', '--query'],
                                              capture_output=True, text=True, timeout=2)
                        if result.returncode == 0:
                            mode = result.stdout.strip().lower()
                            logging.info(f"Queried GPU mode from envycontrol: {mode}")
                            return mode
                    except:
                        pass
                    logging.info("Detected integrated mode via glxinfo (AMD only)")
                    return "integrated"
                elif 'AMD' in renderer and 'NVIDIA' in renderer:
                    # Both GPUs in renderer string - likely hybrid
                    logging.info("Detected hybrid mode via glxinfo")
                    return "hybrid"
        except Exception as e:
            logging.error(f"Failed to query GPU mode with glxinfo: {e}")
            
            # Final fallback to envycontrol only
            try:
                result = subprocess.run(['envycontrol', '--query'], 
                                      capture_output=True, text=True, timeout=2)
                if result.returncode == 0:
                    mode = result.stdout.strip().lower()
                    logging.info(f"Queried GPU mode from envycontrol (fallback): {mode}")
                    return mode
            except:
                pass
        
        return "unknown"

    def update_icon(self):
        """Update tray icon based on current state"""
        if self.switching:
            self.indicator.set_icon("emblem-synchronizing-symbolic")
        elif self.boot_mode in MODE_ICONS:
            self.indicator.set_icon(MODE_ICONS[self.boot_mode])
        else:
            self.indicator.set_icon("dialog-question-symbolic")

    def refresh_mode(self):
        """Refresh menu state (boot_mode is fixed at startup, only changes after reboot)"""
        # boot_mode is intentionally NOT refreshed here - it represents the actual
        # GPU mode at boot time. envycontrol config may change before reboot,
        # but the actual GPU doesn't change until reboot.
        pass

    def build_menu(self):
        """Build the indicator menu"""
        # Reload setting fresh each time menu is built
        self.power_prompts_enabled = self.load_power_prompts_setting()

        menu = Gtk.Menu()

        # Status line
        if self.switching:
            status = Gtk.MenuItem(label='━━━ SWITCHING... ━━━')
        else:
            status = Gtk.MenuItem(label=f'ACTIVE MODE: {self.boot_mode.upper()}')
        status.set_sensitive(False)
        menu.append(status)

        menu.append(Gtk.SeparatorMenuItem())

        # If in NVIDIA mode (BIOS-set), show switchable modes as disabled
        if self.boot_mode == 'nvidia':
            # Integrated - disabled in NVIDIA mode
            integrated = Gtk.CheckMenuItem(label=f'Integrated {POWER_INDICATORS["integrated"]}')
            integrated.set_active(False)
            integrated.set_sensitive(False)
            menu.append(integrated)

            # Hybrid - disabled in NVIDIA mode
            hybrid = Gtk.CheckMenuItem(label=f'Hybrid {POWER_INDICATORS["hybrid"]}')
            hybrid.set_active(False)
            hybrid.set_sensitive(False)
            menu.append(hybrid)

            # Info message at bottom of switchable section
            bios_msg = Gtk.MenuItem(label='    Set BIOS to Hybrid (F2) to enable switching')
            bios_msg.set_sensitive(False)
            menu.append(bios_msg)

            menu.append(Gtk.SeparatorMenuItem())

            # NVIDIA - active and white text (sensitive=True but not clickable)
            nvidia = Gtk.CheckMenuItem(label=f'NVIDIA {POWER_INDICATORS["nvidia"]}')
            nvidia.set_active(True)
            # Keep sensitive for white text, but don't connect a handler
            menu.append(nvidia)
        else:
            # Normal mode - switchable between integrated and hybrid
            # User's selection is target_mode if set, otherwise boot_mode
            selected_mode = self.target_mode if self.target_mode else self.boot_mode

            # Integrated
            integrated_label = f'Integrated {POWER_INDICATORS["integrated"]}'
            if selected_mode == 'integrated' and self.boot_mode != 'integrated':
                integrated_label += ' (ON REBOOT)'
            integrated = Gtk.CheckMenuItem(label=integrated_label)
            integrated.set_active(selected_mode == 'integrated')
            integrated.connect('toggled', self.on_integrated_toggled)
            if self.switching:
                integrated.set_sensitive(False)
            menu.append(integrated)

            # Hybrid
            hybrid_label = f'Hybrid {POWER_INDICATORS["hybrid"]}'
            if selected_mode == 'hybrid' and self.boot_mode != 'hybrid':
                hybrid_label += ' (ON REBOOT)'
            hybrid = Gtk.CheckMenuItem(label=hybrid_label)
            hybrid.set_active(selected_mode == 'hybrid')
            hybrid.connect('toggled', self.on_hybrid_toggled)
            if self.switching:
                hybrid.set_sensitive(False)
            menu.append(hybrid)

            menu.append(Gtk.SeparatorMenuItem())

            # NVIDIA - info only, not switchable from software
            nvidia = Gtk.MenuItem(label=f'NVIDIA {POWER_INDICATORS["nvidia"]}')
            nvidia.set_sensitive(False)
            menu.append(nvidia)

            nvidia_info = Gtk.MenuItem(label='    Set in BIOS (F2)')
            nvidia_info.set_sensitive(False)
            menu.append(nvidia_info)

        menu.append(Gtk.SeparatorMenuItem())

        power_prompts_item = Gtk.CheckMenuItem(label='Prompt on Power Change')
        power_prompts_item.set_active(self.power_prompts_enabled)
        power_prompts_item.connect('toggled', self.toggle_power_prompts)
        if self.switching or self.boot_mode == 'nvidia':
            power_prompts_item.set_sensitive(False)
        menu.append(power_prompts_item)

        menu.append(Gtk.SeparatorMenuItem())

        about_item = Gtk.MenuItem(label='About')
        about_item.connect('activate', self.show_about)
        menu.append(about_item)

        quit_item = Gtk.MenuItem(label='Quit')
        quit_item.connect('activate', Gtk.main_quit)
        if self.switching:
            quit_item.set_sensitive(False)
        menu.append(quit_item)

        menu.show_all()
        return menu

    def on_integrated_toggled(self, widget):
        """Handle integrated mode toggle"""
        selected_mode = self.target_mode if self.target_mode else self.boot_mode
        if widget.get_active() and selected_mode != 'integrated':
            self.switch_gpu('integrated')
        elif not widget.get_active() and selected_mode == 'integrated':
            # User unchecked the active mode - recheck it
            widget.set_active(True)

    def on_hybrid_toggled(self, widget):
        """Handle hybrid mode toggle"""
        selected_mode = self.target_mode if self.target_mode else self.boot_mode
        if widget.get_active() and selected_mode != 'hybrid':
            self.switch_gpu('hybrid')
        elif not widget.get_active() and selected_mode == 'hybrid':
            # User unchecked the active mode - recheck it
            widget.set_active(True)

    def switch_gpu(self, mode):
        """Switch GPU mode"""
        if self.switching:
            return
        
        logging.info(f"Switching to {mode} mode")
        self.switching = True
        self.update_icon()
        self.indicator.set_menu(self.build_menu())
        
        notification = Notify.Notification.new(
            "GPUMode",
            f"Switching to {mode} mode...",
            "emblem-synchronizing"
        )
        notification.show()
        
        def switch_thread():
            try:
                cmd = ['pkexec', 'envycontrol', '-s', mode]
                if mode == 'hybrid':
                    cmd.extend(['--rtd3', '3'])
                
                result = subprocess.run(
                    cmd,
                    capture_output=True, 
                    text=True, 
                    timeout=60
                )
                
                if result.returncode == 126 or result.returncode == 127:
                    GLib.idle_add(self.switch_cancelled)
                elif result.returncode == 0:
                    GLib.idle_add(self.switch_complete, mode, True, None)
                else:
                    GLib.idle_add(self.switch_complete, mode, False, result.stderr)
                    
            except subprocess.TimeoutExpired:
                logging.error("Switch command timed out")
                GLib.idle_add(self.switch_complete, mode, False, "Command timed out")
            except Exception as e:
                logging.error(f"Switch error: {e}")
                GLib.idle_add(self.switch_complete, mode, False, str(e))
        
        thread = threading.Thread(target=switch_thread)
        thread.daemon = True
        thread.start()

    def switch_cancelled(self):
        """Handle user cancelling pkexec password prompt"""
        logging.info("User cancelled authentication")
        self.switching = False
        self.update_icon()
        self.indicator.set_menu(self.build_menu())
        
        notification = Notify.Notification.new(
            "Switch Cancelled",
            "Authentication was cancelled. GPU mode unchanged.",
            "dialog-information"
        )
        notification.show()
        return False

    def switch_complete(self, mode, success, error_msg):
        """Handle switch completion"""
        self.switching = False

        if success:
            logging.info(f"Successfully switched to {mode}")
            self.set_target_mode(mode)
            self.update_icon()
            self.indicator.set_menu(self.build_menu())

            if self.has_pending_change():
                notification = Notify.Notification.new(
                    "✓ GPU Mode Changed",
                    f"⚠️ Reboot to finish the switch to {mode.upper()} mode.",
                    "dialog-warning"
                )
                notification.set_urgency(Notify.Urgency.CRITICAL)
                notification.set_timeout(10000)
            else:
                # Switched back to boot mode - no reboot needed
                notification = Notify.Notification.new(
                    "✓ GPU Mode Restored",
                    f"Restored to {mode.upper()} mode. No reboot required.",
                    "dialog-information"
                )
            notification.show()
        else:
            logging.error(f"Failed to switch to {mode}: {error_msg}")
            self.update_icon()
            self.indicator.set_menu(self.build_menu())

            notification = Notify.Notification.new(
                "✗ GPU Switch Failed",
                f"Error: {error_msg if error_msg else 'Command failed'}",
                "dialog-error"
            )
            notification.show()

        return False

    def show_about(self, _):
        """Show about dialog"""
        dialog = Gtk.AboutDialog()
        dialog.set_program_name("GPUMode")
        dialog.set_version(VERSION)
        dialog.set_comments("Automatic GPU mode switching for laptops with NVIDIA graphics.\n\nNOTE: NVIDIA-only mode must be set in BIOS (F2).")
        dialog.set_website("https://github.com/FrameworkComputer/GPUMode")
        dialog.set_website_label("GPUMode on GitHub")
        dialog.set_logo_icon_name("video-display")
        dialog.run()
        dialog.destroy()

def single_instance():
    """Ensure only one instance is running"""
    try:
        lock_file = open(LOCK_FILE, 'w')
        fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except IOError:
        return False

if __name__ == "__main__":
    if not single_instance():
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="GPUMode is already running"
        )
        dialog.format_secondary_text("Check your system tray for the GPUMode icon.")
        dialog.run()
        dialog.destroy()
        sys.exit(0)
    
    GPUIndicator()
    Gtk.main()
