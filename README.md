# DataHelm

**DataHelm** is a desktop application for scientific data analysis that works like a spreadsheet piloted by an LLM: you describe what you want, the model proposes Python code, and that code runs locally on your own machine — your data never leaves your computer.

## Why DataHelm

Scientists, engineers, and analysts often need to explore, clean, and visualize tabular data (experiment results, sensor logs, survey exports...) without writing pandas code by hand, and without uploading that data to a third-party cloud service. DataHelm is built around one core idea: **the LLM only ever sees metadata and small previews of your data** — column names, types, row counts, a short preview of the active sheet — never the full dataset. It uses that information to write Python code, which the application then reviews and runs locally, entirely offline as far as your data is concerned.

A typical use case: a researcher has a set of Excel files from lab measurements open in several sheet windows. They ask, "merge the calibration and the raw-readings sheets on timestamp, apply the calibration offset, and plot the corrected signal." DataHelm's LLM backend writes the pandas/matplotlib code for that, the application checks it, the user confirms if needed, and the result appears in a new sheet and a new chart window — without the underlying measurements ever being transmitted anywhere except as small structural summaries.

## How it works

- **Multi-window workspace**: any number of independent "Sheet" windows (Excel-style grid view) and "Chart" windows can be open at once. One sheet and one chart are "active" at a time — the ones the LLM's code operates on by default — and you switch which one is active with a "Use for chat" button.
- **Stateless conversation**: no chat history is ever sent to the LLM. Every request is answered fresh, informed only by a system prompt rebuilt on the spot from the sheets and charts currently open (their names, shapes, column types, and — for charts — a short description of what's plotted). The full conversation is still kept in the on-screen log so you can scroll back or copy it, but the model itself starts from a clean slate on every message.
- **Non-destructive by default**: new or derived results (a filtered subset, an extracted series, a merge, a new plot) are placed in a *new* sheet or chart window rather than overwriting what you already have open, unless you clearly ask to modify an existing one by name.
- **Manual, explicit import/export**: bringing data in or saving it out is always a deliberate action you take yourself, through native file-selection dialogs in each sheet window — never something the LLM's code does on its own.

## Security architecture

Code proposed by the LLM is never trusted and never run as-is. It passes through several independent, cooperating layers before (and while) it executes:

1. **Static AST analysis** (`security.py`) — every proposed snippet is parsed into a syntax tree and classified before anything runs:
   - **ALLOW** — ordinary data manipulation (filtering, computing, reshaping), executed immediately.
   - **CONFIRM** — operations that can affect a sheet or chart window other than the one currently active (creating or overwriting one by name) are shown to the user in plain language and require explicit approval.
   - **DENY** — anything with no legitimate place in local data analysis: shell commands, network access, process/thread spawning, reading environment variables, reflective sandbox-escape patterns, and — deliberately, with no exceptions — **any file read or write on disk**, whether through `open()` or through pandas' own file functions.
2. **Import allow-listing** — only a fixed set of data-analysis modules (pandas, numpy, matplotlib, scipy, standard formatting/collection modules, etc.) can be imported at all; anything not explicitly recognized is refused by default, not passed through unclassified.
3. **Restricted execution environment** (`executor.py`) — even code that passed static analysis runs with a stripped-down set of builtins and a restricted `__import__`, and simply has no working file-access primitive available to it: `open` does not exist in that environment, so there is no confined-but-present file handle for generated code to reach for in the first place.
4. **Pre-flight consistency check** — before running anything, the application also checks that every sheet or chart the code refers to by name is actually still open; a window closed earlier in the session produces a clear message instead of a raw error.

These layers are intentionally redundant: a gap in one (for example, a name the static analysis doesn't recognize) is still expected to be caught by another (the restricted runtime, or the import allow-list). No single layer is treated as sufficient on its own.

## Requirements

- Python 3.9+
- A Groq API key (set as the `GROQ_API_KEY` environment variable, or entered directly in the app)
- Dependencies listed in `requirements.txt`: pandas, numpy, matplotlib, openpyxl, requests

## Getting started

```bash
pip install -r requirements.txt
python main.py
```

Open a sheet window, import a data file, enter your Groq API key (or set `GROQ_API_KEY` beforehand), and start describing what you'd like to do with your data.

## License

MIT — see `LICENSE`.
