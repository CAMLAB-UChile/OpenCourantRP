"""Window to save the current layout under a name, and to load or delete a saved one."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QVBoxLayout,
)

from . import presets


class PresetDialog(QDialog):
    """Lists the saved presets. The window only asks; the main window stores and applies them."""

    save_requested = Signal(str)  # name: store the current layout under it
    load_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, names: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Layout presets")
        self.setMinimumWidth(400)
        self.names = QListWidget()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the preset")
        self.name_edit.setMaxLength(presets.MAX_NAME)
        self.btn_save = QPushButton("Save current layout")
        self.btn_load = QPushButton("Load")
        self.btn_delete = QPushButton("Delete")
        close = QPushButton("Close")

        info = QLabel("A preset holds the colour bar (colormap, colours, digits, format, caps), the min/max symbols, "
                      "the probe, the fonts and the model colours (background, entities, triad, cube). "
                      "Double-click a name to load it.")
        info.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.name_edit, 1)
        row.addWidget(self.btn_save)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_load)
        buttons.addWidget(self.btn_delete)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.names, 1)
        lay.addLayout(row)
        lay.addLayout(buttons)

        self.set_names(names)
        self.names.currentTextChanged.connect(self._selected)
        self.names.itemDoubleClicked.connect(lambda item: self.load_requested.emit(item.text()))
        self.name_edit.textChanged.connect(self._update_buttons)
        self.name_edit.returnPressed.connect(self._save)
        self.btn_save.clicked.connect(self._save)
        self.btn_load.clicked.connect(lambda: self.load_requested.emit(self.names.currentItem().text()))
        self.btn_delete.clicked.connect(self._delete)
        close.clicked.connect(self.accept)
        self._update_buttons()

    def set_names(self, names: list[str], select: str | None = None) -> None:
        self.names.clear()
        self.names.addItems(names)
        for i, n in enumerate(names):
            if n == select:
                self.names.setCurrentRow(i)
        self._update_buttons()

    def _selected(self, text: str) -> None:
        if text:
            self.name_edit.setText(text)
        self._update_buttons()

    def _update_buttons(self, *_) -> None:
        has_item = self.names.currentItem() is not None
        self.btn_save.setEnabled(bool(presets.clean_name(self.name_edit.text())))
        self.btn_load.setEnabled(has_item)
        self.btn_delete.setEnabled(has_item)

    def _save(self) -> None:
        name = presets.clean_name(self.name_edit.text())
        if not name:
            return
        if name in [self.names.item(i).text() for i in range(self.names.count())]:
            ask = QMessageBox.question(self, "Layout presets", f"Replace the preset '{name}' with the current layout?")
            if ask != QMessageBox.Yes:
                return
        self.save_requested.emit(name)

    def _delete(self) -> None:
        item = self.names.currentItem()
        if item and QMessageBox.question(self, "Layout presets", f"Delete the preset '{item.text()}'?") == QMessageBox.Yes:
            self.delete_requested.emit(item.text())
