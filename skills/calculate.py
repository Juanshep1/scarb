# name: calculate
# description: Evaluate a mathematical expression and return the number. Use for any arithmetic, e.g. args {"expr": "(1234 * 7) / 3 + 2**8"}. Supports + - * / // % ** and parentheses, including non-decimal integers (0xFF, 0b101, 0o77) and booleans (True, False).
import ast
import operator

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# ast.NameConstant existed before Python 3.8; ast.Constant covers it after.
# ast.Num existed before Python 3.8 for numeric literals.
_COMPAT = {"NameConstant", "Num"}


def _eval(node):
    # ast.Constant (Python 3.8+): handles int, float, bool, str, None, bytes.
    # We care about int (covers hex/binary/octal literals), float, and bool.
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise ValueError(f"only numbers are allowed, not {type(node.value).__name__}")
    # ast.NameConstant (Python < 3.8): True, False, None
    if hasattr(ast, "NameConstant") and isinstance(node, ast.NameConstant):
        if isinstance(node.value, bool) or node.value is None:
            raise ValueError(f"only numbers are allowed, not {node.value!r}")
        return node.value
    # ast.Num (Python < 3.8): plain numeric literals
    if hasattr(ast, "Num") and isinstance(node, ast.Num):
        return node.n
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("only plain arithmetic is allowed")


def run(args):
    expr = str(args.get("expr", "")).strip()
    if not expr:
        return {"ok": False, "error": "no expression given"}
    try:
        value = _eval(ast.parse(expr, mode="eval").body)
        return {"ok": True, "result": value}
    except (ValueError, SyntaxError) as e:
        return {"ok": False, "error": str(e)}
