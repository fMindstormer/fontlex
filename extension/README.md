# Fontlex Reading Hints: the hint fonts on any web page

A browser extension that draws web pages in one of this project's learner
fonts:

- **English pronunciation**: the stressed vowel bold and red, reduced vowels
  blue, silent letters faded ([../english/README.md](../english/README.md)).
- **French pronunciation**: silent letters faded, nasal vowels violet,
  droppable schwas blue, liaisons bold green with a tie
  ([../french/README.md](../french/README.md)).
- **German noun genders**: der blue, die red, das green
  ([../german/README.md](../german/README.md)).
- **German syllables**: syllables in turn blue and red
  ([../german/syllables/README.md](../german/syllables/README.md)).

By default it matches the page's language (`<html lang>`): English pages get
the English hints, French pages the French ones, German pages the genders,
and other pages are left alone. The popup picks a font for every page
instead, turns the extension off, or off for the current site. Hint colors
follow the page's background (light or dark palette), or a fixed choice.

The page's text isn't changed. Copy, search, translation and screen readers
see what they saw before; only the drawing changes.

## Install

From a release: download `fontlex-reading-hints-<version>.zip` from the
[releases page](https://github.com/fMindstormer/fontlex/releases), unzip it,
open `chrome://extensions`, turn on Developer mode, choose **Load unpacked**
and pick the unzipped folder. This works in Chrome, Edge, Brave and other
Chromium browsers.

From the repository: `python extension/package.py` writes the same folder to
`build/extension/` (the fonts must be built; `./check.sh` builds them).

Firefox and Safari aren't supported yet: the manifest has no Firefox add-on
id, and Safari needs an Xcode wrapper. Neither was tested.

## How it works

- `content.js` runs on every page. If the settings call for a font, it
  fetches the font from the extension and registers it with
  `document.fonts`. A font given as data isn't subject to the page's
  `font-src` policy, so pages with a strict Content-Security-Policy work too.
  Then it sets `data-fontlex` on `<html>`.
- `content.css` puts the body's text in that font: everything but code
  (`pre`, `code`, `kbd`, `samp`), math, SVG, and elements that look like
  icons (a class with "icon" or "material-symbols", Font Awesome's `fa-`,
  `aria-hidden`). Icon fonts keep their font, so pages keep their buttons.
- The palette is the page's: the first opaque background from `<body>` up
  decides light or dark.

## Tested

*Measured* with `test_extension.mjs`, which loads `build/extension/` into
Chromium 139 (headless, through Playwright) and checks:

- local pages in English (`lang="en-GB"`, dark background), French (with
  `Content-Security-Policy: default-src 'none'`) and German, and one with no
  language;
- that code and an icon font keep their fonts;
- that the hints are drawn: each palette's hint colors appear in a screenshot;
- the popup's choices, live, and the site switch.

All 17 checks pass. A live French Wikipedia article also renders with its
links and icons intact.

```sh
npm install playwright-core          # once
CHROMIUM=/path/to/Chromium node extension/test_extension.mjs
```

Branded Chrome no longer loads unpacked extensions from the command line, so
the test needs Chromium or Chrome for Testing.

## Limits

- The fonts cover Latin, Greek and Cyrillic text (761 characters in the
  English and French fonts, 1,363 in the German ones). Other characters fall
  back to the system font.
- Pages change their look: the base fonts are Noto Sans (English, French) and
  JetBrains Mono (German, monospaced).
- Only words in the lexicons get hints, and the hints are only as good as
  the fonts' lexicons (see each font's README).

## Licenses

The extension's code is MIT, like the project. The fonts keep their licenses,
and the package carries them (`NOTICE.txt`): the SIL Open Font License for
the base fonts, and CC BY-SA 4.0 for the French and German word lists.
