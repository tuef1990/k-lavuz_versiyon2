from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from models.schedule_entry import ScheduleEntry

@dataclass
class GanttBar:
    row_label: str
    product_type: str
    product_name: str
    start_time: datetime
    end_time: datetime
    is_setup: bool
    group_size: int
    tooltip_text: str
    job_tag: str = ""  # "Bu Hafta", "Gecikmiş / Sarkan", "Gelecek Hafta" veya ""

class GanttDataService:
    # Machine string translation roughly based on algorithm mapping
    ROW_ORDER = [
        "Assembly",
        "FTP",
        "B/N",
        "DKK - M1", "DKK - M2", "DKK - M3", "DKK - M4",
        "RVB",
        "ATP+STP - M1", "ATP+STP - M2", "ATP+STP - M3", "ATP+STP - M4"
    ]

    @staticmethod
    def _map_stage_to_row(stage: str, machine_id: str) -> str:
        stage = stage.upper()
        
        # Parallel machines
        if stage in ["DKK", "ATP_STP"]:
            # M1, M2...
            stage_name = "ATP+STP" if stage == "ATP_STP" else "DKK"
            return f"{stage_name} - {machine_id}"
            
        # Single flow machines
        if stage == "ASSEMBLY": return "Assembly"
        if stage == "B_N" or stage == "BN": return "B/N"
        
        return stage # FTP, RVB

    @staticmethod
    def prepare(schedule: List[ScheduleEntry]) -> Dict[str, List[GanttBar]]:
        """
        Düz schedule listesini, makine satırlarına göre gruplanmış GanttBar listelerine çevirir.
        Ardışık ve aynı ürüne ait (setup olmayan) üretim bloklarını birleştirir.
        """
        rows: Dict[str, List[GanttBar]] = {r: [] for r in GanttDataService.ROW_ORDER}

        # Step 1: Assign entries to rows and generate initial unmerged bars
        for entry in schedule:
            row_key = GanttDataService._map_stage_to_row(entry.step_name, entry.machine_name)
            
            if row_key not in rows:
                rows[row_key] = []
                
            group_size = entry.group_size
            p_type = entry.product_type if entry.product_type else "Bilinmiyor"
            p_name = entry.product_name if entry.product_name else (entry.product_type or "Bilinmiyor")

            # İş etiketini job_id'den çıkar
            raw_id = entry.job_id or ""
            if "||" in raw_id:
                j_tag = raw_id.split("||", 1)[-1]
            else:
                j_tag = ""

            # Eğer kurulum süresi varsa, önce bir kurulum (setup) bloğu oluştur
            if entry.setup_time > 0:
                setup_end = entry.start_time + timedelta(hours=entry.setup_time)
                tt = f"SETUP: {entry.setup_time:.2f} saat\nSonraki: {p_name}"
                bar = GanttBar(
                    row_label=row_key,
                    product_type=p_type,
                    product_name=p_name,
                    start_time=entry.start_time,
                    end_time=setup_end,
                    is_setup=True,
                    group_size=0,
                    tooltip_text=tt,
                    job_tag=j_tag
                )
                rows[row_key].append(bar)
                process_start = setup_end
            else:
                process_start = entry.start_time

            # Now emit the actual processing block
            if (entry.end_time - process_start).total_seconds() > 0:
                tt = "" # Will be formatted after merging
                bar = GanttBar(
                    row_label=row_key,
                    product_type=p_type,
                    product_name=p_name,
                    start_time=process_start,
                    end_time=entry.end_time,
                    is_setup=False,
                    group_size=group_size,
                    tooltip_text=tt,
                    job_tag=j_tag
                )
                rows[row_key].append(bar)
                
        # Step 1.5: Batch çakışma düzeltmesi — setup barın kapsamında başlayan process barlarını
        # setup bittikten sonraya kaydır; aynı end_time'a sahip process barları birleştir.
        for row_key in rows:
            bars = rows[row_key]
            if len(bars) <= 1:
                continue

            bars.sort(key=lambda b: b.start_time)

            setup_intervals = [(b.start_time, b.end_time) for b in bars if b.is_setup]

            fixed: List[GanttBar] = []
            for bar in bars:
                if bar.is_setup:
                    fixed.append(bar)
                    continue
                adjusted = bar.start_time
                for s_start, s_end in setup_intervals:
                    if bar.start_time < s_end and bar.end_time > s_end:
                        adjusted = max(adjusted, s_end)
                if adjusted >= bar.end_time:
                    continue  # setup periyoduna gömülmüş, atla
                bar.start_time = adjusted
                fixed.append(bar)

            # Aynı (start, end, product_type) olan process barlarını birleştir
            fixed.sort(key=lambda b: b.start_time)
            collapsed: List[GanttBar] = []
            for bar in fixed:
                if bar.is_setup:
                    collapsed.append(bar)
                    continue
                matched = next(
                    (b for b in collapsed
                     if not b.is_setup
                     and abs((b.start_time - bar.start_time).total_seconds()) < 5
                     and abs((b.end_time - bar.end_time).total_seconds()) < 5
                     and b.product_type == bar.product_type),
                    None
                )
                if matched:
                    if bar.product_name and bar.product_name not in matched.product_name:
                        matched.product_name = f"{matched.product_name}/{bar.product_name}"
                    # group_size her entry'de zaten toplam batch sayısını taşır → max al
                    matched.group_size = max(matched.group_size, bar.group_size)
                else:
                    collapsed.append(bar)
            rows[row_key] = collapsed

        # Step 2: Merge contiguous identical blocks and format tooltips
        merged_rows: Dict[str, List[GanttBar]] = {}

        for row_key, bars in rows.items():
            if not bars:
                merged_rows[row_key] = []
                continue

            # Sort bars by start time just to be safe
            bars.sort(key=lambda b: b.start_time)

            merged_bars = []
            current_bar = bars[0]

            for next_bar in bars[1:]:
                # Check if we can merge: same product, no setup, contiguous in time
                times_match = abs((next_bar.start_time - current_bar.end_time).total_seconds()) < 60 # Allow 1 min float tolerance
                types_match = current_bar.product_type == next_bar.product_type and current_bar.product_name == next_bar.product_name
                both_not_setup = not current_bar.is_setup and not next_bar.is_setup
                tags_match = current_bar.job_tag == next_bar.job_tag

                if times_match and types_match and both_not_setup and tags_match:
                    # Merge them
                    current_bar.end_time = next_bar.end_time
                    current_bar.group_size += next_bar.group_size
                else:
                    merged_bars.append(current_bar)
                    current_bar = next_bar

            merged_bars.append(current_bar)
            
            # Formatting tooltips
            for bar in merged_bars:
                start_str = bar.start_time.strftime("%d %b %H:%M")
                end_str = bar.end_time.strftime("%d %b %H:%M")
                
                tag_line = f"\nHafta Türü: {bar.job_tag}" if bar.job_tag else ""
                if bar.is_setup:
                    bar.tooltip_text = f"SETUP\nSonraki Ürün: {bar.product_type}\nSüre: {(bar.end_time - bar.start_time).total_seconds()/3600:.2f} saat\nZaman: {start_str} - {end_str}{tag_line}"
                else:
                    bar.tooltip_text = f"{bar.product_name}\nTip: {bar.product_type}\nToplam Adet: {bar.group_size}\nSüre: {(bar.end_time - bar.start_time).total_seconds()/3600:.2f} saat\nZaman: {start_str} - {end_str}{tag_line}"
                    
            # Step 3: Kalan çakışmaları temizle — bir bar'ın başlangıcı öncekinin
            # bitişinden önce geliyorsa o bar'ı kırp ya da sil.
            clean: List[GanttBar] = []
            for bar in merged_bars:
                if clean and bar.start_time < clean[-1].end_time:
                    # Çakışıyor: setup barı olmayanı kırp, gerekirse atla
                    new_start = clean[-1].end_time
                    if new_start >= bar.end_time:
                        continue  # tamamen gömülmüş, atla
                    bar.start_time = new_start
                clean.append(bar)

            merged_rows[row_key] = clean

        return merged_rows
