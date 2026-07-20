"""Test import of a single mod zip with nested structure."""
import sys
import zipfile
import tempfile
from pathlib import Path

sys.path.insert(0, 'e:/Pal work/pal-mod-manager')

# Create a test zip with nested structure
test_dir = Path(tempfile.mkdtemp())
zip_path = test_dir / "ChickNomad InstantRespawn.zip"

with zipfile.ZipFile(zip_path, 'w') as zf:
    # Simulate: zip contains Mods/<name>/Scripts/main.lua structure
    zf.writestr("Mods/ChickNomad InstantRespawn/Scripts/main.lua", "-- mod code")
    zf.writestr("Mods/ChickNomad InstantRespawn/mod.json", "{}")
    zf.writestr("Mods/ChickNomad InstantRespawn/enabled.txt", "enabled")

print(f"Created test zip: {zip_path}")

# List contents
with zipfile.ZipFile(zip_path) as zf:
    for n in zf.namelist():
        print(f"  {n}")

# Test the import
from src.core.manager import ModManager
import shutil

# Copy test zip to a known location
test_zip = Path('C:/Users/XOS/Desktop/test_mod.zip')
shutil.copy(zip_path, test_zip)

# Use a real game path
mgr = ModManager(r'E:\SteamLibrary\steamapps\common\PalServer')
result = mgr.import_mod_pack(str(test_zip))
print(f"\nResult: {result}")
