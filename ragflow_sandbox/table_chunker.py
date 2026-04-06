"""
表格按行 Chunk 处理器 — 剥离自 RAGFlow rag/app/table.py
提供动态列类型推断、行转 KV 文档的核心能力。

优化点 (对比 RAGFlow 原始):
  [OPT-5] 重复列名检测与预警 (RAGFlow table.py 有, 首版遗漏)
  [OPT-6] 自动剔除 id/_id/index/idx 等无意义列 (RAGFlow 有, 首版遗漏)
  [OPT-7] _looks_like_header 增加特殊字符判定 (RAGFlow 有, 首版遗漏)
"""
import re
import copy
import logging
import pandas as pd
from collections import Counter
from dateutil.parser import parse as datetime_parse
from xpinyin import Pinyin


def trans_datatime(s):
    try:
        return datetime_parse(s.strip()).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None

def trans_bool(s):
    if re.match(r"(true|yes|是|\*|✓|✔|☑|✅|√)$", str(s).strip(), flags=re.IGNORECASE):
        return "yes"
    if re.match(r"(false|no|否|⍻|×)$", str(s).strip(), flags=re.IGNORECASE):
        return "no"
    return None

def column_data_type(arr):
    """动态推断列的数据类型: int / float / text / datetime / bool"""
    arr = list(arr)
    counts = {"int": 0, "float": 0, "text": 0, "datetime": 0, "bool": 0}
    trans = {t: f for f, t in
             [(int, "int"), (float, "float"), (trans_datatime, "datetime"), (trans_bool, "bool"), (str, "text")]}
    float_flag = False
    for a in arr:
        if pd.isna(a) if not isinstance(a, str) else False:
            continue
        if a is None:
            continue
        s = str(a).replace("%%", "")
        if re.match(r"[+-]?[0-9]+$", s) and not s.startswith("0"):
            counts["int"] += 1
            try:
                if int(s) > 2 ** 63 - 1:
                    float_flag = True
                    break
            except ValueError:
                pass
        elif re.match(r"[+-]?[0-9.]{,19}$", s) and not s.startswith("0"):
            counts["float"] += 1
        elif re.match(r"(true|yes|是|\*|✓|✔|☑|✅|√|false|no|否|⍻|×)$", str(a), flags=re.IGNORECASE):
            counts["bool"] += 1
        elif trans_datatime(str(a)):
            counts["datetime"] += 1
        else:
            counts["text"] += 1

    if float_flag:
        ty = "float"
    else:
        counts_sorted = sorted(counts.items(), key=lambda x: x[1] * -1)
        ty = counts_sorted[0][0]

    for i in range(len(arr)):
        if pd.isna(arr[i]) if not isinstance(arr[i], str) else False:
            continue
        if arr[i] is None:
            continue
        try:
            arr[i] = trans[ty](str(arr[i]))
        except Exception:
            arr[i] = None
    return arr, ty


# ES 字段类型后缀映射
FIELDS_MAP = {
    "text": "_tks", "int": "_long", "keyword": "_kwd",
    "float": "_flt", "datetime": "_dt", "bool": "_kwd"
}


def chunk_dataframe(df, filename="data.csv"):
    """
    将 DataFrame 按行转为可检索的 Chunk 文档列表。

    返回:
        docs: list[dict]  每个 dict 包含:
            - docnm_kwd: 文件名
            - chunk_data: dict (JSONB 存储用)
            - content_with_weight: str (语义检索用 KV 文本)
            - 各 ES 扁平字段
        field_map: dict  列名->显示名映射
        col_types: list  每列推断出的类型
    """
    # [OPT-6] 自动剔除无意义的 ID 列
    for n in ["id", "_id", "index", "idx"]:
        if n in df.columns:
            del df[n]

    # [OPT-5] 重复列名检测
    clmns = df.columns.values
    col_counts = Counter(clmns)
    duplicates = [col for col, count in col_counts.items() if count > 1]
    if duplicates:
        logging.warning(f"Duplicate column names detected: {duplicates}. This may cause data loss.")

    PY = Pinyin()
    py_clmns = [PY.get_pinyins(re.sub(r"(/.*|（[^（）]+?）|\([^()]+?\))", "", str(n)), "_")[0] for n in clmns]
    clmn_tys = []

    for j in range(len(clmns)):
        cln, ty = column_data_type(df[clmns[j]])
        clmn_tys.append(ty)
        df[clmns[j]] = cln

    clmns_map = [(py_clmns[i].lower() + FIELDS_MAP[clmn_tys[i]], str(clmns[i]).replace("_", " "))
                 for i in range(len(clmns))]
    field_map = {k: v for k, v in clmns_map}

    res = []
    for ii, row in df.iterrows():
        d = {"docnm_kwd": filename, "chunk_data": {}}
        row_fields = []
        for j in range(len(clmns)):
            val = row[clmns[j]]
            if pd.isna(val) if not isinstance(val, str) else False:
                continue
            if val is None or not str(val):
                continue
            d["chunk_data"][str(clmns[j])] = val
            fld = clmns_map[j][0]
            d[fld] = val
            row_fields.append((clmns[j], val))
        if not row_fields:
            continue
        d["content_with_weight"] = "\n".join([f"- {field}: {value}" for field, value in row_fields])
        res.append(d)
    return res, field_map, clmn_tys


def parse_multi_level_headers(ws, rows):
    """对合并单元格的多级表头进行推断合并（返回扁平化的列名列表及表头行数）"""
    if len(rows) < 2:
        return _parse_simple_headers(rows)

    merged_ranges = list(ws.merged_cells.ranges)
    has_merge_in_header = any(rng.min_row <= 2 for rng in merged_ranges)
    if not has_merge_in_header:
        return _parse_simple_headers(rows)

    header_rows = _detect_header_rows(rows)
    if header_rows == 1:
        return _parse_simple_headers(rows)
    return _build_hierarchical_headers(ws, rows, header_rows), header_rows


def _parse_simple_headers(rows):
    if not rows:
        return [], 0
    headers = []
    for i, cell in enumerate(rows[0]):
        if cell.value is not None and str(cell.value).strip():
            headers.append(str(cell.value).strip())
        else:
            headers.append(f"Column_{i + 1}")
    return headers, 1


def _detect_header_rows(rows):
    header_rows = 1
    for i in range(1, min(5, len(rows))):
        row = rows[i]
        header_like = sum(1 for c in row if c.value and _looks_like_header(str(c.value).strip()))
        data_like = sum(1 for c in row if c.value and _looks_like_data(str(c.value).strip()))
        non_empty = sum(1 for c in row if c.value is not None)
        if non_empty > 0 and header_like >= data_like:
            header_rows = i + 1
        else:
            break
    return header_rows


def _looks_like_header(value):
    if len(value) < 1:
        return False
    if any(ord(c) > 127 for c in value):
        return True
    if len([c for c in value if c.isalpha()]) >= 2:
        return True
    # [OPT-7] RAGFlow 原始还判定了括号、冒号等特殊字符
    if any(c in value for c in ["(", ")", "：", ":", "（", "）", "_", "-"]):
        return True
    return False


def _looks_like_data(value):
    if len(value) == 1 and value.upper() in ["Y", "N", "M", "X", "/", "-"]:
        return True
    if value.replace(".", "").replace("-", "").replace(",", "").isdigit():
        return True
    return False


def _build_hierarchical_headers(ws, rows, header_rows):
    headers = []
    max_col = max(len(row) for row in rows[:header_rows])
    merged_ranges = list(ws.merged_cells.ranges)
    for col_idx in range(max_col):
        header_parts = []
        for row_idx in range(header_rows):
            if col_idx < len(rows[row_idx]):
                cell_value = rows[row_idx][col_idx].value
                # Check if this cell is part of a merged range
                for rng in merged_ranges:
                    if rng.min_row <= row_idx + 1 <= rng.max_row and rng.min_col <= col_idx + 1 <= rng.max_col:
                        cell_value = ws.cell(rng.min_row, rng.min_col).value
                        break
                if cell_value is not None:
                    cv = str(cell_value).strip()
                    if cv and cv not in header_parts and not _looks_like_data(cv):
                        header_parts.append(cv)
        headers.append("-".join(header_parts) if header_parts else f"Column_{col_idx + 1}")
    return [h for h in headers if h and h != "-"]
