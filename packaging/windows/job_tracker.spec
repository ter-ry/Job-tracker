# PyInstaller onedir build.  The installer packages this directory, keeping
# the executable and bundled runtime separate from the user's AppData data.
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [
    ("templates", "templates"),
    ("static", "static"),
    ("sources", "sources"),
    ("services", "services"),
    ("db", "db"),
    ("packaging/windows/VERSION.txt", "."),
]
binaries = []
hiddenimports = [
    "app",
    "version",
    "packaging.windows.launcher",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.np_datetime",
    "jobspy",
]

# Keep the optional semantic backend available in the packaged application.
# PyTorch and sentence-transformers are intentionally collected rather than
# silently removed; the resulting size is measured by the CI packaging job.
for package in ("sentence_transformers",):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden
hiddenimports += collect_submodules("torch")

a = Analysis(
    ["packaging/windows/launcher.py"],
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
