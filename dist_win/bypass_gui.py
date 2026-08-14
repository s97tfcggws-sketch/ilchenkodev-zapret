#!/usr/bin/env python3
import os
import sys
import json
import glob
import time
import queue
import shlex
import socket
import platform
import threading
import subprocess
import pystray
from PIL import Image, ImageDraw

# ── Windows: hide console window and remove from taskbar immediately ──────────
# Must run before any window is created. PyInstaller --noconsole already
# suppresses the console; this is a belt-and-suspenders safeguard.
if sys.platform == 'win32':
    try:
        import ctypes
        # SW_HIDE = 0 — hide the console window if it somehow appeared
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


# Global State
OS_TYPE = platform.system()
bypass_process = None
bypass_running = False
log_buffer = []
log_lock = threading.Lock()
global_icon = None

# Resolve path relative to application execution directory
possible_dirs = []
if getattr(sys, 'frozen', False):
    if hasattr(sys, '_MEIPASS'):
        possible_dirs.append(sys._MEIPASS)
    exec_dir = os.path.dirname(sys.executable)
    possible_dirs.append(exec_dir)
    possible_dirs.append(os.path.abspath(os.path.join(exec_dir, "..")))
    possible_dirs.append(os.path.abspath(os.path.join(exec_dir, "..", "..")))
    possible_dirs.append(os.path.abspath(os.path.join(exec_dir, "..", "..", "..")))
    possible_dirs.append(os.path.abspath(os.path.join(exec_dir, "..", "..", "..", "..")))
else:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    possible_dirs.append(script_dir)
    possible_dirs.append(os.path.abspath(os.path.join(script_dir, "..")))
    possible_dirs.append(os.path.abspath(os.path.join(script_dir, "..", "..")))

possible_dirs.append(os.getcwd())
possible_dirs.append(os.path.abspath(os.path.join(os.getcwd(), "..")))

BASE_DIR = possible_dirs[0]
for d in possible_dirs:
    target_check = os.path.join("bin", "mac", "tpws") if OS_TYPE == "Darwin" else (os.path.join("bin", "winws.exe") if OS_TYPE == "Windows" else os.path.join("bin", "linux", "tpws"))
    if os.path.exists(os.path.join(d, target_check)):
        BASE_DIR = d
        break

# Configuration defaults
socks_port = "10800"
sys_proxy = True
custom_args = ""
selected_strategy = ""

# Paths for logs and settings
def get_user_data_dir():
    if OS_TYPE == "Windows":
        appdata = os.getenv("APPDATA")
        if appdata:
            path = os.path.join(appdata, "ILCHENKODEV-Bypass")
        else:
            path = os.path.join(os.path.expanduser("~"), ".ilchenkodev-bypass")
    elif OS_TYPE == "Darwin":
        path = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "ILCHENKODEV-Bypass")
    else:
        path = os.path.join(os.path.expanduser("~"), ".config", "ilchenkodev-bypass")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path

USER_DATA_DIR = get_user_data_dir()
LOG_FILE_PATH = os.path.join(USER_DATA_DIR, "bypass.log")
CONFIG_PATH = os.path.join(USER_DATA_DIR, "config.json")

def init_defaults():
    global custom_args, socks_port, sys_proxy
    socks_port = "10800"
    sys_proxy = True
    if OS_TYPE == "Windows":
        custom_args = ""  # loaded dynamically from bat files
    else:
        custom_args = "--split-pos=midsld --disorder --hostlist=lists/list-google.txt --hostlist=lists/list-general.txt --hostlist-exclude=lists/list-exclude.txt"

init_defaults()

# Log logger helper
def append_log(text, source="stdout"):
    global log_buffer
    timestamp = time.strftime("[%Y-%m-%d %H:%M:%S]")
    log_line = f"{timestamp} [{source.upper()}] {text}\n"
    
    # Print to console
    print(log_line, end="")
    
    # Save to global buffer
    with log_lock:
        log_buffer.append({"time": timestamp, "text": text, "source": source})
        if len(log_buffer) > 1000:
            log_buffer.pop(0)
            
    # Append to log file
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass

# Clean output reader thread
def log_reader_thread(proc):
    global bypass_running
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        try:
            decoded = line.decode('utf-8', errors='ignore')
        except Exception:
            decoded = str(line)
        append_log(decoded.strip('\r\n'), "stdout")
        
    # Process exit cleanup
    proc.wait()
    with log_lock:
        global bypass_process
        if bypass_process == proc:
            bypass_running = False
            bypass_process = None
            append_log(">>> Bypass service stopped.", "system")
            if OS_TYPE == "Darwin" and sys_proxy:
                set_macos_proxy_state("off")
            update_tray_state()

# macOS proxy manager utility
def get_macos_network_services():
    services = []
    try:
        res = subprocess.run(["networksetup", "-listallnetworkservices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                line = line.strip()
                if line and not line.startswith("An asterisk") and not line.startswith("*"):
                    services.append(line)
    except Exception:
        pass
    return services if services else ["Wi-Fi"]

def set_macos_proxy_state(state, port="10800"):
    if OS_TYPE != "Darwin":
        return
    def run_proxy_setup():
        services = get_macos_network_services()
        append_log(f">>> Adjusting system SOCKS5 proxy to {state.upper()}...", "system")
        for svc in services:
            try:
                if state == "on":
                    append_log(f"Enabling SOCKS proxy on: {svc}", "system")
                    subprocess.run(["networksetup", "-setsocksfirewallproxy", svc, "127.0.0.1", port], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0)
                    subprocess.run(["networksetup", "-setsocksfirewallproxystate", svc, "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0)
                else:
                    append_log(f"Disabling SOCKS proxy on: {svc}", "system")
                    subprocess.run(["networksetup", "-setsocksfirewallproxystate", svc, "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0)
            except Exception as e:
                append_log(f"Failed to change proxy on {svc}: {e}", "error")
    
    t = threading.Thread(target=run_proxy_setup, daemon=True)
    t.start()

# Strategy loaders
def get_strategies():
    if OS_TYPE == "Windows":
        bat_files = glob.glob(os.path.join(BASE_DIR, "*.bat"))
        filtered_bats = [os.path.basename(f) for f in bat_files if os.path.basename(f) != "service.bat"]
        filtered_bats.sort()
        return filtered_bats if filtered_bats else ["No .bat files found"]
    else:
        return [
            "Midsld Split (Default - Best for YouTube/Discord)",
            "Midsld Alt (TLS Record + Midsld Split)",
            "General (Split Pos 1 + Disorder)",
            "General Alt (TLS Record + Split Pos 1)",
            "OOB Host (Out-of-band Host Split)",
            "OOB Host Alt (TLS Record + OOB Host)",
            "All Traffic (No Hostlist, Split Pos 1)",
            "All Traffic Alt (No Hostlist, TLS Record + Split)",
            "Custom Parameters"
        ]

def get_strategy_arguments(strategy):
    if OS_TYPE == "Windows":
        filepath = os.path.join(BASE_DIR, strategy)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                cmd_lines = []
                in_command = False
                for line in lines:
                    clean_line = line.strip()
                    if "winws.exe" in clean_line or in_command:
                        in_command = True
                        cmd_lines.append(clean_line.replace("^", "").strip())
                        if not line.endswith("^\n") and not line.endswith("^"):
                            break
                return " ".join(cmd_lines)
            except Exception as e:
                return f"Error loading bat: {e}"
        return ""
    else:
        if strategy.startswith("Midsld Split"):
            return "--split-pos=midsld --disorder --hostlist=lists/list-google.txt --hostlist=lists/list-general.txt --hostlist-exclude=lists/list-exclude.txt"
        elif strategy.startswith("Midsld Alt"):
            return "--tlsrec=1 --split-pos=midsld --disorder --hostlist=lists/list-google.txt --hostlist=lists/list-general.txt --hostlist-exclude=lists/list-exclude.txt"
        elif strategy.startswith("General (Split"):
            return "--split-pos=1 --disorder --hostlist=lists/list-google.txt --hostlist=lists/list-general.txt --hostlist-exclude=lists/list-exclude.txt"
        elif strategy.startswith("General Alt"):
            return "--tlsrec=1 --split-pos=1 --disorder --hostlist=lists/list-google.txt --hostlist=lists/list-general.txt --hostlist-exclude=lists/list-exclude.txt"
        elif strategy.startswith("OOB Host ("):
            return "--split-pos=host --oob --hostlist=lists/list-google.txt --hostlist=lists/list-general.txt --hostlist-exclude=lists/list-exclude.txt"
        elif strategy.startswith("OOB Host Alt"):
            return "--tlsrec=1 --split-pos=host --oob --hostlist=lists/list-google.txt --hostlist=lists/list-general.txt --hostlist-exclude=lists/list-exclude.txt"
        elif strategy.startswith("All Traffic ("):
            return "--split-pos=1 --disorder"
        elif strategy.startswith("All Traffic Alt"):
            return "--tlsrec=1 --split-pos=1 --disorder"
        else:
            return "--split-pos=1 --disorder"

# Core start and stop handlers
def start_bypass_service(port_val, sys_proxy_val, custom_args_val, strategy_val):
    global bypass_process, bypass_running, socks_port, sys_proxy, custom_args, selected_strategy
    
    if bypass_running:
        return True, "Already running"
        
    socks_port = port_val
    sys_proxy = sys_proxy_val
    custom_args = custom_args_val
    selected_strategy = strategy_val
    
    append_log(">>> Starting bypass service...", "system")
    
    # Pre-clean processes to avoid locks
    try:
        if OS_TYPE == "Windows":
            subprocess.run(["taskkill", "/f", "/im", "winws.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["killall", "tpws"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.3)
    except Exception:
        pass
        
    try:
        if OS_TYPE == "Windows":
            winws_path = os.path.join(BASE_DIR, "bin", "winws.exe")
            if not os.path.exists(winws_path):
                raise FileNotFoundError("Could not find bin/winws.exe in your workspace folder.")
            
            cmd_args_str = custom_args.strip()
            if not cmd_args_str:
                raise ValueError("No command string provided!")
            
            base_dir = BASE_DIR
            bin_dir = os.path.join(base_dir, "bin") + "\\"
            lists_dir = os.path.join(base_dir, "lists") + "\\"
            
            parsed_args = cmd_args_str
            if "winws.exe" in parsed_args:
                parsed_args = parsed_args.split("winws.exe", 1)[1]
            
            parsed_args = parsed_args.replace('start "zapret: %~n0" /min', "")
            parsed_args = parsed_args.replace('start /min', "")
            parsed_args = parsed_args.replace('"%BIN%winws.exe"', "")
            parsed_args = parsed_args.replace('%BIN%winws.exe', "")
            
            args_list = []
            try:
                safe_parsed = parsed_args.replace('\\', '\\\\')
                splitted = shlex.split(safe_parsed)
                args_list = [x.replace('\\\\', '\\') for x in splitted]
            except Exception:
                args_list = parsed_args.split()
            
            final_args = []
            for arg in args_list:
                if not arg.strip():
                    continue
                arg = arg.replace('%BIN%', bin_dir)
                arg = arg.replace('%LISTS%', lists_dir)
                arg = arg.replace('%GameFilterTCP%', "12")
                arg = arg.replace('%GameFilterUDP%', "12")
                arg = arg.replace('%~dp0', base_dir + "\\")
                final_args.append(arg)
            
            full_cmd = [os.path.abspath(winws_path)] + final_args
            append_log(f"Executing: {' '.join(full_cmd)}", "system")
            
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            bypass_process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                startupinfo=startupinfo,
                bufsize=0,
                cwd=BASE_DIR
            )
        else:
            tpws_bin = os.path.join(BASE_DIR, "bin", "mac" if OS_TYPE == "Darwin" else "linux", "tpws")
            if not os.path.exists(tpws_bin):
                tpws_bin = os.path.join(BASE_DIR, "bin", "mac", "tpws")
                
            if not os.path.exists(tpws_bin):
                raise FileNotFoundError(f"DPI bypass binary not found at: {tpws_bin}")
            
            args_list = shlex.split(custom_args)
            full_cmd = [
                os.path.abspath(tpws_bin),
                "--socks",
                "--bind-addr=127.0.0.1",
                f"--port={socks_port}"
            ] + args_list
            
            os.chmod(tpws_bin, 0o755)
            append_log(f"Executing: {' '.join(full_cmd)}", "system")
            
            bypass_process = subprocess.Popen(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                bufsize=0,
                cwd=BASE_DIR
            )
            
            if OS_TYPE == "Darwin" and sys_proxy:
                set_macos_proxy_state("on", socks_port)
                
        bypass_running = True
        
        # Fire monitoring thread
        t = threading.Thread(target=log_reader_thread, args=(bypass_process,), daemon=True)
        t.start()
        
        append_log(">>> Bypass service started successfully.", "system")
        return True, "Started"
        
    except Exception as e:
        err_msg = str(e)
        append_log(f">>> Error starting process: {err_msg}", "error")
        if bypass_process:
            try:
                bypass_process.kill()
            except Exception:
                pass
            bypass_process = None
        bypass_running = False
        if OS_TYPE == "Darwin" and sys_proxy:
            set_macos_proxy_state("off")
        return False, err_msg

def stop_bypass_service():
    global bypass_process, bypass_running
    if not bypass_running:
        return True
        
    append_log(">>> Stopping bypass service...", "system")
    bypass_running = False
    
    if OS_TYPE == "Darwin" and sys_proxy:
        set_macos_proxy_state("off")
        
    if bypass_process:
        try:
            bypass_process.kill()
        except Exception:
            pass
        bypass_process = None
        
    append_log(">>> Bypass service stopped.", "system")
    return True

# Load and save configuration settings
def load_config():
    global socks_port, sys_proxy, custom_args, selected_strategy
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            socks_port = cfg.get("socks_port", socks_port)
            sys_proxy = cfg.get("sys_proxy", sys_proxy)
            custom_args = cfg.get("custom_args", custom_args)
            selected_strategy = cfg.get("selected_strategy", selected_strategy)
            append_log("Configuration loaded successfully.", "system")
        except Exception as e:
            append_log(f"Error loading config.json: {e}", "error")

def save_config():
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "socks_port": socks_port,
                "sys_proxy": sys_proxy,
                "custom_args": custom_args,
                "selected_strategy": selected_strategy
            }, f, indent=4, ensure_ascii=False)
        append_log("Configuration saved successfully.", "system")
    except Exception as e:
        append_log(f"Error saving config.json: {e}", "error")

# Clean, symmetric padlock icon for system tray.
# Locked  : U-arch, both legs in body.
# Unlocked: same centred arch, left leg in body, right leg pulled out (short stub).
def create_tray_icon_image(active=False, scale=8):
    SIZE = 22 * scale
    img  = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d    = ImageDraw.Draw(img)
    # Active = green (unlocked), Inactive = red (locked)
    K    = (0, 200, 90, 255) if active else (210, 50, 50, 255)
    C    = (0, 0, 0, 0)

    pad = round(2   * scale)
    bh  = round(9   * scale)
    br  = round(2.2 * scale)
    bx0 = pad
    bx1 = SIZE - pad
    by1 = SIZE - pad
    by0 = by1 - bh

    sw  = round(3.0 * scale)
    scx = SIZE // 2
    sor = round(5.5 * scale)
    sir = sor - sw

    gap    = round(1.2 * scale)
    arc_cy = by0 - gap - sir

    # Body
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=br, fill=K)

    # Arch
    d.pieslice([scx-sor, arc_cy-sor, scx+sor, arc_cy+sor], 180, 360, fill=K)
    d.pieslice([scx-sir, arc_cy-sir, scx+sir, arc_cy+sir], 180, 360, fill=C)

    # Left leg — always in body
    d.rectangle([scx-sor, arc_cy, scx-sir, by0], fill=K)

    if not active:
        # LOCKED: right leg in body
        d.rectangle([scx+sir, arc_cy, scx+sor, by0], fill=K)
    else:
        # UNLOCKED: right leg pulled out
        stub = round(2.5 * scale)
        d.rectangle([scx+sir, arc_cy, scx+sor, arc_cy + stub], fill=K)

    return img


# Native OS prompt input dialogs
def show_input_dialog(prompt_text, title_text, default_val=""):
    if OS_TYPE == "Darwin":
        escaped_prompt = prompt_text.replace('"', '\\"')
        escaped_title = title_text.replace('"', '\\"')
        escaped_default = default_val.replace('"', '\\"')
        applescript = f'text returned of (display dialog "{escaped_prompt}" default answer "{escaped_default}" with title "{escaped_title}" buttons {{"OK", "Отмена"}} default button 1)'
        cmd = ["osascript", "-e", applescript]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                return res.stdout.strip()
            return None
        except Exception as e:
            append_log(f"Error showing AppleScript dialog: {e}", "error")
            return None
    elif OS_TYPE == "Windows":
        escaped_prompt = prompt_text.replace('"', '`"')
        escaped_title = title_text.replace('"', '`"')
        escaped_default = default_val.replace('"', '`"')
        ps_code = f"""
        [void][System.Reflection.Assembly]::LoadWithPartialName('Microsoft.VisualBasic');
        $val = [Microsoft.VisualBasic.Interaction]::InputBox("{escaped_prompt}", "{escaped_title}", "{escaped_default}");
        Write-Output $val
        """
        cmd = ["powershell", "-Command", ps_code]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0:
                return res.stdout.strip()
            return None
        except Exception as e:
            append_log(f"Error showing PowerShell dialog: {e}", "error")
            return None
    return default_val

# Notifications helper
def show_notification(title, message):
    global global_icon
    if global_icon:
        try:
            global_icon.notify(message, title)
        except Exception:
            if OS_TYPE == "Darwin":
                try:
                    escaped_title = title.replace('"', '\\"')
                    escaped_message = message.replace('"', '\\"')
                    applescript = f'display notification "{escaped_message}" with title "{escaped_title}"'
                    subprocess.run(["osascript", "-e", applescript])
                except Exception:
                    pass

# System tray action handlers
def select_strategy_action(strategy):
    global selected_strategy, custom_args
    selected_strategy = strategy
    if strategy != "Custom Parameters":
        custom_args = get_strategy_arguments(strategy)
    save_config()
    
    if bypass_running:
        stop_bypass_service()
        time.sleep(0.5)
        start_bypass_service(socks_port, sys_proxy, custom_args, selected_strategy)
        
    update_tray_state()

def toggle_bypass_action(icon, item):
    if bypass_running:
        stop_bypass_service()
        show_notification("Обход DPI остановлен", "Состояние: Выключен")
    else:
        success, msg = start_bypass_service(socks_port, sys_proxy, custom_args, selected_strategy)
        if success:
            show_notification("Обход DPI запущен", f"Порт: {socks_port}\nСтратегия: {selected_strategy}")
        else:
            show_notification("Ошибка запуска", msg)
            
    update_tray_state()

def toggle_proxy_action(icon, item):
    global sys_proxy
    sys_proxy = not sys_proxy
    save_config()
    
    if bypass_running:
        if sys_proxy:
            set_macos_proxy_state("on", socks_port)
        else:
            set_macos_proxy_state("off")
            
    update_tray_state()

def change_port_action(icon, item):
    global socks_port
    new_port = show_input_dialog("Введите новый SOCKS порт (например, 10800):", "SOCKS Порт", socks_port)
    if new_port:
        new_port = new_port.strip()
        if new_port.isdigit():
            socks_port = new_port
            save_config()
            
            if bypass_running:
                stop_bypass_service()
                time.sleep(0.5)
                start_bypass_service(socks_port, sys_proxy, custom_args, selected_strategy)
                
            update_tray_state()
        else:
            show_notification("Ошибка", "Порт должен быть числом!")

def change_args_action(icon, item):
    global custom_args, selected_strategy
    new_args = show_input_dialog("Введите дополнительные параметры запуска:", "Дополнительные параметры", custom_args)
    if new_args is not None:
        custom_args = new_args.strip()
        selected_strategy = "Custom Parameters"
        save_config()
        
        if bypass_running:
            stop_bypass_service()
            time.sleep(0.5)
            start_bypass_service(socks_port, sys_proxy, custom_args, selected_strategy)
            
        update_tray_state()

def open_file_action(filepath):
    if not os.path.exists(filepath):
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass
            
    try:
        if OS_TYPE == "Darwin":
            subprocess.run(["open", filepath])
        elif OS_TYPE == "Windows":
            subprocess.run(["cmd.exe", "/c", f"start {filepath}"], shell=True)
    except Exception as e:
        append_log(f"Error opening file {filepath}: {e}", "error")

def show_logs_action(icon, item):
    open_file_action(LOG_FILE_PATH)

def exit_action(icon, item):
    stop_bypass_service()
    icon.stop()

# Closure helpers to prevent closure capture and argcount validation issues
def make_strategy_action(strat):
    return lambda icon, item: select_strategy_action(strat)

def make_strategy_checked(strat):
    return lambda item: selected_strategy == strat

def make_open_file_action(path):
    return lambda icon, item: open_file_action(path)

# Dynamic Menu Builder
def rebuild_menu(icon=None):
    from pystray import MenuItem as item, Menu

    if bypass_running:
        status_label = "🟢  Обход активен"
        toggle_label = "Выключить обход"
    else:
        status_label = "🔴  Обход остановлен"
        toggle_label = "Включить обход"

    strategies = get_strategies()
    strategy_items = []
    for s in strategies:
        strategy_items.append(
            item(s, make_strategy_action(s), checked=make_strategy_checked(s))
        )
    strategy_submenu = Menu(*strategy_items) if strategy_items else Menu(
        item("Стратегии не найдены", lambda i, it: None, enabled=False)
    )
    cur_strat = selected_strategy if selected_strategy else "—"
    strategy_label = f"Стратегия: {cur_strat[:28]}"

    settings_items = [
        item(f"SOCKS-порт: {socks_port}", change_port_action),
        item("Системный прокси", toggle_proxy_action, checked=lambda it: sys_proxy),
        item("Доп. параметры…", change_args_action),
    ]
    settings_submenu = Menu(*settings_items)

    lists_dir = os.path.join(BASE_DIR, "lists")
    list_display = [
        ("Google / YouTube",  "list-google.txt"),
        ("Общий список",      "list-general.txt"),
        ("Исключения",        "list-exclude.txt"),
    ]
    list_items = [
        item(label, make_open_file_action(os.path.join(lists_dir, fname)))
        for label, fname in list_display
    ]
    lists_submenu = Menu(*list_items)

    menu_items = [
        item(status_label,        lambda i, it: None, enabled=False),
        Menu.SEPARATOR,
        item(toggle_label,        toggle_bypass_action),
        Menu.SEPARATOR,
        item(strategy_label,      strategy_submenu),
        item("Настройки",         settings_submenu),
        item("Списки блокировок", lists_submenu),
        Menu.SEPARATOR,
        item("Просмотр логов",    show_logs_action),
        Menu.SEPARATOR,
        item("Выход",             exit_action),
    ]

    new_menu = Menu(*menu_items)
    if icon:
        icon.menu = new_menu
    return new_menu

def update_tray_state():
    global global_icon
    if global_icon:
        rebuild_menu(global_icon)
        global_icon.icon = create_tray_icon_image(bypass_running)

# Main Application Entry Point
def main():
    global global_icon, selected_strategy, custom_args
    
    # Hide Dock icon on macOS
    if OS_TYPE == "Darwin":
        try:
            from AppKit import NSApplication
            ns_app = NSApplication.sharedApplication()
            ns_app.setActivationPolicy_(1)  # NSApplicationActivationPolicyAccessory
        except Exception:
            pass
            
    # Reset log file on startup
    try:
        with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
            f.write("=== ilchenkodev-zapret Log Started ===\n")
    except Exception:
        pass
        
    # Load configuration
    load_config()
    
    # Save beautiful active/inactive vector-style PNGs to disk
    try:
        active_png = create_tray_icon_image(True)
        inactive_png = create_tray_icon_image(False)
        active_png.save(os.path.join(BASE_DIR, "tray-tray-active.png"))
        inactive_png.save(os.path.join(BASE_DIR, "tray-intray-active.png"))
        append_log("Saved tray-active.png and intray-active.png to base folder.", "system")
    except Exception as e:
        append_log(f"Error saving icons to disk: {e}", "error")
        
    # Set default strategy if none selected
    strategies = get_strategies()
    if not selected_strategy or selected_strategy not in strategies:
        if strategies:
            selected_strategy = strategies[0]
            if selected_strategy != "Custom Parameters":
                custom_args = get_strategy_arguments(selected_strategy)
            save_config()
            
    # Launch system tray icon
    initial_image = create_tray_icon_image(False)
    
    global_icon = pystray.Icon(
        "ilchenkodev_zapret",
        initial_image,
        "ilchenkodev-zapret"
    )
    
    rebuild_menu(global_icon)
    global_icon.run()

if __name__ == "__main__":
    main()
