from PyQt6.QtCore import Qt, QRect, QRectF, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath
from PyQt6.QtWidgets import (QWidget, QFrame, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QScrollArea, QApplication)


class HelpOverlay(QWidget):
    """Yarı şeffaf overlay — bir widget'ı spotlight ile vurgular, yanında callout gösterir.

    Kullanım:
        overlay = HelpOverlay(main_window.centralWidget())
        overlay.start([(widget1, "Başlık", "Açıklama"), ...])
    """

    PADDING = 8
    DARK_OPACITY = 170

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._steps = []
        self._idx = 0
        self._target_widget = None
        self._on_stop = None

        self._callout = QFrame(self)
        self._callout.setObjectName("HelpCallout")
        self._callout.setStyleSheet("""
            QFrame#HelpCallout {
                background-color: white;
                border: 2px solid #2563EB;
                border-radius: 10px;
            }
        """)
        # Sabit genişlik — word-wrap'in doğru çalışması için (variable width
        # adjustSize'da label heightForWidth'i yanlış hesaplayabiliyor)
        self._callout.setFixedWidth(380)

        cl = QVBoxLayout(self._callout)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(8)

        self._title = QLabel("")
        self._title.setStyleSheet(
            "font-size: 15px; font-weight: 700; color: #1E293B; "
            "background: transparent; border: none;"
        )
        self._title.setWordWrap(True)
        cl.addWidget(self._title)

        self._desc = QLabel("")
        self._desc.setStyleSheet(
            "font-size: 13px; color: #475569; "
            "background: transparent; border: none;"
        )
        self._desc.setWordWrap(True)
        cl.addWidget(self._desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._step_lbl = QLabel("")
        self._step_lbl.setStyleSheet(
            "font-size: 11px; color: #94A3B8; "
            "background: transparent; border: none;"
        )
        btn_row.addWidget(self._step_lbl)
        btn_row.addStretch()

        secondary_style = """
            QPushButton {
                background-color: #F1F5F9; color: #1E293B;
                border: none; border-radius: 6px;
                padding: 6px 12px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background-color: #E2E8F0; }
            QPushButton:disabled { color: #CBD5E1; }
        """
        primary_style = """
            QPushButton {
                background-color: #2563EB; color: white;
                border: none; border-radius: 6px;
                padding: 6px 12px; font-size: 12px; font-weight: 600;
            }
            QPushButton:hover { background-color: #1D4ED8; }
        """

        self._prev_btn = QPushButton("◀ Önceki")
        self._next_btn = QPushButton("Sonraki ▶")
        self._close_btn = QPushButton("✕ Kapat")
        self._prev_btn.setStyleSheet(secondary_style)
        self._close_btn.setStyleSheet(secondary_style)
        self._next_btn.setStyleSheet(primary_style)
        for b in (self._prev_btn, self._next_btn, self._close_btn):
            b.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_row.addWidget(self._prev_btn)
        btn_row.addWidget(self._next_btn)
        btn_row.addWidget(self._close_btn)
        cl.addLayout(btn_row)

        self._prev_btn.clicked.connect(self._prev)
        self._next_btn.clicked.connect(self._next)
        self._close_btn.clicked.connect(self.stop)

        self._callout.adjustSize()
        self.hide()

    def start(self, steps, on_stop=None):
        """steps: [(target, title, description) veya (target, title, description, setup), ...]
        target: QWidget | callable returning QWidget | None (None → ortalı, spotlight yok).
        setup: bu adıma geçmeden önce çalıştırılacak callable (sayfa değiştirme, ürün ekleme vb.).
        on_stop: overlay kapandığında çalışacak callable (temizlik için)."""
        self._steps = [s for s in steps if s and len(s) in (3, 4)]
        if not self._steps:
            return
        self._idx = 0
        self._on_stop = on_stop
        if self.parent():
            self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        self.setFocus()
        self._show_step()

    def stop(self):
        self.hide()
        on_stop = self._on_stop
        self._steps = []
        self._target_widget = None
        self._on_stop = None
        if on_stop:
            on_stop()

    def _show_step(self):
        step = self._steps[self._idx]
        if len(step) == 4:
            target, title, desc, setup = step
        else:
            target, title, desc = step
            setup = None

        # Setup'ı çalıştır (sayfa değiştirme, ürün ekleme gibi aksiyonlar)
        if setup is not None:
            setup()
            QApplication.processEvents()
            self.raise_()  # Olası page switch sonrası overlay'i tekrar üste çıkar

        # Target callable ise şimdi çağır (setup widget'ı yeni oluşturmuş olabilir)
        if callable(target) and not isinstance(target, QWidget):
            try:
                target = target()
            except Exception:
                target = None

        self._target_widget = target
        if isinstance(target, QWidget):
            self._ensure_visible(target)

        self._title.setText(title)
        self._desc.setText(desc)
        self._step_lbl.setText(f"{self._idx + 1} / {len(self._steps)}")
        self._prev_btn.setEnabled(self._idx > 0)
        self._next_btn.setText(
            "Bitir ✓" if self._idx == len(self._steps) - 1 else "Sonraki ▶"
        )

        # Word-wrap'lı label'ların yüksekliğini manuel hesapla — adjustSize tek
        # başına heightForWidth'i hesaba katmıyor
        margins = self._callout.layout().contentsMargins()
        available_w = self._callout.width() - margins.left() - margins.right()
        if available_w > 0:
            self._title.setMinimumHeight(self._title.heightForWidth(available_w))
            self._desc.setMinimumHeight(self._desc.heightForWidth(available_w))

        self._reposition_callout()
        self.update()

    def _ensure_visible(self, widget):
        """Widget'ı içeren en yakın QScrollArea'da görünür alana kaydırır."""
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget, 60, 60)
                # Layout güncellemesinin spotlight hesabından önce işlenmesini garanti et
                QApplication.processEvents()
                return
            parent = parent.parentWidget()

    def _next(self):
        if self._idx < len(self._steps) - 1:
            self._idx += 1
            self._show_step()
        else:
            self.stop()

    def _prev(self):
        if self._idx > 0:
            self._idx -= 1
            self._show_step()

    def _spotlight_rect(self) -> QRect | None:
        w = self._target_widget
        if w is None or not isinstance(w, QWidget) or not w.isVisible():
            return None
        # Hedef widget overlay'in atası olmayabilir (sibling). Global koordinattan çevir.
        global_tl = w.mapToGlobal(QPoint(0, 0))
        local_tl = self.mapFromGlobal(global_tl)
        rect = QRect(local_tl, w.size())
        return rect.adjusted(-self.PADDING, -self.PADDING, self.PADDING, self.PADDING)

    def _reposition_callout(self):
        # Yeniden boyutlandırmadan önce label heightForWidth'in güncel olması
        # için layout'u zorla aktive et — özellikle çok satırlı word-wrap için
        layout = self._callout.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        self._callout.adjustSize()
        cw = self._callout.width()
        ch = self._callout.height()
        margin = 14
        spot = self._spotlight_rect()
        if spot is None:
            x = (self.width() - cw) // 2
            y = (self.height() - ch) // 2
        else:
            if spot.bottom() + margin + ch < self.height():
                x = max(margin, min(self.width() - cw - margin, spot.center().x() - cw // 2))
                y = spot.bottom() + margin
            elif spot.top() - margin - ch > 0:
                x = max(margin, min(self.width() - cw - margin, spot.center().x() - cw // 2))
                y = spot.top() - margin - ch
            elif spot.right() + margin + cw < self.width():
                x = spot.right() + margin
                y = max(margin, min(self.height() - ch - margin, spot.center().y() - ch // 2))
            else:
                x = max(margin, spot.left() - margin - cw)
                y = max(margin, min(self.height() - ch - margin, spot.center().y() - ch // 2))
        self._callout.move(x, y)

    def resizeEvent(self, event):
        if self.parent():
            self.setGeometry(self.parent().rect())
        self._reposition_callout()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        spot = self._spotlight_rect()
        if spot is None:
            painter.fillRect(self.rect(), QColor(0, 0, 0, self.DARK_OPACITY))
            return
        # Spotlight için odd-even fill: tüm alanı doldur, spotlight'ı oydur
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        path.addRoundedRect(QRectF(spot), 6, 6)
        path.setFillRule(Qt.FillRule.OddEvenFill)
        painter.fillPath(path, QColor(0, 0, 0, self.DARK_OPACITY))
        # Vurgu çerçevesi
        pen = QPen(QColor("#2563EB"))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(spot, 6, 6)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.stop()
        elif event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Space, Qt.Key.Key_Return):
            self._next()
        elif event.key() == Qt.Key.Key_Left:
            self._prev()
        else:
            super().keyPressEvent(event)
