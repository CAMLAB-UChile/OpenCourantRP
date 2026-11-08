"""The Results tab: a tree of the variables that can be plotted, and the choice through the shell thickness."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QGridLayout, QGroupBox, QLabel, QPushButton, QRadioButton,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .variables import (
    AXES, DEFAULT_AXES, DEFAULT_KEY, DEFAULT_THICKNESS, FALLBACK_KEYS, GROUPS, THICKNESS, VARIABLES, Variable, available,
    has_shells, has_solids, shell_available, variable,
)

SOLID_NOTE = "Through the thickness and the axes apply to shells; solids show their element value (global axes)."
LOCAL_NOTE = "A component of the tensor: in the global or in the local axes of each element, as chosen under Axes."
HTML_ROLE = Qt.UserRole + 1
KEY_ROLE = Qt.UserRole


class _RichDelegate(QStyledItemDelegate):
    """Draws the rich text (italic symbols with subscripts) of the variable names."""

    def _document(self, option: QStyleOptionViewItem, html: str, colour: str) -> QTextDocument:
        doc = QTextDocument()
        font = option.font
        font.setPointSizeF(font.pointSizeF() + 2)
        doc.setDefaultFont(font)
        doc.setHtml(f'<span style="color:{colour}">{html}</span>')
        return doc

    def paint(self, painter, option, index):
        html = index.data(HTML_ROLE)
        if not html:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)  # background, selection
        if not opt.state & QStyle.State_Enabled:
            role = QPalette.Disabled
        else:
            role = QPalette.Active
        group = QPalette.HighlightedText if opt.state & QStyle.State_Selected else QPalette.Text
        doc = self._document(opt, html, opt.palette.color(role, group).name())
        painter.save()
        painter.translate(opt.rect.left() + 6, opt.rect.top() + (opt.rect.height() - doc.size().height()) / 2)
        doc.documentLayout().draw(painter, QAbstractTextDocumentLayout.PaintContext())
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        html = index.data(HTML_ROLE)
        if html:
            doc = self._document(option, html, "#000000")
            size = QSize(size.width(), int(doc.size().height()) + 2)
        return size


class ResultsPanel(QWidget):
    """Tree of variables, "Through the thickness" buttons and the "Smoothed" box."""

    changed = Signal()

    def __init__(self, smooth_check: QCheckBox, parent=None):
        super().__init__(parent)
        self.smooth_check = smooth_check
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(18)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tree.setItemDelegate(_RichDelegate(self.tree))
        self._items: dict[str, QTreeWidgetItem] = {}
        for group in GROUPS:
            top = QTreeWidgetItem([group])
            top.setFlags(Qt.ItemIsEnabled)  # a heading: neither selectable nor plottable
            self.tree.addTopLevelItem(top)
            for var in (v for v in VARIABLES if v.group == group):
                item = QTreeWidgetItem([var.title])
                item.setData(0, HTML_ROLE, var.html)
                item.setData(0, KEY_ROLE, var.key)
                if var.local:
                    item.setToolTip(0, LOCAL_NOTE)
                top.addChild(item)
                self._items[var.key] = item
            top.setExpanded(True)

        box = QGroupBox("Through the thickness")
        grid = QGridLayout(box)
        self.radios: dict[str, QRadioButton] = {}
        self.group = QButtonGroup(self)
        for n, name in enumerate(THICKNESS):
            radio = QRadioButton(name)
            self.radios[name] = radio
            self.group.addButton(radio)
            grid.addWidget(radio, n // 3, n % 3)
        self.radios[DEFAULT_THICKNESS].setChecked(True)
        self.radios["membrane"].setToolTip("The tensor averaged through the thickness, when the run wrote it")
        self.mesh = None
        grid.addWidget(smooth_check, 2, 0, 1, 3)

        axes_box = QGroupBox("Axes of the components")
        axes_lay = QGridLayout(axes_box)
        self.axes_radios: dict[str, QRadioButton] = {}
        self.axes_group = QButtonGroup(self)
        for n, name in enumerate(AXES):
            radio = QRadioButton(name)
            self.axes_radios[name] = radio
            self.axes_group.addButton(radio)
            axes_lay.addWidget(radio, 0, n)
        self.axes_radios[DEFAULT_AXES].setChecked(True)
        self.local_label = QLabel()
        self.notice_label = QLabel()  # warning about the integration points of the shown parts
        for label in (self.local_label, self.notice_label):
            label.setWordWrap(True)
            label.setVisible(False)
        self.notice = ""
        self.gz_button = QPushButton()  # compressed steps not yet converted: clicking asks again
        self.gz_button.setVisible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.gz_button)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.local_label)
        lay.addWidget(self.notice_label)
        lay.addWidget(axes_box)
        lay.addWidget(box)

        self.tree.currentItemChanged.connect(self._select)
        self.group.buttonToggled.connect(lambda *_: self._update_state() or self.changed.emit())
        self.axes_group.buttonToggled.connect(lambda *_: self._update_state() or self.changed.emit())
        self.axes_box = axes_box
        smooth_check.toggled.connect(lambda *_: self.changed.emit())
        self.select(DEFAULT_KEY)

    # ------------------------------------------------------------ state
    def variable(self) -> Variable:
        item = self.tree.currentItem()
        key = item.data(0, KEY_ROLE) if item is not None else None
        return variable(key or DEFAULT_KEY)

    def thickness(self) -> str:
        return next((name for name, radio in self.radios.items() if radio.isChecked()), DEFAULT_THICKNESS)

    def select(self, key: str) -> None:
        self.tree.setCurrentItem(self._items.get(key, self._items[DEFAULT_KEY]))

    def axes(self) -> str:
        return next((name for name, radio in self.axes_radios.items() if radio.isChecked()), DEFAULT_AXES)

    def set_axes(self, name: str) -> None:
        self.axes_radios.get(name, self.axes_radios[DEFAULT_AXES]).setChecked(True)

    def set_thickness(self, name: str) -> None:
        self.radios.get(name, self.radios[DEFAULT_THICKNESS]).setChecked(True)

    def _select(self, item, _previous=None) -> None:
        if item is not None and item.data(0, KEY_ROLE) is None:  # a heading: keep the variable
            return
        self._update_state()
        self.changed.emit()

    def _update_state(self) -> None:
        var = self.variable()
        for name, radio in self.radios.items():
            # U, V and damage do not vary through the thickness; a place the file has no data for cannot be chosen
            radio.setEnabled(var.layered and self._place_ok(name) and (name != "membrane" or self._membrane_ok(var)))
        self.smooth_check.setEnabled(not var.nodal)  # nodal results are already smooth
        self.axes_box.setEnabled(var.local and self._has_shells())  # only the tensor components depend on the axes;
        # solids are written in the global axes
        self.local_label.setText("Components along the global X, Y, Z (each element's local result rotated)."
                                 if self.axes() == "global" else "Components in the local axes of each element, as the solver writes them.")
        self.local_label.setVisible(var.local)
        text = self.notice if var.layered and self.thickness() in ("middle", "max", "min") else ""
        if var.layered and self.mesh is not None and has_shells(self.mesh) and has_solids(self.mesh):
            text = (text + "\n" if text else "") + SOLID_NOTE
        self.notice_label.setText(text)
        self.notice_label.setVisible(bool(text))

    def set_gz_pending(self, count: int) -> None:
        """Hint with a button while /ANIM/GZIP time steps are not converted to .vtk (0 hides it)."""
        self.gz_button.setText(f"{count} compressed time step(s) not converted. Convert..." if count else "")
        self.gz_button.setVisible(count > 0)

    def set_notice(self, text: str) -> None:
        """Warning shown while a variable that uses the middle of the thickness is selected ("" = none)."""
        self.notice = text
        self._update_state()

    def _has_shells(self) -> bool:
        return self.mesh is None or has_shells(self.mesh)

    def _membrane_ok(self, var: Variable) -> bool:
        """Can `var` be shown as the membrane tensor in the file on screen?"""
        return self.mesh is not None and shell_available(var, self.mesh, "membrane") and var.kind == "tensor"

    def _place_ok(self, name: str) -> bool:
        """Does the file on screen hold anything for this place through the thickness (top, bottom, ...)?"""
        return self.mesh is None or any(shell_available(v, self.mesh, name) for v in VARIABLES if v.layered)

    def set_mesh(self, mesh) -> None:
        """Grey out the variables the result file does not hold; the optional ones (damage) are listed only if it does."""
        self.mesh = mesh
        if not self._place_ok(self.thickness()) or (self.thickness() == "membrane" and not self._membrane_ok(self.variable())):
            self.group.blockSignals(True)  # the caller redraws
            self.radios[DEFAULT_THICKNESS].setChecked(True)
            self.group.blockSignals(False)
        self._update_state()
        thickness = self.thickness()
        for key, item in self._items.items():
            var = variable(key)
            ok = mesh is None or available(var, mesh, "middle" if thickness == "membrane" and var.kind == "plastic" else thickness)
            item.setFlags(item.flags() | Qt.ItemIsEnabled if ok else item.flags() & ~Qt.ItemIsEnabled)
            if var.optional:
                item.setHidden(mesh is None or not ok)
        for n in range(self.tree.topLevelItemCount()):  # a heading with nothing under it is hidden too
            top = self.tree.topLevelItem(n)
            top.setHidden(all(top.child(i).isHidden() for i in range(top.childCount())))
        current = self.tree.currentItem()
        if current is not None and (current.isHidden() or not current.flags() & Qt.ItemIsEnabled):
            # the variable on screen is not in this file: take the first one that is (U, V, sigma_vm, ...)
            usable = [key for key, item in self._items.items() if item.flags() & Qt.ItemIsEnabled and not item.isHidden()]
            fallback = next((k for k in FALLBACK_KEYS if k in usable), usable[0] if usable else DEFAULT_KEY)
            self.tree.blockSignals(True)  # the caller redraws; no second redraw from here
            self.select(fallback)
            self.tree.blockSignals(False)
            self._update_state()
