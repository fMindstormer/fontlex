"""Independent finite oracles for search and proof, plus real font execution."""

import contextlib
import io
import itertools
import json
import random
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

THEORY = Path(__file__).resolve().parents[1] / "theory"
sys.path.insert(0, str(THEORY))
from machines import (Equivalence, Machine, closure, decompose, equivalent,
                      partition_cost, require_equivalent, search_partitions)


def partitions(n):
    """Restricted-growth strings: enumerate set partitions without using joins."""
    def extend(prefix):
        if len(prefix) == n:
            yield prefix
        else:
            for label in range(max(prefix, default=-1) + 2):
                yield from extend(prefix + (label,))
    return extend(())


def oracle(table, p):
    return all(p[table[a][c]] == p[table[b][c]]
               for a in range(len(table)) for b in range(len(table)) if p[a] == p[b]
               for c in range(len(table[0])))


def words(alphabet, length):
    return (word for n in range(length + 1) for word in itertools.product(alphabet, repeat=n))


def reset_six():
    return Machine.from_dict(json.loads((THEORY / "examples" / "reset-six.json").read_text()))


class SearchTests(unittest.TestCase):
    def test_missing_joins_regression(self):
        m = reset_six()
        principals = {closure(m.table, a, b) for a, b in itertools.combinations(range(6), 2)}
        self.assertEqual(len(principals), 15)
        self.assertEqual(min(map(partition_cost, principals)), 7)
        result = search_partitions(m.table)
        self.assertTrue(result.complete)
        self.assertEqual(len(result.partitions), 203)
        self.assertEqual(set(result.partitions), set(partitions(6)))
        self.assertEqual(partition_cost(result.best), 5)
        self.assertTrue(result.optimal)
        for p in result.partitions:
            self.assertTrue(equivalent(m, decompose(m, p)).equivalent)

    def test_all_binary_alphabet_tables_up_to_three_states(self):
        for n in range(1, 4):
            for cells in itertools.product(range(n), repeat=2 * n):
                table = tuple(tuple(cells[i:i + 2]) for i in range(0, len(cells), 2))
                expected = {p for p in partitions(n) if oracle(table, p)}
                result = search_partitions(table)
                self.assertTrue(result.complete)
                self.assertEqual(set(result.partitions), expected, table)

    def test_random_tables_against_partition_oracle(self):
        rng = random.Random(42)
        for _ in range(50):
            n = rng.randrange(2, 7)
            table = tuple(tuple(rng.randrange(n) for _ in range(3)) for _ in range(n))
            result = search_partitions(table, max_joins=100000)
            self.assertTrue(result.complete)
            self.assertEqual(set(result.partitions), {p for p in partitions(n) if oracle(table, p)})

    def test_limits_never_claim_complete(self):
        m = reset_six()
        for limit in ({"max_pairs": 1}, {"max_partitions": 2}, {"max_joins": 1}):
            result = search_partitions(m.table, **limit)
            self.assertFalse(result.complete)
            self.assertFalse(result.optimal)
            self.assertTrue(all(oracle(m.table, p) for p in result.partitions))
        # A bound can prove the state-sum optimum without enumerating all ties.
        result = search_partitions(m.table, max_partitions=100)
        self.assertFalse(result.complete)
        self.assertTrue(result.optimal)

    def test_degenerate_and_prime_cycle(self):
        one = search_partitions(((0,),))
        self.assertEqual(one.partitions, ((0,),))
        self.assertTrue(one.complete)
        cycle = search_partitions(((1,), (2,), (3,), (4,), (0,)))
        self.assertEqual(len(cycle.partitions), 2)
        self.assertTrue(cycle.complete)

    def test_invalid_input(self):
        for table in ((), ((),), ((1,),), ((0,), (0, 1)), ((True,),)):
            with self.assertRaises(ValueError):
                search_partitions(table)
        for limit in ({"max_pairs": 0}, {"max_partitions": 1}, {"workers": 0}, {"max_joins": -1}):
            with self.assertRaises(ValueError):
                search_partitions(((0,),), **limit)


class EquivalenceTests(unittest.TestCase):
    def test_shortest_counterexample(self):
        m = Machine(("a", "b"), ((1, 0), (2, 0), (2, 0)), ((None, None),) * 3)
        changed = replace(m, outputs=((None, None), (None, None), ("bad", None)))
        result = equivalent(m, changed)
        self.assertFalse(result.equivalent)
        self.assertEqual(result.counterexample, ("a", "a", "a"))
        self.assertNotEqual(m.trace(result.counterexample), changed.trace(result.counterexample))
        for w in words(m.alphabet, 2):
            self.assertEqual(m.trace(w), changed.trace(w))

    def test_nonzero_start_reordered_alphabet_and_unreachable_states(self):
        m = Machine(("a", "b"), ((0, 0), (1, 1)), (("unused", None), ("x", "y")), 1)
        same = Machine(("b", "a"), ((0, 0), (1, 1)), (("changed", "ignored"), ("y", "x")), 1)
        proof = equivalent(m, same)
        self.assertTrue(proof.equivalent)
        self.assertEqual(proof.visited, 1)
        self.assertTrue(require_equivalent(m, decompose(m, (0, 0))).equivalent)
        with self.assertRaises(ValueError):
            equivalent(m, Machine(("c",), ((0,),), ((None,),)))

    def test_inconclusive_is_not_equivalent(self):
        m = reset_six()
        limited = equivalent(m, m, max_pairs=1)
        self.assertIsNone(limited.equivalent)
        self.assertIsNone(limited.counterexample)
        with patch("machines.equivalent", return_value=limited):
            with self.assertRaisesRegex(ValueError, "not established"):
                require_equivalent(m, m)

    def test_corrupted_cascade(self):
        m = reset_six()
        cascade = decompose(m, (0, 0, 0, 1, 1, 1))
        changed = replace(cascade, front=((1, 1, 1, 0, 0, 0),) * 2)
        proof = equivalent(m, changed)
        self.assertFalse(proof.equivalent)
        self.assertEqual(len(proof.counterexample), 2)
        back = [[list(row) for row in local] for local in cascade.back]
        back[0][0][0] = (0, "incorrect")
        self.assertEqual(equivalent(m, replace(cascade, back=back)).counterexample, ("a",))
        back[0][0][0] = None
        self.assertFalse(equivalent(m, replace(cascade, back=back)).equivalent)
        with self.assertRaises(ValueError):
            decompose(Machine(("a",), ((1,), (2,), (0,)), ((None,),) * 3), (0, 0, 1))

    def test_json_validation(self):
        m = reset_six()
        self.assertEqual(Machine.from_dict(m.to_dict()), m)
        self.assertEqual(Machine.from_dict(json.loads(json.dumps(m.to_dict()))), m)
        for bad in ({}, [], {"extra": 1}, dict(m.to_dict(), start=-1),
                    dict(m.to_dict(), alphabet="abcdef"), dict(m.to_dict(), outputs=None)):
            with self.assertRaises(ValueError):
                Machine.from_dict(bad)


class FontTests(unittest.TestCase):
    def test_both_encodings_flat_and_cascade(self):
        from machinefont import build, check
        m = reset_six()
        texts = ["".join(w) for w in words(m.alphabet, 3)]
        for p in (None, (0, 0, 0, 1, 1, 1), (0, 0, 0, 1, 1, 2)):
            for encoding in ("variants", "slots"):
                compiled = build(m, p, encoding=encoding)
                self.assertEqual(check(m, compiled, texts), {"harfbuzz": len(texts)})

    def test_spaces_shared_columns_null_labels_and_nonzero_start(self):
        from machinefont import build, check
        m = Machine(tuple("ab "), ((1, 1, 0), (0, 0, 0)), ((None, None, "space"), ("word", "word", None)), 1)
        texts = ["".join(w) for w in words(m.alphabet, 4)]
        for p in (None, (0, 1), (0, 0)):
            for encoding in ("variants", "slots"):
                compiled = build(m, p, encoding=encoding)
                self.assertEqual(check(m, compiled, texts), {"harfbuzz": len(texts)})

    def test_backend_rejects_unproved_or_unsupported_inputs(self):
        from machinefont import build
        m = reset_six()
        with patch("machines.equivalent", return_value=Equivalence(None, None, 1, "limit")):
            with self.assertRaisesRegex(ValueError, "not established"):
                build(m, (0, 0, 0, 1, 1, 1))
        with self.assertRaisesRegex(ValueError, "ASCII"):
            build(Machine(("é",), ((0,),), ((None,),)))

    def test_one_state_without_annotations(self):
        from machinefont import build, check
        m = Machine(("a", " "), ((0, 0),), ((None, None),))
        for encoding in ("variants", "slots"):
            self.assertEqual(check(m, build(m, (0,), encoding=encoding), ("", " a a ")),
                             {"harfbuzz": 2})

    def test_cli_exports_report_and_will_not_overwrite(self):
        from synthesize import main
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            wrong = Path(tmp) / "wrong.json"
            wrong.write_text(json.dumps(replace(reset_six(), outputs=(("wrong",) * 6,) * 6).to_dict()))
            args = ["compile", str(THEORY / "examples" / "reset-six.json"), "--out", str(out),
                    "--candidates", "1", "--random-cases", "3"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 0)
                self.assertEqual(main(args), 2)
                self.assertEqual(main(["check", str(THEORY / "examples" / "reset-six.json"),
                                       str(THEORY / "examples" / "reset-six.json")]), 0)
                self.assertEqual(main(["check", str(THEORY / "examples" / "reset-six.json"),
                                       str(THEORY / "examples" / "reset-six.json"), "--max-pairs", "1"]), 2)
                self.assertEqual(main(["check", str(THEORY / "examples" / "reset-six.json"), str(wrong)]), 1)
            report = json.loads((out / "report.json").read_text())
            self.assertTrue(report["search"]["complete"])
            self.assertEqual(report["search"]["partitions"], 203)
            self.assertEqual(len(report["candidates"]), 4)
            self.assertTrue(all(c["equivalence"]["equivalent"] for c in report["candidates"]))
            self.assertTrue((out / "machine.ttf").stat().st_size > 0)


if __name__ == "__main__":
    unittest.main()
