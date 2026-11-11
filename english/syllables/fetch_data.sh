#!/bin/sh
# The Moby Hyphenation List (Grady Ward, public domain): about 187,000 words
# and phrases split into syllables. Project Gutenberg etext 3204.
#   english/syllables/fetch_data.sh [DIR]     (default english/syllables/data)
set -e
dir=${1:-$(dirname "$0")/data}
mkdir -p "$dir"
curl -sSfL -o "$dir/mhyph.txt" https://www.gutenberg.org/files/3204/files/mhyph.txt
echo "wrote $dir/mhyph.txt"
