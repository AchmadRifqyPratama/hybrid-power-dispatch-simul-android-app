"""Pemeriksa nama tak terdefinisi — menangkap import yang lupa ditulis.

Kelas kesalahan yang ditangkap: memakai ``Qt.PointingHandCursor`` padahal
``Qt`` belum di-import, memakai ``os.path`` tanpa ``import os``, dan
sejenisnya — galat yang baru muncul saat baris tersebut dieksekusi.

Jalankan:  python check_names.py
"""
from __future__ import annotations

import ast
import builtins
import glob
import os
import sys

BUILTINS = set(dir(builtins)) | {'__file__', '__name__', '__doc__',
                                 '__package__', '__spec__', '__builtins__'}


def _bindings(node) -> set:
    """Semua nama yang di-bind pada sebuah lingkup (tanpa turun ke fungsi)."""
    out = set()

    def walk(n, top=False):
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.add(child.name)
                continue                      # tubuhnya lingkup sendiri
            if isinstance(child, ast.ClassDef):
                out.add(child.name)
                continue
            if isinstance(child, ast.Lambda):
                continue
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for a in child.names:
                    out.add((a.asname or a.name).split('.')[0])
            elif isinstance(child, ast.Name) and isinstance(child.ctx,
                                                            ast.Store):
                out.add(child.id)
            elif isinstance(child, ast.arg):
                out.add(child.arg)
            elif isinstance(child, ast.ExceptHandler) and child.name:
                out.add(child.name)
            elif isinstance(child, ast.Global):
                out.update(child.names)
            walk(child)

    walk(node, True)
    return out


def check_file(path: str) -> list:
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src, path)
    module_names = _bindings(tree) | BUILTINS
    bad = []

    class Scope(ast.NodeVisitor):
        def __init__(self, names):
            self.names = names

        def visit_FunctionDef(self, node):
            inner = self.names | _bindings(node) | {a.arg for a in
                                                    node.args.args}
            if node.args.vararg:
                inner.add(node.args.vararg.arg)
            if node.args.kwarg:
                inner.add(node.args.kwarg.arg)
            inner |= {a.arg for a in node.args.kwonlyargs}
            for d in node.decorator_list:
                Scope(self.names).visit(d)
            for st in node.body:
                Scope(inner).visit(st)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Lambda(self, node):
            inner = self.names | {a.arg for a in node.args.args}
            Scope(inner).visit(node.body)

        def visit_ClassDef(self, node):
            inner = self.names | _bindings(node)
            for st in node.body:
                Scope(inner).visit(st)

        def visit_comprehension_scope(self, node):
            inner = set(self.names)
            for gen in node.generators:
                inner |= _bindings(ast.Module(body=[ast.Expr(gen.target)],
                                              type_ignores=[]))
                for n in ast.walk(gen.target):
                    if isinstance(n, ast.Name):
                        inner.add(n.id)
            for gen in node.generators:
                Scope(self.names).visit(gen.iter)
                for ifs in gen.ifs:
                    Scope(inner).visit(ifs)
            for attr in ('elt', 'key', 'value'):
                sub = getattr(node, attr, None)
                if sub is not None:
                    Scope(inner).visit(sub)

        visit_ListComp = visit_comprehension_scope
        visit_SetComp = visit_comprehension_scope
        visit_GeneratorExp = visit_comprehension_scope
        visit_DictComp = visit_comprehension_scope

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Load) and node.id not in self.names:
                bad.append((path, node.lineno, node.id))

    for st in tree.body:
        Scope(module_names).visit(st)
    return bad


def main():
    roots = sys.argv[1:] or ['app', '.']
    files = []
    for r in roots:
        if os.path.isdir(r):
            files += glob.glob(os.path.join(r, '**', '*.py'), recursive=True)
        elif r.endswith('.py'):
            files.append(r)
    files = sorted(set(f for f in files if '__pycache__' not in f))
    bad = []
    for f in files:
        try:
            bad += check_file(f)
        except SyntaxError as e:
            print(f'  SYNTAX  {f}:{e.lineno}  {e.msg}')
    seen, out = set(), []
    for f, ln, name in bad:
        if (f, name) in seen:
            continue
        seen.add((f, name))
        out.append((f, ln, name))
    for f, ln, name in out:
        print(f'  {f}:{ln}  nama tak terdefinisi: {name}')
    print(f'\n{len(files)} berkas diperiksa — '
          + (f'{len(out)} masalah' if out else 'BERSIH ✔'))
    return 1 if out else 0


if __name__ == '__main__':
    raise SystemExit(main())
