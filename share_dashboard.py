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

def is_server_running(url="http://localhost:5173"):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status == 200
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
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE 
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
    if not ensure_ssh_key():
        print("Failed to ensure SSH key. Tunnel may fail.")
        
    # Check/Start Dev Server
    server_proc = None
    if not is_server_running():
        server_proc = start_dev_server()
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Local server already running.", flush=True)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting secure tunnel...", flush=True)
    
    cmd = [
        "ssh", 
        "-o", "StrictHostKeyChecking=no", 
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-R", "80:127.0.0.1:5173",  # Explicitly bind to IPv4 localhost
        "localhost.run" # Removed nokey@ to use identity
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8'
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
                # matches things like https://abcd-1234.localhost.run
                match = re.search(r'(https://[a-zA-Z0-9-]+\.lhr\.life)', line) or \
                        re.search(r'(https://[a-zA-Z0-9-]+\.localhost\.run)', line)
                if match:
                    url = match.group(1)
                    # Ignore generic admin/landing pages if they somehow match
                    if "admin" not in url and url != "https://localhost.run":
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
