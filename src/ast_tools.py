"""Phase 5 — the formula parser, evaluator, and tree analysis.

Formulas are **strings**, parsed with Python's ``ast`` module under a strict
whitelist and never ``eval``'d.  Only these node kinds survive:

    Expression, Call, Name, Constant, BinOp (+ - * / **), and a unary minus/plus
    applied *directly to a numeric literal* (so ``-1 * rank(x)`` is expressible).

Everything else — attribute access (``close.values``), subscripts, comprehensions
(``[x for x in y]``), lambdas, string constants (``__import__('os')``), keyword
args, starred args — raises :class:`ParseError`.

Public surface
--------------
* ``parse(formula, strict=True) -> Node``       structural parse (+ name check)
* ``evaluate(formula, panel, strict=True)``     run against a ``{field: date x symbol}`` dict
* ``canonical(formula) -> str``                 normalized string for duplicate detection
* ``complexity(formula) -> {"nodes","depth","free_params"}``
* ``fingerprint(formula) -> str``               cheap bucketing hash

A ``Node`` is a plain nested tuple:
``("const", float)`` | ``("field", str)`` | ``("op", name, (child, ...))``.
BinOps are normalized to ``("op", "add"|"sub"|"mul"|"div"|"pow", ...)``.
"""
from __future__ import annotations

import ast
import hashlib

from .operators import (
    ARITH_OPS,
    COMMUTATIVE_OPS,
    FIELDS,
    OPERATORS,
    SYMMETRIC_HEAD_OPS,
)

Node = tuple

_BINOP = {
    ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul",
    ast.Div: "div", ast.Pow: "pow",
}


class ParseError(ValueError):
    """A formula violated the whitelist or referenced an unknown name."""


class EvalError(ValueError):
    """A parsed formula could not be evaluated against the supplied panel."""


# --------------------------------------------------------------------------- #
# Parsing                                                                      #
# --------------------------------------------------------------------------- #
def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_node(n: ast.AST, strict: bool) -> Node:
    if isinstance(n, ast.BinOp):
        if type(n.op) not in _BINOP:
            raise ParseError(
                f"binary operator {type(n.op).__name__} is not allowed "
                f"(only + - * / **)"
            )
        return ("op", _BINOP[type(n.op)],
                (_to_node(n.left, strict), _to_node(n.right, strict)))

    if isinstance(n, ast.UnaryOp):
        if isinstance(n.op, (ast.USub, ast.UAdd)) and isinstance(
            n.operand, ast.Constant
        ) and _is_number(n.operand.value):
            v = float(n.operand.value)
            return ("const", -v if isinstance(n.op, ast.USub) else v)
        raise ParseError(
            "unary operators are only allowed directly on a numeric literal "
            "(write mul(-1, x), not -x)"
        )

    if isinstance(n, ast.Call):
        if not isinstance(n.func, ast.Name):
            raise ParseError("a call target must be a bare operator name")
        if n.keywords:
            raise ParseError("keyword arguments are not allowed in formulas")
        if any(isinstance(a, ast.Starred) for a in n.args):
            raise ParseError("starred arguments are not allowed in formulas")
        name = n.func.id
        if strict and name not in OPERATORS:
            raise ParseError(f"unknown operator: {name!r}")
        return ("op", name, tuple(_to_node(a, strict) for a in n.args))

    if isinstance(n, ast.Name):
        if strict and n.id not in FIELDS:
            raise ParseError(
                f"unknown field: {n.id!r} (known: {sorted(FIELDS)})"
            )
        return ("field", n.id)

    if isinstance(n, ast.Constant):
        if not _is_number(n.value):
            raise ParseError(
                f"only numeric constants are allowed, got {n.value!r}"
            )
        return ("const", float(n.value))

    raise ParseError(f"disallowed syntax: {type(n).__name__}")


def parse(formula: str, strict: bool = True) -> Node:
    """Parse ``formula`` into a :data:`Node` tree under the strict whitelist.

    ``strict=True`` also checks every bare name against the field table and
    every call against the operator table.  ``strict=False`` keeps the safety
    whitelist but allows unknown names (used by ``canonical``/``complexity``/
    ``fingerprint``, which are purely structural).
    """
    if not isinstance(formula, str) or not formula.strip():
        raise ParseError("formula must be a non-empty string")
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:  # noqa: TRY003
        raise ParseError(f"could not parse formula: {exc}") from exc
    if not isinstance(tree, ast.Expression):
        raise ParseError("formula must be a single expression")
    return _to_node(tree.body, strict)


# --------------------------------------------------------------------------- #
# Evaluation                                                                   #
# --------------------------------------------------------------------------- #
def _eval(node: Node, panel: dict):
    tag = node[0]
    if tag == "const":
        return node[1]
    if tag == "field":
        name = node[1]
        if name not in panel:
            raise EvalError(
                f"field {name!r} is not in the panel (have: {sorted(panel)})"
            )
        return panel[name]
    _, name, args = node
    fn = OPERATORS.get(name)
    if fn is None:
        raise EvalError(f"unknown operator: {name!r}")
    values = [_eval(a, panel) for a in args]
    try:
        return fn(*values)
    except (ParseError, EvalError):
        raise
    except Exception as exc:  # noqa: BLE001 - surface with formula context
        raise EvalError(f"operator {name!r} failed: {exc}") from exc


def evaluate(formula, panel: dict, strict: bool = True):
    """Evaluate ``formula`` (a string or a :data:`Node`) against ``panel``.

    ``panel`` maps a field name to a wide ``date x symbol`` DataFrame.  Returns
    a DataFrame (or a scalar for a constant-only formula).
    """
    node = parse(formula, strict) if isinstance(formula, str) else formula
    return _eval(node, panel)


# --------------------------------------------------------------------------- #
# Canonicalization (for duplicate detection)                                   #
# --------------------------------------------------------------------------- #
def _numstr(v: float) -> str:
    f = float(v)
    if f.is_integer():
        return str(int(f))
    return repr(f)


def _fold(name: str, vals: list[float]):
    try:
        if name == "add":
            return sum(vals)
        if name == "mul":
            out = 1.0
            for v in vals:
                out *= v
            return out
        if name == "sub" and len(vals) == 2:
            return vals[0] - vals[1]
        if name == "div" and len(vals) == 2:
            return vals[0] / vals[1] if vals[1] != 0 else None
        if name == "pow" and len(vals) == 2:
            if vals[0] < 0 and not float(vals[1]).is_integer():
                return None
            return vals[0] ** vals[1]
    except (ArithmeticError, ValueError):
        return None
    return None


def _canon(node: Node) -> Node:
    tag = node[0]
    if tag in ("const", "field"):
        return node
    _, name, args = node
    cargs = [_canon(a) for a in args]

    if name in ARITH_OPS and all(a[0] == "const" for a in cargs):
        folded = _fold(name, [a[1] for a in cargs])
        if folded is not None:
            return ("const", float(folded))

    if name in COMMUTATIVE_OPS:
        cargs.sort(key=_emit)
    elif name in SYMMETRIC_HEAD_OPS and len(cargs) >= 2:
        head = sorted(cargs[:2], key=_emit)
        cargs = head + cargs[2:]

    return ("op", name, tuple(cargs))


def _emit(node: Node) -> str:
    tag = node[0]
    if tag == "const":
        return _numstr(node[1])
    if tag == "field":
        return node[1]
    _, name, args = node
    return f"{name}({','.join(_emit(a) for a in args)})"


def canonical(formula, strict: bool = False) -> str:
    """Normalized string: commutative operands sorted, constant arithmetic
    folded, numeric literals normalized.  ``canonical("a*b") == canonical("b*a")``.
    """
    node = parse(formula, strict) if isinstance(formula, str) else formula
    return _emit(_canon(node))


# --------------------------------------------------------------------------- #
# Complexity / fingerprint                                                     #
# --------------------------------------------------------------------------- #
def _count_nodes(node: Node) -> int:
    if node[0] in ("const", "field"):
        return 1
    return 1 + sum(_count_nodes(a) for a in node[2])


def _depth(node: Node) -> int:
    if node[0] in ("const", "field"):
        return 1
    if not node[2]:
        return 1
    return 1 + max(_depth(a) for a in node[2])


def _count_consts(node: Node) -> int:
    if node[0] == "const":
        return 1
    if node[0] == "field":
        return 0
    return sum(_count_consts(a) for a in node[2])


def _op_multiset(node: Node, acc: dict) -> dict:
    if node[0] == "op":
        acc[node[1]] = acc.get(node[1], 0) + 1
        for a in node[2]:
            _op_multiset(a, acc)
    return acc


def _leaf_fields(node: Node, acc: set) -> set:
    if node[0] == "field":
        acc.add(node[1])
    elif node[0] == "op":
        for a in node[2]:
            _leaf_fields(a, acc)
    return acc


def complexity(formula, strict: bool = False) -> dict:
    """``{"nodes": int, "depth": int, "free_params": int}``.

    ``nodes`` counts every leaf and every operator; ``depth`` is the deepest
    nesting (a bare field is depth 1); ``free_params`` counts numeric literals —
    the knobs available for overfitting (window sizes included).
    """
    node = parse(formula, strict) if isinstance(formula, str) else formula
    return {
        "nodes": _count_nodes(node),
        "depth": _depth(node),
        "free_params": _count_consts(node),
    }


def fingerprint(formula, strict: bool = False) -> str:
    """Cheap bucketing hash: sorted operator multiset + depth + leaf-field set.

    Two formulas with different fingerprints **cannot** be duplicates; matching
    fingerprints are escalated to exact canonical comparison.
    """
    node = parse(formula, strict) if isinstance(formula, str) else formula
    ops = tuple(sorted(_op_multiset(node, {}).items()))
    fields = tuple(sorted(_leaf_fields(node, set())))
    key = repr((ops, _depth(node), fields))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
