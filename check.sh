#!/bin/sh
# Build everything and run every check this machine can run.
#   ./check.sh                    # every section
#   ./check.sh markdown german    # some: unit python javascript german syllables markdown theory
#   PYTHON=... to pick the interpreter, N=... random cases
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
N=${N:-20000}
BASE=fonts/JetBrainsMono-Regular.ttf
SECTIONS="unit python javascript german syllables markdown theory"
want=${*:-$SECTIONS}
for s in $want; do
    case " $SECTIONS " in *" $s "*) ;; *) echo "unknown section: $s (sections: $SECTIONS)" >&2; exit 2 ;; esac
done
wants() { case " $want " in *" $1 "*) return 0 ;; esac; return 1; }

shapers="--shaper harfbuzz"
macos=no
if "$PY" -c "import CoreText, WebKit" 2>/dev/null; then
    shapers="--shaper harfbuzz --shaper coretext"
    macos=yes
fi

if wants unit; then
    echo "== unit tests"
    "$PY" -m unittest discover -s tests
fi

for lang in python javascript; do
    wants $lang || continue
    case $lang in python) font=build/Fontlex-Python ;; javascript) font=build/Fontlex-JavaScript ;; esac
    echo "== $lang: compile"
    "$PY" fontlex.py specs/$lang.yaml --base $BASE --out build > /dev/null
    echo "== $lang: test ($shapers)"
    "$PY" test_fontlex.py specs/$lang.yaml "$font.ttf" --base $BASE $shapers --n "$N"
    page=demo/fontlex-demo.html
    [ $lang = python ] || page=demo/fontlex-demo-$lang.html
    echo "== $lang: demo page"
    "$PY" demo/build_demo.py specs/$lang.yaml --base $BASE --out $page --fuzz "$N" > /dev/null
    if [ $macos = yes ]; then
        echo "== $lang: demo palettes in WebKit"
        "$PY" demo/check_webkit.py specs/$lang.yaml $page
    fi
done

if wants german; then
    echo "== german: compile"
    "$PY" fontlex.py specs/german.yaml --base $BASE --out build > /dev/null
    echo "== german: test ($shapers)"
    "$PY" test_fontlex.py specs/german.yaml build/Fontlex-German.ttf --base $BASE $shapers --n "$N"
    echo "== german: everyday nouns"
    "$PY" german/evaluate.py specs/german.yaml build/Fontlex-German.ttf german/core_nouns.tsv | sed -n 2,4p
    hdt=german/data/hdt/de_hdt-ud-test.conllu pud=german/data/pud/de_pud-ud-test.conllu
    if [ -f $hdt ] && [ -f $pud ]; then
        echo "== german: treebanks and demo page"
        "$PY" german/build_page.py --out german/demo.html --test $hdt --test $pud
        if [ $macos = yes ]; then
            echo "== german: demo palettes in WebKit"
            "$PY" demo/check_webkit.py specs/german.yaml german/demo.html
        fi
    else
        echo "(German treebank scores and demo page skipped: run german/fetch_ud.sh german/data)"
    fi
fi

if wants syllables; then
    echo "== german syllables: compile"
    "$PY" fontlex.py specs/german-syllables.yaml --base $BASE --out build > /dev/null
    echo "== german syllables: test ($shapers)"
    "$PY" test_fontlex.py specs/german-syllables.yaml build/Fontlex-German-Syllables.ttf --base $BASE $shapers --n "$N"
    echo "== german syllables: hand-labeled words"
    "$PY" german/syllables/evaluate.py build/Fontlex-German-Syllables.ttf german/syllables/words-heldout.txt
    echo "== german syllables: demo page"
    "$PY" german/syllables/build_page.py --out german/syllables/demo.html > /dev/null
    if [ $macos = yes ]; then
        echo "== german syllables: demo palettes in WebKit"
        "$PY" demo/check_webkit.py specs/german-syllables.yaml german/syllables/demo.html
    fi
fi

if wants markdown; then
    mono="fonts/JetBrainsMono-Regular.ttf fonts/JetBrainsMono-Bold.ttf fonts/JetBrainsMono-Italic.ttf fonts/JetBrainsMono-BoldItalic.ttf"
    echo "== markdown: compile"
    "$PY" markdown/mdfont.py --base $BASE --bold fonts/JetBrainsMono-Bold.ttf --italic fonts/JetBrainsMono-Italic.ttf \
        --bold-italic fonts/JetBrainsMono-BoldItalic.ttf --out build > /dev/null
    echo "== markdown: compile the proportional edition"
    "$PY" markdown/mdfont.py --base fonts/NotoSans-Regular.ttf --bold fonts/NotoSans-Bold.ttf \
        --italic fonts/NotoSans-Italic.ttf --bold-italic fonts/NotoSans-BoldItalic.ttf --mono $mono \
        --family "Fontlex Markdown Sans" --out build > /dev/null
    for font in build/Fontlex-Markdown.ttf build/Fontlex-MarkdownSans.ttf; do
        echo "== markdown: test $font ($shapers)"
        "$PY" markdown/verify.py $font $shapers --n "$N" \
            --corpus README.md german/README.md german/syllables/README.md markdown/README.md
    done
    echo "== markdown: demo page"
    "$PY" markdown/build_page.py --font build/Fontlex-Markdown.ttf --sans build/Fontlex-MarkdownSans.ttf \
        --out markdown/demo.html --n "$N" > /dev/null
    if [ $macos = yes ]; then
        echo "== markdown: demo page in WebKit"
        "$PY" markdown/check_webkit.py markdown/demo.html
    fi
fi

if wants theory; then
    echo "== theory: bracket matching as deep as the rounds ($shapers)"
    "$PY" theory/depth.py --distinct --rounds 10 300 $shapers
    echo "== theory: HarfBuzz's coverage cache (ids 32512-32767 read aaa where HarfBuzz 13+ has the bug)"
    "$PY" theory/hbcache.py
fi

[ $macos = yes ] || echo "(Core Text and WebKit checks skipped: needs macOS and requirements-macos.txt)"
echo "all checks passed"
