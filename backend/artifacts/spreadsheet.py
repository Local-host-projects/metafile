"""
Spreadsheet artifact: a grid of cells, each either a literal value or a
formula starting with "=". Formulas are evaluated with a hand-rolled
recursive-descent parser -- deliberately NOT Python eval(), because
this runs on content that arrives over a public, capability-URL-authed
endpoint. Supports: + - * / ( ), numeric literals, cell refs (A1),
ranges (A1:A5) inside SUM/AVERAGE/MIN/MAX/COUNT.
"""
import re

CELL_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def col_to_index(col: str) -> int:
    idx = 0
    for ch in col.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def parse_ref(ref: str):
    m = CELL_RE.match(ref.strip())
    if not m:
        raise ValueError(f"Bad cell reference: {ref}")
    return col_to_index(m.group(1)), int(m.group(2)) - 1  # (col, row) 0-indexed


def cells_in_range(a: str, b: str):
    (c1, r1), (c2, r2) = parse_ref(a), parse_ref(b)
    lo_c, hi_c = min(c1, c2), max(c1, c2)
    lo_r, hi_r = min(r1, r2), max(r1, r2)
    out = []
    for r in range(lo_r, hi_r + 1):
        for c in range(lo_c, hi_c + 1):
            out.append(index_to_ref(c, r))
    return out


def index_to_ref(col: int, row: int) -> str:
    col += 1
    letters = ""
    while col > 0:
        col, rem = divmod(col - 1, 26)
        letters = chr(65 + rem) + letters
    return f"{letters}{row + 1}"


class FormulaError(Exception):
    pass


_TOKEN_RE = re.compile(r"""
    \s*(?:
        (?P<num>\d+\.?\d*)
      | (?P<func>SUM|AVERAGE|MIN|MAX|COUNT)\(
      | (?P<ref>[A-Za-z]+\d+)
      | (?P<op>[+\-*/(),:])
    )
""", re.VERBOSE | re.IGNORECASE)


def tokenize(formula: str):
    pos, out = 0, []
    while pos < len(formula):
        m = _TOKEN_RE.match(formula, pos)
        if not m or m.end() == pos:
            if formula[pos:].strip() == "":
                break
            raise FormulaError(f"Bad token near: {formula[pos:pos+10]!r}")
        pos = m.end()
        if m.group("num") is not None:
            out.append(("num", float(m.group("num"))))
        elif m.group("func") is not None:
            out.append(("func", m.group("func").upper()))
        elif m.group("ref") is not None:
            out.append(("ref", m.group("ref").upper()))
        elif m.group("op") is not None:
            out.append(("op", m.group("op")))
    return out


class Parser:
    """Recursive descent: expr := term (('+'|'-') term)*; term := factor (('*'|'/') factor)*"""

    def __init__(self, tokens, resolve_ref):
        self.tokens = tokens
        self.i = 0
        self.resolve_ref = resolve_ref  # fn(cell_ref) -> float

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse(self):
        val = self.expr()
        if self.peek() is not None:
            raise FormulaError("Unexpected trailing tokens")
        return val

    def expr(self):
        val = self.term()
        while self.peek() and self.peek()[0] == "op" and self.peek()[1] in "+-":
            op = self.next()[1]
            rhs = self.term()
            val = val + rhs if op == "+" else val - rhs
        return val

    def term(self):
        val = self.factor()
        while self.peek() and self.peek()[0] == "op" and self.peek()[1] in "*/":
            op = self.next()[1]
            rhs = self.factor()
            if op == "/":
                if rhs == 0:
                    raise FormulaError("Division by zero")
                val = val / rhs
            else:
                val = val * rhs
        return val

    def factor(self):
        tok = self.peek()
        if tok is None:
            raise FormulaError("Unexpected end of formula")
        if tok[0] == "op" and tok[1] == "-":
            self.next()
            return -self.factor()
        if tok[0] == "op" and tok[1] == "(":
            self.next()
            val = self.expr()
            close = self.next()
            if not close or close != ("op", ")"):
                raise FormulaError("Missing closing paren")
            return val
        if tok[0] == "num":
            self.next()
            return tok[1]
        if tok[0] == "ref":
            self.next()
            return self.resolve_ref(tok[1])
        if tok[0] == "func":
            return self.func_call()
        raise FormulaError(f"Unexpected token: {tok}")

    def func_call(self):
        fname = self.next()[1]  # already consumed the '(' via regex on func token
        args_refs = []
        # arguments are either single refs or ref:ref ranges, comma separated
        while True:
            tok = self.next()
            if tok is None:
                raise FormulaError("Unterminated function call")
            if tok[0] == "ref":
                first = tok[1]
                nxt = self.peek()
                if nxt and nxt == ("op", ":"):
                    self.next()
                    second = self.next()[1]
                    args_refs.extend(cells_in_range(first, second))
                else:
                    args_refs.append(first)
            elif tok[0] == "num":
                args_refs.append(None)  # literal handled below via closure trick
            close_or_comma = self.peek()
            if close_or_comma and close_or_comma == ("op", ","):
                self.next()
                continue
            if close_or_comma and close_or_comma == ("op", ")"):
                self.next()
                break
            raise FormulaError("Malformed function arguments")

        values = [self.resolve_ref(r) for r in args_refs if r is not None]
        if fname == "SUM":
            return sum(values)
        if fname == "AVERAGE":
            return sum(values) / len(values) if values else 0.0
        if fname == "MIN":
            return min(values) if values else 0.0
        if fname == "MAX":
            return max(values) if values else 0.0
        if fname == "COUNT":
            return float(len(values))
        raise FormulaError(f"Unknown function {fname}")


def evaluate_grid(cells: dict) -> dict:
    """
    cells: {"A1": {"formula": "=B1+1"} or {"value": "10"}, ...}
    Returns {"A1": <evaluated float or original string>, ...}
    Formula cells are evaluated lazily with cycle detection.
    """
    computed = {}
    in_progress = set()

    def resolve(ref: str):
        ref = ref.upper()
        if ref in computed:
            return computed[ref]
        if ref in in_progress:
            raise FormulaError(f"Circular reference at {ref}")
        cell = cells.get(ref)
        if cell is None:
            return 0.0
        in_progress.add(ref)
        try:
            if cell.get("formula"):
                tokens = tokenize(cell["formula"].lstrip("="))
                val = Parser(tokens, resolve).parse()
            else:
                raw = cell.get("value", "")
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    val = raw
        finally:
            in_progress.discard(ref)
        computed[ref] = val
        return val

    for ref in cells:
        resolve(ref)
    return computed
