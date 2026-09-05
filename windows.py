"""
windows.py
==========
Reusable "data sheet" and "chart" windows.

Each imported file or each chart can open in its OWN independent window
("New sheet" / "New chart" button), while previous windows stay open and
browsable. Only one window of each type is "active" at a time: that is
the one the LLM operates on (the `df` variable for data, the displayed
figure for charts). The user picks the active window via the "Use for
chat" button present in every window.
"""

import string
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

MAX_ROWS_DISPLAY = 500
ZOOM_FACTOR = 1.2


def excel_col_name(index: int) -> str:
    """Converts a 0-based index into an Excel-style column name (0->'A', 25->'Z', 26->'AA', ...)."""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = string.ascii_uppercase[remainder] + letters
    return letters


# ==========================================================================
# Data window (Excel-style sheet)
# ==========================================================================
class DataWindow:
    """An independent window displaying a DataFrame in an Excel-style
    grid (columns A, B, C..., rows 1, 2, 3...)."""

    _counter = 0

    def __init__(self, app, root, df=None, title=None):
        DataWindow._counter += 1
        self.app = app
        self.df = df
        self.title_str = title or f"Sheet {DataWindow._counter}"

        self.win = tk.Toplevel(root)
        self.win.title(f"Data — {self.title_str}")
        self.win.resizable(True, True)
        self.win.minsize(480, 300)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.refresh_table()

    # ------------------------------------------------------------------
    def _build_ui(self):
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(2, weight=1)

        header = ttk.Frame(self.win, padding=(6, 6, 6, 0))
        header.grid(row=0, column=0, sticky="ew")
        self.name_label = ttk.Label(header, text=self.title_str, font=("", 12, "bold"))
        self.name_label.pack(side=tk.LEFT)

        ttk.Button(header, text="Close", command=self._on_close).pack(side=tk.RIGHT)
        ttk.Button(header, text="+ New sheet", command=self._on_new_window).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(header, text="Export .xlsx", command=self._on_export).pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Button(header, text="Import here", command=self._on_import_here).pack(side=tk.RIGHT, padx=(0, 6))

        activate_row = ttk.Frame(self.win, padding=(6, 4, 6, 0))
        activate_row.grid(row=1, column=0, sticky="ew")
        ttk.Button(activate_row, text="Use for chat", command=self._on_activate).pack(side=tk.LEFT)
        self.active_var = tk.StringVar()
        ttk.Label(activate_row, textvariable=self.active_var, foreground="#26a269", font=("", 9, "bold")).pack(
            side=tk.LEFT, padx=8
        )
        self.info_var = tk.StringVar(value="No data loaded.")
        ttk.Label(activate_row, textvariable=self.info_var, foreground="#5e5c64").pack(side=tk.RIGHT)

        table_frame = ttk.Frame(self.win, padding=(6, 0, 6, 6))
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, show="tree headings")
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=45, minwidth=35, anchor="center", stretch=False)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        self.tree.tag_configure("header_row", background="#e8e8e8", font=("", 9, "bold"))
        self.tree.tag_configure("even_row", background="#ffffff")
        self.tree.tag_configure("odd_row", background="#f5f7fa")

    # ------------------------------------------------------------------
    def set_active_visual(self, is_active):
        self.active_var.set("● Active sheet for chat" if is_active else "")

    def refresh_table(self):
        self.tree.delete(*self.tree.get_children())
        if self.df is None or self.df.empty:
            self.tree["columns"] = []
            self.info_var.set("No data loaded.")
            return

        n_cols = self.df.shape[1]
        col_ids = [f"c{i}" for i in range(n_cols)]
        self.tree["columns"] = col_ids
        for i, col_id in enumerate(col_ids):
            self.tree.heading(col_id, text=excel_col_name(i))
            self.tree.column(col_id, width=110, anchor="w")

        header_values = [str(c) for c in self.df.columns]
        self.tree.insert("", tk.END, text="1", values=header_values, tags=("header_row",))

        display_df = self.df.head(MAX_ROWS_DISPLAY)
        for row_offset, (_, row) in enumerate(display_df.iterrows()):
            row_number = row_offset + 2  # data starts after the header row
            values = ["" if pd.isna(v) else str(v) for v in row.tolist()]
            tag = "even_row" if row_offset % 2 == 0 else "odd_row"
            self.tree.insert("", tk.END, text=str(row_number), values=values, tags=(tag,))

        note = "" if len(self.df) <= MAX_ROWS_DISPLAY else f" (display limited to the first {MAX_ROWS_DISPLAY} rows)"
        self.info_var.set(f"{self.df.shape[0]} rows x {self.df.shape[1]} columns{note}")

    def set_dataframe(self, df, title=None):
        """Replaces the DataFrame displayed IN THIS window (does not affect the others)."""
        self.df = df
        if title:
            self.title_str = title
            self.win.title(f"Data — {title}")
            self.name_label.configure(text=title)
        self.refresh_table()

    # ------------------------------------------------------------------
    # Callbacks delegated to the application
    # ------------------------------------------------------------------
    def _on_activate(self):
        self.app.set_active_data_window(self)

    def _on_new_window(self):
        self.app.new_data_window()

    def _on_import_here(self):
        self.app.import_into_window(self)

    def _on_export(self):
        self.app.export_data_window(self)

    def _on_close(self):
        self.app.remove_data_window(self)
        self.win.destroy()


# ==========================================================================
# Chart window
# ==========================================================================
class PlotWindow:
    """An independent window displaying a matplotlib chart, with a native
    toolbar, mouse-wheel zoom, and Xmin/Xmax/Ymin/Ymax fields."""

    _counter = 0

    def __init__(self, app, root, title=None):
        PlotWindow._counter += 1
        self.app = app
        self.title_str = title or f"Chart {PlotWindow._counter}"
        self.current_ax = None
        self.plot_fig = None
        self.plot_canvas = None

        self.win = tk.Toplevel(root)
        self.win.title(f"Chart — {self.title_str}")
        self.win.resizable(True, True)
        self.win.minsize(480, 420)
        self.win.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._init_empty_plot()

    # ------------------------------------------------------------------
    def _build_ui(self):
        self.win.columnconfigure(0, weight=1)
        self.win.rowconfigure(2, weight=1)

        header = ttk.Frame(self.win, padding=(6, 6, 6, 0))
        header.grid(row=0, column=0, sticky="ew")
        self.name_label = ttk.Label(header, text=self.title_str, font=("", 12, "bold"))
        self.name_label.pack(side=tk.LEFT)
        ttk.Button(header, text="Close", command=self._on_close).pack(side=tk.RIGHT)
        ttk.Button(header, text="+ New chart", command=self._on_new_window).pack(
            side=tk.RIGHT, padx=(0, 6)
        )
        ttk.Button(header, text="Clear", command=self._init_empty_plot).pack(side=tk.RIGHT, padx=(0, 6))

        activate_row = ttk.Frame(self.win, padding=(6, 4, 6, 0))
        activate_row.grid(row=1, column=0, sticky="ew")
        ttk.Button(activate_row, text="Use for chat", command=self._on_activate).pack(side=tk.LEFT)
        self.active_var = tk.StringVar()
        ttk.Label(activate_row, textvariable=self.active_var, foreground="#26a269", font=("", 9, "bold")).pack(
            side=tk.LEFT, padx=8
        )

        canvas_frame = ttk.Frame(self.win)
        canvas_frame.grid(row=2, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)
        self.canvas_frame = canvas_frame

        self.toolbar_holder = ttk.Frame(self.win)
        self.toolbar_holder.grid(row=3, column=0, sticky="ew")

        axis_frame = ttk.LabelFrame(self.win, text="Precise view control", padding=6)
        axis_frame.grid(row=4, column=0, sticky="ew", padx=6, pady=6)

        self.xmin_var = tk.StringVar()
        self.xmax_var = tk.StringVar()
        self.ymin_var = tk.StringVar()
        self.ymax_var = tk.StringVar()

        for i, (label, var) in enumerate([
            ("Xmin", self.xmin_var), ("Xmax", self.xmax_var),
            ("Ymin", self.ymin_var), ("Ymax", self.ymax_var),
        ]):
            ttk.Label(axis_frame, text=label + ":").grid(row=0, column=2 * i, sticky="w", padx=(0, 2))
            ttk.Entry(axis_frame, textvariable=var, width=10).grid(row=0, column=2 * i + 1, padx=(0, 8))

        ttk.Button(axis_frame, text="Apply", command=self._on_apply_axis_limits).grid(
            row=0, column=8, padx=(4, 4)
        )
        ttk.Button(axis_frame, text="Auto", command=self._on_autoscale_axis).grid(row=0, column=9)

        ttk.Label(
            self.win,
            text="Mouse wheel = zoom (centered on the cursor). The toolbar above also "
                 "provides rectangle zoom, pan, and image export.",
            foreground="#5e5c64", wraplength=520, justify="left",
        ).grid(row=5, column=0, sticky="w", padx=6, pady=(0, 6))

    # ------------------------------------------------------------------
    def set_active_visual(self, is_active):
        self.active_var.set("● Active window for chat" if is_active else "")

    def _init_empty_plot(self):
        fig = plt.figure(figsize=(5, 3))
        fig.add_subplot(111)
        self.display_figure(fig, log=False)

    def display_figure(self, fig, log=True):
        """Fully replaces the matplotlib canvas OF THIS window with `fig`
        (natively handles lines, bars, scatter plots, images, etc.)."""
        if self.plot_canvas is not None:
            self.plot_canvas.get_tk_widget().destroy()
        for child in self.toolbar_holder.winfo_children():
            child.destroy()

        self.plot_fig = fig
        self.plot_canvas = FigureCanvasTkAgg(fig, master=self.canvas_frame)
        self.plot_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
        NavigationToolbar2Tk(self.plot_canvas, self.toolbar_holder)

        self.plot_canvas.mpl_connect("scroll_event", self._on_scroll_zoom)

        self.current_ax = fig.axes[0] if fig.axes else None
        if self.current_ax is not None:
            self.current_ax.callbacks.connect("xlim_changed", lambda ax: self._sync_axis_fields())
            self.current_ax.callbacks.connect("ylim_changed", lambda ax: self._sync_axis_fields())

        self.plot_canvas.draw()
        self._sync_axis_fields()
        if log:
            self.app._log("system", f"The chart was updated in window '{self.title_str}'.")

    def _on_scroll_zoom(self, event):
        ax = event.inaxes
        if ax is None or event.xdata is None or event.ydata is None:
            return
        scale = (1 / ZOOM_FACTOR) if event.button == "up" else ZOOM_FACTOR

        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        xdata, ydata = event.xdata, event.ydata

        new_w = (xmax - xmin) * scale
        new_h = (ymax - ymin) * scale
        relx = (xmax - xdata) / (xmax - xmin) if xmax != xmin else 0.5
        rely = (ymax - ydata) / (ymax - ymin) if ymax != ymin else 0.5

        ax.set_xlim(xdata - new_w * (1 - relx), xdata + new_w * relx)
        ax.set_ylim(ydata - new_h * (1 - rely), ydata + new_h * rely)
        self.plot_canvas.draw_idle()
        self._sync_axis_fields()

    def _sync_axis_fields(self):
        if self.current_ax is None:
            return
        xmin, xmax = self.current_ax.get_xlim()
        ymin, ymax = self.current_ax.get_ylim()
        self.xmin_var.set(f"{xmin:.4g}")
        self.xmax_var.set(f"{xmax:.4g}")
        self.ymin_var.set(f"{ymin:.4g}")
        self.ymax_var.set(f"{ymax:.4g}")

    def _on_apply_axis_limits(self):
        if self.current_ax is None:
            messagebox.showinfo("Chart view", "No chart displayed yet.")
            return
        try:
            xmin = float(self.xmin_var.get())
            xmax = float(self.xmax_var.get())
            ymin = float(self.ymin_var.get())
            ymax = float(self.ymax_var.get())
        except ValueError:
            messagebox.showerror("Invalid values", "Xmin/Xmax/Ymin/Ymax must be numbers.")
            return
        if xmin >= xmax or ymin >= ymax:
            messagebox.showerror("Invalid values", "Each minimum must be strictly less than its maximum.")
            return
        self.current_ax.set_xlim(xmin, xmax)
        self.current_ax.set_ylim(ymin, ymax)
        self.plot_canvas.draw_idle()

    def _on_autoscale_axis(self):
        if self.current_ax is None:
            return
        self.current_ax.relim()
        self.current_ax.autoscale()
        self.plot_canvas.draw_idle()
        self._sync_axis_fields()

    # ------------------------------------------------------------------
    # Callbacks delegated to the application
    # ------------------------------------------------------------------
    def _on_activate(self):
        self.app.set_active_plot_window(self)

    def _on_new_window(self):
        self.app.new_plot_window()

    def _on_close(self):
        self.app.remove_plot_window(self)
        self.win.destroy()
