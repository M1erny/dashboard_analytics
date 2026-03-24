import subprocess
import sys
import re
import qrcode
import threading
import time
import io
import urllib.request
import os
from datetime import datetime

def generate_qr(url):
    qr = qrcode.QRCode(version=1, box_size=1, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    f = io.StringIO()
    qr.print_ascii(out=f)
    f.seek(0)
    print("\n" + "="*40)
    print(f"MOBILE DASHBOARD LINK [{datetime.now().strftime('%H:%M:%S')}]")
    print(f"{url}")
    print("="*40 + "\n")
    print(f.read())
    print("="*40)
    print("Scan this QR code with your phone!", flush=True)

def ensure_ssh_key():
    ssh_dir = os.path.expanduser("~/.ssh")
    key_path = os.path.join(ssh_dir, "id_rsa")
    
    if not os.path.exists(key_path):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] SSH key not found. Generating one...", flush=True)
        if not os.path.exists(ssh_dir):
            os.makedirs(ssh_dir)
            
        try:
            subprocess.run(
                ["ssh-keygen", "-t", "rsa", "-b", "4096", "-f", key_path, "-N", ""],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] SSH key generated successfully.", flush=True)
        except subprocess.CalledProcessError as e:
            print(f"Error generating SSH key: {e}")
            return False
    return True

# Port must match vite.config.ts server.port
DASHBOARD_PORT = 2137

def is_server_running():
    try:
        import socket
        with socket.create_connection(("127.0.0.1", DASHBOARD_PORT), timeout=1):
            return True
    except:
        return False

def start_dev_server():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting local dashboard server...", flush=True)
    # Use shell=True for npm on Windows to find the executable
    try:
        # Start npm run dev in background
        proc = subprocess.Popen(
            "npm run dev", 
            shell=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL 
        )
        # Wait a bit for it to come up
        for _ in range(30):
            if is_server_running():
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Local server is active!", flush=True)
                return proc
            time.sleep(1)
            
        print("Warning: Timed out waiting for server to start. Continuing anyway...")
        return proc
    except Exception as e:
        print(f"Failed to start server: {e}")
        return None

def start_tunnel():
    # Check if cloudflared exists
    if not os.path.exists("cloudflared.exe"):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Cloudflared not found. Downloading...", flush=True)
        try:
            # Fallback download if missing (though we did it in task)
            subprocess.run(
               ["powershell", "-Command", "Invoke-WebRequest -Uri https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe -OutFile cloudflared.exe"],
               check=True
            )
        except Exception as e:
            print(f"Failed to download cloudflared: {e}")
            return

    # Check/Start Dev Server
    server_proc = None
    if not is_server_running():
        server_proc = start_dev_server()
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Local server already running.", flush=True)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting Cloudflare Tunnel...", flush=True)
    
    # Cloudflared command
    cmd = [
        "cloudflared.exe", 
        "tunnel", 
        "--url", f"http://127.0.0.1:{DASHBOARD_PORT}",
        "--metrics", "localhost:49589"
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace'
    )

    url_found = False

    try:
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            # Print output for debugging (to see generic messages)
            # print(line.strip())

            if not url_found:
                # matches things like https://dark-forest-123.trycloudflare.com
                match = re.search(r'(https://[a-zA-Z0-9-]+\.trycloudflare\.com)', line)
                if match:
                    url = match.group(1)
                    url_found = True
                    generate_qr(url)
            
            if process.poll() is not None:
                break
                
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait()
        # Clean up dev server if we started it
        if server_proc:
            print("Stopping local server...")
            subprocess.run("taskkill /F /T /PID " + str(server_proc.pid), shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main_loop():
    print("Mobile Access Tunnel Wrapper")
    print("Press Ctrl+C to stop.")
    
    while True:
        try:
            start_tunnel()
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Connection lost. Restarting in 5 seconds...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nStopping tunnel...")
            break

if __name__ == "__main__":
    main_loop()
