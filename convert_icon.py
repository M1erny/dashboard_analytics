from PIL import Image
import os

png_path = r"C:/Users/Tomek/.gemini/antigravity/brain/03922524-2a4e-4cbf-8847-51908dd855a7/donkey_icon_1769971143172.png"
ico_path = r"c:/Users/Tomek/Projects/portfolio-dashboard-2026/donkey.ico"

try:
    img = Image.open(png_path)
    # Resize to standard icon sizes
    img.save(ico_path, format='ICO', sizes=[(256, 256)])
    print(f"Successfully converted PNG to ICO at {ico_path}")
except Exception as e:
    print(f"Error converting image: {e}")
