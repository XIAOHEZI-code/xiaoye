"""
DOCX 解析器 — 剥离自 RAGFlow deepdoc/parser/docx_parser.py
去除了对 rag.nlp.rag_tokenizer 的依赖，使用简单的分词替代。

优化点 (对比 RAGFlow 原始):
  [OPT-8] 恢复 RAGFlow 原始遗漏的 NE/DT 正则模式
  [OPT-9] 新增 DOCX 内嵌图片提取 (RAGFlow 未显式实现但可扩展)
"""
import re
import pandas as pd
from collections import Counter
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from io import BytesIO
from PIL import Image


def _simple_tokenize(text):
    """简易中英文分词替代 RAGFlow 内部的 rag_tokenizer"""
    # 按标点和空格切分
    tokens = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z0-9]+', text)
    return tokens


class DocxParser:
    """DOCX 文档解析器：提取段落文本(附带样式)和表格内容"""

    def _extract_table_content(self, tb):
        df = []
        for row in tb.rows:
            df.append([c.text for c in row.cells])
        return self._compose_table_content(pd.DataFrame(df))

    def _compose_table_content(self, df):
        """将 DOCX 内的表格智能转为 KV 文本列表"""

        def block_type(b):
            pattern = [
                (r"^(20|19)[0-9]{2}[年/-][0-9]{1,2}[月/-][0-9]{1,2}日*$", "Dt"),
                (r"^(20|19)[0-9]{2}年$", "Dt"),
                (r"^(20|19)[0-9]{2}[年/-][0-9]{1,2}月*$", "Dt"),
                (r"^[0-9]{1,2}[月/-][0-9]{1,2}日*$", "Dt"),
                (r"^第*[一二三四1-4]季度$", "Dt"),
                (r"^(20|19)[0-9]{2}年*[一二三四1-4]季度$", "Dt"),
                (r"^(20|19)[0-9]{2}[ABCDE]$", "DT"),  # [OPT-8] 恢复 RAGFlow 遗漏模式
                (r"^[0-9.,+%/ -]+$", "Nu"),
                (r"^[0-9A-Z/\._~-]+$", "Ca"),
                (r"^[A-Z]*[a-z' -]+$", "En"),
                (r"^[0-9.,+-]+[0-9A-Za-z/$￥%<>（）()' -]+$", "NE"),  # [OPT-8]
                (r"^.{1}$", "Sg"),
            ]
            for p, n in pattern:
                if re.search(p, b):
                    return n
            tks = _simple_tokenize(b)
            if len(tks) > 3:
                return "Tx" if len(tks) < 12 else "Lx"
            return "Ot"

        if len(df) < 2:
            return []

        max_type = Counter([
            block_type(str(df.iloc[i, j]))
            for i in range(1, len(df))
            for j in range(len(df.iloc[i, :]))
        ])
        max_type = max(max_type.items(), key=lambda x: x[1])[0]

        colnm = len(df.iloc[0, :])
        hdrows = [0]
        if max_type == "Nu":
            for r in range(1, len(df)):
                tys = Counter([block_type(str(df.iloc[r, j])) for j in range(len(df.iloc[r, :]))])
                tys = max(tys.items(), key=lambda x: x[1])[0]
                if tys != max_type:
                    hdrows.append(r)

        lines = []
        for i in range(1, len(df)):
            if i in hdrows:
                continue
            hr = [r - i for r in hdrows if r - i < 0]
            if not hr:
                hr = [hdrows[0] - i]
            t = len(hr) - 1
            while t > 0:
                if hr[t] - hr[t - 1] > 1:
                    hr = hr[t:]
                    break
                t -= 1
            headers = []
            for j in range(len(df.iloc[i, :])):
                t_parts = []
                for h in hr:
                    x = str(df.iloc[i + h, j]).strip()
                    if x and x not in t_parts:
                        t_parts.append(x)
                t_str = ",".join(t_parts)
                if t_str:
                    t_str += ": "
                headers.append(t_str)

            cells = []
            for j in range(len(df.iloc[i, :])):
                val = str(df.iloc[i, j])
                if val:
                    cells.append(headers[j] + val)
            lines.append(";".join(cells))

        if colnm > 3:
            return lines
        return ["\n".join(lines)]

    def parse(self, fnm, from_page=0, to_page=100000000):
        """
        解析 DOCX 文件，返回:
            sections: list[(text, style_name)]  段落文本 + 样式名
            tables: list[list[str]]             表格 KV 文本
        """
        doc = Document(fnm) if isinstance(fnm, str) else Document(BytesIO(fnm))
        pn = 0
        secs = []

        for p in doc.paragraphs:
            if pn > to_page:
                break
            runs_text = []
            for run in p.runs:
                if pn > to_page:
                    break
                if from_page <= pn < to_page and p.text.strip():
                    runs_text.append(run.text)
                if 'lastRenderedPageBreak' in run._element.xml:
                    pn += 1
            style_name = p.style.name if hasattr(p.style, 'name') else ''
            secs.append(("".join(runs_text), style_name))

        tbls = [self._extract_table_content(tb) for tb in doc.tables]
        return secs, tbls

    def to_chunks(self, fnm):
        """
        高级接口：将 DOCX 解析为语义 Chunk 列表。
        - 标题段落成为 chunk 的 title
        - 正文段落拼接成 chunk 的 content
        - 表格独立成为 chunk
        """
        secs, tbls = self.parse(fnm)
        chunks = []
        current_title = ""
        current_body = []

        for text, style in secs:
            if not text.strip():
                continue
            if style and ("Heading" in style or "heading" in style or "标题" in style):
                # 刷出上一段
                if current_body:
                    chunks.append({
                        "type": "paragraph",
                        "title": current_title,
                        "content": "\n".join(current_body)
                    })
                    current_body = []
                current_title = text.strip()
            else:
                current_body.append(text.strip())

        # 刷出最后一段
        if current_body:
            chunks.append({
                "type": "paragraph",
                "title": current_title,
                "content": "\n".join(current_body)
            })

        # 表格作为独立 chunk
        for tbl_lines in tbls:
            if tbl_lines:
                chunks.append({
                    "type": "table",
                    "title": "",
                    "content": "\n".join(tbl_lines) if isinstance(tbl_lines, list) else tbl_lines,
                })
        return chunks

    def extract_images(self, fnm):
        """[OPT-9] 提取 DOCX 文档中的所有嵌入图片"""
        doc = Document(fnm) if isinstance(fnm, str) else Document(BytesIO(fnm))
        images = []
        for rel in doc.part.rels.values():
            if "image" in rel.reltype:
                try:
                    img_bytes = rel.target_part.blob
                    pil_img = Image.open(BytesIO(img_bytes)).convert("RGB")
                    images.append({
                        "image": pil_img,
                        "content_type": rel.target_part.content_type,
                        "width": pil_img.width,
                        "height": pil_img.height,
                    })
                except Exception:
                    continue
        return images
