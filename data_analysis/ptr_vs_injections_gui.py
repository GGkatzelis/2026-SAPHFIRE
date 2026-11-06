"""SAPHFIRE 2026 — PTR-ToF-MS against the logged injections (desktop window, PyQt6 + matplotlib).

    run_ptr_vs_injections.bat          no console window
    python ptr_vs_injections_gui.py    from a terminal or the VS Code Run button

The filters on the left apply to every tab.  The calculation is in ``ptr_vs_injections.py``,
the figures are in ``ptr_vs_injections_figures.py``, and the look and the mouse interaction
come from ``../saphfire_gui`` (the JUICE format).

Mouse on every plot: wheel zooms horizontally · Ctrl+wheel or right-drag up/down zooms
vertically · left-drag pans · double-click resets · right-click opens the zoom / log scale
menu.  Hovering a point reads its values; clicking it opens its time series.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):                  # saphfire_gui, and this folder's own modules
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import PyQt6  # noqa: F401
except ImportError:
    # Started with a Python that has no packages (for example the VS Code Run button with the
    # wrong interpreter): hand over to the shared venv.
    import subprocess
    _venv = ROOT.parents[1] / ".venv" / "Scripts" / "python.exe"
    if _venv.exists() and Path(sys.executable).resolve() != _venv.resolve():
        raise SystemExit(subprocess.call([str(_venv), str(Path(__file__).resolve())], cwd=HERE))
    raise

# Started as a program: say what is happening before pandas / matplotlib load
_LOADER = None
if __name__ == "__main__":
    try:
        from saphfire_gui.loading_box import LoadingBox
        _LOADER = LoadingBox.start("PTR vs injections")
        _LOADER.step("Loading the plotting and data libraries", None,
                     "pandas, matplotlib and Qt are imported once per window; this takes a few seconds")
    except Exception:
        _LOADER = None

import numpy as np                                                              # noqa: E402
import pandas as pd                                                             # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas  # noqa: E402
from matplotlib.figure import Figure                                            # noqa: E402
from PyQt6.QtCore import Qt, QTimer                                             # noqa: E402
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,  # noqa: E402
                             QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                             QPushButton, QSizePolicy, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem,
                             QTabWidget, QToolButton, QVBoxLayout, QWidget)

import ptr_vs_injections as pvi                                                 # noqa: E402
import ptr_vs_injections_figures as figs                                        # noqa: E402
from injections import OUTPUT_DIR, injection_log                                # noqa: E402
from saphfire_gui.plot_interaction import attach                                # noqa: E402

ROUTES = ["Solution A", "Solution B", "Solution C", "Solution D", "Gas bottle", "Neat liquid"]
HINT = ("wheel: zoom horizontally · Ctrl+wheel or right-drag up/down: zoom vertically · left-drag: pan · "
        "double-click: reset · right-click: zoom / log scale menu")
POINT_HINT = " · hover a point: values · click a point: its time series"
NO_DATA = "No comparison left with these filters."


def _progress(message: str, percent=None, why: str = "") -> None:
    """Report a start-up stage to the loading window when there is one (no-op otherwise)."""
    if _LOADER is not None:
        try:
            _LOADER.step(message, percent, why)
        except Exception:
            pass


def _small_button(text: str, tip: str, slot) -> QToolButton:
    b = QToolButton(); b.setText(text); b.setToolTip(tip); b.clicked.connect(slot); b.setAutoRaise(True)
    return b


def _combo(items, slot, tip: str = "") -> QComboBox:
    c = QComboBox(); c.addItems(items); c.setToolTip(tip); c.currentIndexChanged.connect(slot)
    return c


def _refill(combo: QComboBox, items, data=None) -> None:
    """Replace a combo's entries without firing its signal; keep the selection when it still exists."""
    keep = combo.currentData() if data is not None else combo.currentText()
    combo.blockSignals(True)
    combo.clear()
    for i, text in enumerate(items):
        combo.addItem(text, None if data is None else data[i])
    idx = combo.findData(keep) if data is not None else combo.findText(keep)
    combo.setCurrentIndex(max(idx, 0))
    combo.blockSignals(False)


class PointReadout:
    """Hover readout for the points of a scatter-like panel, and a click on a point."""
    RADIUS = 12            # px: how close the mouse has to be

    def __init__(self, canvas, on_click=None):
        self.canvas, self.on_click = canvas, on_click
        self.ax, self.points, self._xy, self._note, self._down = None, [], np.empty((0, 2)), None, None
        canvas.mpl_connect("motion_notify_event", self._motion)
        canvas.mpl_connect("button_press_event", self._press)
        canvas.mpl_connect("button_release_event", self._release)
        canvas.mpl_connect("axes_leave_event", lambda _e: self._clear())

    def set(self, ax, points) -> None:
        self.ax, self.points, self._note = ax, points or [], None
        self._xy = np.array([[p["x"], p["y"]] for p in self.points], dtype=float).reshape(-1, 2)

    def _nearest(self, event):
        if self.ax is None or event.inaxes is not self.ax or not len(self._xy) or event.x is None:
            return None
        with np.errstate(all="ignore"):
            px = self.ax.transData.transform(self._xy)
        dist = np.hypot(px[:, 0] - event.x, px[:, 1] - event.y)
        dist[~np.isfinite(dist)] = np.inf
        i = int(np.argmin(dist))
        return i if dist[i] <= self.RADIUS * self.canvas.device_pixel_ratio else None

    def _clear(self, draw=True):
        if self._note is not None:
            try:
                self._note.remove()
            except Exception:
                pass
            self._note = None
            if draw:
                self.canvas.draw_idle()

    def _motion(self, event):
        if event.button is not None and self._down is not None:      # dragging: the pan has the mouse
            self._clear(); return
        i = self._nearest(event)
        self._clear(draw=False)
        if i is not None:
            p = self.points[i]
            fx, fy = self.ax.transAxes.inverted().transform((event.x, event.y))
            self._note = self.ax.annotate(
                p["text"], xy=(p["x"], p["y"]), xytext=(-12 if fx > 0.6 else 12, -12 if fy > 0.6 else 12),
                textcoords="offset points", ha="right" if fx > 0.6 else "left", va="top" if fy > 0.6 else "bottom",
                fontsize=9.5, color=figs.INK, zorder=20, annotation_clip=False,
                bbox=dict(boxstyle="round,pad=0.35", fc="white", ec="#aaaaaa", alpha=0.95))
            self._note.set_in_layout(False)
        self.canvas.draw_idle()

    def _press(self, event):
        self._down = (event.x, event.y) if event.button == 1 and not event.dblclick else None

    def _release(self, event):
        down, self._down = self._down, None
        if down is None or event.x is None or self.on_click is None:
            return
        if abs(event.x - down[0]) + abs(event.y - down[1]) < 4:      # a click, not a drag
            i = self._nearest(event)
            if i is not None:
                self.on_click(self.points[i])


class PlotTab(QWidget):
    """One tab: a row of options, a note line, and an interactive matplotlib canvas."""

    def __init__(self, window, name: str, points: bool = True):
        super().__init__()
        self.w, self.name = window, name
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 2); lay.setSpacing(2)
        self.bar = QHBoxLayout(); self.bar.setSpacing(6); lay.addLayout(self.bar)
        self.note = QLabel(""); self.note.setStyleSheet("color: #666; font-size: 9pt;"); self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.fig = Figure(layout="constrained"); self.canvas = FigureCanvas(self.fig)
        lay.addWidget(self.canvas, stretch=1)
        attach(self.canvas, hover=not points)                # JUICE mouse interaction
        self.readout = PointReadout(self.canvas, window.open_time_series) if points else None
        self._hint = HINT + (POINT_HINT if points else " · move the mouse: read the values")

    def option(self, label: str, widget) -> None:
        if label:
            self.bar.addWidget(QLabel(label))
        self.bar.addWidget(widget)

    def finish_bar(self) -> None:
        self.bar.addWidget(_small_button("Reset view", "back to the full view (or double-click the plot)", self.redraw))
        self.bar.addWidget(_small_button("Save image", "save this figure as PNG, SVG or PDF", self.save_image))
        hint = QLabel(self._hint); hint.setStyleSheet("color: #888; font-size: 10px;")
        hint.setToolTip(self._hint.replace(" · ", "\n"))          # the full list when the row is too narrow
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.bar.addWidget(hint, stretch=1)

    def draw(self, ax):                     # overridden per tab: draw into ax, return hover points
        raise NotImplementedError

    def redraw(self) -> None:
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        points = None
        if self.w.valid.empty:
            ax.set_axis_off()
            ax.text(0.5, 0.5, NO_DATA, ha="center", va="center", color=figs.MUTED, transform=ax.transAxes)
        else:
            points = self.draw(ax)
        if self.readout is not None:
            self.readout.set(ax, points)
        self.canvas.draw_idle()

    def save_image(self) -> None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "Save image", str(OUTPUT_DIR / f"{self.name}.png"),
                                              "PNG image (*.png);;SVG (*.svg);;PDF (*.pdf)")
        if path:
            self.fig.savefig(path, dpi=200)
            self.w.statusBar().showMessage(f"Saved {path}", 6000)


class PercentTab(PlotTab):
    def __init__(self, window):
        super().__init__(window, "ptr_pct_difference_by_formula")
        self.kind = _combo(["Violin", "Box", "Points"], self.redraw, "violin or box for formulas with at least three experiments")
        self.sort = _combo(["Median", "Formula"], self.redraw)
        self.high = _combo(["None"], self.redraw, "draw one experiment in a second colour")
        self.option("Show as", self.kind); self.option("Order by", self.sort); self.option("Highlight", self.high)
        self.finish_bar()
        self.note.setText("Each point is one experiment; the black line marks the median. Isomers share one row.")

    def draw(self, ax):
        hi = self.high.currentText()
        return figs.pct_by_formula(ax, self.w.valid, self.kind.currentText(), self.sort.currentText(),
                                   None if hi == "None" else hi)


class ScatterTab(PlotTab):
    def __init__(self, window):
        super().__init__(window, "ptr_observed_vs_expected")
        self.mode = _combo(["Mean per formula", "Every experiment"], self._mode_changed)
        self.error = _combo(["Std dev", "Min-max"], self.redraw, "spread between the experiments of a formula")
        self.labels = _combo(["Outliers", "All", "None"], self.redraw, "which formulas are named in the plot")
        self.log = QCheckBox("Log axes"); self.log.setChecked(True); self.log.toggled.connect(self.redraw)
        self.high = _combo(["None"], self.redraw, "draw one experiment in a second colour")
        self.option("Points", self.mode); self.option("Error bars", self.error); self.option("Labels", self.labels)
        self.option("", self.log); self.option("Highlight", self.high)
        self.finish_bar()
        self._mode_changed()

    def _mode_changed(self):
        mean = self.mode.currentText() == "Mean per formula"
        self.error.setEnabled(mean); self.labels.setEnabled(mean); self.high.setEnabled(not mean)
        if hasattr(self.w, "valid"):
            self.redraw()

    def draw(self, ax):
        mean = self.mode.currentText() == "Mean per formula"
        hi = self.high.currentText()
        points, hidden, floor = figs.observed_vs_expected(
            ax, self.w.valid, self.mode.currentText(), self.log.isChecked(), self.labels.currentText(),
            None if hi == "None" or mean else hi, self.error.currentText())
        spread = "the standard deviation" if self.error.currentText() == "Std dev" else "the lowest and highest value"
        note = (f"Each point is one formula, averaged over its experiments. Error bars show {spread} between "
                "experiments, so they include the different amounts injected."
                if mean else "Each point is one formula in one experiment.")
        if hidden:
            note += (f" Not shown on logarithmic axes: {hidden} point(s) with a PTR increase below {floor:.2f} ppbv; "
                     "switch off log axes to see them.")
        self.note.setText(note)
        return points


class TimeSeriesTab(PlotTab):
    def __init__(self, window):
        super().__init__(window, "ptr_time_series", points=False)
        self.period = _combo([], self._period_changed)
        self.formula = _combo([], self.redraw)
        self.option("Experiment", self.period); self.option("PTR formula", self.formula)
        self.finish_bar()

    def refill(self) -> None:
        v = self.w.valid
        _refill(self.period, [p for p in self.w.periods if p in set(v.period)])
        self._fill_formulas()

    def _fill_formulas(self) -> None:
        v = self.w.valid
        sub = v[v.period == self.period.currentText()].sort_values("expected_ppbv", ascending=False)
        _refill(self.formula, [f"{r.formula} · {r.compounds}" for r in sub.itertuples()], list(sub.formula))

    def _period_changed(self):
        self._fill_formulas()
        self.redraw()

    def select(self, period: str, formula: str) -> None:
        self.period.blockSignals(True); self.period.setCurrentIndex(max(self.period.findText(period), 0))
        self.period.blockSignals(False)
        self._fill_formulas()
        self.formula.blockSignals(True); self.formula.setCurrentIndex(max(self.formula.findData(formula), 0))
        self.formula.blockSignals(False)
        self.redraw()

    def draw(self, ax):
        v = self.w.valid
        sel = v[(v.period == self.period.currentText()) & (v.formula == self.formula.currentData())]
        if sel.empty:
            ax.set_axis_off(); self.note.setText(""); return None
        rec = sel.iloc[0]
        log = self.w.log
        inj = log[(log.date == rec.date) & (log.formula.map(pvi.canon) == pvi.canon(rec.formula))]
        figs.time_series(ax, pvi.ptr_series(rec.date, rec.formula), rec, inj)
        self.note.setText(f"{rec.pattern}. Expected {rec.expected_ppbv:.2f} ppbv, PTR increase {rec.observed_ppbv:.2f} ppbv, "
                          f"difference {rec.pct_difference:+.0f} %. {rec.rule}. {rec.note}".strip())
        return None


class _Cell(QTableWidgetItem):
    """Table cell that sorts numbers as numbers."""

    def __init__(self, value):
        number = isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, bool)
        missing = number and value != value
        if number:
            text = "" if missing else (f"{value:.2f}" if isinstance(value, (float, np.floating)) else str(value))
        else:
            text = "" if value is None else str(value)
        super().__init__(text)
        self.key = (-np.inf if missing else float(value)) if number else text.lower()
        if number:
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        try:
            return self.key < other.key
        except TypeError:
            return str(self.key) < str(other.key)


class TableTab(QWidget):
    def __init__(self, window):
        super().__init__()
        self.w = window
        lay = QVBoxLayout(self); lay.setContentsMargins(4, 4, 4, 2); lay.setSpacing(4)
        bar = QHBoxLayout(); bar.setSpacing(6); lay.addLayout(bar)
        bar.addWidget(QLabel("Rows"))
        self.view = _combo(["Every experiment", "Per formula"], self.fill); bar.addWidget(self.view)
        bar.addWidget(_small_button("Export CSV", "save this table as a CSV file", self.export))
        bar.addStretch()
        self.table = QTableWidget(); self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        lay.addWidget(self.table, stretch=1)
        self.df = pd.DataFrame()

    def fill(self) -> None:
        per_formula = self.view.currentText() == "Per formula"
        self.df = df = (pvi.formula_summary(self.w.valid) if per_formula and not self.w.valid.empty
                        else (pd.DataFrame() if per_formula else self.w.cmp))
        t = self.table
        t.setSortingEnabled(False)
        t.clear(); t.setRowCount(len(df)); t.setColumnCount(len(df.columns))
        t.setHorizontalHeaderLabels([c.replace("_", " ") for c in df.columns])
        for j, col in enumerate(df.columns):
            for i, value in enumerate(df[col].tolist()):
                t.setItem(i, j, _Cell(value))
        t.resizeColumnsToContents()
        for j in range(t.columnCount()):
            t.setColumnWidth(j, min(t.columnWidth(j), 320))
        t.setSortingEnabled(True)

    def export(self) -> None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        name = "ptr_vs_expected_by_formula.csv" if self.view.currentText() == "Per formula" else "ptr_vs_expected.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export table", str(OUTPUT_DIR / name), "CSV (*.csv)")
        if path:
            self.df.to_csv(path, index=False)
            self.w.statusBar().showMessage(f"Saved {path}", 6000)


class PtrVsInjections(QMainWindow):
    def __init__(self, log: pd.DataFrame, cmp: pd.DataFrame):
        super().__init__()
        self.log = log
        self._by_window = {10: cmp}                      # comparison per averaging length (minutes)
        self.periods = list(dict.fromkeys(cmp.period))
        self.cmp = cmp
        self.valid = cmp.dropna(subset=["pct_difference"])
        self.setWindowTitle("SAPHFIRE — PTR-ToF-MS vs injections")
        self.resize(1500, 950)
        self._timer = QTimer(self); self._timer.setSingleShot(True); self._timer.setInterval(200)
        self._timer.timeout.connect(self.refresh)        # several quick clicks give one redraw

        splitter = QSplitter(Qt.Orientation.Horizontal); self.setCentralWidget(splitter)
        splitter.addWidget(self._controls())
        self.tabs = QTabWidget(); splitter.addWidget(self.tabs)
        self.tab_pct, self.tab_scatter, self.tab_ts, self.tab_table = (PercentTab(self), ScatterTab(self),
                                                                       TimeSeriesTab(self), TableTab(self))
        for tab, name in ((self.tab_pct, "% difference by formula"), (self.tab_scatter, "Observed vs expected"),
                          (self.tab_ts, "Time series"), (self.tab_table, "Table")):
            self.tabs.addTab(tab, name)
        splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1); splitter.setSizes([310, 1190])
        self.refresh()

    # ── left panel: the filters ──
    def _controls(self) -> QWidget:
        panel = QWidget(); panel.setMinimumWidth(290); panel.setMaximumWidth(380)
        lay = QVBoxLayout(panel); lay.setContentsMargins(10, 8, 6, 8); lay.setSpacing(6)
        title = QLabel("PTR vs injections"); title.setObjectName("title"); lay.addWidget(title)
        sub = QLabel("Expected mixing ratio of every logged injection against the increase the PTR measured "
                     "before the roof opened. Isomers are compared as a sum.")
        sub.setObjectName("subtitle"); sub.setWordWrap(True); lay.addWidget(sub)

        box = QGroupBox("Experiments"); v = QVBoxLayout(box)
        self.exp_list = QListWidget(); self.exp_list.setToolTip("experiment, date and the time the PTR average ends (UTC)")
        for p in self.periods:
            item = QListWidgetItem(p); item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked); self.exp_list.addItem(item)
        self.exp_list.itemChanged.connect(lambda _i: self._timer.start())
        v.addWidget(self.exp_list)
        row = QHBoxLayout()
        row.addWidget(_small_button("All", "select every experiment", lambda: self._check_all(True)))
        row.addWidget(_small_button("None", "clear the selection", lambda: self._check_all(False)))
        row.addStretch(); v.addLayout(row)
        lay.addWidget(box, stretch=1)

        box = QGroupBox("Injected as"); v = QVBoxLayout(box); v.setSpacing(2)
        self.route_boxes = {}
        for r in ROUTES:
            cb = QCheckBox(r); cb.setChecked(True); cb.toggled.connect(lambda _on: self._timer.start())
            self.route_boxes[r] = cb; v.addWidget(cb)
        lay.addWidget(box)

        box = QGroupBox("PTR average"); form = QFormLayout(box)
        self.minutes = QSpinBox(); self.minutes.setRange(3, 20); self.minutes.setValue(10); self.minutes.setSuffix(" min")
        self.minutes.setToolTip("length of the PTR average before the roof opened")
        self.minutes.valueChanged.connect(lambda _v: self._timer.start())
        form.addRow("Length", self.minutes)
        self.only_clear = QCheckBox("Only clear increases")
        self.only_clear.setToolTip("keep only comparisons where the PTR signal stepped up at the injection")
        self.only_clear.toggled.connect(lambda _on: self._timer.start())
        form.addRow(self.only_clear)
        lay.addWidget(box)

        box = QGroupBox("Summary"); form = QFormLayout(box)
        self.sum_n, self.sum_f, self.sum_med, self.sum_in = QLabel(), QLabel(), QLabel(), QLabel()
        for text, lab in (("Comparisons", self.sum_n), ("PTR formulas", self.sum_f), ("Median difference", self.sum_med),
                          (f"Within ± {figs.TOLERANCE:.0f} %", self.sum_in)):
            lab.setStyleSheet("font-weight: bold;"); form.addRow(text, lab)
        lay.addWidget(box)
        return panel

    def _check_all(self, on: bool) -> None:
        self.exp_list.blockSignals(True)
        for i in range(self.exp_list.count()):
            self.exp_list.item(i).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.exp_list.blockSignals(False)
        self._timer.start()

    # ── data ──
    def _comparison(self, minutes: int) -> pd.DataFrame:
        if minutes not in self._by_window:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._by_window[minutes] = pvi.compare(self.log, window_min=float(minutes))
            finally:
                QApplication.restoreOverrideCursor()
        return self._by_window[minutes]

    def refresh(self) -> None:
        """Apply the filters and redraw everything."""
        periods = [self.exp_list.item(i).text() for i in range(self.exp_list.count())
                   if self.exp_list.item(i).checkState() == Qt.CheckState.Checked]
        routes = [r for r, cb in self.route_boxes.items() if cb.isChecked()]
        cmp = self._comparison(self.minutes.value())
        cmp = cmp[cmp.period.isin(periods) & cmp.route.apply(lambda r: any(x in routes for x in r.split(", ")))]
        if self.only_clear.isChecked():
            cmp = cmp[cmp.pattern.str.contains("Increase at injection|Slow increase")]
        self.cmp, self.valid = cmp, cmp.dropna(subset=["pct_difference"])
        v = self.valid
        self.sum_n.setText(str(len(v))); self.sum_f.setText(str(v.formula.nunique()))
        self.sum_med.setText(f"{v.pct_difference.median():+.0f} %" if len(v) else "–")
        self.sum_in.setText(f"{(v.pct_difference.abs() <= figs.TOLERANCE).mean():.0%}" if len(v) else "–")
        shown = ["None"] + [p for p in self.periods if p in periods]
        _refill(self.tab_pct.high, shown); _refill(self.tab_scatter.high, shown)
        self.tab_ts.refill()
        for tab in (self.tab_pct, self.tab_scatter, self.tab_ts):
            tab.redraw()
        self.tab_table.fill()
        self.statusBar().showMessage(NO_DATA if v.empty else
                                     f"{len(v)} comparisons · {v.formula.nunique()} formulas · {v.period.nunique()} experiments")

    def open_time_series(self, point: dict) -> None:
        """A click on a point: show that formula in that experiment on the Time series tab."""
        period = point.get("period")
        if period is None:                               # a formula mean: its first experiment
            rows = self.valid[self.valid.formula == point["formula"]]
            if rows.empty:
                return
            period = rows.period.iloc[0]
        self.tab_ts.select(period, point["formula"])
        self.tabs.setCurrentWidget(self.tab_ts)


def _excepthook(kind, value, tb) -> None:
    """Without a console (pythonw) an error would vanish: show it instead."""
    import traceback
    text = "".join(traceback.format_exception(kind, value, tb))
    sys.stderr.write(text) if sys.stderr else None
    if QApplication.instance() is not None:
        QMessageBox.warning(None, "PTR vs injections", f"{kind.__name__}: {value}\n\n{text[-1500:]}")


def main() -> int:
    global _LOADER
    from saphfire_gui.theme import apply_theme, taskbar_identity
    taskbar_identity()
    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app)
    sys.excepthook = _excepthook
    try:
        _progress("Calculating the expected mixing ratios", 30,
                  "every logged injection is converted to ppbv with the injection planner")
        log = injection_log()
        _progress("Reading the PTR data from the archive", 55, "one file per measurement day in the sciebo archive")
        cmp = pvi.compare(log)
        if cmp.empty:
            raise FileNotFoundError(f"No PTR files found in {pvi.archive_dir()}")
    except Exception as exc:                             # missing injections file, archive not reachable …
        if _LOADER is not None:
            _LOADER.close(); _LOADER = None
        QMessageBox.critical(None, "PTR vs injections", str(exc))
        return 1
    _progress("Building the window", 85)
    win = PtrVsInjections(log, cmp)
    win.show()
    try:
        from saphfire_gui.theme import force_taskbar_icon
        force_taskbar_icon(win)                          # the taskbar shows the SAPHFIRE icon, not Python's
    except Exception:
        pass
    if _LOADER is not None:
        _LOADER.done(); _LOADER = None
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
