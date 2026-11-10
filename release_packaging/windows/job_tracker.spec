# PyInstaller onedir build. The installer packages this directory, keeping
# the executable and bundled runtime separate from the user's AppData data.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

REPO_ROOT = Path(SPECPATH).resolve().parents[1]

datas = [
    (str(REPO_ROOT / "templates"), "templates"),
    (str(REPO_ROOT / "static"), "static"),
    (str(REPO_ROOT / "sources"), "sources"),
    (str(REPO_ROOT / "services"), "services"),
    (str(REPO_ROOT / "db"), "db"),
    (str(REPO_ROOT / "release_packaging/windows/VERSION.txt"), "."),
]
binaries = []
hiddenimports = [
    "app",
    "version",
    "release_packaging.windows.launcher",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.np_datetime",
    "jobspy",
]

# Keep the optional semantic backend available in the packaged application.
for package in ("sentence_transformers",):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
hiddenimports += collect_submodules("torch")

a = Analysis(
    [str(REPO_ROOT / "release_packaging/windows/launcher.py")],
    pathex=[str(REPO_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JobTracker", debug=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="JobTracker")
