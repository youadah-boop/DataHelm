"""
llm_backend.py
==============
Connector to the Groq API, compatible with the OpenAI-style
"chat/completions" format.
"""

import re
import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

DEFAULT_MODELS = {
    # NOTE: Groq regularly deprecates its older Llama models
    # (llama-3.3-70b-versatile, llama-3.1-8b-instant are decommissioned).
    # openai/gpt-oss-120b is currently the recommended general-purpose
    # model (larger sibling of openai/gpt-oss-20b, better suited to the
    # code-generation work this app relies on).
    # Check the up-to-date list at https://console.groq.com/docs/models
    "Groq": "openai/gpt-oss-120b",
}

SYSTEM_PROMPT = """You are a scientific data analysis assistant.

This conversation has NO memory between messages: this system prompt
and the user's current request below are the ONLY context you receive
— no earlier turns are sent to you. The "Currently open" lists below
are refreshed on every single request and are the ONLY source of truth
for what sheets and charts exist right now; never assume a sheet or
chart mentioned in a past exchange still exists, and never assume one
that exists now was discussed before.

You have access to:
- `df`: the pandas DataFrame of the currently ACTIVE sheet (the one the
  user selected via "Use for chat").
- `sheets`: a dictionary containing ALL data sheets currently open in
  the application: {"sheet_name": DataFrame, ...}. `df` is equivalent
  to `sheets['<active sheet name>']`.
- `charts`: a dictionary containing ALL chart windows currently open:
  {"chart_name": matplotlib Figure, ...}. Read from it to inspect an
  existing chart (title, axis labels, plotted data) if the request needs
  that.
- `pd` (pandas), `np` (numpy), `plt` (matplotlib.pyplot).

STRICT RESPONSE RULES:
1. Respond ONLY with a Python code block (```python ... ```), with no
   explanation outside the block, unless the question requires no code at all.
2. DEFAULT TO CREATING A NEW SHEET for any new, derived, or extracted
   result (e.g. data extracted from a chart, a filtered subset, a
   computed summary, the result of a merge/join). Do this by assigning
   to a NEW key of `sheets`, with a short descriptive name, for example:
   sheets['Extracted data'] = extracted_df
   sheets['Merged'] = pd.merge(sheets['Sheet 1'], sheets['Sheet 2'], on='id')
   A new window is automatically created for it. This never overwrites
   a sheet the user already has open.
3. Only overwrite an EXISTING sheet (by reassigning `df`, or by
   assigning to an existing key of `sheets`) when the user's request
   clearly asks to modify/clean/transform that sheet's own data in
   place, or explicitly names the sheet to overwrite. When in doubt,
   prefer creating a new sheet — it is non-destructive.
4. Charts follow the same logic. For a quick one-off chart, you can
   simply plot with `plt` directly (e.g. `plt.plot(...)`) — it will be
   shown in the currently active chart window. To create a NEW chart
   without touching the active one, or to explicitly replace a
   specific existing chart by name, build the figure and assign it to
   `charts`, for example:
   fig = plt.figure()
   ax = fig.add_subplot()
   ax.plot(sheets['Sheet 1']['x'], sheets['Sheet 1']['y'])
   charts['New chart'] = fig
   Use an existing name from the "Currently open" chart list to replace
   that specific window; use a new descriptive name to create one
   alongside the others without disturbing them.
5. To read, combine, or compare several sheets (merge, join,
   concatenation...), use `sheets['ExactName']` for each of them.
   Use the sheet names EXACTLY as listed below.
6. Never use system commands, network access, or libraries outside the
   scope of data analysis (the code will be checked before execution
   and may be refused).
7. Only import the modules strictly necessary for the analysis.
8. The generated code can NEVER read or write a file on disk — no
   open(), no pd.read_csv/read_excel/to_csv/to_excel or similar: these
   calls are always refused before execution. Importing or exporting a
   file is exclusively a manual action the user performs themselves,
   using the "Import here" / "Export .xlsx" buttons in the sheet
   windows. If the user's request requires reading or writing a file,
   tell them (in a short comment or, if no code applies, in plain text)
   to use those buttons instead — never attempt file access yourself.

Data sheets currently open:
{data_context}

Chart windows currently open:
{chart_context}
"""


def _headers(api_key):
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _call_openai_compatible(url, api_key, model, messages, timeout=60):
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    try:
        resp = requests.post(url, headers=_headers(api_key), json=payload, timeout=timeout)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        detail = ""
        try:
            body = resp.json()
            # Typical error format for OpenAI-compatible APIs: {"error": {"message": "..."}}
            detail = (body.get("error") or {}).get("message") or str(body)
        except Exception:
            detail = (resp.text or "")[:400]
        hint = ""
        if resp.status_code == 404:
            hint = ("\nLikely cause: the requested model does not exist or is no longer "
                    "available from this provider (often after deprecation). Check the "
                    "model name in the 'Model' field.")
        elif resp.status_code == 401:
            hint = "\nLikely cause: the API key is invalid, missing, or expired."
        elif resp.status_code == 429:
            hint = "\nLikely cause: quota or rate limit exceeded."
        raise RuntimeError(
            f"HTTP error {resp.status_code} while calling {url}\n"
            f"Requested model: '{model}'\n"
            f"Detail returned by the API: {detail}{hint}"
        ) from e
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Could not reach the API ({url}): {e}") from e

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def call_llm(provider, api_key, model, messages):
    """Calls the selected LLM and returns the response text."""
    if not api_key:
        raise ValueError("Missing API key for the selected provider.")
    if provider == "Groq":
        return _call_openai_compatible(GROQ_URL, api_key, model or DEFAULT_MODELS["Groq"], messages)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def test_connection(provider, api_key, model):
    """
    Sends a minimal request to check that the API key, the model, and
    the network are working. Returns the LLM's response text on
    success; raises an exception (with a detailed message) otherwise.
    """
    messages = [
        {"role": "system", "content": "Reply with only the word 'ok', with no punctuation."},
        {"role": "user", "content": "ping"},
    ]
    return call_llm(provider, api_key, model, messages)


def extract_code_block(text):
    """Extracts the first ```python ... ``` (or ``` ... ```) block from the text."""
    match = re.search(r"```(?:python)?\s*(.*?)```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def build_data_context(sheets, active_name=None):
    """
    Builds a text summary of ALL open data sheets, for the system
    prompt. Deliberately kept light on tokens: only the active sheet
    gets a detailed preview (5 rows); the others only show their
    dimensions and column types.

    `sheets`: dict {name: DataFrame}
    `active_name`: name of the active sheet (marked "(ACTIVE)")
    """
    if not sheets:
        return "No data sheet is currently open."

    lines = [f"{len(sheets)} sheet(s) currently open:"]
    for name, df in sheets.items():
        marker = " (ACTIVE)" if name == active_name else ""
        if df is None or df.empty:
            lines.append(f"- '{name}'{marker}: empty")
            continue
        dtypes_str = ", ".join(f"{c}: {t}" for c, t in df.dtypes.astype(str).items())
        lines.append(f"- '{name}'{marker}: {df.shape[0]} rows x {df.shape[1]} columns | {dtypes_str}")

    if active_name and active_name in sheets:
        active_df = sheets[active_name]
        if active_df is not None and not active_df.empty:
            lines.append(f"\nPreview of the active sheet '{active_name}' (first 5 rows):\n"
                         f"{active_df.head().to_string()}")

    return "\n".join(lines)


def _describe_figure(fig):
    """One-line best-effort textual summary of a matplotlib Figure's
    content, so the (text-only) LLM can 'see' what a chart currently
    shows without needing image/vision input."""
    if fig is None or not fig.axes:
        return "empty"
    parts = []
    for ax in fig.axes:
        title = ax.get_title().strip()
        xlabel = ax.get_xlabel().strip()
        ylabel = ax.get_ylabel().strip()
        labels = [line.get_label() for line in ax.get_lines() if not line.get_label().startswith("_")]
        n_points = sum(len(line.get_xdata()) for line in ax.get_lines())
        desc = []
        if title:
            desc.append(f"title='{title}'")
        if xlabel or ylabel:
            desc.append(f"x='{xlabel}' y='{ylabel}'")
        if labels:
            desc.append(f"series={labels}")
        if n_points:
            desc.append(f"~{n_points} points")
        if ax.patches:
            desc.append(f"{len(ax.patches)} bar/patch element(s)")
        if ax.collections:
            desc.append(f"{len(ax.collections)} scatter/collection element(s)")
        parts.append(", ".join(desc) if desc else "drawn but no readable metadata")
    return " | ".join(parts)


def build_chart_context(charts, active_name=None):
    """
    Builds a text summary of ALL open chart windows, for the system
    prompt: name, active marker, and a best-effort content description
    (title/axis labels/series names/point count) so the LLM can reason
    about updating a specific existing chart without needing to re-plot
    from scratch.

    `charts`: dict {name: Figure or None}
    `active_name`: name of the active chart window (marked "(ACTIVE)")
    """
    if not charts:
        return "No chart window is currently open."

    lines = [f"{len(charts)} chart window(s) currently open:"]
    for name, fig in charts.items():
        marker = " (ACTIVE)" if name == active_name else ""
        lines.append(f"- '{name}'{marker}: {_describe_figure(fig)}")
    return "\n".join(lines)
