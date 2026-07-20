"""
Convert tubiao.png to ICO with full alpha transparency.
The image is already RGBA with green background pixels set to alpha=0.
"""
from PIL import Image
import struct
import os
from io import BytesIO

src = r'e:\Pal work\pal-mod-manager\resources\tubiao.png'
img = Image.open(src).convert('RGBA')

# Save PNG for reference
img.save(r'e:\Pal work\pal-mod-manager\resources\app_icon.png', 'PNG')

# Build ICO with 32-bit PNG entries
target_sizes = [256, 128, 64, 48, 32, 16]
png_data_list = []
for s in target_sizes:
    resized = img.resize((s, s), Image.LANCZOS).convert('RGBA')
    buf = BytesIO()
    resized.save(buf, format='PNG')
    png_data_list.append((s, buf.getvalue()))

ico_path = r'e:\Pal work\pal-mod-manager\resources\app_icon.ico'
with open(ico_path, 'wb') as f:
    # ICONDIR header
    f.write(struct.pack('<HHH', 0, 1, len(png_data_list)))
    offset = 6 + 16 * len(png_data_list)
    for s, data in png_data_list:
        w = 0 if s == 256 else s
        h = 0 if s == 256 else s
        f.write(struct.pack('<BBBBHHII', w, h, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    for _, data in png_data_list:
        f.write(data)

print(f'ICO created: {ico_path} ({os.path.getsize(ico_path)} bytes)')
print('Done - fully transparent background')
