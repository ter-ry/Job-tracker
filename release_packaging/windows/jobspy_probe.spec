from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

REPO_ROOT = Path(SPECPATH).resolve().parents[1]

datas = collect_data_files("tls_client")
binaries = collect_dynamic_libs("tls_client")

a = Analysis(
    [str(REPO_ROOT / "release_packaging/windows/jobspy_probe.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JobSpyProbe", debug=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="JobSpyProbe")
