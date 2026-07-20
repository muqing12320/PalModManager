import sys
sys.path.insert(0, 'e:/Pal work/pal-mod-manager')
from src.core.manager import ModManager

mgr = ModManager(r'E:\SteamLibrary\steamapps\common\PalServer')
mgr.refresh()
print(f'Total mods: {len(mgr._mods)}')
print(f'Enabled: {sum(1 for m in mgr._mods.values() if str(m.status.value) == "enabled")}')

# Print all mods with their display name
for m in mgr._mods.values():
    name_repr = m.name if m.name else '<EMPTY>'
    print(f'  {name_repr!r:50s}  type={m.mod_type.value}, status={m.status.value}')
