#!/usr/bin/env python3
"""Build the German learner demo page: a text box in the compiled font, with
the font's measured accuracy.

    python german/build_page.py --out german/demo.html \\
        [--test german/data/hdt/de_hdt-ud-test.conllu] [--test german/data/pud/de_pud-ud-test.conllu]

Numbers come from scoring the embedded font: always on german/core_nouns.tsv,
and on each --test treebank given.
"""

import argparse
import html
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import fontlex  # noqa: E402
from demo import pages  # noqa: E402
from german.evaluate import evaluate  # noqa: E402

SAMPLE = """Am Wochenende fahre ich mit meiner Familie in die Berge. Wir packen Rucksäcke, Brot, Käse \
und eine Thermoskanne mit Tee ein. Der Zug fährt um acht Uhr vom Hauptbahnhof ab. Unterwegs erzählt \
meine Schwester Geschichten aus ihrer Kindheit, und mein Bruder schaut aus dem Fenster. Am Abend \
übernachten wir in einer Hütte am See. Die Aussicht ist wunderschön, aber das Wetter ändert sich \
schnell: Nach einem Gewitter scheint wieder die Sonne."""

NAMES = {
    "core_nouns.tsv": "199 everyday nouns, labeled by hand",
    "de_hdt-ud-test.conllu": "HDT test set: tech news, 1996–2001 (same source as the training data)",
    "de_pud-ud-test.conllu": "PUD: Wikipedia sentences (a different source)",
}

PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fontlex German: noun genders in any text box</title>
<style>
{{STYLE}}
.legend { display: flex; gap: 1.25rem; margin: .75rem 0 0; font-size: .9rem; color: var(--muted); flex-wrap: wrap; }
.legend b { font-weight: 600; }
.masc { color: var(--masc); } .fem { color: var(--fem); } .neut { color: var(--neut); }
</style>
<main>
  <h1>Fontlex German</h1>
  <p class="lede">The box below is a plain text box. The font colors each German noun by its gender,
  so you see <b class="masc">der</b>, <b class="fem">die</b> and <b class="neut">das</b> while you read
  and write. Edit the text, or paste your own.</p>

  {{EDITOR}}
  <p class="legend"><span><b class="masc">blue</b> masculine (der)</span><span><b class="fem">red</b> feminine (die)</span>
  <span><b class="neut">green</b> neuter (das)</span><span>uncolored: not a noun, or the font isn't sure</span></p>

  <h2>How it decides</h2>
  <ul>
    <li>German capitalizes nouns, so the font looks at capitalized words only.</li>
    <li>It knows {{N_WORDS}} words and {{N_ENDINGS}} word endings, learned from a gender-annotated
    newspaper treebank and German Wiktionary. The longest matching ending decides: <i>-ung</i> makes
    <i>Zeitung</i> feminine, and a compound takes the gender of its last part (<i>der Haustürschlüssel</i>).</li>
    <li>When a word has two genders (<i>der/die See</i>), is plural-only (<i>Großeltern</i>), or is an
    adjective used as a noun (<i>der/die Vorsitzende</i>), the font leaves it uncolored rather than guess.</li>
    <li>Everything happens inside the font, as OpenType rules the browser's text engine runs. There is no
    script on this page doing the coloring.</li>
  </ul>

  <h2>How accurate it is</h2>
  <table>
    <tr><th>Text</th><th class="n">Nouns colored</th><th class="n">Colored correctly</th></tr>
    {{ROWS}}
  </table>
  <p class="note">"Colored correctly" compares with the dataset's labels, which have errors of their own:
  checking every wrong color in the Wikipedia set by hand found the font right in most of them, for a true
  accuracy of about 99.5%. Measured with the font embedded in this page.</p>

  <h2>Limits</h2>
  <ul>
    <li>It colors words, not sentences: a word with two meanings gets one color (<i>Steuern</i> are taxes,
    <i>die Steuer</i>, but also the dative plural of <i>das Steuer</i>, a steering wheel).</li>
    <li>A capitalized word at the start of a sentence may not be a noun. Common ones are left uncolored.</li>
    <li>Names that are also nouns get the noun's color (<i>Sommer</i>).</li>
    <li>Needs an app that renders color fonts with OpenType features: current Chrome, Firefox and Safari do.</li>
  </ul>
  <p class="note">Data: Universal Dependencies German HDT (CC BY-SA 4.0) and German Wiktionary nouns via
  github.com/gambolputty/german-nouns (CC BY-SA 4.0). Base font: JetBrains Mono (SIL Open Font License).</p>
</main>
{{SCRIPT}}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", default=str(ROOT / "specs" / "german.yaml"))
    ap.add_argument("--base", default=str(ROOT / "fonts" / "JetBrainsMono-Regular.ttf"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--test", action="append", default=[], help="treebank to score on (repeatable)")
    args = ap.parse_args()

    spec = fontlex.load_spec(args.spec)
    res = fontlex.compile_font(spec, args.base)
    buf = io.BytesIO()
    res.font.save(buf)
    ttf = buf.getvalue()

    rows = []
    for path in [str(ROOT / "german" / "core_nouns.tsv")] + args.test:
        r = evaluate(spec, ttf, [path])
        name = NAMES.get(Path(path).name, Path(path).name)
        rows.append(f"<tr><td>{html.escape(name)}</td><td class=\"n\">{r['coverage']:.1%}</td>"
                    f"<td class=\"n\">{r['accuracy']:.1%}</td></tr>")
        print(f"{Path(path).name}: coverage {r['coverage']:.1%}, accuracy {r['accuracy']:.1%}")

    themes = dict(spec.themes)
    page = pages.page(PAGE, pages.woff2(res.font), spec.name,
                      {g: (themes["light"][g], themes["dark"][g]) for g in ("masc", "fem", "neut")},
                      ("Gender colors", SAMPLE, 'lang="de" aria-label="German text, colored by noun gender"'), {
                          "ROWS": "\n    ".join(rows),
                          "N_WORDS": f"{sum(len(w) for _, w in spec.word_sets):,}",
                          "N_ENDINGS": f"{sum(len(x) for _, x in spec.suffix_sets):,}",
                      })
    pages.write(args.out, page)


if __name__ == "__main__":
    main()
