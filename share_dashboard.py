import subprocess
import sys
import re
import qrcode
import threading
import time
import io

def generate_qr(url):
    qr = qrcode.QRCode(version=1, box_size=1, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    f = io.StringIO()
    qr.print_ascii(out=f)
    f.seek(0)
    print("\n" + "="*40)
    print(f"MOBILE DASHBOARD LINK:\n{url}")
    print("="*40 + "\n")
    print(f.read())
    print("="*40)
    print("Scan this QR code with your phone camera!")
    print("Keep this window OPEN to stay connected.")
    print("="*40 + "\n")

def start_tunnel():
    print("Starting secure tunnel... (Press Ctrl+C to stop)")
    
    # Start SSH tunnel to serveo.net
    # -R 80:localhost:5173 -> Forward port 80 on remote to 5173 on local
    # -o StrictHostKeyChecking=no -> Don't ask for fingerprint confirmation
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-R", "80:localhost:5173", "serveo.net"]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8' # Force utf-8
    )

    url_found = False

    try:
        while True:
            line = process.stdout.readline()
            if not line:
                break
            
            # Print output for debugging (optional, or just status)
            # print(line.strip()) 

            # Serveo usually outputs: "Forwarding HTTP traffic from https://xxxx.serveo.net"
            if not url_found:
                match = re.search(r'(https://[a-zA-Z0-9-]+\.serveo\.net)', line) or \
                        re.search(r'(https://[a-zA-Z0-9-]+\.serveousercontent\.com)', line)
                if match:
                    url = match.group(1)
                    url_found = True
                    generate_qr(url)
            
            # If process exits
            if process.poll() is not None:
                break
                
    except KeyboardInterrupt:
        print("\nStopping tunnel...")
        process.terminate()

if __name__ == "__main__":
    start_tunnel()
