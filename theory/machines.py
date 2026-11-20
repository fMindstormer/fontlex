"""Finite, synchronous transducers and checked two-component cascades.

No font or solver dependencies. One input symbol produces one output label,
including None (no annotation). Words are in consumption order; a font that
scans right to left consumes the reverse of the displayed text.
"""

from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from itertools import combinations, islice


def validate_table(table):
    if not table or not table[0]:
        raise ValueError("a machine needs states and a nonempty alphabet")
    n, width = len(table), len(table[0])
    if any(len(row) != width for row in table):
        raise ValueError("transition rows must have the same length")
    if any(type(t) is not int or not 0 <= t < n for row in table for t in row):
        raise ValueError("transition targets must be state indices")


@dataclass(frozen=True)
class Machine:
    alphabet: tuple
    table: tuple
    outputs: tuple
    start: int = 0

    def __post_init__(self):
        object.__setattr__(self, "alphabet", tuple(self.alphabet))
        object.__setattr__(self, "table", tuple(tuple(row) for row in self.table))
        object.__setattr__(self, "outputs", tuple(tuple(row) for row in self.outputs))
        validate_table(self.table)
        if (any(not isinstance(c, str) or not c for c in self.alphabet)
                or len(set(self.alphabet)) != len(self.alphabet)
                or len(self.alphabet) != len(self.table[0])):
            raise ValueError("alphabet must contain one distinct nonempty string per column")
        if type(self.start) is not int or not 0 <= self.start < len(self.table):
            raise ValueError("start must be a state index")
        if (len(self.outputs) != len(self.table)
                or any(len(row) != len(self.alphabet) for row in self.outputs)):
            raise ValueError("outputs must have the same shape as transitions")
        if any(o is not None and not isinstance(o, str) for row in self.outputs for o in row):
            raise ValueError("output labels must be strings or null")

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {"alphabet", "transitions", "outputs", "start"}:
            raise ValueError("expected alphabet, transitions, outputs and optional start")
        try:
            if (any(not isinstance(data[k], list) for k in ("alphabet", "transitions", "outputs"))
                    or any(not isinstance(row, list) for k in ("transitions", "outputs") for row in data[k])):
                raise ValueError("alphabet, transitions and outputs must be JSON arrays")
            return cls(data["alphabet"], data["transitions"], data["outputs"], data.get("start", 0))
        except (KeyError, TypeError) as exc:
            raise ValueError("malformed machine: expected alphabet, transitions and outputs arrays") from exc

    def to_dict(self):
        return dict(alphabet=list(self.alphabet), transitions=[list(row) for row in self.table],
                    outputs=[list(row) for row in self.outputs], start=self.start)

    def step(self, state, symbol):
        return self.table[state][symbol], self.outputs[state][symbol]

    def trace(self, word):
        state, out = self.start, []
        indices = {c: i for i, c in enumerate(self.alphabet)}
        for c in word:
            state, label = self.step(state, indices[c])
            out.append(label)
        return tuple(out)


def canonical(labels):
    numbers = {}
    return tuple(numbers.setdefault(x, len(numbers)) for x in labels)


def partition_cost(labels):
    sizes = Counter(labels)
    return len(sizes) + max(sizes.values())


def compatible(table, labels):
    """Whether the partition respects every transition (outputs may differ)."""
    if len(labels) != len(table):
        return False
    rows = {}
    for s, row in enumerate(table):
        image = tuple(labels[t] for t in row)
        if rows.setdefault(labels[s], image) != image:
            return False
    return True


def closure(table, s, t):
    """The least transition-compatible equivalence identifying s and t."""
    parent = list(range(len(table)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    todo = [(s, t)]
    while todo:
        a, b = (find(x) for x in todo.pop())
        if a != b:
            parent[b] = a
            todo.extend(zip(table[a], table[b]))
    return canonical(find(x) for x in range(len(table)))


def join(a, b):
    """Join of two equivalence relations; congruences stay congruences."""
    if len(a) != len(b):
        raise ValueError("partitions have different sizes")
    parent = list(range(len(a)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for labels in (a, b):
        representatives = {}
        for s, block in enumerate(labels):
            parent[find(s)] = find(representatives.setdefault(block, s))
    return canonical(find(x) for x in range(len(a)))


def _pair_closures(table, pairs):
    return {closure(table, s, t) for s, t in pairs}


@dataclass(frozen=True)
class SearchResult:
    partitions: tuple
    complete: bool
    reason: str
    pair_checks: int
    join_checks: int
    lower_bound: int

    @property
    def best(self):
        return self.partitions[0]

    @property
    def optimal(self):
        # Only the sum of component state counts in this partition-based
        # architecture, never font size, shaping time, or arbitrary cascades.
        return self.complete or partition_cost(self.best) == self.lower_bound


def search_partitions(table, *, max_partitions=2000, max_pairs=100000, max_joins=20000, workers=1):
    """All congruences are joins of principal (pair-generated) congruences.

    Seed with the principal congruences, then close under joins. Limits bound
    work; hitting one never turns a partial search into a proof of optimality.
    Identity and universal partitions provide valid fallbacks even at a cap.
    """
    validate_table(table)
    if any(type(v) is not int or v < minimum for v, minimum in
           ((max_partitions, 2), (max_pairs, 1), (max_joins, 1), (workers, 1))):
        raise ValueError("limits must be positive integers (max_partitions at least 2)")
    n = len(table)
    lower = min(k + (n + k - 1) // k for k in range(1, n + 1))
    found = {tuple(range(n)), (0,) * n}
    pairs = list(islice(combinations(range(n), 2), max_pairs))
    reasons, joins = [], 0
    if len(pairs) < n * (n - 1) // 2:
        reasons.append("pair limit")
    # Bounded batches keep temporary principal partitions bounded too.
    pool = ProcessPoolExecutor(workers) if workers > 1 and pairs else None
    try:
        for offset in range(0, len(pairs), 128 * workers):
            batch = pairs[offset:offset + 128 * workers]
            chunks = [batch[i::workers] for i in range(workers)]
            results = pool.map(_pair_closures, [table] * workers, chunks) if pool else [_pair_closures(table, batch)]
            candidates = sorted(set().union(*results))
            for p in candidates:
                if p not in found:
                    if len(found) == max_partitions:
                        reasons.append("partition limit")
                        break
                    found.add(p)
            if "partition limit" in reasons:
                pairs = pairs[:offset + len(batch)]
                break
    finally:
        if pool:
            pool.shutdown()

    generators = sorted(found)
    todo = list(generators)
    if "partition limit" not in reasons:
        for a in todo:
            for b in generators:
                if joins == max_joins:
                    reasons.append("join limit")
                    break
                joins += 1
                p = join(a, b)
                if p not in found:
                    if len(found) == max_partitions:
                        reasons.append("partition limit")
                        break
                    found.add(p)
                    todo.append(p)
            if "join limit" in reasons or "partition limit" in reasons:
                break
    ordered = tuple(sorted(found, key=lambda p: (partition_cost(p), len(set(p)), p)))
    return SearchResult(ordered, not reasons, ", ".join(reasons) or "all congruences enumerated",
                        len(pairs), joins, lower)


@dataclass(frozen=True)
class Cascade:
    alphabet: tuple
    front: tuple                     # [block][symbol] -> next block
    back: tuple                      # [local index][block][symbol] -> (next local, output) or None
    start: tuple
    partition: tuple

    def step(self, state, symbol):
        block, local = state
        if not 0 <= block < len(self.front) or not 0 <= local < len(self.back):
            raise ValueError("invalid cascade state")
        cell = self.back[local][block][symbol]
        if cell is None:
            raise ValueError("undefined back transition")
        nxt, out = cell
        return (self.front[block][symbol], nxt), out


def decompose(machine, labels):
    labels = tuple(labels)
    if any(type(x) is not int or x < 0 for x in labels):
        raise ValueError("partition labels must be nonnegative integers")
    labels = canonical(labels)
    if not compatible(machine.table, labels):
        raise ValueError("partition does not respect transitions")
    members = [[] for _ in range(max(labels) + 1)]
    for s, block in enumerate(labels):
        members[block].append(s)
    local = {s: i for block in members for i, s in enumerate(block)}
    front = tuple(tuple(labels[t] for t in machine.table[ss[0]]) for ss in members)
    back = tuple(tuple(tuple((local[machine.table[ss[i]][c]], machine.outputs[ss[i]][c])
                             if i < len(ss) else None for c in range(len(machine.alphabet)))
                       for ss in members) for i in range(max(map(len, members))))
    return Cascade(machine.alphabet, front, back, (labels[machine.start], local[machine.start]), labels)


@dataclass(frozen=True)
class Equivalence:
    equivalent: bool | None
    counterexample: tuple | None
    visited: int
    reason: str


def equivalent(left, right, *, max_pairs=1000000):
    """BFS of the reachable product; a shortest distinguishing input or proof.

    A completed traversal proves equality of output traces for all finite
    words in consumption order. A resource cap returns None, not True.
    This checks machine semantics, not font binaries or shaping engines.
    """
    if type(max_pairs) is not int or max_pairs < 1:
        raise ValueError("max_pairs must be positive")
    if set(left.alphabet) != set(right.alphabet):
        raise ValueError("machines have different alphabets")
    right_columns = [right.alphabet.index(c) for c in left.alphabet]
    start = (left.start, right.start)
    parents, todo = {start: None}, deque([start])

    def witness(state, last):
        word = [last]
        while parents[state] is not None:
            state, c = parents[state]
            word.append(c)
        return tuple(reversed(word))

    while todo:
        pair = todo.popleft()
        for c, symbol in enumerate(left.alphabet):
            try:
                lnext, lout = left.step(pair[0], c)
                rnext, rout = right.step(pair[1], right_columns[c])
            except (ValueError, IndexError) as exc:
                return Equivalence(False, witness(pair, symbol), len(parents), str(exc))
            if lout != rout:
                return Equivalence(False, witness(pair, symbol), len(parents), "different output labels")
            nxt = (lnext, rnext)
            if nxt not in parents:
                if len(parents) == max_pairs:
                    return Equivalence(None, None, len(parents), "product-state limit")
                parents[nxt] = (pair, symbol)
                todo.append(nxt)
    return Equivalence(True, None, len(parents), "all reachable product states checked")


def require_equivalent(machine, candidate):
    result = equivalent(machine, candidate)
    if result.equivalent is not True:
        raise ValueError(f"equivalence not established: {result.reason}; counterexample={result.counterexample!r}")
    return result
