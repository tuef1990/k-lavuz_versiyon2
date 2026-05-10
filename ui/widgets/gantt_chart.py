from PyQt6.QtWidgets import QWidget, QToolTip
from PyQt6.QtGui import QPainter, QBrush, QColor, QFont, QPen, QImage
from PyQt6.QtCore import Qt, QRectF, QPoint, pyqtSignal
from datetime import datetime, timedelta
from typing import Dict, List
import random
from services.gantt_data_service import GanttBar

class GanttChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(400)
        self.setMinimumWidth(800)
        self.setMouseTracking(True)
        
        self.data: Dict[str, List[GanttBar]] = {}
        self.start_time: datetime = None
        self.end_time: datetime = None
        
        self.row_height = 40
        self.label_width = 100
        self.header_height = 30
        self.pixels_per_hour = 20.0
        self._min_pixels_per_hour = 12.0
        
        # Görsel olarak belirgin rastgele renkler üretmek için Altın Oran eşleniği kullanımı
        self._current_hue = random.random()
        self.colors = {}
        
        self._hovered_bar: GanttBar = None

    def set_data(self, gantt_data: Dict[str, List[GanttBar]]):
        self.data = gantt_data
        
        # Mutlak min/max zamanları bul
        all_bars = [bar for bars in self.data.values() for bar in bars]
        if all_bars:
            self.start_time = min(b.start_time for b in all_bars)
            self.end_time = max(b.end_time for b in all_bars)
            # Bir miktar kenar boşluğu ekle
            self.start_time -= timedelta(hours=1)
            self.end_time += timedelta(hours=2)
            
            self._update_scale()
            
            # Lejant için alt kısımda ekstra boşluk bırak (iki satır lejant)
            required_height = self.header_height + (len(self.data) * self.row_height) + 100
            self.setMinimumHeight(max(400, required_height))
            
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scale()

    def _update_scale(self):
        if not self.start_time or not self.end_time:
            return
            
        total_hours = (self.end_time - self.start_time).total_seconds() / 3600.0
        if total_hours <= 0:
            return
            
        available_width = self.width() - self.label_width - 80 # Kenar payı bırak
        
        # Tüm şemayı yatayda mevcut genişliğe sığdırmayı dene
        dynamic_px_per_hour = available_width / total_hours
        
        # Ancak tamamen okunamaz hale gelecek kadar küçülmesine izin verme
        self.pixels_per_hour = max(self._min_pixels_per_hour, dynamic_px_per_hour)
        
        # Pencere çok büyükse ve üretim planı kısaysa çubukların devasa olmasını engelle
        self.pixels_per_hour = min(150.0, self.pixels_per_hour)
        
        required_width = self.label_width + int(total_hours * self.pixels_per_hour) + 50
        self.setMinimumWidth(max(800, int(required_width)))

    # Hafta etiketi renkleri
    JOB_TAG_COLORS = {
        "Bu Hafta":      "#2563EB",   # mavi
        "Gelecek Hafta": "#7C3AED",   # mor
    }

    def _tag_color(self, job_tag: str) -> QColor | None:
        """job_tag string'i için şerit rengi döndürür; bilinmiyorsa None."""
        hex_c = self.JOB_TAG_COLORS.get(job_tag)
        return QColor(hex_c) if hex_c else None

    def get_color(self, product_type: str) -> QColor:
        # Her benzersiz ürün tipi için farklı bir rastgele renk üret
        if product_type not in self.colors:
            # Altın oran eşleniği, ton (hue) dağılımının dengeli olmasını sağlar
            self._current_hue += 0.618033988749895
            self._current_hue %= 1.0
            
            h = int(self._current_hue * 359)
            s = random.randint(70, 95) # Parlak renkler için yüksek doygunluk
            l = random.randint(45, 60) # Görünürlük için dengeli açıklık
            
            color = QColor.fromHsl(h, int(s * 2.55), int(l * 2.55))
            self.colors[product_type] = color.name()
            
        return QColor(self.colors[product_type])

    def paintEvent(self, event):
        if not self.data or not self.start_time:
            self._draw_placeholder()
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Arka Plan
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        
        # Eksenleri ve ızgarayı çiz
        self._draw_grid(painter)
        
        # Satırları ve çubukları çiz
        y_offset = self.header_height
        
        # Eğer tüm anahtarlar varsa standart sırayı kullan, yoksa genel döngü
        # İstenirse boş satırlar temizlenebilir, ancak bağlam için gösterilmesi iyidir
        for row_label, bars in self.data.items():
            # Satır etiketi arka planı
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F8FAFC"))
            painter.drawRect(0, y_offset, self.label_width, self.row_height)
            
            # Satır etiketi metni
            painter.setPen(QColor("#2D3748"))
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            painter.drawText(QRectF(5, y_offset, self.label_width - 10, self.row_height), 
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, row_label)
                             
            # Satır ayırıcı çizgi
            painter.setPen(QColor("#E2E8F0"))
            painter.drawLine(0, y_offset + self.row_height, self.width(), y_offset + self.row_height)
            
            # Çubukları çiz
            for bar in bars:
                x_start = self.label_width + ((bar.start_time - self.start_time).total_seconds() / 3600.0) * self.pixels_per_hour
                bar_width = ((bar.end_time - bar.start_time).total_seconds() / 3600.0) * self.pixels_per_hour
                
                # Görünmez derecede küçük çubukları önle
                if bar_width < 2: bar_width = 2
                
                rect = QRectF(x_start, y_offset + 5, bar_width, self.row_height - 10)
                
                base_color = self.get_color(bar.product_type)
                tag_col = self._tag_color(getattr(bar, "job_tag", ""))

                if bar.is_setup:
                    # Kurulum (Setup) bloğu: daha koyu ton, çapraz desen
                    brush = QBrush(base_color.darker(120), Qt.BrushStyle.BDiagPattern)
                    painter.setBrush(brush)
                    painter.setPen(QPen(base_color.darker(150), 1))
                    painter.drawRoundedRect(rect, 3, 3)
                else:
                    # Normal blok: düz renk
                    painter.setBrush(QBrush(base_color))
                    painter.setPen(QPen(base_color.darker(110), 1))
                    painter.drawRoundedRect(rect, 3, 3)

                    # Hafta etiketi şeridi: üst kenar boyunca 4px renkli çizgi
                    if tag_col and bar_width >= 4:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(tag_col))
                        stripe_rect = QRectF(rect.x(), rect.y(), rect.width(), 4)
                        painter.drawRoundedRect(stripe_rect, 2, 2)

                    # Çubuk içi metin
                    painter.setPen(Qt.GlobalColor.white)
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))

                    p_name_part = bar.product_name if bar.product_name and bar.product_name != bar.product_type else ""
                    full_text  = f"{bar.product_type}-{p_name_part}" if p_name_part else bar.product_type
                    short_text = bar.product_type

                    fm = painter.fontMetrics()
                    avail_w = bar_width - 10

                    if avail_w > 0:
                        if fm.horizontalAdvance(full_text) <= avail_w:
                            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, full_text)
                        elif fm.horizontalAdvance(short_text) <= avail_w:
                            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, short_text)

            y_offset += self.row_height

        # Lejantı çiz
        self._draw_legend(painter, self.height() - 40)

    def _draw_legend(self, painter: QPainter, start_y: int):
        # Verilerden benzersiz ürün tiplerini çıkar
        unique_products = set()
        for bars in self.data.values():
            for bar in bars:
                unique_products.add(bar.product_type)

        if not unique_products:
            return

        # --- Satır 1: Ürün renkleri ---
        x_offset = self.label_width + 20
        y_offset = start_y - 22  # İki satır için biraz yukarı kaydır

        painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        painter.setPen(QColor("#2D3748"))
        painter.drawText(x_offset, y_offset + 12, "Ürün Renkleri:")
        x_offset += 95

        for prod_type in sorted(list(unique_products)):
            color = self.get_color(prod_type)
            painter.setPen(QPen(color.darker(110), 1))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(x_offset, y_offset, 16, 16, 2, 2)
            painter.setPen(QColor("#4A5568"))
            painter.setFont(QFont("Arial", 9))
            text_width = painter.fontMetrics().horizontalAdvance(prod_type)
            painter.drawText(x_offset + 22, y_offset + 12, prod_type)
            x_offset += 35 + text_width

        # --- Satır 2: Hafta tipi şeritler ---
        x_offset = self.label_width + 20
        y_offset = start_y + 4

        painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        painter.setPen(QColor("#2D3748"))
        painter.drawText(x_offset, y_offset + 12, "Hafta Türü:")
        x_offset += 80

        week_items = [
            ("Bu Hafta",      self.JOB_TAG_COLORS["Bu Hafta"]),
            ("Gelecek Hafta", self.JOB_TAG_COLORS["Gelecek Hafta"]),
        ]
        for label, hex_c in week_items:
            color = QColor(hex_c)
            painter.setPen(QPen(color.darker(120), 1))
            painter.setBrush(QBrush(color))
            # Şerit göster: ince yatay dikdörtgen
            painter.drawRoundedRect(x_offset, y_offset + 5, 26, 6, 2, 2)
            painter.setPen(QColor("#4A5568"))
            painter.setFont(QFont("Arial", 9))
            text_width = painter.fontMetrics().horizontalAdvance(label)
            painter.drawText(x_offset + 32, y_offset + 12, label)
            x_offset += 48 + text_width

    def _draw_grid(self, painter: QPainter):
        total_hours = int((self.end_time - self.start_time).total_seconds() / 3600.0)
        
        painter.setFont(QFont("Arial", 8))
        
        for hour in range(total_hours + 1):
            x = self.label_width + (hour * self.pixels_per_hour)
            current_t = self.start_time + timedelta(hours=hour)
            
            # Izgara çizgisi çiz
            painter.setPen(QColor("#E2E8F0"))
            painter.drawLine(int(x), 0, int(x), self.height())
            
            # Çakışmaları önlemek için yakınlaştırma seviyesine göre etiket sıklığını hesapla
            tick_freq = 1
            if self.pixels_per_hour < 20: tick_freq = 6
            elif self.pixels_per_hour < 35: tick_freq = 4
            elif self.pixels_per_hour < 60: tick_freq = 2
            
            # İlk ve son etiketi ve frekansa uyan etiketleri daima çiz
            if hour % tick_freq == 0 or hour == total_hours:
                painter.setPen(QColor("#718096"))
                # Eğer gece yarısıysa tarih göster, değilse saat
                if current_t.hour == 0:
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))
                    lbl = current_t.strftime("%d %b")
                else:
                    painter.setFont(QFont("Arial", 8))
                    lbl = current_t.strftime("%H:%M")
                    
                painter.drawText(int(x) - 20, 10, 40, 20, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, lbl)


    def _draw_placeholder(self):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#F8FAFC"))
        painter.setPen(QColor("#A0AEC0"))
        painter.setFont(QFont("Arial", 14))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Gantt Şeması Görünümü\nHenüz Veri Yok")

    def mouseMoveEvent(self, event):
        if not self.data or not self.start_time:
            return
            
        pos = event.pos()
        x, y = pos.x(), pos.y()
        
        if x < self.label_width or y < self.header_height:
            QToolTip.hideText()
            return
            
        row_idx = (y - self.header_height) // self.row_height
        if row_idx < 0 or row_idx >= len(self.data):
            QToolTip.hideText()
            return
            
        row_label = list(self.data.keys())[row_idx]
        bars = self.data.get(row_label, [])
        
        # Üzerine gelinen çubuğu bul
        found = False
        for bar in bars:
            x_start = self.label_width + ((bar.start_time - self.start_time).total_seconds() / 3600.0) * self.pixels_per_hour
            bar_width = ((bar.end_time - bar.start_time).total_seconds() / 3600.0) * self.pixels_per_hour
            
            if bar_width < 2: bar_width = 2
                
            if x_start <= x <= x_start + bar_width:
                html = bar.tooltip_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
                styled = (
                    "<div style='color:#FFFFFF;background-color:#1E293B;"
                    "font-family:Segoe UI,Arial;font-size:12px;"
                    "padding:6px 10px;border-radius:6px;'>"
                    f"{html}</div>"
                )
                QToolTip.showText(event.globalPosition().toPoint(), styled, self)
                found = True
                break
                
        if not found:
            QToolTip.hideText()

    def save_as_image(self, filepath: str):
        if not self.data: return False
        
        # Ekran görünümünden bağımsız olarak şemanın tam kapsamını kapsayan bir görüntü oluşturun
        total_hours = (self.end_time - self.start_time).total_seconds() / 3600.0
        full_width = self.label_width + int(total_hours * self.pixels_per_hour) + 50
        # Lejant için alt kısımda ekstra boşluk bırak (iki satır lejant)
        full_height = self.header_height + (len(self.data) * self.row_height) + 100
        
        image = QImage(full_width, full_height, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        
        painter = QPainter(image)
        # Widget'ın boyama hedefini geçici olarak değiştiriyoruz veya aynı mantığa güveniyoruz
        # ancak paintEvent widget bağlamını aldığından, görüntünün üzerine boyamayı kopyalıyoruz:
        
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Izgara
        painter.setFont(QFont("Arial", 8))
        for hour in range(int(total_hours) + 1):
            x = self.label_width + (hour * self.pixels_per_hour)
            current_t = self.start_time + timedelta(hours=hour)
            painter.setPen(QColor("#E2E8F0"))
            painter.drawLine(int(x), 0, int(x), full_height)
            
            # Yakınlaştırma seviyesine göre etiket sıklığını hesapla
            tick_freq = 1
            if self.pixels_per_hour < 20: tick_freq = 6
            elif self.pixels_per_hour < 35: tick_freq = 4
            elif self.pixels_per_hour < 60: tick_freq = 2
            
            if hour % tick_freq == 0 or hour == int(total_hours):
                painter.setPen(QColor("#718096"))
                lbl = current_t.strftime("%d %b") if current_t.hour == 0 else current_t.strftime("%H:%M")
                painter.drawText(int(x) - 20, 10, 40, 20, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom, lbl)

        # Satırlar ve Çubuklar
        y_offset = self.header_height
        for row_label, bars in self.data.items():
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#F8FAFC"))
            painter.drawRect(0, y_offset, self.label_width, self.row_height)
            
            painter.setPen(QColor("#2D3748"))
            painter.setFont(QFont("Arial", 9, QFont.Weight.Bold))
            painter.drawText(QRectF(5, y_offset, self.label_width - 10, self.row_height), 
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, row_label)
                             
            painter.setPen(QColor("#E2E8F0"))
            painter.drawLine(0, y_offset + self.row_height, full_width, y_offset + self.row_height)
            
            for bar in bars:
                x_start = self.label_width + ((bar.start_time - self.start_time).total_seconds() / 3600.0) * self.pixels_per_hour
                bar_width = ((bar.end_time - bar.start_time).total_seconds() / 3600.0) * self.pixels_per_hour
                if bar_width < 2: bar_width = 2
                
                rect = QRectF(x_start, y_offset + 5, bar_width, self.row_height - 10)
                base_color = self.get_color(bar.product_type)
                
                tag_col = self._tag_color(getattr(bar, "job_tag", ""))

                if bar.is_setup:
                    brush = QBrush(base_color.darker(120), Qt.BrushStyle.BDiagPattern)
                    painter.setBrush(brush)
                    painter.setPen(QPen(base_color.darker(150), 1))
                    painter.drawRoundedRect(rect, 3, 3)
                else:
                    painter.setBrush(QBrush(base_color))
                    painter.setPen(QPen(base_color.darker(110), 1))
                    painter.drawRoundedRect(rect, 3, 3)

                    if tag_col and bar_width >= 4:
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(tag_col))
                        stripe_rect = QRectF(rect.x(), rect.y(), rect.width(), 4)
                        painter.drawRoundedRect(stripe_rect, 2, 2)

                    painter.setPen(Qt.GlobalColor.white)
                    painter.setFont(QFont("Arial", 8, QFont.Weight.Bold))

                    p_name_part = bar.product_name if bar.product_name and bar.product_name != bar.product_type else ""
                    full_text  = f"{bar.product_type}-{p_name_part}" if p_name_part else bar.product_type
                    short_text = bar.product_type

                    fm = painter.fontMetrics()
                    avail_w = bar_width - 10

                    if avail_w > 0:
                        if fm.horizontalAdvance(full_text) <= avail_w:
                            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, full_text)
                        elif fm.horizontalAdvance(short_text) <= avail_w:
                            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, short_text)

            y_offset += self.row_height

        # Resim üzerine lejantı boya
        self._draw_legend(painter, full_height - 40)
            
        painter.end()
        image.save(filepath)
        return True
