#!/bin/sh
# Every font's check, shaped by DirectWrite (Windows): the committed fonts in
# build/, the same checks check.sh runs with HarfBuzz and Core Text.
#   engines/check_directwrite.sh        # needs build/dwshape.exe (or DWSHAPE=...)
#   PYTHON=... N=... as for check.sh
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}
N=${N:-20000}
BASE=fonts/JetBrainsMono-Regular.ttf
S="--shaper directwrite"
status=0
run() { echo "== $1"; shift; "$@" || { echo "FAILED"; status=1; }; }

run "python" "$PY" test_fontlex.py specs/python.yaml build/Fontlex-Python.ttf --base $BASE $S --n "$N"
run "javascript" "$PY" test_fontlex.py specs/javascript.yaml build/Fontlex-JavaScript.ttf --base $BASE $S --n "$N"
run "german" "$PY" test_fontlex.py specs/german.yaml build/Fontlex-German.ttf --base $BASE $S --n "$N"
run "german syllables" "$PY" test_fontlex.py specs/german-syllables.yaml build/Fontlex-German-Syllables.ttf \
    --base $BASE $S --n "$N"
run "math" "$PY" math/verify.py build/Fontlex-Math.ttf $S --n "$N"
run "relaxed math" "$PY" math/verify.py build/Fontlex-RelaxedMath.ttf --relaxed $S --n "$N"
run "english" "$PY" english/verify.py build/Fontlex-English.ttf $S \
    --corpus README.md specs/README.md markdown/README.md theory/README.md
run "french" "$PY" french/verify.py build/Fontlex-French.ttf $S --corpus french/sample.txt
# last: DirectWrite takes far longer on these than on the others
for font in build/Fontlex-Markdown.ttf build/Fontlex-MarkdownSans.ttf; do
    run "markdown: $font" "$PY" markdown/verify.py $font $S --n "$N" \
        --corpus README.md specs/README.md german/README.md german/syllables/README.md markdown/README.md
done
exit $status
