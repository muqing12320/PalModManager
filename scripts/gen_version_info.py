"""根据 version.json 生成 PyInstaller 版本资源文件 version_info.txt。

生成的文件被 PalModManager.spec 引用，使打包出的 exe 内嵌
ProductName=PalModManager 与正确的 FileVersion，供自更新时精确识别
“同应用且更旧”的旧版本副本。
"""
import json
import os


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "version.json"), "r", encoding="utf-8") as f:
        ver = json.load(f)["version"]

    parts = []
    for x in ver.split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    while len(parts) < 4:
        parts.append(0)
    fp = tuple(parts[:4])

    text = (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        "    filevers=%s,\n"
        "    prodvers=%s,\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable(\n"
        "        u'040904B0',\n"
        "        [StringStruct(u'CompanyName', u'muqing12320'),\n"
        "         StringStruct(u'FileDescription', u'Pal Mod Manager'),\n"
        "         StringStruct(u'FileVersion', u'%s'),\n"
        "         StringStruct(u'InternalName', u'PalModManager'),\n"
        "         StringStruct(u'OriginalFilename', u'PalModManager.exe'),\n"
        "         StringStruct(u'ProductName', u'PalModManager'),\n"
        "         StringStruct(u'ProductVersion', u'%s')]\n"
        "      )\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    ) % (fp, fp, ver, ver)

    out = os.path.join(root, "version_info.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("[OK] version_info.txt -> " + ver)


if __name__ == "__main__":
    main()
