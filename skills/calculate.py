# name: calculate
# description: Evaluate a mathematical expression and return the number. Use for any arithmetic, e.g. args {"expr": "(1234 * 7) / 3 + 2**8"}. Supports + - * / // % ** and parentheses.
import ast
import operator

_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow, ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
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
    except Exception as e:
        return {"ok": False, "error": str(e)}
