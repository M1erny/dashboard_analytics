import subprocess
import sys
import re
import qrcode
import threading
import time
import io
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

def start_tunnel():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting secure tunnel...", flush=True)
    
    # SSH command for localhost.run with keep-alive
    cmd = [
        "ssh", 
        "-o", "StrictHostKeyChecking=no", 
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-R", "80:localhost:5173", 
        "nokey@localhost.run"
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
            
            # Print output for debugging
            # print(line.strip())

            # Look for localhost.run URL pattern
            if not url_found:
                # matches things like https://abcd-1234.localhost.run
                match = re.search(r'(https://[a-zA-Z0-9-]+\.lhr\.life)', line) or \
                        re.search(r'(https://[a-zA-Z0-9-]+\.localhost\.run)', line)
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
