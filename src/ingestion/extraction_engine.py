import os
import json
import base64
import tempfile
import logging
from typing import Optional, Callable, List, Tuple
from concurrent.futures import ThreadPoolExecutor

try:
    import fitz
except ImportError:
    fitz = None

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from src.core.config import settings
from src.ingestion.models import (
    DocumentResult,
    TripletResult,
    MediaAssetResult,
    ParameterResult,
    ExtractionError,
)
from src.ingestion.pdf_parser import (
    extract_pdf_with_marker,
    split_markdown_into_chunk_documents,
)
from src.models.chunk_document import make_text_chunk
from src.ingestion.figure_extractor import (
    extract_figures_from_markdown,
    is_figure_item,
)
from src.ingestion.image_analyzer import analyze_metallurgy_image_with_context
from src.ingestion.graph_extractor import Neo4jGraphExtractor

logger = logging.getLogger("xiaoye.ingestion.extraction_engine")


class DocumentKnowledgeExtractionEngine:
    """文档知识抽取模块主入口 (Facade/White-box Interface)"""

    def __init__(self):
        pass

    @staticmethod
    def _join_chunks_for_extraction(text_chunks: list, target_size: int = 5000) -> list:
        """Join adjacent small chunks into ~target_size char groups for LLM extraction.
        
        ES indexing uses original small chunks (fine-grained search).
        LLM extraction benefits from larger context windows.
        """
        if not text_chunks:
            return []
        
        joined = []
        current_text = ""
        # Track provenance fields from the first chunk in each group
        current_doc_id = ""
        current_source_pdf_id = ""
        current_page = -1
        
        for chunk in text_chunks:
            content = getattr(chunk, "text_content", "")
            if not content.strip():
                continue
            
            if len(current_text) + len(content) > target_size and current_text:
                # Finalize current group, preserving provenance from first chunk
                joined.append(make_text_chunk(
                    text=current_text.strip(),
                    doc_id=current_doc_id,
                    source_pdf_id=current_source_pdf_id,
                    page_number=current_page,
                ))
                current_text = content
                current_doc_id = getattr(chunk, "doc_id", "")
                current_source_pdf_id = getattr(chunk, "source_pdf_id", "")
                current_page = getattr(chunk, "page_number", -1)
            else:
                if not current_text:
                    current_doc_id = getattr(chunk, "doc_id", "")
                    current_source_pdf_id = getattr(chunk, "source_pdf_id", "")
                    current_page = getattr(chunk, "page_number", -1)
                current_text = current_text + "\n\n" + content if current_text else content
        
        # Don't forget the last group
        if current_text.strip():
            joined.append(make_text_chunk(
                text=current_text.strip(),
                doc_id=current_doc_id,
                source_pdf_id=current_source_pdf_id,
                page_number=current_page,
            ))
        
        logger.info(
            f"Chunk joining: {len(text_chunks)} original → {len(joined)} extraction chunks "
            f"(target={target_size} chars)"
        )
        return joined

    def extract_knowledge(
        self,
        file_stream: bytes,
        file_type: str,
        on_progress: Optional[Callable[[str, str], None]] = None,
        analyze_with_vlm: bool = False,
        text_chunks: Optional[List] = None,
    ) -> DocumentResult:
        """
        根据白箱接口契约同步解析文档。
        """
        if not file_stream:
            raise ExtractionError("文件流不能为空。")

        # 1. 建立临时运行目录隔离环境 (使用 tempfile.TemporaryDirectory)
        with tempfile.TemporaryDirectory(prefix="xiaoye_extraction_") as temp_dir:
            temp_pdf_path = os.path.join(temp_dir, f"input_document.{file_type}")
            with open(temp_pdf_path, "wb") as f:
                f.write(file_stream)

            # 2. 物理格式解析 (支持 Marker-PDF 与 PyMuPDF 降级)
            md_text, image_paths, out_metadata = self._parse_format(
                temp_pdf_path, temp_dir, file_type, on_progress
            )

            if not md_text:
                raise ExtractionError("未能从文档中解析出任何文本内容。")

            # 3. 文本分块 — 如果调用方已预分块则跳过
            if text_chunks is None:
                if on_progress:
                    on_progress("chunking", "正在对解析文本进行分块与物理页码对齐...")
                text_chunks = split_markdown_into_chunk_documents(
                    md_text=md_text,
                    out_metadata=out_metadata,
                    doc_id="temp_doc",
                    source_pdf_id="temp.pdf",
                )
                logger.info(f"Text chunks split completed: {len(text_chunks)} chunks")
            else:
                logger.info(f"Using pre-split chunks from caller: {len(text_chunks)} chunks")

            # 4. 富媒体资产抽取与 Base64 编码 (含可选 VLM 深度分析)
            media_assets = self._extract_media_assets(
                md_text, image_paths, temp_dir, on_progress, analyze_with_vlm
            )

            # 5. 知识图谱三元组提取 (无状态纯算力运算，移除了 DB 交互)
            triplet_list = self._extract_triplets(text_chunks, on_progress)

            # 6. 冶金工艺与物理性能参数提取
            extracted_parameters = self._extract_metallurgical_parameters(
                text_chunks, on_progress
            )

            # 7. 构造并返回标准 DocumentResult 包
            return DocumentResult(
                markdown_text=md_text,
                triplet_list=triplet_list,
                media_assets=media_assets,
                extracted_parameters=extracted_parameters,
            )

    def _parse_format(
        self,
        filepath: str,
        temp_dir: str,
        file_type: str,
        on_progress: Optional[Callable[[str, str], None]] = None
    ) -> Tuple[str, List[str], dict]:
        """解析文档排版与格式 (PDF 格式支持 Marker，非 PDF 或 Marker 失败时降级)"""
        if file_type.lower() != "pdf":
            # 非 PDF 文档，直接执行纯文本提取降级
            if on_progress:
                on_progress("parsing", f"非 PDF 文档类型 '{file_type}'，使用文本抽取器...")
            return self._fallback_text_extract(filepath)

        if on_progress:
            on_progress("parsing", "正在启动排版解析引擎 (Marker-PDF)...")

        try:
            # 运行 Marker CLI
            md_text, image_paths, out_metadata = extract_pdf_with_marker(
                filepath=filepath,
                out_dir=os.path.join(temp_dir, "marker_output"),
            )
            if on_progress:
                on_progress(
                    "parsing",
                    f"排版解析成功：解析出 {len(md_text)} 字符，{len(image_paths)} 张图片。",
                )
            return md_text, image_paths, out_metadata
        except Exception as e:
            logger.warning(f"Marker-PDF extraction failed: {e}. Falling back to PyMuPDF.")
            if on_progress:
                on_progress("parsing", "排版解析引擎异常，正在启动降级文本提取 (PyMuPDF)...")
            return self._fallback_text_extract(filepath)

    def _fallback_text_extract(self, filepath: str) -> Tuple[str, List[str], dict]:
        """PyMuPDF 文本提取降级方案"""
        if not fitz:
            raise ExtractionError("PyMuPDF (fitz) is not installed.")
        try:
            doc = fitz.open(filepath)
            md_text = "\n\n".join(page.get_text() for page in doc)
            return md_text, [], {}
        except Exception as e2:
            logger.error(f"Fallback extraction failed completely: {e2}")
            raise ExtractionError(f"文档提取失败: {e2}")

    def _extract_media_assets(
        self,
        md_text: str,
        image_paths: List[str],
        temp_dir: str,
        on_progress: Optional[Callable[[str, str], None]] = None,
        analyze_with_vlm: bool = False
    ) -> List[MediaAssetResult]:
        """富媒体资产提取，转化为 Base64"""
        if not image_paths:
            return []

        if on_progress:
            on_progress("figures", f"正在关联并分析图片资产 (共 {len(image_paths)} 张)...")

        # 1. 扫描 markdown 中的图片引用、Caption 与上下文
        # 临时的 marker 目录包含 basename 子目录
        marker_out_dir = os.path.join(temp_dir, "marker_output")
        if os.path.exists(marker_out_dir):
            image_subdirs = [
                os.path.join(marker_out_dir, d)
                for d in os.listdir(marker_out_dir)
                if os.path.isdir(os.path.join(marker_out_dir, d))
            ]
            img_search_dir = image_subdirs[0] if image_subdirs else marker_out_dir
        else:
            img_search_dir = temp_dir

        figures = extract_figures_from_markdown(md_text=md_text, image_dir=img_search_dir)
        meaningful = [f for f in figures if is_figure_item(f)]

        result_assets = []
        referenced_paths = set()

        # 辅助方法：读取图片转 base64
        def get_base64(path: str) -> Optional[str]:
            if not os.path.exists(path):
                return None
            try:
                with open(path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
            except Exception as ex:
                logger.warning(f"Failed to read image at {path}: {ex}")
                return None

        # 2. 抽取有上下文的有意义图片（可选执行 VLM 分析，暂默认为 False 避免过多 Token 消耗）
        for fig in meaningful:
            img_b64 = get_base64(fig.image_path)
            if not img_b64:
                continue

            referenced_paths.add(fig.image_path)
            description = ""

            # 如果开启了 VLM 且有 API Key，进行分析
            if analyze_with_vlm and settings.VLM_MODEL and settings.QWEN_API_KEY:
                try:
                    result = analyze_metallurgy_image_with_context(
                        image_base64=img_b64,
                        caption=fig.caption if fig.caption else None,
                        context_above=fig.context_above if fig.context_above else None,
                        context_below=fig.context_below if fig.context_below else None,
                    )
                    description = (
                        f"分类: {result.category}/{result.sub_category}\n"
                        f"描述: {result.description}\n"
                        f"指标: {', '.join(result.key_metrics)}"
                    )
                except Exception as ex:
                    logger.warning(f"VLM analysis failed for {fig.image_filename}: {ex}")
                    description = fig.caption

            asset = MediaAssetResult(
                image_base64=img_b64,
                image_filename=fig.image_filename,
                caption=fig.caption,
                context_above=fig.context_above,
                context_below=fig.context_below,
                description=description,
            )
            result_assets.append(asset)

        # 3. 补充提取未在 Markdown 中引用的图片作为基础资产
        for path in image_paths:
            if path in referenced_paths:
                continue
            img_b64 = get_base64(path)
            if not img_b64:
                continue

            asset = MediaAssetResult(
                image_base64=img_b64,
                image_filename=os.path.basename(path),
                caption="",
                context_above="",
                context_below="",
                description="未在正文引用的图像资产",
            )
            result_assets.append(asset)

        return result_assets

    def _extract_triplets(
        self, text_chunks: list, on_progress: Optional[Callable[[str, str], None]] = None
    ) -> List[TripletResult]:
        """利用 Ontology 规则与 LLM 抽取知识三元组"""
        if on_progress:
            on_progress("graphing", "正在调用大模型提取冶金知识图谱三元组...")

        # 实例化 extractor (内部持有了 Qwen LLM), 使用合并模式减少 LLM 调用
        extractor = Neo4jGraphExtractor(use_merged_prompt=True)
        try:
            
            # 合并小块为 ~5000 字大块，减少 LLM 调用次数
            target_chunks = self._join_chunks_for_extraction(
                [c for c in text_chunks if len(getattr(c, "text_content", "").strip()) > 50],
                target_size=5000,
            )

            def process_chunk(chunk) -> List[TripletResult]:
                content = getattr(chunk, "text_content", "")
                try:
                    triplets = extractor.extract_triplets_from_text(content)
                    return [
                        TripletResult(
                            subject=t.subject,
                            subject_type=t.subject_type,
                            relation=t.relation,
                            object=t.object_,
                            object_type=t.object_type,
                            mechanism=t.mechanism,
                            context=t.context,
                        )
                        for t in triplets
                    ]
                except Exception as ex:
                    logger.warning(f"Triplet extraction failed for chunk: {ex}")
                    return []

            all_triplets = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                results = list(executor.map(process_chunk, target_chunks))
                for r_list in results:
                    all_triplets.extend(r_list)

            if on_progress:
                on_progress("graphing", f"图谱抽取完成：提取出 {len(all_triplets)} 个知识三元组。")
            return all_triplets
        except Exception as e:
            logger.warning(f"Triplets extraction failed (non-fatal): {e}")
            if on_progress:
                on_progress("graphing", f"图谱抽取失败(非致命): {e}")
            return []
        finally:
            extractor.close()

    def _extract_metallurgical_parameters(
        self, text_chunks: list, on_progress: Optional[Callable[[str, str], None]] = None
    ) -> List[ParameterResult]:
        """冶金工艺参数大模型抽取"""
        if on_progress:
            on_progress("graphing", "正在分析文献并识别冶金工艺参数与性能指标...")

        target_chunks = self._join_chunks_for_extraction(
            [c for c in text_chunks if len(getattr(c, "text_content", "").strip()) > 50],
            target_size=10000,  # Parameters can use even larger context
        )

        if not target_chunks:
            return []

        text_to_analyze = "\n\n".join(
            [f"--- Chunk {i+1} ---\n{c.text_content}" for i, c in enumerate(target_chunks)]
        )

        llm = ChatOpenAI(
            model=settings.CODE_MODEL,
            streaming=False,
            max_retries=2,
            api_key=settings.QWEN_API_KEY,
            base_url=settings.QWEN_BASE_URL,
        )

        system_prompt = (
            "You are an expert metallurgist and structured data extractor.\n"
            "Your task is to analyze the provided metallurgy text and extract key process and physical parameters.\n"
            "Look for parameters such as holding temperature, holding time, heating/cooling rates, chemical compositions (e.g. C, Mn, Si contents), grain sizes, tensile/yield strengths, elongation, hardness, etc.\n"
            "You MUST output the result ONLY as a JSON list of objects, with each object containing exactly two keys:\n"
            "- 'key': the parameter name in snake_case (e.g., 'holding_temperature')\n"
            "- 'value': the extracted parameter value including units (e.g., '950 °C', '120 min', '0.4 wt%')\n"
            "If no parameters are found, return [].\n"
            "Do not output markdown codeblocks around the JSON, and do not add any explanation."
        )

        try:
            response = llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"Text to parse:\n{text_to_analyze}"),
                ]
            )
            content = response.content.strip()

            # 兼容 JSON markdown 代码块包裹
            if content.startswith("```json"):
                content = content.split("```json")[1].split("```")[0].strip()
            elif content.startswith("```"):
                content = content.split("```")[1].split("```")[0].strip()

            parameters = json.loads(content)
            if not isinstance(parameters, list):
                logger.warning("Parameter extraction did not return a list")
                return []

            results = []
            for param in parameters:
                if not isinstance(param, dict):
                    continue
                key = param.get("key")
                value = param.get("value")
                if key and value:
                    results.append(ParameterResult(key=key, value=str(value)))
            return results
        except Exception as e:
            logger.error(f"Error extracting parameters: {e}")
            return []
