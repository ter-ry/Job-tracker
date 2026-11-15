from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parents[1]

a = Analysis(
    [str(REPO_ROOT / "release_packaging/windows/provider_runtime_probe.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=["sources.provider_runtime", "sources.jobspy_worker"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ProviderRuntimeProbe", debug=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ProviderRuntimeProbe")
