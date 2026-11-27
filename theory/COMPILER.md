# Checked cascade synthesis

The first compiler milestone turns the cascade experiment into a reusable
pipeline: machine → bounded congruence search → equivalence check → font
encodings → real-engine checks → measured selection.

## Run it

From the repository root, after installing `requirements.txt`:

```sh
python theory/synthesize.py compile theory/examples/reset-six.json --out /tmp/fontlex-reset-six
python theory/synthesize.py compile theory/examples/reset-six.json --out /tmp/fontlex-reset-bytes \
  --objective font_bytes --shaper harfbuzz --shaper coretext
python theory/synthesize.py check source.json candidate.json
python -m unittest discover -s tests -p test_cascade.py
```

Core Text needs macOS and `requirements-macos.txt`. HarfBuzz is the default.
The output directory must be new. It contains `machine.ttf`,
`annotations.json` (glyph → original character and output label), and
`report.json` with the input machine, selected candidate, partitions,
search limits, completeness, equivalence results, engine checks and costs.
The font colors each character according to its output label; `null` leaves
its appearance unchanged. The example labels `q0` through `q5` encode the
state before consuming a character, which is determined by the character
to its right.

## Input and scope

Input is a deterministic synchronous transducer: exactly one output label
per input symbol, including `null`. State indices are zero-based. For example:

```json
{
  "alphabet": ["a", "b"],
  "start": 0,
  "transitions": [[1, 0], [0, 0]],
  "outputs": [[null, "even"], [null, "odd"]]
}
```

`transitions[state][symbol_index]` gives the next state;
`outputs[state][symbol_index]` gives the current character's label. This
machine marks `b` according to the parity of the `a`s immediately to its
right. The font consumes the displayed text **right to left**. A counterexample
from `check` is in **consumption order**, so reverse it to display it.

The pure machine model supports arbitrary distinct string symbols. The
font backend supports single printable ASCII characters in **one
left-to-right shaping run**, using the included JetBrains Mono base. Only
strings over the declared alphabet are covered. Run boundaries reset the
machine. There are no epsilon transitions, initial/final outputs, string
replacement, Unicode segmentation model, or positioning outputs in this
milestone. Supplied states are not minimized or trimmed; their count is the
basis of search costs, including unreachable states.

## The search gap and its regression

A transition-compatible partition is an equivalence relation preserved by
every input transition. Merging a single pair of states and propagating
that merge gives a **principal congruence**. There can be other congruences:
take the equivalence closure of the union of two or more principal ones.

`machines.search_partitions` seeds identity and universal partitions, computes
pair closures, then closes the resulting set under joins with the generators.
Every congruence is a join of the pair closures it contains. Thus completing
this enumeration covers all compatible partitions. It does not impose
equal outputs within a block: the back component preserves those distinctions.

`examples/reset-six.json` is a regression for the old search: all six states
are reachable, each symbol resets to a fixed state, and the states have
distinct outputs. Every one of the **203** set partitions is compatible.
The **15** principal partitions have best front-plus-back cost **7**. A
partition into two blocks of three has cost **5**, which the joined search
finds. Its cost meets the lower bound
`min(k + ceil(n/k), k=1..n)`, proving the optimum in this architecture.

Tests independently enumerate set partitions, rather than reusing the search
algorithm. They compare against every two-symbol transition table with up
to three states, plus 50 seeded random tables up to six states, and check
every cascade of the reset example for equivalence.

Defaults bound search to 100,000 pair closures, 20,000 joins and 2,000
partitions. Change these with `--max-pairs`, `--max-joins` and
`--max-partitions`; `--workers` parallelizes pair closures. A stopped search
always reports `complete: false`. It may still prove the minimum state sum
if a candidate meets the counting lower bound. Neither result proves a
minimum font size or an optimum among arbitrary multi-stage decompositions.

## What the checks establish

`machines.equivalent` traverses the reachable synchronized product of two
machines and compares their output labels on each transition. Completion
proves equal output traces on **all finite words**, not just sampled inputs.
A mismatch returns a shortest distinguishing word. Reordered alphabets and
nonzero initial states are supported; unreachable differences do not matter.
A product-state cap returns `equivalent: null` with a reason, never success.
The `check` command exits 0 for equivalence, 1 for a mismatch, and 2 for an
inconclusive result or invalid input.

Compilation requires successful equivalence checking. Tests deliberately
corrupt cascade transitions and labels and verify that the checker rejects
them. This is an exact check implemented in Python, not a proof-assistant
certificate, and it proves the **abstract cascade**, not the generated GSUB
binary or an engine's implementation.

The font check is separate: for every reachable source transition it tests
a word reaching that transition, then adds seeded random words of up to
160 characters. It compares every output character and label in the chosen
shapers, and checks the total advance against the same font with GSUB removed.
Unit tests also exhaust short words and cover spaces, shared input
classes, null labels and nonzero starts. Native engine limits still apply
to longer runs. DirectWrite can be requested on Windows; it has not been
validated for this backend in the initial milestone.

## Measure the target, not just the state sum

The compiler builds flat baselines and the best `--candidates` partitions
(default 3), each with both character variants and separate state slots.
It records total/added glyphs, font bytes, GSUB bytes and lookup count.
`--objective glyphs|font_bytes|gsub_bytes` chooses the best measured candidate;
it does not claim an exhaustive search over font implementations. Ties are
resolved by font bytes and candidate name. No shaping-speed claim is made.

With the pinned dependencies and bundled base font, the reset example gives:

| Construction | Machine state sum | Added glyphs | GSUB bytes | Font bytes |
|---|---:|---:|---:|---:|
| Flat, variants | 6 | 78 | 444 | 168,924 |
| Flat, slots | 6 | 78 | 2,452 | 170,904 |
| Cascade 2 + 3, variants | 5 | 90 | 458 | 169,184 |
| Cascade 2 + 3, slots | 5 | 72 | 2,442 | 170,796 |

All eight default candidates (two baselines and three partitions in two
encodings) passed 236 distinct words each in HarfBuzz and Core Text. Slots
win by glyph count; flat variants win by bytes. Fewer component states alone
do not imply a smaller font.

The existing `cascade.py serial` workload also uses the corrected search
and equivalence gate, while retaining its specialized link-tail emitter and
independent grammar oracle. Its historical 35 + 24 construction remains a
valid measured candidate; the old pair-only search did not certify optimality.
At the default limits the corrected search finds 1,254 partitions on that
364-state workload, stops at the join limit, and still selects 35 + 24.
Equivalence checks all 364 reachable product states. The run reports
**best found**, with a counting lower bound of 39, not a global optimum.

Next work can add better candidate ranking, recursive decompositions and
larger benchmark families on top of this checked baseline. Binary-level
equivalence, full Unicode runs, engine-speed optimization and an experiment
comparing agent-assisted development with hand development remain separate
research tasks.
