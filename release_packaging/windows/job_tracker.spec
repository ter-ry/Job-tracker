# PyInstaller onedir build. The installer packages this directory, keeping
# the executable and bundled runtime separate from the user's AppData data.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("sources", "sources"),
    ("services", "services"),
    ("db", "db"),
    ("release_packaging/windows/VERSION.txt", "."),
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
    ["release_packaging/windows/launcher.py"],
    pathex=["."],
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
