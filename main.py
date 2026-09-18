"""Repo-root entry shim.

Makes `python main.py` (from the repo root) behave exactly like
`cd backend && python run.py`: it switches into backend/ first so
`main` is importable, the sqlite DB lands next to the app, and the
frontend resolves via ../frontend. Exists so the "obvious" start
command can never silently do nothing.
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "backend")

os.chdir(BACKEND)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

runpy.run_path(os.path.join(BACKEND, "run.py"), run_name="__main__")
