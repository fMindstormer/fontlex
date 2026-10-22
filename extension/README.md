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
instead, turns the extension off, or off for the current site. Each kind of
pronunciation hint (stress, reduced vowels and schwas, silent letters, nasal
vowels, liaisons) can be hidden on its own. Hint colors follow the page's
background (light or dark palette), or a fixed choice.

The page's text isn't changed. Copy, search, translation and screen readers
see what they saw before; only the drawing changes.

## Install

From a release: download `fontlex-reading-hints-<version>.zip` from the
[releases page](https://github.com/fMindstormer/fontlex/releases), unzip it,
open `chrome://extensions`, turn on Developer mode, choose **Load unpacked**
and pick the unzipped folder. This works in Chrome, Edge, Brave and other
Chromium browsers.

In Firefox 140 or later, download `fontlex-reading-hints-<version>-firefox.zip`,
open `about:debugging#/runtime/this-firefox`, choose **Load Temporary
Add-on…** and pick the zip. Firefox keeps a temporary add-on until it
quits. To keep it installed, it must be signed by Mozilla (through
addons.mozilla.org, listed or not); Firefox Developer Edition and Nightly
can instead set `xpinstall.signatures.required` to false in `about:config`.

From the repository: `python extension/package.py` writes both folders,
`build/extension/` and `build/extension-firefox/` (the fonts must be built;
`./check.sh` builds them). The Firefox manifest adds an add-on id and
leaves out `use_dynamic_url`, which Firefox doesn't support; the code is
the same.

Safari isn't supported: it needs an Xcode wrapper.

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
- A hidden kind of hint is the font's stylistic set for it (`ss01` to
  `ss05`, numbered alike in the English and French fonts), which
  `content.js` puts in a `--fontlex-features` variable on `<html>` and
  `content.css` applies as `font-feature-settings`.
- The palette is the page's: the first opaque background from `<body>` up
  decides light or dark.

## Tested

*Measured* with `test_extension.mjs`, which loads `build/extension/` into
Chromium 139 (headless, through Playwright), or `build/extension-firefox/`
into Firefox 158 (headless, through Puppeteer and WebDriver BiDi, as a
temporary add-on), and checks:

- local pages in English (`lang="en-GB"`, dark background), French (with
  `Content-Security-Policy: default-src 'none'`) and German, and one with no
  language;
- that code and an icon font keep their fonts;
- that the hints are drawn: each palette's hint colors appear in a screenshot;
- the popup's choices, live, and the site switch;
- hiding a kind of hint: its color leaves the screen, the others stay.

All 21 checks pass in each browser; CI runs both on Linux. A live French
Wikipedia article also renders in Chromium with its links and icons intact.

```sh
npm install playwright-core puppeteer-core @puppeteer/browsers      # once
CHROMIUM=/path/to/Chromium node extension/test_extension.mjs
FIREFOX=$(npx @puppeteer/browsers install firefox@stable_158.0.1 --format "{{path}}") \
  node extension/test_extension.mjs firefox
```

Branded Chrome no longer loads unpacked extensions from the command line, so
the test needs Chromium or Chrome for Testing. In Firefox the test sets
`MOZ_REMOTE_ALLOW_SYSTEM_ACCESS=1`, without which WebDriver BiDi won't open
the popup's `moz-extension://` page.

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
