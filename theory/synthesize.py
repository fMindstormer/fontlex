"""Search, prove, compile and measure finite annotation machines.

python theory/synthesize.py compile theory/examples/reset-six.json --out /tmp/reset-six
python theory/synthesize.py check source.json candidate.json
"""

import argparse
import json
import random
import sys
from collections import deque
from dataclasses import asdict
from pathlib import Path

from machines import Machine, decompose, equivalent, partition_cost, require_equivalent, search_partitions


def read_machine(path):
    return Machine.from_dict(json.loads(Path(path).read_text()))


def test_words(machine, count=200, seed=0):
    """Reach every reachable transition, then add reproducible longer walks.

    These are engine tests, not the equivalence proof. Displayed words are
    reversed because this backend consumes its input from right to left.
    """
    words, paths, todo = {""}, {machine.start: ()}, deque([machine.start])
    while todo:
        state = todo.popleft()
        for c, symbol in enumerate(machine.alphabet):
            word = paths[state] + (symbol,)
            words.add("".join(reversed(word)))
            nxt = machine.table[state][c]
            if nxt not in paths:
                paths[nxt] = word
                todo.append(nxt)
    rng = random.Random(seed)
    for _ in range(count):
        words.add("".join(rng.choices(machine.alphabet, k=rng.randrange(1, 161))))
    return sorted(words, key=lambda w: (len(w), w))


def compile_machine(machine, *, candidates=3, random_cases=200, seed=0,
                    objective="glyphs", shapers=("harfbuzz",), **limits):
    from machinefont import build, check

    if candidates < 1 or random_cases < 0:
        raise ValueError("candidates must be positive and random cases nonnegative")
    if objective not in ("glyphs", "font_bytes", "gsub_bytes"):
        raise ValueError("unknown objective")
    search = search_partitions(machine.table, **limits)
    words = test_words(machine, random_cases, seed)
    measured, fonts = [], {}
    # The flat baselines reveal when the extra cascade pass costs more than
    # it saves. State cost ranks candidates, actual font metrics choose one.
    choices = [("flat", None)] + [(f"cascade-{i}", p)
                                     for i, p in enumerate(search.partitions[:candidates])]
    for name, partition in choices:
        proof = require_equivalent(machine, machine if partition is None else decompose(machine, partition))
        for encoding in ("variants", "slots"):
            ident = f"{name}-{encoding}"
            print(f"building {ident}", flush=True)
            compiled = build(machine, partition, encoding=encoding)
            engine_checks = check(machine, compiled, words, shapers)
            measured.append(dict(id=ident, partition=partition, encoding=encoding,
                                 state_cost=len(machine.table) if partition is None else partition_cost(partition),
                                 equivalence=asdict(proof), engine_checks=engine_checks, **compiled.metrics))
            fonts[ident] = compiled
    selected = min(measured, key=lambda m: (m[objective], m["font_bytes"], m["id"]))
    report = dict(schema_version=1, machine=machine.to_dict(),
                  semantics="one label per symbol; right-to-left consumption; one printable-ASCII shaping run",
                  search=dict(complete=search.complete, reason=search.reason,
                              partitions=len(search.partitions), pair_checks=search.pair_checks,
                              join_checks=search.join_checks, lower_bound=search.lower_bound,
                              best_state_cost=partition_cost(search.best), state_cost_optimal=search.optimal,
                              optimality_scope="two-component partition cascades over the supplied states; state sum only",
                              limits=limits),
                  validation=dict(seed=seed, random_cases=random_cases, engine_test_words=len(words),
                                  proof_scope="abstract machine output traces on all finite input words",
                                  engine_scope="tested words only; not a proof of the font binary"),
                  candidates=measured, selected=selected["id"], objective=objective,
                  selection_scope="best measured among these candidates; no font-cost optimality claim")
    return fonts[selected["id"]], report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    proof = sub.add_parser("check", help="prove two JSON machines equivalent or show a shortest counterexample")
    proof.add_argument("source", type=Path)
    proof.add_argument("candidate", type=Path)
    proof.add_argument("--max-pairs", type=int, default=1000000)
    comp = sub.add_parser("compile", help="search cascades and compare both font encodings with flat baselines")
    comp.add_argument("machine", type=Path)
    comp.add_argument("--out", type=Path, required=True, help="new output directory (never overwrites a run)")
    comp.add_argument("--candidates", type=int, default=3)
    comp.add_argument("--random-cases", type=int, default=200)
    comp.add_argument("--seed", type=int, default=0)
    comp.add_argument("--objective", choices=("glyphs", "font_bytes", "gsub_bytes"), default="glyphs")
    comp.add_argument("--shaper", action="append", choices=("harfbuzz", "coretext", "directwrite"))
    comp.add_argument("--max-partitions", type=int, default=2000)
    comp.add_argument("--max-pairs", type=int, default=100000)
    comp.add_argument("--max-joins", type=int, default=20000)
    comp.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)
    try:
        if args.command == "check":
            result = equivalent(read_machine(args.source), read_machine(args.candidate), max_pairs=args.max_pairs)
            print(json.dumps(asdict(result), indent=2))
            return 0 if result.equivalent is True else 1 if result.equivalent is False else 2
        if args.out.exists():
            raise ValueError(f"output directory already exists: {args.out}")
        compiled, report = compile_machine(
            read_machine(args.machine), candidates=args.candidates, random_cases=args.random_cases,
            seed=args.seed, objective=args.objective, shapers=args.shaper or ("harfbuzz",),
            max_partitions=args.max_partitions, max_pairs=args.max_pairs,
            max_joins=args.max_joins, workers=args.workers)
        args.out.mkdir(parents=True)
        (args.out / "machine.ttf").write_bytes(compiled.data)
        (args.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        (args.out / "annotations.json").write_text(json.dumps(compiled.annotations, indent=2) + "\n")
        print(f"{report['search']['reason']}; selected {report['selected']} by {report['objective']}")
        print(f"wrote {args.out}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
