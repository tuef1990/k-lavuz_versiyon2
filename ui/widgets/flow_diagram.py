from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QBrush, QColor, QFont, QPen
from PyQt6.QtCore import Qt, QRectF, QPoint
from core.models import AppState

class FlowDiagram(QWidget):
    def __init__(self, data_manager, parent=None):
        super().__init__(parent)
        self.data_manager = data_manager
        self.setMinimumSize(900, 250)
        self.bg_color = QColor("#F8FAFC")
        
        # Kutular için statik tanımlamalar
        self.stages = [
            {"id": "assembly", "label": "Assembly", "desc": "İşçilik Grup"},
            {"id": "ftp", "label": "FTP", "desc": "İstasyon"},
            {"id": "bn", "label": "B/N", "desc": "İstasyon"},
            {"id": "dkk", "label": "DKK", "desc": "4 Paralel İstasyon"},
            {"id": "rvb", "label": "RVB", "desc": "İstasyon"},
            {"id": "atp_stp", "label": "ATP + STP", "desc": "İstasyon"}
        ]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Arka plan
        painter.fillRect(self.rect(), self.bg_color)
        
        width = self.width()
        height = self.height()
        
        # Dinamik hesaplamalar
        box_count = len(self.stages)
        margin_x = 40
        spacing = 40
        box_width = int((width - (2 * margin_x) - ((box_count - 1) * spacing)) / box_count)
        if box_width < 100: box_width = 100 
        
        box_height = 120
        y_pos = (height - box_height) // 2
        
        state: AppState = self.data_manager.state
        capacities = state.capacity_data
        shifts = state.shift_data
        
        current_x = margin_x
        
        for i, stage in enumerate(self.stages):
            # Kapasite bilgisini topla (tüm vardiyaların toplamı)
            stage_cap = capacities.get(stage["id"], [])
            total_cap = sum(stage_cap) if stage_cap else 0
            active_shifts = len([s for s in shifts if s]) # Sadece tanımlı (boş olmayan) vardiyalar
            
            # 1. Kutu Arka Planı
            rect = QRectF(current_x, y_pos, box_width, box_height)
            painter.setPen(QPen(QColor("#E2E8F0"), 1))
            painter.setBrush(QBrush(QColor("white")))
            painter.drawRoundedRect(rect, 8, 8)
            
            # 2. Kutu Üst Başlık
            header_rect = QRectF(current_x, y_pos, box_width, 40)
            painter.setBrush(QBrush(QColor("#1B2A4A")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(header_rect, 8, 8)
            # Alt köşeleri düzeltmek için (sadece üst yuvarlak olsun diye)
            painter.drawRect(QRectF(current_x, y_pos + 20, box_width, 20))
            
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            painter.drawText(header_rect, Qt.AlignmentFlag.AlignCenter, stage["label"])
            
            # 3. Kutu İçi Detaylar
            details_rect = QRectF(current_x, y_pos + 45, box_width, box_height - 45)
            painter.setPen(QColor("#4A5568"))
            
            # Tür
            painter.setFont(QFont("Arial", 9))
            painter.drawText(QRectF(current_x, y_pos + 50, box_width, 20), Qt.AlignmentFlag.AlignHCenter, stage["desc"])
            
            # Kapasite
            painter.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            painter.setPen(QColor("#2F855A")) # Yeşil ton
            painter.drawText(QRectF(current_x, y_pos + 70, box_width, 30), Qt.AlignmentFlag.AlignHCenter, f"{total_cap} / gün")
            
            # Vardiya Bilgisi
            painter.setFont(QFont("Arial", 8))
            painter.setPen(QColor("#A0AEC0"))
            
            
            # Özel Durumlar: DKK (İçinde 4 makine göster)
            if stage["id"] == "dkk":
                m_width = (box_width - 25) / 4
                for m in range(4):
                    m_rect = QRectF(current_x + 5 + (m * (m_width + 5)), y_pos + box_height + 5, m_width, 20)
                    painter.setBrush(QBrush(QColor("#EDF2F7")))
                    painter.setPen(QPen(QColor("#CBD5E0"), 1))
                    painter.drawRoundedRect(m_rect, 4, 4)
                    
                    painter.setPen(QColor("#2D3748"))
                    painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))
                    painter.drawText(m_rect, Qt.AlignmentFlag.AlignCenter, f"M{m+1}")
            
            # Özel Durum: ATP+STP (Bağlantı notu)
            if stage["id"] == "atp_stp":
                painter.setPen(QColor("#E53E3E"))
                painter.setFont(QFont("Arial", 8))
                painter.drawText(QRectF(current_x - 50, y_pos + box_height + 10, box_width + 100, 20), 
                                 Qt.AlignmentFlag.AlignHCenter, "*DKK (M1-M4) havuzunu paylaşır")

            # 4. Bağlantı Oku (Son eleman değilse)
            if i < box_count - 1:
                arrow_start_x = current_x + box_width
                arrow_end_x = current_x + box_width + spacing
                arrow_y = y_pos + (box_height // 2)
                
                painter.setPen(QPen(QColor("#A0AEC0"), 2))
                painter.drawLine(int(arrow_start_x), arrow_y, int(arrow_end_x), arrow_y)
                
                # Ok Ucu
                painter.setBrush(QBrush(QColor("#A0AEC0")))
                painter.setPen(Qt.PenStyle.NoPen)
                poly = [
                    QPoint(int(arrow_end_x), arrow_y),
                    QPoint(int(arrow_end_x) - 10, arrow_y - 5),
                    QPoint(int(arrow_end_x) - 10, arrow_y + 5)
                ]
                
                from PyQt6.QtGui import QPolygon
                polygon = QPolygon(poly)
                painter.drawPolygon(polygon)
            
            current_x += box_width + spacing
