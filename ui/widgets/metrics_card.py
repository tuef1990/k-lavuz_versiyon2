from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt

class MetricsCard(QFrame):
    def __init__(self, title: str, value: str, icon: str = None, color: str = "#4ECDC4", parent=None):
        super().__init__(parent)
        self.title = title
        self.value = value
        self.icon = icon
        self.color = color
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background-color: white;
                border-radius: 12px;
                border-left: 4px solid {self.color};
                border-top: 1px solid #E2E8F0;
                border-right: 1px solid #E2E8F0;
                border-bottom: 1px solid #E2E8F0;
            }}
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(5)
        
        # Title
        title_text = f"{self.icon} {self.title}" if self.icon else self.title
        self.lbl_title = QLabel(title_text)
        self.lbl_title.setStyleSheet("color: #718096; font-size: 14px; font-weight: 500; border: none;")
        layout.addWidget(self.lbl_title)
        
        # Value
        self.lbl_value = QLabel(self.value)
        self.lbl_value.setStyleSheet("color: #2D3748; font-size: 24px; font-weight: 800; border: none;")
        layout.addWidget(self.lbl_value)
        
        # Optional: Add drop shadow here if PyQt permits, but omitting box-shadow per previous bug
        
    def update_value(self, new_value: str):
        self.value = new_value
        self.lbl_value.setText(str(new_value))
