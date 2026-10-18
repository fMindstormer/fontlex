#!/usr/bin/env python3
"""Check a demo page's palettes in WebKit, the engine Safari uses.

Renders the page in an offscreen WKWebView, switches the page theme and the
palette menu, snapshots the code box, and checks which theme's token colors
dominate the pixels. macOS only; needs pyobjc-framework-WebKit.

    python demo/check_webkit.py specs/python.yaml demo/fontlex-demo.html [--out DIR]
"""

import argparse
import sys
from pathlib import Path

import yaml
from AppKit import NSApplication, NSBackingStoreBuffered, NSBitmapImageRep, NSMakeRect, NSPNGFileType, NSWindow
from Foundation import NSDate, NSRunLoop, NSURL
from WebKit import WKSnapshotConfiguration, WKWebView, WKWebViewConfiguration

THEME = "document.documentElement.dataset.theme = '{}';"
PALETTE = "const p = document.getElementById('pal'); p.value = '{}'; p.dispatchEvent(new Event('change'));"
RED_TOKEN = ("const k = document.getElementById('c-{}'); k.value = '#ff0000';"
             " k.dispatchEvent(new Event('input'));")


def scenarios(token):
    """(name, script, theme whose colors should dominate, expect pure red)."""
    return [
        ("light", THEME.format("light"), "light", False),
        ("dark", THEME.format("dark"), "dark", False),
        ("dark-page-light-palette", THEME.format("dark") + PALETTE.format("light"), "light", False),
        ("light-page-dark-palette", THEME.format("light") + PALETTE.format("dark"), "dark", False),
        (f"custom-red-{token}", THEME.format("light") + PALETTE.format("custom") + RED_TOKEN.format(token),
         None, True),
    ]

# A hidden window doesn't run CSS transitions and repaints lazily, so a color
# change can be captured half-applied. Turn transitions off and force the
# textarea to lay out again before each snapshot.
SETTLE = ("(() => { const st = document.createElement('style');"
          " st.textContent = '* { transition: none !important; }'; document.head.appendChild(st); })();")
RELAYOUT = ("(() => { const c = document.getElementById('code'); c.style.display = 'none';"
            " c.offsetHeight; c.style.display = ''; })();")


class Page:
    def __init__(self, path: Path):
        NSApplication.sharedApplication()
        frame = NSMakeRect(0, 0, 1100, 1400)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(-3000, 0, 1100, 1400), 0, NSBackingStoreBuffered, False)
        self.view = WKWebView.alloc().initWithFrame_configuration_(frame, WKWebViewConfiguration.alloc().init())
        self.window.setContentView_(self.view)
        self.window.orderBack_(None)
        url = NSURL.fileURLWithPath_(str(path.resolve()))
        self.view.loadFileURL_allowingReadAccessToURL_(url, url.URLByDeletingLastPathComponent())
        for _ in range(200):
            self.spin(0.05)
            if not self.view.isLoading():
                break
        self.spin(1.0)   # let the embedded font load

    @staticmethod
    def spin(seconds):
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))

    def run(self, script):
        done = {}
        self.view.evaluateJavaScript_completionHandler_(script, lambda r, e: done.update(r=r, e=e))
        while not done:
            self.spin(0.02)
        if done["e"]:
            raise RuntimeError(f"JavaScript failed: {done['e']}")
        return done["r"]

    def snapshot_code(self):
        x, y, w, h = self.run("(() => { const r = document.getElementById('code')"
                              ".getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; })()")
        conf = WKSnapshotConfiguration.alloc().init()
        conf.setRect_(((x, y), (w, h)))
        done = {}
        self.view.takeSnapshotWithConfiguration_completionHandler_(conf, lambda img, e: done.update(img=img, e=e))
        while not done:
            self.spin(0.02)
        if done["e"]:
            raise RuntimeError(f"snapshot failed: {done['e']}")
        return NSBitmapImageRep.imageRepWithData_(done["img"].TIFFRepresentation())


def pixels(rep):
    for y in range(0, rep.pixelsHigh(), 2):
        for x in range(0, rep.pixelsWide(), 2):
            c = rep.colorAtX_y_(x, y)
            yield c.redComponent() * 255, c.greenComponent() * 255, c.blueComponent() * 255


def near(px, hexcolor, tolerance=24):
    r, g, b = (int(hexcolor.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    return sum(1 for pr, pg, pb in px if abs(pr - r) + abs(pg - g) + abs(pb - b) < tolerance)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("page")
    ap.add_argument("--out", help="directory to save snapshots in")
    args = ap.parse_args()

    themes = yaml.safe_load(Path(args.spec).read_text())["themes"]
    page = Page(Path(args.page))
    failed = 0
    token = next(iter(next(iter(themes.values()))))
    for name, script, want, red in scenarios(token):
        if red and not page.run(f"!!document.getElementById('c-{token}')"):
            print(f"skip {name}: the page has no custom colors")
            continue
        page.run(SETTLE + "(() => {" + script + "})();" + RELAYOUT + "1")
        page.spin(0.5)
        rep = page.snapshot_code()
        if args.out:
            rep.representationUsingType_properties_(NSPNGFileType, {}).writeToFile_atomically_(
                f"{args.out}/{name}.png", True)
        px = list(pixels(rep))
        counts = {t: sum(near(px, c) for c in colors.values()) for t, colors in themes.items()}
        reds = near(px, "#ff0000", 60)
        ok = (want is None or max(counts, key=counts.get) == want) and (reds > 0) == red
        failed += not ok
        shown = ", ".join(f"{t} colors {n}" for t, n in counts.items())
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {shown}, pure red {reds}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
