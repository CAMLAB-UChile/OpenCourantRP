"""Compressed animation files (/ANIM/GZIP): the All / Some / Cancel question, the file window and the progress window."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

from . import gzanim


def size_text(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def ask_mode(parent, files: list[gzanim.GzFile]) -> str | None:
    """Ask what to convert: "all", "some" or None (Cancel, or the box was closed)."""
    total = size_text(sum(f.size for f in files))
    box = QMessageBox(QMessageBox.Question, "Compressed animation files",
                      f"This run wrote {len(files)} compressed animation file(s) (/ANIM/GZIP, {total}) that are not yet "
                      "converted to .vtk, so they cannot be shown.\n\n"
                      "Decompress and convert all the time steps, or only some of them?", parent=parent)
    all_btn = box.addButton("All", QMessageBox.AcceptRole)
    some_btn = box.addButton("Some", QMessageBox.AcceptRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(some_btn)
    box.exec()
    return {all_btn: "all", some_btn: "some"}.get(box.clickedButton())


def choose_files(parent, folder: str, name: str) -> list[Path]:
    """File window that lists only the compressed animation files of the run."""
    paths, _ = QFileDialog.getOpenFileNames(parent, "Choose the time steps to decompress and convert", folder,
                                            f"Compressed animation files ({name}A*.gz)")
    return [Path(p) for p in paths]


class _Worker(QThread):
    """Converts the files one after another so that the window stays alive."""

    progress = Signal(int, str)  # how many are done, the file being converted
    failed = Signal(str)

    def __init__(self, files: list[Path], solver: Path, parent=None):
        super().__init__(parent)
        self.files, self.solver = files, solver

    def run(self) -> None:
        for n, gz in enumerate(self.files):
            self.progress.emit(n, gz.name)
            try:
                gzanim.convert(gz, self.solver)
            except RuntimeError as exc:
                self.failed.emit(str(exc))
                return
        self.progress.emit(len(self.files), "")


class ConvertDialog(QDialog):
    """Progress of the conversion; it closes by itself when every file is done and stays open to show an error."""

    def __init__(self, files: list[Path], solver: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Decompressing and converting")
        self.setMinimumWidth(460)
        self.files = files
        self.count = 0
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, len(files))
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.status)
        lay.addWidget(self.bar)
        lay.addLayout(buttons)
        self._failed = False
        self._worker = _Worker(files, solver, self)
        self._worker.progress.connect(self._progress)
        self._worker.failed.connect(self._fail)
        self._worker.finished.connect(self._finished)

    def exec(self) -> int:
        self._worker.start()
        return super().exec()

    def reject(self) -> None:
        if not self._worker.isRunning():  # Esc or the close box do nothing while the converter works
            super().reject()

    def _progress(self, done: int, current: str) -> None:
        self.count = done
        self.bar.setValue(done)
        self.status.setText(f"Converting {current} ({done + 1} of {len(self.files)})..." if current
                            else f"Done: {done} file(s) converted.")

    def _fail(self, message: str) -> None:
        self._failed = True
        self.status.setText(message)

    def _finished(self) -> None:
        self.close_btn.setEnabled(True)
        if not self._failed:
            self.accept()
