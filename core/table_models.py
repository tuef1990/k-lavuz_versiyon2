from PyQt6.QtCore import Qt, QAbstractTableModel
from .models import STAGES

class ProductTableModel(QAbstractTableModel):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        # Sıralama: Ürün Tipi, Aylık Hedef, Üretilen
        # 'Üretilen' Çizelgeleme sayfasındakiyle senkron — data_manager.state.produced_amounts'tan okunur
        self.headers = ["Ürün Tipi", "Aylık Hedef", "Üretilen"]
        self.delete_mode = False
        self.data_manager.products_changed.connect(self.layoutChanged.emit)

    def set_delete_mode(self, enabled):
        self.delete_mode = enabled
        self.headerDataChanged.emit(Qt.Orientation.Vertical, 0, self.rowCount() - 1)

    def rowCount(self, parent=None):
        return len(self.data_manager.state.products)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None

        product = self.data_manager.state.products[index.row()]
        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if index.column() == 0: return product.type
            if index.column() == 1: return str(product.monthly_target)
            if index.column() == 2:
                produced = self.data_manager.state.produced_amounts.get(product.display_name, 0)
                return str(produced)

        if role == Qt.ItemDataRole.ForegroundRole and self.delete_mode:
            return Qt.GlobalColor.red

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole:
            import copy
            product = self.data_manager.state.products[index.row()]

            if index.column() == 0:
                # Tip değişikliği — display_name değişeceği için update_product akışı çalışır
                new_product = copy.copy(product)
                new_product.type = value
                self.data_manager.update_product(index.row(), new_product)
                self.data_manager.save_state()
                return True
            if index.column() == 1:
                # Aylık hedef
                new_product = copy.copy(product)
                try:
                    new_product.monthly_target = int(value)
                except (ValueError, TypeError):
                    return False
                self.data_manager.update_product(index.row(), new_product)
                self.data_manager.save_state()
                return True
            if index.column() == 2:
                # Üretilen — data_manager üzerinden Çizelgeleme sayfasıyla senkron
                self.data_manager.set_produced(product.display_name, value)
                return True
        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        
        if orientation == Qt.Orientation.Vertical and role == Qt.ItemDataRole.DisplayRole:
            if self.delete_mode:
                return "❌" # Or "🗑️"
            return str(section + 1)
            
        return None

    def flags(self, index):
        if self.delete_mode:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

class DependentTableModel(QAbstractTableModel):
    def __init__(self, data_manager, data_dict_name):
        super().__init__()
        self.data_manager = data_manager
        self.data_dict_name = data_dict_name
        self.data_manager.products_changed.connect(self.layoutChanged.emit)

    def rowCount(self, parent=None):
        return len(self.data_manager.active_products)

    def columnCount(self, parent=None):
        return len(STAGES) + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None

        product = self.data_manager.active_products[index.row()]
        if index.column() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return product.type
            return None

        stage = STAGES[index.column() - 1]
        data_dict = getattr(self.data_manager.state, self.data_dict_name)
        values = data_dict.get(product.display_name, {}).get(stage, [])

        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            if isinstance(values, list):
                return values
            return str(values) # For single values like production times
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.column() > 0:
            product = self.data_manager.active_products[index.row()]
            stage = STAGES[index.column() - 1]
            data_dict = getattr(self.data_manager.state, self.data_dict_name)

            # Sanal ürünler için girişi initialize et
            if product.display_name not in data_dict:
                data_dict[product.display_name] = {}

            try:
                if self.data_dict_name == "capacity_data": # List-based
                    clean_values = []
                    for v in value:
                        clean_values.append(int(float(str(v).replace(",", "."))) if str(v).strip() else 0)
                    data_dict[product.display_name][stage] = clean_values
                else: # Single value (Production Times)
                    clean_value = float(str(value).replace(",", "."))
                    data_dict[product.display_name][stage] = clean_value

                self.data_manager.save_state()
                self.dataChanged.emit(index, index)
                return True
            except (ValueError, TypeError):
                return False
        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == 0: return "Ürün"
            return STAGES[section - 1]
        return None

    def flags(self, index):
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

class SetupMatrixTableModel(QAbstractTableModel):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.data_manager.products_changed.connect(self.layoutChanged.emit)

    def rowCount(self, parent=None):
        return len(self.data_manager.active_products)

    def columnCount(self, parent=None):
        return len(self.data_manager.active_products) + 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None

        products = self.data_manager.active_products
        if index.column() == 0:
            if role == Qt.ItemDataRole.DisplayRole:
                return products[index.row()].type
            return None

        from_prod = products[index.row()].display_name
        to_prod = products[index.column() - 1].display_name

        if from_prod == to_prod:
            if role == Qt.ItemDataRole.DisplayRole: return "0"
            if role == Qt.ItemDataRole.BackgroundRole: return Qt.GlobalColor.lightGray
            return None

        value = self.data_manager.state.setup_matrix.get(from_prod, {}).get(to_prod, 0.0)
        if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
            return str(value)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole and index.column() > 0:
            products = self.data_manager.active_products
            row_prod = products[index.row()].display_name
            col_prod = products[index.column() - 1].display_name

            if row_prod == col_prod: return False

            try:
                if row_prod not in self.data_manager.state.setup_matrix:
                    self.data_manager.state.setup_matrix[row_prod] = {}

                clean_value = float(value.replace(",", "."))
                self.data_manager.state.setup_matrix[row_prod][col_prod] = clean_value

                self.data_manager.save_state()
                self.dataChanged.emit(index, index)
                return True
            except (ValueError, TypeError):
                return False
        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if section == 0: return "Ürün (Gelen)"
            return self.data_manager.active_products[section - 1].type
        return None

    def flags(self, index):
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable

class ShiftTableModel(QAbstractTableModel):
    def __init__(self, data_manager):
        super().__init__()
        self.data_manager = data_manager
        self.headers = ["İşlem Adımı", "Vardiya Sayısı", "Vardiya 1", "Vardiya 2", "Vardiya 3"]
        self.data_manager.products_changed.connect(self.layoutChanged.emit)

    def rowCount(self, parent=None):
        return len(STAGES)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        
        stage = STAGES[index.row()]
        if index.column() == 0:
            if role == Qt.ItemDataRole.DisplayRole: return stage
            return None
            
        if index.column() == 1:
            if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
                return str(len(self.data_manager.state.shift_data.get(stage, [])))
            return None
        
        shift_idx = index.column() - 2
        shifts = self.data_manager.state.shift_data.get(stage, [])
        
        if shift_idx < len(shifts):
            shift = shifts[shift_idx]
            if role == Qt.ItemDataRole.DisplayRole or role == Qt.ItemDataRole.EditRole:
                return f"{shift['start']} - {shift['end']}"
        else:
            if role == Qt.ItemDataRole.DisplayRole:
                return "-"
            if role == Qt.ItemDataRole.BackgroundRole:
                return Qt.GlobalColor.transparent # Or lightGray
            
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.EditRole:
            stage = STAGES[index.row()]
            
            if index.column() == 1: # Shift Count
                try:
                    count = int(value)
                    if 1 <= count <= 3:
                        self.data_manager.update_shift_count(stage, count)
                        self.dataChanged.emit(index, index)
                        return True
                except: pass
                return False

            if index.column() >= 2: # Shift Times
                shift_idx = index.column() - 2
                try:
                    parts = value.split("-")
                    if len(parts) == 2:
                        start = parts[0].strip()
                        end = parts[1].strip()
                        
                        shifts = self.data_manager.state.shift_data.get(stage, [])
                        if shift_idx < len(shifts):
                            shifts[shift_idx]["start"] = start
                            shifts[shift_idx]["end"] = end
                            self.data_manager.save_state()
                            self.dataChanged.emit(index, index)
                            return True
                except: pass
        return False

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None

    def flags(self, index):
        if index.column() == 0:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEditable
