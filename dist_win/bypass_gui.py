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
import webbrowser
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Global State
OS_TYPE = platform.system()
bypass_process = None
bypass_running = False
log_buffer = []
log_clients = []
log_lock = threading.Lock()

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

# Load persistent configurations
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
    timestamp = time.strftime("[%H:%M:%S]")
    log_item = {"time": timestamp, "text": text, "source": source}
    
    with log_lock:
        log_buffer.append(log_item)
        if len(log_buffer) > 1200:
            log_buffer.pop(0)
            
        # Notify SSE clients
        for client_queue in log_clients:
            try:
                client_queue.put(log_item)
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
            # If macOS, ensure proxy is reverted
            if OS_TYPE == "Darwin" and sys_proxy:
                set_macos_proxy_state("off")

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
            parsed_args = parsed_args.replace('%BIN%', bin_dir).replace('"%BIN%', f'"{bin_dir}')
            parsed_args = parsed_args.replace('%LISTS%', lists_dir).replace('"%LISTS%', f'"{lists_dir}')
            parsed_args = parsed_args.replace('%GameFilterTCP%', "12")
            parsed_args = parsed_args.replace('%GameFilterUDP%', "12")
            parsed_args = parsed_args.replace('%~dp0', base_dir + "\\")
            
            args_list = []
            try:
                safe_parsed = parsed_args.replace('\\', '\\\\')
                splitted = shlex.split(safe_parsed)
                args_list = [x.replace('\\\\', '\\') for x in splitted]
            except Exception:
                args_list = parsed_args.split()
            
            full_cmd = [os.path.abspath(winws_path)] + args_list
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

# Web HTTP Request Handler
class WebServerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging to terminal console to keep it clean
        pass
        
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        # 1. Main HTML UI Serve
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
            return
            
        # 2. SSE logs stream endpoint
        elif path == "/api/logs":
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            q = queue.Queue()
            with log_lock:
                log_clients.append(q)
                # Send history logs
                for log_item in log_buffer:
                    q.put(log_item)
                    
            try:
                while True:
                    try:
                        log_item = q.get(timeout=1.0)
                        self.wfile.write(f"data: {json.dumps(log_item)}\n\n".encode('utf-8'))
                        self.wfile.flush()
                    except queue.Empty:
                        # Keep-alive heartbeat ping
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (ConnectionResetError, BrokenPipeError, socket.error):
                pass
            finally:
                with log_lock:
                    if q in log_clients:
                        log_clients.remove(q)
            return

        # 3. GET status config
        elif path == "/api/status":
            data = {
                "running": bypass_running,
                "socks_port": socks_port,
                "sys_proxy": sys_proxy,
                "custom_args": custom_args,
                "strategy": selected_strategy,
                "os": OS_TYPE
            }
            self.send_json(data)
            return
            
        # 4. GET strategies
        elif path == "/api/strategies":
            self.send_json({
                "strategies": get_strategies()
            })
            return

        # 5. GET strategy target arguments
        elif path == "/api/strategy_args":
            query = parse_qs(parsed_url.query)
            strat = query.get("name", [""])[0]
            args_str = get_strategy_arguments(strat)
            self.send_json({"args": args_str})
            return

        # 6. GET file lists
        elif path == "/api/lists":
            files = []
            lists_dir_path = os.path.join(BASE_DIR, "lists")
            if os.path.exists(lists_dir_path):
                files = [os.path.basename(x) for x in glob.glob(os.path.join(lists_dir_path, "*.txt"))]
            self.send_json({"files": files})
            return
 
        # 7. GET list file contents
        elif path == "/api/list/get":
            query = parse_qs(parsed_url.query)
            filename = query.get("name", [""])[0]
            
            # Prevent directory traversal
            clean_name = os.path.basename(filename)
            filepath = os.path.join(BASE_DIR, "lists", clean_name)
            
            if not clean_name or not os.path.exists(filepath):
                self.send_json({"error": "File not found"}, status=404)
                return
                
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                self.send_json({"content": content})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        # Not Found fallbacks
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def do_POST(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        
        # Read payload body
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
        try:
            payload = json.loads(post_data.decode('utf-8')) if post_data else {}
        except Exception:
            payload = {}

        # 1. POST start service
        if path == "/api/start":
            port = str(payload.get("socks_port", socks_port))
            proxy_val = bool(payload.get("sys_proxy", sys_proxy))
            args_val = str(payload.get("custom_args", custom_args))
            strat_val = str(payload.get("strategy", selected_strategy))
            
            success, msg = start_bypass_service(port, proxy_val, args_val, strat_val)
            self.send_json({"success": success, "message": msg})
            return

        # 2. POST stop service
        elif path == "/api/stop":
            success = stop_bypass_service()
            self.send_json({"success": success})
            return

        # 3. POST save list content
        elif path == "/api/list/save":
            filename = payload.get("name", "")
            content = payload.get("content", "")
            
            clean_name = os.path.basename(filename)
            if not clean_name:
                self.send_json({"error": "Invalid filename"}, status=400)
                return
                
            lists_dir_path = os.path.join(BASE_DIR, "lists")
            os.makedirs(lists_dir_path, exist_ok=True)
            filepath = os.path.join(lists_dir_path, clean_name)
            
            try:
                with open(filepath, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content.strip() + "\n")
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        self.send_response(404)
        self.end_headers()

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

# Inline HTML/CSS/JS frontend application string
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ILCHENKODEV</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0d0d0d;
            --card-bg: #121212;
            --card-border: #242424;
            --card-border-active: #ffffff;
            --text: #ffffff;
            --text-muted: #737373;
            --accent: #ffffff;
            --accent-hover: #e5e5e5;
            --accent-glow: rgba(255, 255, 255, 0.05);
            --red: #ffffff;
            --green: #ffffff;
            --sidebar-width: 240px;
            --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background: var(--bg);
            font-family: var(--font-sans);
            color: var(--text);
            display: flex;
            height: 100vh;
            overflow: hidden;
        }

        /* Sidebar navigation */
        .sidebar {
            width: var(--sidebar-width);
            background: #080808;
            border-right: 1px solid var(--card-border);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            padding: 30px 18px;
            z-index: 10;
        }

        .logo {
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 4px;
            text-transform: uppercase;
            color: var(--text);
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 40px;
            padding: 0 10px;
        }

        .logo-dot {
            width: 8px;
            height: 8px;
            background: #404040;
            border-radius: 50%;
            transition: all 0.3s ease;
        }
        
        .logo-dot.running {
            background: #ffffff;
            box-shadow: 0 0 10px rgba(255, 255, 255, 0.5);
        }

        .nav-menu {
            display: flex;
            flex-direction: column;
            gap: 6px;
            flex-grow: 1;
        }

        .nav-btn {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 10px 14px;
            background: transparent;
            border: none;
            border-radius: 6px;
            color: var(--text-muted);
            font-family: inherit;
            font-size: 14px;
            font-weight: 500;
            text-align: left;
            cursor: pointer;
            transition: all 0.2s ease;
            width: 100%;
            outline: none;
        }

        .nav-btn:hover {
            color: var(--text);
            background: rgba(255, 255, 255, 0.03);
        }

        .nav-btn.active {
            color: var(--text);
            background: #18181b;
            font-weight: 600;
        }

        .sidebar-footer {
            font-size: 11px;
            color: var(--text-muted);
            padding: 0 10px;
            letter-spacing: 0.5px;
        }

        /* Main Content wrapper */
        .main-content {
            flex: 1;
            padding: 40px 50px;
            overflow: hidden;
            position: relative;
            display: flex;
            flex-direction: column;
        }

        /* Mobile Header */
        .mobile-header {
            display: none;
            align-items: center;
            gap: 16px;
            padding: 16px 20px;
            background: #080808;
            border-bottom: 1px solid var(--card-border);
            z-index: 15;
            margin-bottom: 20px;
            width: 100%;
        }

        .burger-btn {
            background: transparent;
            border: none;
            color: #ffffff;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 4px;
            outline: none;
        }

        .mobile-title {
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 4px;
            text-transform: uppercase;
        }

        /* Responsive Styles */
        @media (max-width: 768px) {
            body {
                flex-direction: column;
            }

            .sidebar {
                position: fixed;
                top: 0;
                left: 0;
                bottom: 0;
                transform: translateX(-100%);
                transition: transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
                z-index: 20;
                box-shadow: 10px 0 30px rgba(0,0,0,0.8);
            }

            .sidebar.open {
                transform: translateX(0);
            }

            .mobile-header {
                display: flex;
            }

            .main-content {
                padding: 0;
                height: calc(100vh - 57px); /* subtract header height */
            }

            .pane {
                padding: 20px;
                overflow-y: auto;
            }
        }

        .pane {
            display: none;
            animation: paneFade 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            flex-direction: column;
            height: 100%;
        }

        .pane.active {
            display: flex;
        }

        #dashboardPane.active {
            display: flex;
            flex-direction: column;
            gap: 20px;
        }

        @keyframes paneFade {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .header-title {
            font-size: 20px;
            font-weight: 700;
            letter-spacing: -0.5px;
            margin-bottom: 24px;
            color: #ffffff;
        }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 24px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
            transition: all 0.2s ease;
        }

        .card:hover {
            border-color: #333333;
        }

        .card.active {
            border-color: var(--card-border-active);
        }

        .card-title {
            font-size: 11px;
            font-weight: 700;
            color: var(--text-muted);
            letter-spacing: 1.5px;
            text-transform: uppercase;
            margin-bottom: 16px;
        }

        /* B&W Connect Button */
        .connect-btn {
            width: 100%;
            padding: 16px;
            background: transparent;
            border: 1px solid #404040;
            color: #ffffff;
            border-radius: 8px;
            font-family: inherit;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            text-transform: uppercase;
            letter-spacing: 2px;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            outline: none;
        }

        .connect-btn:hover {
            border-color: #ffffff;
            background: rgba(255, 255, 255, 0.02);
        }

        .connect-btn:active {
            transform: scale(0.99);
        }

        .connect-btn.running {
            background: #ffffff;
            border-color: #ffffff;
            color: #000000;
            font-weight: 700;
        }

        .connect-btn.running:hover {
            background: #e5e5e5;
            border-color: #e5e5e5;
        }

        .status-badge {
            font-size: 12px;
            font-weight: 600;
            letter-spacing: 1px;
            text-transform: uppercase;
            color: var(--text-muted);
            transition: all 0.3s ease;
        }

        .status-badge.running {
            color: #ffffff;
        }

        /* Form elements & Configuration */
        .form-group {
            margin-bottom: 20px;
            position: relative;
        }

        .form-group label {
            display: block;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-muted);
            letter-spacing: 1px;
            text-transform: uppercase;
            margin-bottom: 8px;
        }

        .form-control {
            width: 100%;
            padding: 12px 16px;
            background: #161616;
            border: 1px solid var(--card-border);
            border-radius: 6px;
            color: var(--text);
            font-family: inherit;
            font-size: 14px;
            box-sizing: border-box;
            transition: all 0.2s ease;
            outline: none;
        }

        .form-control:focus {
            border-color: #ffffff;
        }

        select.form-control {
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%23737373'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 16px center;
            background-size: 16px;
            padding-right: 40px;
        }

        textarea.form-control {
            font-family: var(--font-mono);
            font-size: 12px;
            line-height: 1.6;
            resize: vertical;
            height: 120px;
        }

        .checkbox-container {
            display: flex !important;
            align-items: center;
            gap: 12px;
            cursor: pointer;
            user-select: none;
            font-size: 13px;
            font-weight: 400 !important;
            text-transform: none !important;
            letter-spacing: normal !important;
            color: #a3a3a3;
            margin: 12px 0;
        }

        .checkbox-container input {
            display: none;
        }

        .checkbox-custom {
            width: 18px;
            height: 18px;
            border: 1px solid var(--card-border);
            border-radius: 4px;
            background: #161616;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
            flex-shrink: 0;
        }

        .checkbox-container:hover .checkbox-custom {
            border-color: #404040;
        }

        .checkbox-container input:checked + .checkbox-custom {
            background: #ffffff;
            border-color: #ffffff;
        }

        .checkbox-container input:checked + .checkbox-custom::after {
            content: '';
            width: 5px;
            height: 9px;
            border: solid #000000;
            border-width: 0 2px 2px 0;
            transform: rotate(45deg) translate(-0.5px, -1px);
        }

        .btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 10px 20px;
            background: #ffffff;
            border: 1px solid #ffffff;
            border-radius: 6px;
            color: #000000;
            font-family: inherit;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            outline: none;
        }

        .btn:hover {
            background: #e5e5e5;
            border-color: #e5e5e5;
        }

        .btn:active {
            transform: scale(0.98);
        }

        .btn-secondary {
            background: transparent;
            border-color: #333333;
            color: var(--text);
        }

        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.03);
            border-color: #ffffff;
        }

        /* Terminal Console component */
        .terminal-container {
            background: #080808;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            flex-grow: 1;
            min-height: 0;
        }

        .terminal-header {
            background: #0d0d0d;
            border-bottom: 1px solid var(--card-border);
            padding: 12px 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .terminal-info {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-muted);
            letter-spacing: 1px;
            text-transform: uppercase;
        }

        .terminal-status-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: #404040;
        }

        .terminal-status-dot.active {
            background: #ffffff;
            box-shadow: 0 0 6px #ffffff;
        }

        .terminal-actions {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .action-link {
            font-size: 12px;
            color: var(--text-muted);
            text-decoration: none;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .action-link:hover {
            color: var(--text);
        }

        .terminal-body {
            flex: 1;
            padding: 16px;
            overflow-y: auto;
            font-family: var(--font-mono);
            font-size: 13px;
            line-height: 1.6;
            color: #a3a3a3;
            background: #080808;
        }

        .log-line {
            margin-bottom: 6px;
            white-space: pre-wrap;
            word-break: break-all;
            display: flex;
            gap: 12px;
        }

        .log-time {
            color: #525252;
            flex-shrink: 0;
            user-select: none;
        }

        .log-text {
            flex-grow: 1;
        }

        .log-line.system {
            color: #ffffff;
            font-weight: 500;
        }

        .log-line.error {
            color: #ffffff;
            text-decoration: underline;
        }

        .editor-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            gap: 20px;
        }

        .editor-header .form-group {
            margin-bottom: 0;
            flex-grow: 1;
            max-width: 300px;
        }

        .editor-textarea {
            width: 100%;
            height: calc(100vh - 280px);
            font-family: var(--font-mono);
            font-size: 13px;
            line-height: 1.6;
            background: #040507;
            border: 1px solid var(--card-border);
            border-radius: 12px;
            color: #cbd5e1;
            padding: 20px;
            outline: none;
            resize: none;
            transition: all 0.25s ease;
        }

        .editor-textarea:focus {
            border-color: var(--accent);
            box-shadow: 0 0 15px rgba(102, 252, 241, 0.08);
        }

        /* Toast popup notifications */
        .toast-container {
            position: fixed;
            bottom: 30px;
            right: 30px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            z-index: 100;
        }

        .toast {
            background: rgba(16, 18, 23, 0.95);
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 14px 20px;
            color: var(--text);
            font-size: 13px;
            font-weight: 500;
            box-shadow: 0 10px 25px rgba(0,0,0,0.4);
            display: flex;
            align-items: center;
            gap: 12px;
            transform: translateX(120%);
            transition: all 0.35s cubic-bezier(0.16, 1, 0.3, 1);
            backdrop-filter: blur(10px);
        }

        .toast.show {
            transform: translateX(0);
        }

        .toast-icon {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--accent);
        }
        
        .toast.error .toast-icon {
            background: var(--red);
        }

        /* Info Block */
        .info-block {
            margin-top: 10px;
            padding: 16px;
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.01);
            border: 1px dashed var(--card-border);
            font-size: 13px;
            line-height: 1.5;
            color: var(--text-muted);
        }
        
        .info-block strong {
            color: var(--text);
        }

        /* Custom scrollbars */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        ::-webkit-scrollbar-track {
            background: transparent;
        }

        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.08);
            border-radius: 4px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.15);
        }

        /* Helper utils */
        .flex-row {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        .space-between {
            justify-content: space-between;
        }
        .mt-auto {
            margin-top: auto;
        }
    </style>
</head>
<body>

    <!-- Sidebar Navigation -->
    <div class="sidebar">
        <div>
            <div class="logo">
                <div class="logo-dot" id="logoDot"></div>
                ILCHENKODEV
            </div>
            
            <div class="nav-menu">
                <button class="nav-btn active" data-target="dashboardPane">
                    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2H6a2 2 0 01-2-2v-4zM14 16a2 2 0 012-2h2a2 2 0 012 2v4a2 2 0 01-2 2h-2a2 2 0 01-2-2v-4z"/></svg>
                    Dashboard
                </button>
                <button class="nav-btn" data-target="settingsPane">
                    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
                    Settings
                </button>
                <button class="nav-btn" data-target="editorPane" id="editorNavBtn">
                    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                    Rules Editor
                </button>
                <button class="nav-btn" data-target="logsPane">
                    <svg width="18" height="18" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
                    Live Logs
                </button>
            </div>
        </div>

        <div class="sidebar-footer" style="display: none;">
            <div id="osIndicator">OS: Detecting...</div>
            <div style="margin-top: 4px;">Service GUI v1.10.1</div>
        </div>
    </div>

    <!-- Main Content Area -->
    <div class="main-content">
        <!-- Mobile Header Bar -->
        <div class="mobile-header">
            <button class="burger-btn" id="burgerBtn">
                <svg width="24" height="24" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16"/>
                </svg>
            </button>
            <div class="mobile-title">ILCHENKODEV</div>
        </div>
        
        <!-- DASHBOARD PANE -->
        <div class="pane active" id="dashboardPane">
            <!-- Large Connect Button spanning full width and flex height -->
            <button class="connect-btn" id="powerBtn" style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; border-radius: 8px; font-size: 24px; font-weight: 700; letter-spacing: 4px; gap: 16px;">
                <span id="powerBtnText">Connect</span>
                <span class="status-badge" id="statusBadge" style="font-size: 11px; font-weight: 500; letter-spacing: 2px;">Disconnected</span>
            </button>
            
            <!-- Strategy Selector below -->
            <div class="card" style="padding: 16px 20px;">
                <div class="form-group" style="margin-bottom: 0;">
                    <label for="strategySelect" style="font-size: 10px;">Select Strategy</label>
                    <select class="form-control" id="strategySelect">
                        <!-- Strategies injected here -->
                    </select>
                </div>
            </div>
        </div>

        <!-- SETTINGS PANE -->
        <div class="pane" id="settingsPane">
            
            <div class="card" style="max-width: 600px;">
                <div class="card-title">Network Configurations</div>
                
                <div class="form-group" id="portGroup">
                    <label for="socksPort">SOCKS5 Proxy Port</label>
                    <input type="text" class="form-control" id="socksPort" placeholder="e.g. 10800">
                </div>

                <div class="form-group" id="sysProxyGroup">
                    <label class="checkbox-container">
                        <input type="checkbox" id="sysProxyCheck">
                        <div class="checkbox-custom"></div>
                        Auto-configure system proxy settings on connection
                    </label>
                </div>

                <div class="form-group">
                    <label for="customArgs">Active DPI arguments</label>
                    <textarea class="form-control" id="customArgs" placeholder="e.g. --split-pos=midsld ..."></textarea>
                </div>

                <!-- Hidden helper for JS DOM state compatibility -->
                <div id="argsPreviewBlock" style="display: none;">
                    <div id="strategyArgsPreview"></div>
                </div>

                <div style="margin-top: 20px; width: 100%;">
                    <button class="btn" id="saveSettingsBtn" style="width: 100%; padding: 14px;">Apply & Save Configurations</button>
                </div>

                <div class="info-block" id="browserConfigLink" style="cursor: pointer; transition: all 0.2s ease; margin-top: 24px;">
                    <strong>💡 Setup Browser Proxy</strong><br>
                    Click here to read the configuration instructions for Firefox, Chrome, and system-wide modes.
                </div>
            </div>
        </div>

        <!-- RULES EDITOR PANE -->
        <div class="pane" id="editorPane">
            <div class="editor-header">
                <div class="form-group">
                    <select class="form-control" id="listSelect">
                        <!-- Loaded txt files -->
                    </select>
                </div>
                <button class="btn" id="saveListBtn">Save Rules File</button>
            </div>
            
            <textarea class="editor-textarea" id="editorTextarea" spellcheck="false" placeholder="Loading rules content..."></textarea>
        </div>

        <!-- LIVE LOGS PANE -->
        <div class="pane" id="logsPane">
            
            <div class="terminal-container">
                <div class="terminal-header">
                    <div class="terminal-info">
                        <div class="terminal-status-dot" id="terminalStatusDot"></div>
                        <span>Stdout / Stderr Pipeline</span>
                    </div>
                    <div class="terminal-actions">
                        <label class="checkbox-container" style="margin: 0; font-size: 11px; color: var(--text-muted);">
                            <input type="checkbox" id="autoscrollCheck" checked>
                            <div class="checkbox-custom" style="width: 14px; height: 14px;"></div>
                            Autoscroll
                        </label>
                        <a class="action-link" id="clearLogsBtn">Clear logs</a>
                    </div>
                </div>
                <div class="terminal-body" id="terminalBody">
                    <!-- Logs injected dynamically -->
                </div>
            </div>
        </div>

    </div>

    <!-- Toast Notifications Container -->
    <div class="toast-container" id="toastContainer"></div>

    <script>
        // State variables
        let appState = {
            running: false,
            socks_port: "10800",
            sys_proxy: true,
            custom_args: "",
            strategy: "",
            os: ""
        };

        // DOM elements
        const navBtns = document.querySelectorAll('.nav-btn');
        const panes = document.querySelectorAll('.pane');
        const powerBtn = document.getElementById('powerBtn');
        const powerBtnText = document.getElementById('powerBtnText');
        const statusBadge = document.getElementById('statusBadge');
        const strategySelect = document.getElementById('strategySelect');
        const strategyArgsPreview = document.getElementById('strategyArgsPreview');
        const logoDot = document.getElementById('logoDot');
        const terminalStatusDot = document.getElementById('terminalStatusDot');
        
        // Settings pane inputs
        const socksPortInput = document.getElementById('socksPort');
        const sysProxyCheck = document.getElementById('sysProxyCheck');
        const customArgsInput = document.getElementById('customArgs');
        const saveSettingsBtn = document.getElementById('saveSettingsBtn');
        const osIndicator = document.getElementById('osIndicator');

        // Rules editor inputs
        const listSelect = document.getElementById('listSelect');
        const editorTextarea = document.getElementById('editorTextarea');
        const saveListBtn = document.getElementById('saveListBtn');

        // Logs terminal inputs
        const terminalBody = document.getElementById('terminalBody');
        const autoscrollCheck = document.getElementById('autoscrollCheck');
        const clearLogsBtn = document.getElementById('clearLogsBtn');

        // Helper toast popup manager
        function showToast(message, type = 'success') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.innerHTML = `<div class="toast-icon"></div><span>${message}</span>`;
            container.appendChild(toast);
            
            // Trigger animation frame
            setTimeout(() => toast.classList.add('show'), 10);
            
            // Delete toast after 3 seconds
            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 350);
            }, 3000);
        }

        // Tab views selector switching
        navBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                navBtns.forEach(b => b.classList.remove('active'));
                panes.forEach(p => p.classList.remove('active'));
                
                btn.classList.add('active');
                const target = btn.dataset.target;
                document.getElementById(target).classList.add('active');

                // Load list content if navigating to rules editor
                if (target === 'editorPane') {
                    loadListsInfo();
                }
            });
        });

        // Initialize dashboard and configuration
        async function fetchStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                appState = data;
                
                updateUIState();
            } catch (err) {
                console.error("Failed to load status details", err);
            }
        }

        async function fetchStrategies() {
            try {
                const response = await fetch('/api/strategies');
                const data = await response.json();
                
                strategySelect.innerHTML = "";
                data.strategies.forEach(strat => {
                    const opt = document.createElement('option');
                    opt.value = strat;
                    opt.textContent = strat;
                    strategySelect.appendChild(opt);
                });

                if (appState.strategy) {
                    strategySelect.value = appState.strategy;
                } else if (data.strategies.length > 0) {
                    strategySelect.value = data.strategies[0];
                    updateStrategyArgs(data.strategies[0]);
                }
            } catch (err) {
                console.error("Failed to fetch strategies", err);
            }
        }

        async function updateStrategyArgs(strategyName) {
            try {
                const response = await fetch(`/api/strategy_args?name=${encodeURIComponent(strategyName)}`);
                const data = await response.json();
                strategyArgsPreview.textContent = data.args || "No arguments needed / manual config";
                
                // If not currently running, populate settings arguments textarea with this template
                if (!appState.running) {
                    customArgsInput.value = data.args;
                }
            } catch (err) {
                console.error("Failed to retrieve strategy args template", err);
            }
        }

        function updateUIState() {
            osIndicator.textContent = `OS: ${appState.os}`;
            
            // Adjust forms for Windows (no socks port configurations needed since windivert works systemwide)
            if (appState.os === "Windows") {
                document.getElementById('portGroup').style.display = 'none';
                document.getElementById('sysProxyGroup').style.display = 'none';
            } else {
                document.getElementById('portGroup').style.display = 'block';
                document.getElementById('sysProxyGroup').style.display = 'block';
            }

            // Sync inputs values
            socksPortInput.value = appState.socks_port;
            sysProxyCheck.checked = appState.sys_proxy;
            customArgsInput.value = appState.custom_args;

            // Power control UI changes
            if (appState.running) {
                powerBtn.classList.add('running');
                powerBtnText.textContent = "Disconnect";
                logoDot.classList.add('running');
                terminalStatusDot.classList.add('active');
                statusBadge.textContent = "Protected & Connected";
                statusBadge.className = "status-badge running";
            } else {
                powerBtn.classList.remove('running');
                powerBtnText.textContent = "Connect";
                logoDot.classList.remove('running');
                terminalStatusDot.classList.remove('active');
                statusBadge.textContent = "Disconnected";
                statusBadge.className = "status-badge";
            }
        }

        // Handle power button toggling click
        powerBtn.addEventListener('click', async () => {
            powerBtn.style.pointerEvents = "none"; // Temporarily disable to avoid spamming clicks
            try {
                if (appState.running) {
                    // Send stop command
                    const res = await fetch('/api/stop', { method: 'POST' });
                    const data = await res.json();
                    if (data.success) {
                        appState.running = false;
                        showToast("Bypass pipeline terminated.");
                    } else {
                        showToast("Failed to stop service.", "error");
                    }
                } else {
                    // Send start command with current inputs
                    const payload = {
                        socks_port: socksPortInput.value,
                        sys_proxy: sysProxyCheck.checked,
                        custom_args: customArgsInput.value,
                        strategy: strategySelect.value
                    };

                    const res = await fetch('/api/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                    const data = await res.json();
                    if (data.success) {
                        appState.running = true;
                        showToast("DPI Bypass pipeline is active!");
                    } else {
                        showToast(`Start failed: ${data.message}`, "error");
                    }
                }
                updateUIState();
            } catch (err) {
                console.error("Action error", err);
                showToast("Connection to server lost.", "error");
            } finally {
                powerBtn.style.pointerEvents = "auto";
            }
        });

        // Strategy select box changes
        strategySelect.addEventListener('change', (e) => {
            updateStrategyArgs(e.target.value);
        });

        // Save manual settings parameters
        saveSettingsBtn.addEventListener('click', async () => {
            const payload = {
                socks_port: socksPortInput.value,
                sys_proxy: sysProxyCheck.checked,
                custom_args: customArgsInput.value,
                strategy: strategySelect.value
            };

            // If running, warn user to restart bypass
            showToast("Settings template applied successfully!");
            appState.socks_port = payload.socks_port;
            appState.sys_proxy = payload.sys_proxy;
            appState.custom_args = payload.custom_args;

            if (appState.running) {
                showToast("Restart the active bypass server to load settings.", "error");
            }
        });

        // Setup real-time Log Pipeline stream using EventSource
        function initLogsStream() {
            const sse = new EventSource('/api/logs');
            
            sse.onmessage = function(e) {
                try {
                    const log = JSON.parse(e.data);
                    
                    const logEl = document.createElement('div');
                    logEl.className = `log-line ${log.source || 'stdout'}`;
                    
                    const timeEl = document.createElement('span');
                    timeEl.className = 'log-time';
                    timeEl.textContent = log.time;
                    
                    const textEl = document.createElement('span');
                    textEl.className = 'log-text';
                    textEl.textContent = log.text;
                    
                    logEl.appendChild(timeEl);
                    logEl.appendChild(textEl);
                    
                    terminalBody.appendChild(logEl);
                    
                    // Limit text inside terminal body to prevent RAM freeze
                    if (terminalBody.childNodes.length > 1000) {
                        terminalBody.removeChild(terminalBody.firstChild);
                    }
                    
                    if (autoscrollCheck.checked) {
                        terminalBody.scrollTop = terminalBody.scrollHeight;
                    }
                } catch (err) {
                    console.error("Error writing logs parsing", err);
                }
            };

            sse.onerror = function() {
                // If disconnected, try reconnecting automatically
                console.warn("Logs pipeline SSE stream lost connection. Attempting reconnect...");
            };
        }

        // Rules editor operations
        async function loadListsInfo() {
            try {
                const response = await fetch('/api/lists');
                const data = await response.json();
                
                const currentSelection = listSelect.value;
                listSelect.innerHTML = "";
                
                data.files.forEach(file => {
                    const opt = document.createElement('option');
                    opt.value = file;
                    opt.textContent = file;
                    listSelect.appendChild(opt);
                });

                if (currentSelection && data.files.includes(currentSelection)) {
                    listSelect.value = currentSelection;
                } else if (data.files.length > 0) {
                    listSelect.value = data.files[0];
                    loadSelectedFileContent(data.files[0]);
                }
            } catch (err) {
                showToast("Failed to retrieve file list details", "error");
            }
        }

        async function loadSelectedFileContent(filename) {
            editorTextarea.value = "Loading list content details...";
            try {
                const response = await fetch(`/api/list/get?name=${encodeURIComponent(filename)}`);
                const data = await response.json();
                
                if (data.error) {
                    editorTextarea.value = `Error: ${data.error}`;
                } else {
                    editorTextarea.value = data.content;
                }
            } catch (err) {
                editorTextarea.value = "Connection error reading file details.";
            }
        }

        listSelect.addEventListener('change', (e) => {
            loadSelectedFileContent(e.target.value);
        });

        saveListBtn.addEventListener('click', async () => {
            const filename = listSelect.value;
            const content = editorTextarea.value;
            
            if (!filename) return;

            try {
                const response = await fetch('/api/list/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: filename, content: content })
                });
                
                const data = await response.json();
                if (data.success || response.ok) {
                    showToast(`Successfully saved rules file ${filename}!`);
                } else {
                    showToast(`Save failed: ${data.error}`, "error");
                }
            } catch (err) {
                showToast("Save file connection error.", "error");
            }
        });

        // Logs helper triggers
        clearLogsBtn.addEventListener('click', () => {
            terminalBody.innerHTML = "";
        });

        // Setup Browser Proxies instructions modal popup
        document.getElementById('browserConfigLink').addEventListener('click', () => {
            let msg = "";
            if (appState.os === "Windows") {
                msg = "Windows System-Wide Mode:\\n\\n" +
                      "The bypass tool automatically captures and patches all system network traffic using the WinDivert driver.\\n" +
                      "No browser configurations are needed!\\n\\n" +
                      "Important: Please run the terminal or command script as Administrator so the system drivers can load.";
            } else {
                msg = `macOS / Linux SOCKS5 Mode (Port: ${appState.socks_port}):\\n\\n` +
                      "The GUI automatically sets SOCKS proxy rules when you connect. If some browsers fail to load:\\n\\n" +
                      "1. Firefox (Recommended):\\n" +
                      "   - Settings -> Network Settings -> Settings\\n" +
                      "   - Choose 'Manual proxy configuration'\\n" +
                      "   - SOCKS Host: 127.0.0.1, Port: " + appState.socks_port + "\\n" +
                      "   - Ensure 'Proxy DNS when using SOCKS v5' is checked at the bottom!\\n\\n" +
                      "2. Chrome / Edge / Brave:\\n" +
                      "   - Enable SOCKS5 proxy extension (like SwitchyOmega) pointed to 127.0.0.1:" + appState.socks_port + "\\n" +
                      "   - Or run Chrome via Terminal:\\n" +
                      "     open -a 'Google Chrome' --args --proxy-server='socks5://127.0.0.1:" + appState.socks_port + "'";
            }
            alert(msg);
        });

        // Mobile Sidebar toggler
        const sidebar = document.querySelector('.sidebar');
        const burgerBtn = document.getElementById('burgerBtn');

        burgerBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            sidebar.classList.toggle('open');
        });

        // Close sidebar on navigation click
        navBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                sidebar.classList.remove('open');
            });
        });

        // Close sidebar when clicking outside on mobile
        document.addEventListener('click', (e) => {
            if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && !burgerBtn.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        });

        // Initial setup sequence
        async function runInit() {
            await fetchStatus();
            await fetchStrategies();
            initLogsStream();
        }

        runInit();
    </script>
</body>
</html>
"""

# Server launcher main loop
def start_gui_server(host="127.0.0.1", port=58180):
    # Auto-detect free ports if 58180 is taken
    for p in range(port, port + 100):
        try:
            httpd = ThreadingHTTPServer((host, p), WebServerHandler)
            actual_port = p
            break
        except OSError:
            continue
    else:
        print("[-] Error: Could not find any open ports to start the GUI web server.")
        sys.exit(1)
        
    url = f"http://{host}:{actual_port}/"
    print(f"[+] ILCHENKODEV GUI Server started at {url}")
    append_log(f"GUI Dashboard available at {url}", "system")
    append_log(f"Running on OS platform: {OS_TYPE}", "system")
    
    # Start HTTP server in a background daemon thread
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()
    
    try:
        import webview
        print("[+] pywebview detected. Launching native desktop window...")
        # Create and launch the native web view window
        webview.create_window(
            title="ILCHENKODEV",
            url=url,
            width=860,
            height=620,
            resizable=True
        )
        webview.start()
        print("[+] Native desktop window closed.")
    except (ImportError, Exception) as e:
        print(f"[!] pywebview is not installed or failed to load ({e}).")
        print("[!] For a native app experience, install it using: pip install pywebview")
        print("[!] Falling back to opening dashboard in your default browser...")
        
        # On Windows, if pywebview fails to open the window, show a native popup alert
        if OS_TYPE == "Windows":
            try:
                import ctypes
                # MB_ICONINFORMATION = 0x40
                ctypes.windll.user32.MessageBoxW(
                    0, 
                    "В системе отсутствует компонент Microsoft Edge WebView2 Runtime, необходимый для работы приложения в виде отдельного окна.\n\nПрограмма откроется в вашем обычном веб-браузере. Для работы в виде отдельного окна скачайте и установите WebView2 Runtime с сайта Microsoft.", 
                    "ILCHENKODEV - Требуется WebView2 Runtime", 
                    0x40
                )
            except Exception:
                pass
        
        # Auto-launch default browser tab
        webbrowser.open(url)
        
        # Keep the main thread alive since server_thread is running in background
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[-] Received keyboard interrupt...")
            
    finally:
        print("[-] Stopping services and cleaning up...")
        stop_bypass_service()
        httpd.shutdown()
        httpd.server_close()
        print("[+] Cleanup complete. Exited.")

if __name__ == "__main__":
    start_gui_server()
