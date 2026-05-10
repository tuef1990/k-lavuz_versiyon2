import json
import os
from PyQt6.QtCore import QObject, pyqtSignal
from .models import Product, AppState, STAGES

class DataManager(QObject):
    # Senkronizasyon için sinyaller
    products_changed = pyqtSignal()
    product_added = pyqtSignal(Product)
    product_removed = pyqtSignal(str) # görünen_ad
    product_updated = pyqtSignal(str, Product) # eski_görünen_ad, yeni_ürün

    DATA_FILE = "data.json"

    DEFAULT_CAPACITIES = {"Assembly": 10, "FTP": 1, "B/N": 8, "DKK": 8, "RVB": 8, "ATP+STP": 8}
    # Tip bazlı kapasite default'ları — vardiya bazlı liste [V1, V2, V3].
    # Listede olmayan tipler DEFAULT_CAPACITIES'e düşer.
    DEFAULT_CAPACITIES_BY_TYPE = {
        "K11": {"Assembly": [10, 4, 2], "FTP": [1, 1, 1], "B/N": [8, 8, 8], "DKK": [8, 8, 8], "RVB": [8, 8, 8], "ATP+STP": [8, 8, 8]},
        "K12": {"Assembly": [10, 4, 2], "FTP": [1, 1, 1], "B/N": [8, 8, 8], "DKK": [8, 8, 8], "RVB": [8, 8, 8], "ATP+STP": [8, 8, 8]},
        "K20": {"Assembly": [10, 4, 2], "FTP": [1, 1, 1], "B/N": [8, 8, 8], "DKK": [8, 8, 8], "RVB": [8, 8, 8], "ATP+STP": [8, 8, 8]},
        "K31": {"Assembly": [10, 4, 2], "FTP": [1, 1, 1], "B/N": [8, 8, 8], "DKK": [6, 6, 6], "RVB": [6, 6, 6], "ATP+STP": [6, 6, 6]},
        "K40": {"Assembly": [10, 4, 2], "FTP": [1, 1, 1], "B/N": [8, 8, 8], "DKK": [6, 6, 6], "RVB": [6, 6, 6], "ATP+STP": [6, 6, 6]},
    }
    DEFAULT_TIMES = {"Assembly": 3.5, "FTP": 1.0, "B/N": 12.0, "DKK": 18.0, "RVB": 3.0, "ATP+STP": 21.0}
    # Tip bazlı setup süresi default'ları (saat) — DEFAULT_SETUP_MATRIX_BY_TYPE[from_type][to_type]
    DEFAULT_SETUP_MATRIX_BY_TYPE = {
        "K11": {"K11": 0, "K12": 0,   "K20": 3.5, "K31": 2.5, "K40": 3.5},
        "K12": {"K11": 0, "K12": 0,   "K20": 3.5, "K31": 2.5, "K40": 3.5},
        "K20": {"K11": 3.5, "K12": 3.5, "K20": 0,   "K31": 3.5, "K40": 2.5},
        "K31": {"K11": 2.5, "K12": 2.5, "K20": 3.5, "K31": 0,   "K40": 3.5},
        "K40": {"K11": 3.5, "K12": 3.5, "K20": 2.5, "K31": 3.5, "K40": 0},
    }
    DEFAULT_SHIFTS = {
        "Assembly": [
            {"name": "1. Vardiya", "start": "07:00", "end": "15:00"},
            {"name": "2. Vardiya", "start": "15:00", "end": "23:00"},
            {"name": "3. Vardiya", "start": "23:00", "end": "07:00"}
        ],
        "default_3": [
            {"name": "1. Vardiya", "start": "07:00", "end": "15:00"},
            {"name": "2. Vardiya", "start": "15:00", "end": "23:00"},
            {"name": "3. Vardiya", "start": "23:00", "end": "07:00"}
        ]
    }

    def __init__(self):
        super().__init__()
        self.state = AppState()
        self.excel_products = None
        self.excel_raw_rows = None
        self.excel_only_mode = False
        if not self.load_state():
            self._load_defaults()
            self.save_state()

    @property
    def active_products(self):
        """
        Diğer tablolarda (üretim süresi, kapasite, setup matrix) gösterilecek ürün listesi.
        - excel_only_mode kapalı: state.products + Excel'de olup tabloda olmayan sanal ürünler
        - excel_only_mode açık: sadece Excel'deki tiplerle eşleşen ürünler + Excel-only sanal ürünler
        state.products'a HİÇ dokunulmaz.
        """
        state_types = {p.type for p in self.state.products}

        if self.excel_only_mode and self.excel_products:
            excel_types = {ep.product_type for ep in self.excel_products}
            result = [p for p in self.state.products if p.type in excel_types]
        else:
            result = list(self.state.products)

        # Excel'de olup state.products'ta olmayan tipler → sanal Product ekle
        if self.excel_products:
            seen = set()
            for ep in self.excel_products:
                if ep.product_type not in state_types and ep.product_type not in seen:
                    seen.add(ep.product_type)
                    result.append(Product(type=ep.product_type, name=ep.product_name,
                                          monthly_target=ep.quantity))
        return result

    def _default_capacity_for_type(self, product_type: str) -> dict:
        """Tip için her stage'de vardiya bazlı kapasite listesi döner.
        Tip listede yoksa veya stage eksikse DEFAULT_CAPACITIES'e düşer.
        Vardiya sayısı 3'ten farklıysa otomatik kırpar/doldurur.
        """
        type_caps = self.DEFAULT_CAPACITIES_BY_TYPE.get(product_type, {})
        result = {}
        for stage in STAGES:
            shift_count = len(self.state.shift_data.get(stage, [])) or 1
            base_val = self.DEFAULT_CAPACITIES.get(stage, 0)
            if stage in type_caps:
                vals = list(type_caps[stage])
                if len(vals) < shift_count:
                    vals = vals + [base_val] * (shift_count - len(vals))
                elif len(vals) > shift_count:
                    vals = vals[:shift_count]
                result[stage] = vals
            else:
                result[stage] = [base_val] * shift_count
        return result

    def _default_setup_row_for_type(self, product_type: str) -> dict:
        """Tip için mevcut ürünlere doğru çıkış setup sürelerini döner (display_name → değer)."""
        type_row = self.DEFAULT_SETUP_MATRIX_BY_TYPE.get(product_type)
        if not type_row:
            return {}
        return {p.display_name: type_row[p.type]
                for p in self.state.products if p.type in type_row}

    def _apply_default_incoming_setup(self, new_product, same_type_name=None):
        """Mevcut ürünlerin satırlarına yeni ürüne doğru olan setup süresini doldurur.
        - same_type_name varsa: o sütundaki değeri kopyalar (kullanıcı düzenlemelerini korur)
        - yoksa: tip bazlı default'tan alır
        Mevcut bir değer varsa override etmez.
        """
        new_name = new_product.display_name
        for p in self.state.products:
            if p.display_name == new_name:
                continue
            row = self.state.setup_matrix.get(p.display_name)
            if row is None:
                continue
            if new_name in row:
                continue
            if same_type_name and same_type_name in row:
                row[new_name] = row[same_type_name]
                continue
            type_row = self.DEFAULT_SETUP_MATRIX_BY_TYPE.get(p.type, {})
            if new_product.type in type_row:
                row[new_name] = type_row[new_product.type]

    def _load_defaults(self):
        # Varsayılan ürünler
        default_products = [
            Product("K11", "Ürün A", 0),
            Product("K12", "Ürün B", 0),
            Product("K20", "Ürün C", 0),
            Product("K31", "Ürün D", 0),
            Product("K40", "Ürün E", 0)
        ]

        # Varsayılan vardiya verileri
        for stage in STAGES:
            if stage == "Assembly":
                self.state.shift_data[stage] = [s.copy() for s in self.DEFAULT_SHIFTS["Assembly"]]
            else:
                self.state.shift_data[stage] = [s.copy() for s in self.DEFAULT_SHIFTS["default_3"]]

        # Önce tüm ürünleri ekle ki helper'lar tam listeyi görsün
        for p in default_products:
            self.state.products.append(p)

        # Tip bazlı default'ları her ürüne uygula
        for p in default_products:
            name = p.display_name
            self.state.capacity_data[name] = self._default_capacity_for_type(p.type)
            self.state.production_time_data[name] = {
                stage: self.DEFAULT_TIMES.get(stage, 0.0) for stage in STAGES
            }
            self.state.setup_matrix[name] = self._default_setup_row_for_type(p.type)

    def add_product(self, product: Product):
        self.state.products.append(product)
        name = product.display_name

        # Aynı tipten başka bir ürün var mı? Varsa verilerini kopyala (Kural 1)
        same_type_name = None
        for p in self.state.products[:-1]:  # Yeni eklenenin öncesindeki ürünler
            if p.type == product.type:
                same_type_name = p.display_name
                break

        if name not in self.state.capacity_data:
            if same_type_name and same_type_name in self.state.capacity_data:
                import copy
                self.state.capacity_data[name] = copy.deepcopy(self.state.capacity_data[same_type_name])
            else:
                self.state.capacity_data[name] = self._default_capacity_for_type(product.type)

        if name not in self.state.production_time_data:
            if same_type_name and same_type_name in self.state.production_time_data:
                import copy
                self.state.production_time_data[name] = copy.deepcopy(self.state.production_time_data[same_type_name])
            else:
                self.state.production_time_data[name] = {stage: self.DEFAULT_TIMES.get(stage, 0.0) for stage in STAGES}

        if name not in self.state.setup_matrix:
            if same_type_name and same_type_name in self.state.setup_matrix:
                import copy
                self.state.setup_matrix[name] = copy.deepcopy(self.state.setup_matrix[same_type_name])
            else:
                self.state.setup_matrix[name] = self._default_setup_row_for_type(product.type)

        # Mevcut ürünlerin satırlarına yeni ürüne doğru setup süresini ekle
        self._apply_default_incoming_setup(product, same_type_name)

        self.save_state()
        self.products_changed.emit()
        self.product_added.emit(product)


    def remove_product(self, index: int):
        if 0 <= index < len(self.state.products):
            product = self.state.products.pop(index)
            name = product.display_name
            
            if name in self.state.capacity_data: del self.state.capacity_data[name]
            if name in self.state.production_time_data: del self.state.production_time_data[name]
            if name in self.state.setup_matrix: del self.state.setup_matrix[name]
            
            # Diğer matris satırlarındaki referansları da temizle
            for row in self.state.setup_matrix.values():
                if name in row: del row[name]
            
            self.save_state()
            self.products_changed.emit()
            self.product_removed.emit(name)

    def update_product(self, index: int, new_product: Product):
        if 0 <= index < len(self.state.products):
            old_product = self.state.products[index]
            old_name = old_product.display_name
            new_name = new_product.display_name
            
            self.state.products[index] = new_product
            
            if old_name != new_name:
                if old_name in self.state.capacity_data:
                    self.state.capacity_data[new_name] = self.state.capacity_data.pop(old_name)
                if old_name in self.state.production_time_data:
                    self.state.production_time_data[new_name] = self.state.production_time_data.pop(old_name)
                if old_name in self.state.setup_matrix:
                    self.state.setup_matrix[new_name] = self.state.setup_matrix.pop(old_name)

                # Diğer matris satırlarındaki referansları güncelle
                for row in self.state.setup_matrix.values():
                    if old_name in row:
                        row[new_name] = row.pop(old_name)

            # Tip değiştiyse default'ları yeniden uygula
            # ("KXX" placeholder'lı yeni ürünün wizard'da gerçek tipe geçişi için)
            if old_product.type != new_product.type:
                # Bu tipte başka ürün varsa onun değerlerini kopyala (kullanıcı edit'ini koru)
                same_type_other = None
                for p in self.state.products:
                    if p.display_name != new_name and p.type == new_product.type:
                        same_type_other = p.display_name
                        break

                if same_type_other:
                    if same_type_other in self.state.capacity_data:
                        import copy
                        self.state.capacity_data[new_name] = copy.deepcopy(
                            self.state.capacity_data[same_type_other])
                    if same_type_other in self.state.setup_matrix:
                        import copy
                        self.state.setup_matrix[new_name] = copy.deepcopy(
                            self.state.setup_matrix[same_type_other])
                else:
                    if new_product.type in self.DEFAULT_CAPACITIES_BY_TYPE:
                        self.state.capacity_data[new_name] = self._default_capacity_for_type(new_product.type)
                    if new_product.type in self.DEFAULT_SETUP_MATRIX_BY_TYPE:
                        self.state.setup_matrix[new_name] = self._default_setup_row_for_type(new_product.type)

                # Diğer ürünlerin satırlarındaki eski entry'leri sil ki yeni tipe göre yeniden eklensin
                for p in self.state.products:
                    if p.display_name == new_name:
                        continue
                    row = self.state.setup_matrix.get(p.display_name)
                    if row is not None and new_name in row:
                        del row[new_name]
                self._apply_default_incoming_setup(new_product, same_type_other)

            self.save_state()
            self.products_changed.emit()
            self.product_updated.emit(old_name, new_product)

    def save_state(self):
        data = {
            "products": [{"type": p.type, "name": p.name, "monthly_target": p.monthly_target} for p in self.state.products],
            "capacity_data": self.state.capacity_data,
            "production_time_data": self.state.production_time_data,
            "setup_matrix": self.state.setup_matrix,
            "shift_data": self.state.shift_data,
            "weekend_shifts": self.state.weekend_shifts,
            "carryover_data": self.state.carryover_data,
            "produced_amounts": self.state.produced_amounts,
        }
        with open(self.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

    def set_produced(self, display_name: str, amount: int):
        """'Üretilen' miktarını günceller; her iki tablo da bu sözlükten okur."""
        try:
            amount = max(0, int(amount))
        except (TypeError, ValueError):
            return
        self.state.produced_amounts[display_name] = amount
        self.save_state()
        self.products_changed.emit()

    def load_state(self):
        if not os.path.exists(self.DATA_FILE):
            return False
        try:
            with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.state.products = [Product(**p) for p in data.get("products", [])]
                self.state.capacity_data = data.get("capacity_data", {})
                self.state.production_time_data = data.get("production_time_data", {})
                self.state.setup_matrix = data.get("setup_matrix", {})
                self.state.shift_data = data.get("shift_data", {})
                self.state.weekend_shifts = data.get("weekend_shifts", {"saturday": [0], "sunday": []})
                self.state.carryover_data = data.get("carryover_data", {})
                self.state.produced_amounts = data.get("produced_amounts", {})

                # VERİ MİGRASYONU: Tekli değerleri gerekiyorsa listeye çevir
                self._migrate_to_multi_shift()
                self._repair_orphaned_data()
            return True
        except Exception as e:
            print(f"Veri yükleme hatası: {e}")
            return False

    def apply_schedule_result(self, result, week_number: int):
        """
        Çizelgeleme tamamlandıktan sonra çağrılır.
        Her ürün tipi için haftalık hedef, üretilen adet, gecikme (deficit)
        ve kümülatif aylık tüketim carryover_data sözlüğüne kaydedilir.
        """
        for rt in result.remaining_targets:
            pt = rt.product_type
            weekly_target = rt.period_target
            produced = rt.scheduled_count
            deficit = max(0, weekly_target - produced)

            # Kümülatif aylık tüketim: önceki + bu dönem üretilen
            prev = self.state.carryover_data.get(pt, {})
            prev_consumed = prev.get("monthly_consumed", 0)
            monthly_consumed = prev_consumed + produced

            self.state.carryover_data[pt] = {
                "week": week_number,
                "weekly_target": weekly_target,
                "produced": produced,
                "deficit": deficit,
                "monthly_consumed": monthly_consumed,
            }

        self.save_state()
        self.products_changed.emit()

    def clear_carryover(self):
        """Gecikme hafızasını sıfırlar (yeni ay başladığında çağrılabilir)."""
        self.state.carryover_data = {}
        self.save_state()

    def _repair_orphaned_data(self):
        """Tüm ürünlerin veri sözlüklerinde anahtarı olmasını sağlar ve yetim verileri temizler."""
        valid_names = {p.display_name for p in self.state.products}
        repair_happened = False
        
        # Eksik girişleri onar
        for name in valid_names:
            if name not in self.state.capacity_data:
                self.state.capacity_data[name] = {stage: [self.DEFAULT_CAPACITIES.get(stage, 0)] * len(self.state.shift_data.get(stage, [])) for stage in STAGES}
                repair_happened = True
            if name not in self.state.production_time_data:
                self.state.production_time_data[name] = {stage: self.DEFAULT_TIMES.get(stage, 0.0) for stage in STAGES}
                repair_happened = True
            if name not in self.state.setup_matrix:
                self.state.setup_matrix[name] = {}
                repair_happened = True
                
        # Yetim anahtarları temizle
        for name in list(self.state.capacity_data.keys()):
            if name not in valid_names:
                del self.state.capacity_data[name]
                repair_happened = True
        for name in list(self.state.production_time_data.keys()):
            if name not in valid_names:
                del self.state.production_time_data[name]
                repair_happened = True
        for name in list(self.state.setup_matrix.keys()):
            if name not in valid_names:
                del self.state.setup_matrix[name]
                repair_happened = True
                
        for row in self.state.setup_matrix.values():
            for name in list(row.keys()):
                if name not in valid_names:
                    del row[name]
                    repair_happened = True
                
        if repair_happened:
            self.save_state()

    def _migrate_to_multi_shift(self):
        """Eski int/float kapasite verilerini [değer, 0, 0] formatına çevirir,
        production_time_data'nın tekil değer olmasını sağlar."""
        migration_happened = False
        
        # 1. Kapasite Migrasyonu (Çoklu vardiya)
        for prod_name, stages in self.state.capacity_data.items():
            for stage, value in stages.items():
                if not isinstance(value, list):
                    shift_count = len(self.state.shift_data.get(stage, []))
                    stages[stage] = [value] + [0] * max(0, shift_count - 1)
                    migration_happened = True

        # 2. Üretim Süresi Migrasyonu (Tekil değer)
        for prod_name, stages in self.state.production_time_data.items():
            for stage, value in stages.items():
                if isinstance(value, list):
                    # Listedeki ilk değeri tekil değer olarak alıyoruz
                    stages[stage] = value[0] if len(value) > 0 else 0.0
                    migration_happened = True
        
        if migration_happened:
            self.save_state()

    def update_shift_count(self, stage: str, new_count: int):
        """Vardiya sayısı değiştiğinde ilgili sahne için tüm veri listelerini yeniden boyutlandırır."""
        # 1. shift_data güncelleme (zaman dilimleri)
        if stage not in self.state.shift_data:
            self.state.shift_data[stage] = []
            
        current_shifts = self.state.shift_data[stage]
        if len(current_shifts) < new_count:
            for i in range(len(current_shifts), new_count):
                last_end = current_shifts[-1]["end"] if current_shifts else "08:00"
                start_h = int(last_end.split(":")[0])
                end_h = (start_h + 8) % 24
                current_shifts.append({
                    "name": f"{i+1}. Vardiya",
                    "start": f"{start_h:02d}:00",
                    "end": f"{end_h:02d}:00"
                })
        elif len(current_shifts) > new_count:
            self.state.shift_data[stage] = current_shifts[:new_count]

        # 2. Tüm ürünler için kapasite listelerini yeniden boyutlandır
        for prod_name in self.state.capacity_data:
            data_dict = self.state.capacity_data
            if stage not in data_dict[prod_name]:
                data_dict[prod_name][stage] = [self.DEFAULT_CAPACITIES.get(stage, 0)] * new_count
                continue
            
            vals = data_dict[prod_name][stage]
            if len(vals) < new_count:
                data_dict[prod_name][stage] = vals + [self.DEFAULT_CAPACITIES.get(stage, 0)] * (new_count - len(vals))
            elif len(vals) > new_count:
                data_dict[prod_name][stage] = vals[:new_count]
        
        # 3. Üretim süresinin mevcut olduğundan emin ol (tekil değer)
        for prod_name in self.state.production_time_data:
            if stage not in self.state.production_time_data[prod_name]:
                self.state.production_time_data[prod_name][stage] = self.DEFAULT_TIMES.get(stage, 0.0)
        
        self.save_state()
        self.products_changed.emit() # Tabloları yenileme uyarısıyoria
