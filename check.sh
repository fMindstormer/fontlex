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
[ $macos = yes ] || echo "(Core Text and WebKit checks skipped: needs macOS and requirements-macos.txt)"
echo "all checks passed"
