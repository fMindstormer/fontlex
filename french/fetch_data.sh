#!/bin/bash
# Fetch what french/align.py reads into DIR (it isn't in the repository):
#   DIR/Lexique383.tsv  Lexique 3.83 (CC BY-SA 4.0), http://www.lexique.org
#   DIR/h_aspire.txt    French Wiktionary's "Termes en français à h aspiré" (CC BY-SA 4.0)
#
#   french/fetch_data.sh french/data
set -e
dir=${1:?usage: fetch_data.sh DIR}
mkdir -p "$dir"
curl -sSL -o "$dir/Lexique383.tsv" http://www.lexique.org/databases/Lexique383/Lexique383.tsv
: > "$dir/h_aspire.json"
cont=""
while :; do
    args=(-sS -A "fontlex-data-script/0.1" -G "https://fr.wiktionary.org/w/api.php"
          --data-urlencode "action=query" --data-urlencode "list=categorymembers"
          --data-urlencode "cmtitle=Catégorie:Termes en français à h aspiré" --data-urlencode "cmlimit=500"
          --data-urlencode "cmnamespace=0" --data-urlencode "format=json")
    [ -n "$cont" ] && args+=(--data-urlencode "cmcontinue=$cont")
    page=$(curl "${args[@]}")
    echo "$page" >> "$dir/h_aspire.json"
    cont=$(printf '%s' "$page" | grep -o '"cmcontinue":"[^"]*"' | head -1 | sed 's/"cmcontinue":"//; s/"$//')
    [ -z "$cont" ] && break
    sleep 1
done
python3 -I -c 'import json, sys
titles = [m["title"] for l in open(sys.argv[1]) if l.strip() for m in json.loads(l)["query"]["categorymembers"]]
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(titles) + "\n")
print(len(titles), "h aspiré terms")' "$dir/h_aspire.json" "$dir/h_aspire.txt"
