#!/bin/sh
# Download the Universal Dependencies treebanks the German gender prototype
# learns from (HDT train/dev/test) and is tested on (HDT test, PUD).
#   german/fetch_ud.sh DIR
# Licenses: HDT annotations CC BY-SA 4.0 (text: academic use), PUD CC BY-SA 3.0.
set -e
dir=${1:?usage: fetch_ud.sh DIR}
base=https://raw.githubusercontent.com/UniversalDependencies
mkdir -p "$dir/hdt" "$dir/pud"
for f in train-a-1 train-a-2 train-b-1 train-b-2 dev test; do
    curl -fsSL -o "$dir/hdt/de_hdt-ud-$f.conllu" "$base/UD_German-HDT/master/de_hdt-ud-$f.conllu"
done
curl -fsSL -o "$dir/pud/de_pud-ud-test.conllu" "$base/UD_German-PUD/master/de_pud-ud-test.conllu"
ls -l "$dir"/hdt "$dir"/pud
