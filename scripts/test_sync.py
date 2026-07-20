import sys, os
sys.path.insert(0, 'e:/Pal work/pal-mod-manager')
from src.core.manager import ModManager

server = ModManager(r'E:\SteamLibrary\steamapps\common\PalServer')
server.refresh()

# Check PAK mods on server
print("=== Server PAK mods ===")
for m in server._mods.values():
    if m.mod_type.value == 'pak':
        print(f"  {m.name}: {m.install_path}")

# Test sync to client
client_path = r'E:\SteamLibrary\steamapps\common\Palworld'
if os.path.exists(client_path):
    copied, deleted, fail, msgs = server.sync_mirror(client_path)
    print(f"\n=== Sync result ===")
    print(f"copied={copied}, deleted={deleted}, fail={fail}")
    if msgs:
        for m in msgs[:5]:
            print(f"  {m}")
    
    # Check what's now in client ~mods
    paks = r'E:\SteamLibrary\steamapps\common\Palworld\Pal\Content\Paks\~mods'
    if os.path.exists(paks):
        files = os.listdir(paks)
        print(f"\n=== Client ~mods after sync ===")
        for f in files:
            print(f"  {f}")
