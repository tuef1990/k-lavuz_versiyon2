from PyQt6.QtWidgets import QStyledItemDelegate, QLineEdit, QHBoxLayout, QWidget, QFrame, QStyle
from PyQt6.QtCore import Qt, QRect, QSize
from PyQt6.QtGui import QPainter, QColor, QPen

class MultiValueDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)

    def paint(self, painter, option, index):
        values = index.data(Qt.ItemDataRole.EditRole)
        if not isinstance(values, list):
            super().paint(painter, option, index)
            return

        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        n = len(values)
        if n == 0: return

        width = option.rect.width() / n
        height = option.rect.height()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        for i, val in enumerate(values):
            rect = QRect(int(option.rect.x() + i * width), 
                         option.rect.y(), 
                         int(width), 
                         height)
            
            # Draw border
            painter.setPen(QPen(QColor("#E2E8F0"), 1))
            painter.drawRect(rect)
            
            # Draw text
            text = str(val)
            painter.setPen(QPen(Qt.GlobalColor.black))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

        painter.restore()

    def createEditor(self, parent, option, index):
        values = index.data(Qt.ItemDataRole.EditRole)
        if not isinstance(values, list):
            return super().createEditor(parent, option, index)

        editor = QWidget(parent)
        layout = QHBoxLayout(editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        
        for val in values:
            line_edit = QLineEdit()
            line_edit.setText(str(val))
            line_edit.setFrame(False)
            line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            line_edit.setStyleSheet("background: white; border-right: 1px solid #E2E8F0;")
            layout.addWidget(line_edit)
            
        editor.setLayout(layout)
        return editor

    def setEditorData(self, editor, index):
        values = index.data(Qt.ItemDataRole.EditRole)
        line_edits = editor.findChildren(QLineEdit)
        for i, le in enumerate(line_edits):
            if i < len(values):
                le.setText(str(values[i]))

    def setModelData(self, editor, model, index):
        line_edits = editor.findChildren(QLineEdit)
        new_values = []
        for le in line_edits:
            new_values.append(le.text())
        model.setData(index, new_values, Qt.ItemDataRole.EditRole)

    def sizeHint(self, option, index):
        return QSize(150, 40)

class TimeRangeDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setInputMask("99:99 - 99:99")
        return editor
