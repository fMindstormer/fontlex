#!/usr/bin/env python3
"""Assemble the browser extension, for Chromium browsers and for Firefox:
build/extension/ and build/extension-firefox/ (to load unpacked), and
build/fontlex-reading-hints-<version>.zip and -firefox.zip.

    python extension/package.py

It copies this directory's files, the four hint fonts from build/ (built by
./check.sh english french german syllables) and their licenses. Firefox's
manifest adds an add-on id and leaves out `use_dynamic_url`, which Firefox
doesn't support.
"""

import json
import shutil
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCES = ["manifest.json", "fonts.js", "content.js", "content.css", "popup.html", "popup.js", "icons"]
FONTS = ["Fontlex-English.woff2", "Fontlex-French.woff2", "Fontlex-German.woff2", "Fontlex-German-Syllables.woff2"]
LICENSES = {"LICENSE.txt": ROOT / "LICENSE", "OFL-NotoSans.txt": ROOT / "fonts" / "OFL-NotoSans.txt",
            "OFL-JetBrainsMono.txt": ROOT / "fonts" / "OFL.txt",
            "CMUDICT-LICENSE.txt": ROOT / "english" / "lexicon" / "CMUDICT-LICENSE.txt"}
GECKO = {"id": "reading-hints@fontlex.fmindstormer.github.io", "strict_min_version": "140.0",
         "data_collection_permissions": {"required": ["none"]}}
NOTICE = """Fontlex Reading Hints, https://github.com/fMindstormer/fontlex

The extension's code is under the MIT License (LICENSE.txt).

The fonts in fonts/ are modified versions of Noto Sans (English, French) and
JetBrains Mono (German), under the SIL Open Font License 1.1
(OFL-NotoSans.txt, OFL-JetBrainsMono.txt). Their word lists carry these terms:
- English: derived from the CMU Pronouncing Dictionary (CMUDICT-LICENSE.txt).
- French: derived from Lexique 3.83 (New, Pallier et al., www.lexique.org) and
  French Wiktionary, under CC BY-SA 4.0.
- German genders: derived from Universal Dependencies treebanks (HDT, PUD) and
  German Wiktionary data under CC BY-SA (german/README.md in the project).
- German syllables: TeX's hyph-de patterns (MIT License).
"""


def firefox(manifest):
    m = json.loads(json.dumps(manifest))
    m["browser_specific_settings"] = {"gecko": GECKO}
    for entry in m["web_accessible_resources"]:
        entry.pop("use_dynamic_url", None)
    return m


def main():
    manifest = json.loads((HERE / "manifest.json").read_text())
    for name, m in (("extension", None), ("extension-firefox", firefox(manifest))):
        assemble(ROOT / "build" / name, m, name.replace("extension", f"fontlex-reading-hints-{manifest['version']}"))
    return 0


def assemble(out, manifest, archive_name):
    if out.exists():
        shutil.rmtree(out)
    (out / "fonts").mkdir(parents=True)
    for name in SOURCES:
        src = HERE / name
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, out / name)
    if manifest:                     # else the source's, as written
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for name in FONTS:
        src = ROOT / "build" / name
        if not src.exists():
            sys.exit(f"missing {src}: build the fonts first (./check.sh english french german syllables)")
        shutil.copy2(src, out / "fonts" / name)
    for name, src in LICENSES.items():
        shutil.copy2(src, out / name)
    (out / "NOTICE.txt").write_text(NOTICE, encoding="utf-8")
    archive = ROOT / "build" / f"{archive_name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(out.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(out).as_posix())
    print(f"wrote {out}/ and {archive} ({archive.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    sys.exit(main())
