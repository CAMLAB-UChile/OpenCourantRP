"""Window where the user types the units of the model and of the results."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QDialog

from .units import FIELDS, Units


class UnitsDialog(QDialog):
    """One text box per quantity. Units are labels only; nothing is converted. Changes apply as you type."""

    changed = Signal(Units)

    def __init__(self, units: Units, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Units")
        self.setMinimumWidth(360)
        note = QLabel("Declare the units of your model. They are only shown next to the values (colour bar title, "
                      "min/max, probes); nothing is converted. A box left empty shows no unit. "
                      "Strains have no unit.")
        note.setWordWrap(True)
        self._edits = {}
        form = QFormLayout()
        for key, label, hint in FIELDS:
            edit = QLineEdit(getattr(units, key))
            edit.setPlaceholderText(hint)
            edit.setMaxLength(24)
            edit.textChanged.connect(self._edited)
            self._edits[key] = edit
            form.addRow(label + ":", edit)
        clear, close = QPushButton("Clear all"), QPushButton("Close")
        clear.clicked.connect(self._clear)
        close.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(clear)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay = QVBoxLayout(self)
        lay.addWidget(note)
        lay.addLayout(form)
        lay.addLayout(buttons)

    def units(self) -> Units:
        return Units(**{k: e.text().strip() for k, e in self._edits.items()})

    def _edited(self, *_) -> None:
        self.changed.emit(self.units())

    def _clear(self) -> None:
        for edit in self._edits.values():
            edit.blockSignals(True)
            edit.clear()
            edit.blockSignals(False)
        self.changed.emit(self.units())
