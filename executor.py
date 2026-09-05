"""
executor.py
===========
Sandboxed execution of the Python code validated by the security
controller (security.py). Even code already marked "ALLOW" or approved
by the user ("CONFIRM") is executed with:
  - a restricted set of builtins (no free open, eval, exec, __import__,
    etc.)
  - a restricted __import__ that only lets through modules listed in
    security.ALLOWED_MODULES
  - access only to explicitly injected objects (df, sheets, charts,
    pd, np, plt)

NO FILE ACCESS OF ANY KIND is available to the generated code: `open`
is simply not defined in the sandbox (referencing it raises
NameError, exactly like any other undefined name), `os`/`shutil`/
`pathlib` are not importable, and the real pandas module's file I/O
functions (read_csv, to_excel, ...) are refused before execution ever
reaches this module (see security.py — they are DENY, not CONFIRM).
Importing and exporting data is exclusively a user-triggered action
through the "Import here"/"Export .xlsx" buttons in the sheet windows
(main.py), never something the LLM's code can do.

`sheets` and `charts` follow the same pattern:
  - `sheets`: {sheet_name: DataFrame} for every data window currently
    open. Reassigning `df` updates the active sheet; assigning a new or
    existing key of `sheets` targets that sheet specifically (creating
    a new window, or replacing an existing one, on the application
    side after execution).
  - `charts`: {chart_name: matplotlib Figure} for every chart window
    currently open (read-only references, for inspecting an existing
    chart's title/labels/data). To create or replace a chart, the code
    assigns a NEW Figure object to a key of `charts` (new key = new
    window, existing key = that window's chart is replaced). If the
    code never touches `charts` at all and simply plots with the
    implicit `plt` current figure (e.g. `plt.plot(...)`), that figure
    is returned separately and applied to the currently active chart
    window, or a new one if none is active — this keeps the simple,
    single-chart case effortless while still allowing explicit,
    multi-chart control when needed.
"""

import io
import builtins as _builtins_module
import contextlib
import traceback

import matplotlib
matplotlib.use("Agg")  # off-screen rendering; the figure is then displayed in Tkinter
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

import security


def _restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
    """Restricted __import__: only whitelisted modules go through."""
    root = name.split(".")[0]
    if root in security.FORBIDDEN_MODULES:
        raise ImportError(f"Importing '{name}' is forbidden by the security policy.")
    return _builtins_module.__import__(name, globals, locals, fromlist, level)


_ALLOWED_BUILTIN_NAMES = [
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "format", "frozenset", "int", "len", "list", "map", "max", "min",
    "print", "range", "repr", "reversed", "round", "set", "sorted",
    "str", "sum", "tuple", "zip", "True", "False", "None", "isinstance",
    "type", "Exception", "ValueError", "TypeError", "KeyError",
    "IndexError", "StopIteration", "ZeroDivisionError", "AttributeError",
    "NameError", "RuntimeError", "PermissionError",
    "slice", "hasattr",
]

SAFE_BUILTINS = {
    name: getattr(_builtins_module, name)
    for name in _ALLOWED_BUILTIN_NAMES
    if hasattr(_builtins_module, name)
}
SAFE_BUILTINS["__import__"] = _restricted_import
# NOTE: "open" is deliberately absent from SAFE_BUILTINS and from
# sandbox_globals below. There is no sandboxed/confined version of it
# — it simply does not exist for the generated code to call.


def _figure_has_content(fig):
    return fig is not None and len(fig.axes) > 0 and any(ax.has_data() for ax in fig.axes)


def execute_code(code: str, df: pd.DataFrame, sheets: dict = None,
                  active_sheet_name: str = None, charts: dict = None):
    """
    Executes `code` in a restricted environment.

    `sheets`: dictionary {sheet_name: DataFrame} representing ALL data
    sheets currently open in the application (not just the active one).
    The LLM's code can therefore read/combine several sheets (e.g.
    pd.merge(sheets['A'], sheets['B'], ...)).
    `active_sheet_name`: key of `sheets` corresponding to `df` (the
    sheet currently selected by the user via "Use for chat").
    `charts`: dictionary {chart_name: Figure} representing every chart
    window currently open, for the code to inspect if needed. New or
    replacement charts are produced by assigning a new Figure object to
    a key of this same dictionary.

    Returns a tuple (new_df, new_sheets, chart_updates, implicit_fig,
    stdout_text, error_text) where:
      - new_df        : the active DataFrame after execution (may be unchanged)
      - new_sheets    : the `sheets` dictionary after execution — may
                        contain modified sheets and/or new keys (new
                        sheets created by the code)
      - chart_updates : dict {chart_name: Figure} for charts the code
                        explicitly created or replaced via `charts[...]`
      - implicit_fig  : a Figure if the code drew via the implicit
                        current `plt` figure WITHOUT touching `charts`
                        at all, otherwise None (see module docstring)
      - stdout        : everything the code printed via print()
      - error         : the text traceback in case of exception, otherwise None
    """
    plt.close("all")
    plt.figure()

    sheets = sheets or {}
    charts_input = charts or {}

    # Independent copies: the code can modify these DataFrames without
    # affecting the real windows until the application explicitly
    # applies the result back (see main.py::_execute).
    sheets_copy = {
        name: (d.copy() if isinstance(d, pd.DataFrame) else d)
        for name, d in sheets.items()
    }
    # Charts are exposed as direct references (for inspection); a new
    # or replaced chart is produced by ASSIGNING a new Figure object to
    # a key, never by mutating an existing one in place — see docstring.
    charts_copy = dict(charts_input)

    sandbox_globals = {
        "__builtins__": SAFE_BUILTINS,
        "pd": pd,
        "np": np,
        "plt": plt,
        "df": df.copy() if df is not None else None,
        "sheets": sheets_copy,
        "charts": charts_copy,
    }

    stdout_buffer = io.StringIO()
    error = None
    new_df = df

    try:
        with contextlib.redirect_stdout(stdout_buffer):
            exec(compile(code, "<llm_code>", "exec"), sandbox_globals)
        if isinstance(sandbox_globals.get("df"), pd.DataFrame):
            new_df = sandbox_globals["df"]
    except Exception:
        error = traceback.format_exc()

    # The code may have fully reassigned `sheets` (e.g. sheets = {}).
    # As a safety measure, if it is no longer a dict, fall back to the
    # original dict rather than losing the reference to all known sheets.
    result_sheets = sandbox_globals.get("sheets")
    if not isinstance(result_sheets, dict):
        result_sheets = sheets_copy

    # If the code modified `df` without going through sheets[...], apply
    # the change to the active sheet anyway, to stay consistent with the
    # system prompt instruction ("reassign the result into df").
    if active_sheet_name is not None and isinstance(new_df, pd.DataFrame):
        previous = result_sheets.get(active_sheet_name)
        if previous is None or not new_df.equals(previous):
            result_sheets[active_sheet_name] = new_df

    # --- Charts: figure out what the code explicitly produced --------
    result_charts = sandbox_globals.get("charts")
    if not isinstance(result_charts, dict):
        result_charts = charts_copy

    chart_updates = {}
    for name, fig_obj in result_charts.items():
        original = charts_input.get(name)
        if fig_obj is not original and _figure_has_content(fig_obj):
            chart_updates[name] = fig_obj

    # Fallback for the simple/implicit case: the code just did
    # `plt.plot(...)` without ever touching `charts`.
    implicit_fig = plt.gcf() if error is None else None
    implicit_already_registered = any(fig_obj is implicit_fig for fig_obj in result_charts.values())
    if chart_updates or implicit_already_registered or not _figure_has_content(implicit_fig):
        implicit_fig = None

    return new_df, result_sheets, chart_updates, implicit_fig, stdout_buffer.getvalue(), error
