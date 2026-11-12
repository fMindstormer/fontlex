"""Random lines of Fontlex Math source, for checking the font against
layout.py: well formed formulas, and the same with characters dropped,
doubled or swapped, the way they look while being typed."""

import random

import layout as L

ATOMS = list("abcdxyzn012349+-=()<>,.'|*/!") + ["\\" + n for n in ("alpha", "pi", "theta", "le", "cdot", "infty", "sum", "to", "pm", "Delta")]


def formula(rng, depth=0):
    """A random well formed expression."""
    out = []
    for _ in range(rng.randint(1, 4 if depth else 6)):
        r = rng.random()
        if depth < 4 and r < 0.12:
            cmd = "binom" if rng.random() < 0.3 else "frac"
            out.append(f"\\{cmd}{{" + formula(rng, depth + 1) + "}{" + formula(rng, depth + 1) + "}")
        elif depth < 4 and r < 0.2:
            out.append("\\sqrt{" + formula(rng, depth + 1) + "}")
        elif depth < 4 and r < 0.24:
            out.append("\\overline{" + formula(rng, depth + 1) + "}")
        elif depth < 4 and r < 0.28:
            accent = rng.choice(sorted(L.ACCENTS))
            out.append(f"\\{accent}{{" + (rng.choice(ATOMS) if rng.random() < 0.6 else formula(rng, depth + 1)) + "}")
        elif depth < 4 and r < 0.4:
            base = rng.choice(ATOMS)
            scripts = rng.sample(["^", "_"], rng.randint(1, 2))
            s = base
            for sc in scripts:
                s += sc + (rng.choice(ATOMS) if rng.random() < 0.5 else "{" + formula(rng, depth + 1) + "}")
            out.append(s)
        elif depth < 4 and r < 0.44:
            out.append("{" + formula(rng, depth + 1) + "}")
        elif r < 0.51 and not depth:
            out.append(" ")
        else:
            out.append(rng.choice(ATOMS))
    return "".join(out)


def mangle(rng, line):
    """Typing in progress: a prefix, or a character dropped, doubled, or a
    space or brace put in."""
    r = rng.random()
    if not line:
        return line
    i = rng.randrange(len(line))
    if r < 0.25:
        return line[:i]
    if r < 0.45:
        return line[:i] + line[i + 1:]
    if r < 0.6:
        return line[:i] + line[i] + line[i:]
    if r < 0.75:
        return line[:i] + " " + line[i:]
    if r < 0.9:
        return line[:i] + rng.choice("{}^_") + line[i:]
    return line[:i] + rng.choice(("\\frac{", "\\binom{")) + line[i:]


def lines(n, seed=1):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        line = formula(rng)
        for _ in range(rng.choice((0, 0, 1, 2))):
            line = mangle(rng, line)
        out.append(line)
    return out


EDGES = [
    "", " ", "x", "\\", "\\frac", "\\frac{", "\\frac{}", "\\frac{}{}", "\\frac{a}", "\\frac{a}{", "\\frac{a}b",
    "\\frac {a}{b}", "\\frac{a} {b}", "\\fracx{a}{b}", "\\frac{a}{b}}", "}{", "^", "_", "x^", "x^^2", "x^ 2",
    "x^{}", "x_{}^{}", "{}", "{{{{{x}}}}}", "{{{{x}}}}", "\\sqrt", "\\sqrt{}", "\\sqrt{x", "\\sqrt x",
    "\\frac{\\frac{\\frac{a}{b}}{c}}{d}", "\\frac{\\frac{a}{b}}{\\frac{c}{d}}", "x^{y^{z^{w}}}",
    "\\sqrt{\\sqrt{\\sqrt{x}}}", "\\sqrt{\\sqrt{\\sqrt{\\sqrt{x}}}}", "\\alpha\\beta", "\\alphabet",
    "\\frac{" + "a" * 30 + "}{b}", "\\sqrt{" + "x" * 40 + "}", "x^" + "\\alpha",
    "\\frac{a}{b}\\frac{c}{d}", "x_1^2_3^4", "x^1_2^3", "a_{b_{c_{d}}}", "\\frac{a^{b}}{c_{d}}",
    "\\over", "\\overline", "\\overline{}", "\\overline{x", "\\overline x", "\\overlinex{a}", "\\overline{x^2}",
    "\\overline{\\overline{\\overline{x}}}", "\\overline{\\overline{\\overline{\\overline{x}}}}",
    "\\sqrt{\\overline{x}}", "\\overline{\\sqrt{x}}", "\\overline{\\frac{a}{b}}", "\\frac{\\overline{a}}{b}",
    "\\hat", "\\hat{", "\\hat{}", "\\hat{x", "\\hat x", "\\hatx{y}", "\\hat{\\alpha}", "\\vec{v}^2", "\\bar{x}_1",
    "\\tilde{\\hat{x}y}", "\\dot{\\ddot{\\vec{x}}}", "\\hat{\\hat{\\hat{\\hat{x}}}}", "\\hat{\\frac{a}{b}}",
    "\\vec{\\frac{\\hat{a}}{b}}", "\\overline{\\hat{x}}", "\\hat{x^{\\bar{2}}}", "\\hat{\\frac{a}{b",
    "\\binom", "\\binom{", "\\binom{n}", "\\binom{n}{", "\\binom{n}{k}", "\\binom {n}{k}", "\\binom{n} {k}",
    "\\binomial{n}{k}", "\\binom{n}k", "\\binom{}{}", "\\binom{n}{k}}", "\\binom{n+1}{k}", "\\binom{n}{k+1}",
    "\\binom{\\binom{a}{b}}{c}", "\\binom{\\frac{a}{b}}{\\frac{c}{d}}", "\\frac{\\binom{a}{b}}{\\binom{c}{d}}",
    "\\binom{\\binom{\\binom{a}{b}}{c}}{d}", "\\sqrt{\\binom{n}{k}}", "\\overline{\\binom{n}{k}}",
    "\\hat{\\binom{n}{k}}", "x^{\\binom{n}{2}}", "\\binom{n}{k}^2", "\\binom{n}{k}\\binom{a}{b}",
    "\\binom{x^2}{y_1}", "\\binom{" + "n" * 30 + "}{k}",
]


# relaxed notation (relaxed.py) -----------------------------------------------

RELAXED_ATOMS = list("abcxyzn0123459+-=<>,.'|*") + ["12", "3.5", "2a", "<=", "->", "+-", "!=", "and", "km", "f"]


def relaxed_operand(rng, depth):
    r = rng.random()
    if depth < 3 and r < 0.3:
        return "(" + relaxed_formula(rng, depth + 1) + ")"
    if depth < 3 and r < 0.38:
        return "sqrt(" + relaxed_formula(rng, depth + 1) + ")"
    if r < 0.43:
        inner = rng.choice(["x", "y", "v", "z", "AB", "θ"]) if rng.random() < 0.7 or depth >= 3 else \
            relaxed_formula(rng, depth + 1)
        return rng.choice(list(L.ACCENTS)) + "(" + inner + ")"
    if r < 0.5:
        return rng.choice("fg") + "(" + relaxed_formula(rng, depth + 1) + ")" if depth < 3 else "x"
    return rng.choice(["a", "b", "x", "y", "n", "1", "2", "12", "3.5", "2a", "3x", "ab"])


def relaxed_formula(rng, depth=0):
    """A random expression in the relaxed notation, with words and slashes
    of the kinds prose has."""
    out = []
    for _ in range(rng.randint(1, 3 if depth else 6)):
        r = rng.random()
        if r < 0.2:
            out.append(relaxed_operand(rng, depth) + "/" + relaxed_operand(rng, depth))
        elif r < 0.35:
            s = relaxed_operand(rng, depth)
            for sc in rng.sample(["^", "_"], rng.randint(1, 2)):
                s += sc + (rng.choice(["2", "n", "i", "12", "-1", "x"]) if rng.random() < 0.6 or depth >= 3
                           else "(" + relaxed_formula(rng, depth + 1) + ")")
            out.append(s)
        elif r < 0.4:
            out.append(relaxed_operand(rng, depth))
        elif r < 0.47 and not depth:
            out.append(" ")
        else:
            out.append(rng.choice(RELAXED_ATOMS))
    return "".join(out)


def relaxed_mangle(rng, line):
    if not line:
        return line
    r, i = rng.random(), rng.randrange(len(line))
    if r < 0.25:
        return line[:i]
    if r < 0.45:
        return line[:i] + line[i + 1:]
    if r < 0.6:
        return line[:i] + line[i] + line[i:]
    if r < 0.75:
        return line[:i] + " " + line[i:]
    return line[:i] + rng.choice("()^_/") + line[i:]


def relaxed_lines(n, seed=1):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        line = relaxed_formula(rng)
        for _ in range(rng.choice((0, 0, 1, 2))):
            line = relaxed_mangle(rng, line)
        out.append(line)
    return out


RELAXED_EDGES = [
    "", " ", "/", "//", "a/", "/b", "a//b", "1/2/3", "(", ")", "()", "()/()", "(a)/", "(a)/(", "(a)/(b",
    "x^", "x^(", "x^()", "x^^2", "x__1", "x^2^3", "x_1_2", "^2", "_1", "sqrt", "sqrt(", "sqrt()", "sqrt(x",
    "sqrtx", "asqrt(x)", "((((x))))", "(((((x)))))", "1/(1/(1/x))", "(1/(1/x))/2", "x^(y^(z^w))",
    "sqrt(sqrt(sqrt(x)))", "sqrt(sqrt(sqrt(sqrt(x))))", "(" + "a" * 30 + ")/b", "w/o", "and/or", "a/b",
    "a+b/c", "C/C++", "1_000", "x_1^2_3", "<=>", "=>", "<==", "x ->0", "(a + b)/2", "1/2 + 1/3",
    "hat", "hat(", "hat()", "hat(x", "hatx", "ahat(x)", "np.dot(x)", "x_dot(y)", "dot(a,b)", "dot(a, b)",
    "vec(AB)", "hat(12)", "hat(x y)", "bar(x_1)", "hat(hat(x))", "x^hat(y)", "hat(x)_1^2", "hat(x)^2/2",
    "vec(v)/(1+hat(x))", "hat(x)y", "tilde(f)(x)", "ddot(x) = -x", "((((hat(x))))", "(((((hat(x)))))",
    "dot(x)/ddot(x)",
]
