from PIL import Image
from pathlib import Path
import sys

if len(sys.argv) < 2:
    raise SystemExit("Usage: python convert_icon.py path-to-source-png [path-to-output-ico]")

png_path = Path(sys.argv[1]).expanduser()
ico_path = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else Path(__file__).with_name("donkey.ico")

try:
    img = Image.open(png_path)
    # Resize to standard icon sizes
    img.save(ico_path, format='ICO', sizes=[(256, 256)])
    print(f"Successfully converted PNG to ICO at {ico_path}")
except Exception as e:
    print(f"Error converting image: {e}")
