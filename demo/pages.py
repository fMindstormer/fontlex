"""What the German and Markdown demo pages share: the page style, the text
box with its toggle and palette menu, the script behind them, and the font,
embedded as WOFF2.

A page template holds {{STYLE}} inside its <style> (page rules follow it and
can override it), {{EDITOR}} where the text box goes and {{SCRIPT}} at the
end; fill() puts these and the page's own {{FIELDS}} in.
"""

import base64
import html
import io
from pathlib import Path

STYLE = """@font-face { font-family: "{{FAMILY}}"; src: url(data:font/woff2;base64,{{FONT}}) format("woff2"); }
:root { --bg: #F4F5F7; --surface: #FFFFFF; --ink: #1B2130; --muted: #5B6476; --rule: #D8DCE3;
        --fp: light;{{LIGHT}} color-scheme: light; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11141B; --surface: #181C25; --ink: #E4E7EE; --muted: #98A0B1; --rule: #2A303D;
  --fp: dark;{{DARK}} color-scheme: dark; } }
:root[data-theme="dark"] { --bg: #11141B; --surface: #181C25; --ink: #E4E7EE; --muted: #98A0B1;
  --rule: #2A303D; --fp: dark;{{DARK}} color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 52rem; margin: 0 auto; padding: 2.5rem 1.25rem 4rem; }
h1 { font-size: 2rem; margin: 0 0 .25rem; }
h2 { font-size: 1.15rem; margin: 2.25rem 0 .5rem; }
.lede { color: var(--muted); margin: 0 0 1.5rem; }
.editor { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }
.bar { display: flex; gap: 1.25rem; align-items: center; padding: .6rem 1rem; border-bottom: 1px solid var(--rule);
       font-size: .875rem; color: var(--muted); flex-wrap: wrap; }
.bar label { display: inline-flex; gap: .4rem; align-items: center; }
select { font: inherit; color: var(--ink); background: var(--bg); border: 1px solid var(--rule); border-radius: 6px; }
textarea#code { display: block; width: 100%; min-height: 15rem; border: 0; outline: none; resize: vertical;
  padding: 1rem 1.1rem; background: transparent; color: var(--ink);
  font: 400 1.05rem/1.7 "{{FAMILY}}", ui-monospace, monospace; font-palette: var(--fp); }
#editor.off textarea#code { font-feature-settings: "calt" 0; }
table { border-collapse: collapse; width: 100%; font-size: .92rem; }
th, td { text-align: left; padding: .45rem .6rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.note { color: var(--muted); font-size: .9rem; }
code { font: .92em ui-monospace, monospace; }
ul, ol { padding-left: 1.2rem; } li { margin: .25rem 0; }"""

EDITOR = """<div class="editor" id="editor">
    <div class="bar">
      <label for="hl"><input type="checkbox" id="hl" checked> {{TOGGLE}}</label>
      <label for="pal">Palette
        <select id="pal"><option value="auto">Match page</option><option value="light">Light</option>
        <option value="dark">Dark</option></select></label>{{CONTROLS}}
    </div>
    <textarea id="code" spellcheck="false" {{ATTRIBUTES}}>{{SAMPLE}}</textarea>
  </div>"""

# The toggle turns the font's features off (the plain characters); the menu
# picks the font's palette, or the one matching the page.
SCRIPT = """<script>
(() => {
  const editor = document.getElementById('editor'), hl = document.getElementById('hl'), pal = document.getElementById('pal');
  const style = document.createElement('style');
  document.head.appendChild(style);
  function apply() {
    editor.classList.toggle('off', !hl.checked);
    const value = pal.value === 'auto' ? 'var(--fp)' : pal.value;
    style.textContent = 'textarea#code { font-palette: ' + value + '; }';
  }
  hl.addEventListener('change', apply);
  pal.addEventListener('change', apply);
  apply();
})();
</script>"""


def woff2(font):
    """The font as WOFF2 bytes."""
    font.flavor = "woff2"
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue()


def editor(toggle, sample, attributes, controls=""):
    """The text box holding `sample`, under a bar with the `toggle` checkbox,
    the palette menu and any other `controls`; `attributes` are the
    textarea's other attributes."""
    return fill(EDITOR, {"TOGGLE": toggle, "SAMPLE": html.escape(sample), "ATTRIBUTES": attributes,
                         "CONTROLS": controls})


def page(template, font, family, colors, box, fields):
    """Fill a page template. `font` is the WOFF2 data, `colors` maps CSS
    variable names to (light, dark) values, `box` is editor()'s arguments."""
    style = fill(STYLE, {
        "FAMILY": family,
        "FONT": base64.b64encode(font).decode(),
        "LIGHT": "".join(f" --{name}: {light};" for name, (light, _) in colors.items()),
        "DARK": "".join(f" --{name}: {dark};" for name, (_, dark) in colors.items()),
    })
    return fill(template, {"STYLE": style, "EDITOR": editor(*box), "SCRIPT": SCRIPT, **fields})


def fill(template, fields):
    for name, value in fields.items():
        template = template.replace("{{" + name + "}}", value)
    assert "{{" not in template, "unfilled placeholder"
    return template


def write(path, text):
    Path(path).write_text(text, encoding="utf-8")
    print(f"wrote {path} ({len(text) // 1024} KB)")
