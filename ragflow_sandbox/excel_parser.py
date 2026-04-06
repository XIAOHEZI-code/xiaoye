"""
Excel / CSV 统一加载器 — 剥离自 RAGFlow deepdoc/parser/excel_parser.py

优化点 (对比 RAGFlow 原始):
  [OPT-1] CSV 编码自动探测: 引入 chardet 替代 rag.nlp.find_codec
  [OPT-2] 新增 markdown() 输出方法 (RAGFlow 原始有, 首版遗漏)
  [OPT-3] 新增 row_number() 快速行数统计 (RAGFlow 原始有, 首版遗漏)
  [OPT-4] CSV 读取增加编码回退链 (utf-8 -> chardet -> latin-1)
"""
import logging
import re
from io import BytesIO

import pandas as pd
from openpyxl import Workbook, load_workbook
from PIL import Image

ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010]|[\013-\014]|[\016-\037]")


def _detect_encoding(binary: bytes) -> str:
    """[OPT-1] 自动探测二进制流的编码，替代 RAGFlow 内部的 find_codec"""
    try:
        import chardet
        result = chardet.detect(binary[:10000])
        return result.get('encoding', 'utf-8') or 'utf-8'
    except ImportError:
        # chardet 未安装时的回退链
        for enc in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5', 'latin-1']:
            try:
                binary.decode(enc)
                return enc
            except (UnicodeDecodeError, LookupError):
                continue
        return 'utf-8'


class ExcelParser:
    """统一的 Excel / CSV 加载与解析器"""

    @staticmethod
    def _load_to_workbook(file_like_object):
        """自动判断文件类型（xlsx / xls / csv），统一转为 openpyxl Workbook"""
        if isinstance(file_like_object, bytes):
            file_like_object = BytesIO(file_like_object)

        file_like_object.seek(0)
        file_head = file_like_object.read(4)
        file_like_object.seek(0)

        # 非 Excel 二进制头 => 尝试 CSV
        if not (file_head.startswith(b"PK\x03\x04") or file_head.startswith(b"\xd0\xcf\x11\xe0")):
            logging.info("Not an Excel file, converting CSV to Excel Workbook")
            # [OPT-4] 多编码回退链读取 CSV
            file_like_object.seek(0)
            raw_bytes = file_like_object.read()
            encoding = _detect_encoding(raw_bytes)
            for enc in [encoding, 'utf-8', 'gbk', 'latin-1']:
                try:
                    text = raw_bytes.decode(enc)
                    df = pd.read_csv(BytesIO(text.encode('utf-8')), on_bad_lines='skip')
                    return ExcelParser._dataframe_to_workbook(df)
                except (UnicodeDecodeError, Exception):
                    continue
            raise Exception(f"Failed to parse CSV with any encoding (tried {encoding}, utf-8, gbk, latin-1)")

        # Excel 文件: openpyxl 优先，pandas 回退
        try:
            return load_workbook(file_like_object, data_only=True)
        except Exception as e:
            logging.info(f"openpyxl load error: {e}, trying pandas")
            try:
                file_like_object.seek(0)
                try:
                    dfs = pd.read_excel(file_like_object, sheet_name=None)
                    return ExcelParser._dataframe_to_workbook(dfs)
                except Exception:
                    file_like_object.seek(0)
                    df = pd.read_excel(file_like_object, engine="calamine")
                    return ExcelParser._dataframe_to_workbook(df)
            except Exception as e_pandas:
                raise Exception(f"pandas error: {e_pandas}, original: {e}")

    @staticmethod
    def _clean_dataframe(df: pd.DataFrame):
        def clean_string(s):
            if isinstance(s, str):
                return ILLEGAL_CHARACTERS_RE.sub(" ", s)
            return s
        return df.apply(lambda col: col.map(clean_string))

    @staticmethod
    def _fill_worksheet_from_dataframe(ws, df: pd.DataFrame):
        for col_num, column_name in enumerate(df.columns, 1):
            ws.cell(row=1, column=col_num, value=column_name)
        for row_num, row in enumerate(df.values, 2):
            for col_num, value in enumerate(row, 1):
                ws.cell(row=row_num, column=col_num, value=value)

    @staticmethod
    def _dataframe_to_workbook(df):
        if isinstance(df, dict) and len(df) > 1:
            return ExcelParser._dataframes_to_workbook(df)
        if isinstance(df, dict):
            df = list(df.values())[0]
        df = ExcelParser._clean_dataframe(df)
        wb = Workbook()
        ws = wb.active
        ws.title = "Data"
        ExcelParser._fill_worksheet_from_dataframe(ws, df)
        return wb

    @staticmethod
    def _dataframes_to_workbook(dfs: dict):
        wb = Workbook()
        default_sheet = wb.active
        wb.remove(default_sheet)
        for sheet_name, df in dfs.items():
            df = ExcelParser._clean_dataframe(df)
            ws = wb.create_sheet(title=sheet_name)
            ExcelParser._fill_worksheet_from_dataframe(ws, df)
        return wb

    @staticmethod
    def _get_actual_row_count(ws):
        max_row = ws.max_row
        if not max_row:
            return 0
        if max_row <= 10000:
            return max_row
        max_col = min(ws.max_column or 1, 50)

        def row_has_data(row_idx):
            for col_idx in range(1, max_col + 1):
                cell = ws.cell(row=row_idx, column=col_idx)
                if cell.value is not None and str(cell.value).strip():
                    return True
            return False

        if not any(row_has_data(i) for i in range(1, min(101, max_row + 1))):
            return 0
        left, right = 1, max_row
        last_data_row = 1
        while left <= right:
            mid = (left + right) // 2
            found = False
            for r in range(mid, min(mid + 10, max_row + 1)):
                if row_has_data(r):
                    found = True
                    last_data_row = max(last_data_row, r)
                    break
            if found:
                left = mid + 1
            else:
                right = mid - 1
        for r in range(last_data_row, min(last_data_row + 500, max_row + 1)):
            if row_has_data(r):
                last_data_row = r
        return last_data_row

    @staticmethod
    def _get_rows_limited(ws):
        actual_rows = ExcelParser._get_actual_row_count(ws)
        if actual_rows == 0:
            return []
        return list(ws.iter_rows(min_row=1, max_row=actual_rows))

    @staticmethod
    def extract_images(ws, sheetname=None):
        """提取 worksheet 中嵌入的图片及其锚定坐标"""
        images = getattr(ws, "_images", [])
        if not images:
            return []
        raw_items = []
        for img in images:
            try:
                img_bytes = img._data()
                pil_img = Image.open(BytesIO(img_bytes)).convert("RGB")
                anchor = img.anchor
                if hasattr(anchor, "_from") and hasattr(anchor, "_to"):
                    r1, c1 = anchor._from.row + 1, anchor._from.col + 1
                    r2, c2 = anchor._to.row + 1, anchor._to.col + 1
                    span = "single_cell" if (r1 == r2 and c1 == c2) else "multi_cell"
                else:
                    r1, c1 = anchor._from.row + 1, anchor._from.col + 1
                    r2, c2 = r1, c1
                    span = "single_cell"
                raw_items.append({
                    "sheet": sheetname or ws.title,
                    "image": pil_img,
                    "row_from": r1, "col_from": c1,
                    "row_to": r2, "col_to": c2,
                    "span_type": span,
                })
            except Exception:
                continue
        return raw_items

    def html(self, fnm, chunk_rows=256):
        """将 Excel/CSV 转换为按 chunk_rows 分块的 HTML 表格列表"""
        from html import escape
        file_like_object = BytesIO(fnm) if isinstance(fnm, bytes) else fnm
        wb = ExcelParser._load_to_workbook(file_like_object)
        tb_chunks = []
        def _fmt(v):
            return "" if v is None else str(v).strip()

        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            try:
                rows = ExcelParser._get_rows_limited(ws)
            except Exception:
                continue
            if not rows:
                continue
            tb_rows_0 = "<tr>" + "".join(f"<th>{escape(_fmt(t.value))}</th>" for t in rows[0]) + "</tr>"
            for chunk_i in range((len(rows) - 1) // chunk_rows + 1):
                tb = f"<table><caption>{sheetname}</caption>" + tb_rows_0
                for r in rows[1 + chunk_i * chunk_rows: min(1 + (chunk_i + 1) * chunk_rows, len(rows))]:
                    tb += "<tr>" + "".join(
                        f"<td>{escape(_fmt(c.value))}</td>" if c.value is not None else "<td></td>"
                        for c in r
                    ) + "</tr>"
                tb += "</table>\n"
                tb_chunks.append(tb)
        return tb_chunks

    def to_dataframes(self, fnm):
        """将 Excel/CSV 加载为 DataFrame 列表（每个 sheet 一个）"""
        file_like_object = BytesIO(fnm) if isinstance(fnm, bytes) else fnm
        wb = ExcelParser._load_to_workbook(file_like_object)
        results = []
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            try:
                rows = ExcelParser._get_rows_limited(ws)
            except Exception:
                continue
            if not rows:
                continue
            headers = [str(c.value) if c.value else f"Col_{i}" for i, c in enumerate(rows[0])]
            data = []
            for r in rows[1:]:
                data.append([c.value for c in r])
            if data:
                results.append((sheetname, pd.DataFrame(data, columns=headers)))
        return results

    def to_row_texts(self, fnm):
        """将 Excel/CSV 每行转为 '列头：值' 拼接的纯文本行列表"""
        file_like_object = BytesIO(fnm) if isinstance(fnm, bytes) else fnm
        wb = ExcelParser._load_to_workbook(file_like_object)
        res = []
        for sheetname in wb.sheetnames:
            ws = wb[sheetname]
            try:
                rows = ExcelParser._get_rows_limited(ws)
            except Exception:
                continue
            if not rows:
                continue
            ti = list(rows[0])
            for r in rows[1:]:
                fields = []
                for i, c in enumerate(r):
                    if not c.value:
                        continue
                    t = str(ti[i].value) if i < len(ti) and ti[i].value else ""
                    t += ("：" if t else "") + str(c.value)
                    fields.append(t)
                if fields:
                    line = "; ".join(fields)
                    if sheetname.lower().find("sheet") < 0:
                        line += " ——" + sheetname
                    res.append(line)
        return res

    def markdown(self, fnm):
        """[OPT-2] 将 Excel/CSV 转为 Markdown 表格字符串 (RAGFlow 原始功能, 首版遗漏)"""
        file_like_object = BytesIO(fnm) if isinstance(fnm, bytes) else fnm
        try:
            file_like_object.seek(0)
            df = pd.read_excel(file_like_object)
        except Exception:
            file_like_object.seek(0)
            raw = file_like_object.read()
            encoding = _detect_encoding(raw)
            text = raw.decode(encoding, errors='ignore')
            df = pd.read_csv(BytesIO(text.encode('utf-8')), on_bad_lines='skip')
        df = df.replace(r"^\s*$", "", regex=True)
        return df.to_markdown(index=False)

    @staticmethod
    def row_number(fnm, binary):
        """[OPT-3] 快速统计文件总行数 (RAGFlow 原始功能, 首版遗漏)"""
        ext = fnm.rsplit('.', 1)[-1].lower() if '.' in fnm else ''
        if ext in ('xls', 'xlsx'):
            wb = ExcelParser._load_to_workbook(BytesIO(binary))
            total = 0
            for sheetname in wb.sheetnames:
                try:
                    ws = wb[sheetname]
                    total += ExcelParser._get_actual_row_count(ws)
                except Exception:
                    continue
            return total
        if ext in ('csv', 'txt'):
            encoding = _detect_encoding(binary)
            txt = binary.decode(encoding, errors='ignore')
            return len(txt.split('\n'))
