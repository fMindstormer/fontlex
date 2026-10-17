#!/bin/sh
# Build everything and run every check this machine can run.
#   ./check.sh            # PYTHON=... to pick the interpreter, N=... random cases
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
N=${N:-20000}
BASE=fonts/JetBrainsMono-Regular.ttf

shapers="--shaper harfbuzz"
macos=no
if "$PY" -c "import CoreText, WebKit" 2>/dev/null; then
    shapers="--shaper harfbuzz --shaper coretext"
    macos=yes
fi

echo "== unit tests"
"$PY" -m unittest discover -s tests

for lang in python javascript; do
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
else
    echo "(German treebank scores skipped: run german/fetch_ud.sh german/data)"
fi
echo "== german syllables: compile"
"$PY" fontlex.py specs/german-syllables.yaml --base $BASE --out build > /dev/null
echo "== german syllables: test ($shapers)"
"$PY" test_fontlex.py specs/german-syllables.yaml build/Fontlex-German-Syllables.ttf --base $BASE $shapers --n "$N"
echo "== german syllables: hand-labeled words"
"$PY" german/syllables/evaluate.py build/Fontlex-German-Syllables.ttf german/syllables/words-heldout.txt
"$PY" german/syllables/build_page.py --out german/syllables/demo.html > /dev/null
if [ $macos = yes ]; then
    echo "== german pages: palettes in WebKit"
    [ -f german/demo.html ] && "$PY" demo/check_webkit.py specs/german.yaml german/demo.html
    "$PY" demo/check_webkit.py specs/german-syllables.yaml german/syllables/demo.html
fi
[ $macos = yes ] || echo "(Core Text and WebKit checks skipped: needs macOS and requirements-macos.txt)"
echo "all checks passed"
