"""The "Save snapshot" file window, with a quality (picture size) box under the file name."""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QSpinBox, QWidget

from . import snapshot


class SnapshotDialog(QFileDialog):
    """Save-file window with the four picture types and a "Quality" box.

    Quality is how many times larger than the view on screen the picture is drawn (1 = as on screen).
    It is remembered for each type: `qualities` maps an extension (".pdf") to its last value.
    """

    def __init__(self, parent, directory: str, view_size: tuple[int, int], qualities: dict[str, int], filter_text: str):
        super().__init__(parent, "Save snapshot", directory, snapshot.FILTERS)
        self.setAcceptMode(QFileDialog.AcceptSave)
        self.setOption(QFileDialog.DontUseNativeDialog, True)  # a custom row cannot be added to the native window
        self._view = view_size
        self._qualities = dict(qualities)
        self._ext = None  # type whose quality the box shows
        if filter_text:
            self.selectNameFilter(filter_text)

        self.quality = QSpinBox()
        self.quality.setRange(*snapshot.QUALITY_RANGE)
        self.quality.setSuffix(" x")
        self.quality.setToolTip("How many times larger than the view on screen the picture is drawn")
        self.size_label = QLabel()
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.quality)
        box.addWidget(self.size_label)
        box.addStretch(1)
        grid = self.layout()
        r = grid.rowCount()
        grid.addWidget(QLabel("Quality:"), r, 0)
        grid.addWidget(row, r, 1, 1, grid.columnCount() - 1)

        self.quality.valueChanged.connect(self._update_size)
        self.filterSelected.connect(self._filter_changed)
        self._filter_changed(self.selectedNameFilter())

    def extension(self) -> str:
        return snapshot.extension_for(self.selectedNameFilter())

    def qualities(self) -> dict[str, int]:
        """All remembered qualities, with the one just chosen for the selected type."""
        return {**self._qualities, self._ext: self.quality.value()}

    def _filter_changed(self, filter_text: str) -> None:
        if self._ext is not None:  # keep the value of the type being left
            self._qualities[self._ext] = self.quality.value()
        self._ext = snapshot.extension_for(filter_text)
        self.quality.setValue(self._qualities.get(self._ext, snapshot.default_quality(self._ext)))
        self._update_size()

    def _update_size(self, *_) -> None:
        w, h = self._view
        q = self.quality.value()
        self.size_label.setText(f"{w * q} × {h * q} px")
