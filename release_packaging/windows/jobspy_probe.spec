from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parents[1]

a = Analysis(
    [],
    pathex=[str(REPO_ROOT)],
    hiddenimports=["jobspy"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JobSpyProbe", debug=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="JobSpyProbe")
