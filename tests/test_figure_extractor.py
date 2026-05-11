"""
图注提取模块的单元测试。

测试覆盖：
  1. is_caption_line() — 图注行检测
  2. extract_figures_from_markdown() — 从 Markdown 提取图片
  3. is_figure_item() — 有意义图表过滤
  4. build_vision_prompt() — Prompt 构建
"""

import os
import sys
import tempfile

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.pipeline.figure_extractor import (
    is_caption_line,
    extract_figures_from_markdown,
    is_figure_item,
    build_vision_prompt,
    FigureInfo,
)


class TestIsCaptionLine:
    """测试图注行检测"""

    def test_chinese_figure_caption(self):
        assert is_caption_line("图1: 淬火后马氏体组织")
        assert is_caption_line("图 2  退火温度曲线")
        assert is_caption_line("图3-1 相图分析")

    def test_english_figure_caption(self):
        assert is_caption_line("Fig.1: Microstructure of martensite")
        assert is_caption_line("Figure 2: Temperature profile")
        assert is_caption_line("FIG.3 Stress-strain curve")

    def test_chinese_table_caption(self):
        assert is_caption_line("表1: 合金成分表")
        assert is_caption_line("表 2  力学性能参数")

    def test_english_table_caption(self):
        assert is_caption_line("Table 1: Chemical composition")

    def test_non_caption_lines(self):
        assert not is_caption_line("这是一段普通文本")
        assert not is_caption_line("根据图1所示，我们可以观察到")
        assert not is_caption_line("")
        assert not is_caption_line("参考文献")
        assert not is_caption_line("数据来源: 实验测量")


class TestExtractFiguresFromMarkdown:
    """测试从 Markdown 提取图片"""

    def test_single_image_with_caption_below(self):
        """图片下方有图注"""
        md = """前面的一段文字描述。

![微观组织](images/fig1.png)

图1: 淬火后马氏体组织
这是对图1的详细解释。"""
        figures = extract_figures_from_markdown(md, image_dir="/tmp")
        assert len(figures) == 1
        assert figures[0].caption == "图1: 淬火后马氏体组织"
        assert figures[0].caption_type == "figure"
        assert figures[0].alt_text == "微观组织"

    def test_image_with_english_caption(self):
        """英文图注"""
        md = """The heat treatment process is shown below.

![SEM image](images/sem1.png)

Fig.1: SEM micrograph of fractured surface"""
        figures = extract_figures_from_markdown(md)
        assert len(figures) == 1
        assert "Fig.1" in figures[0].caption

    def test_image_with_caption_above(self):
        """图注在图片上方（某些排版）"""
        md = """一些分析结果。

图1-2: 不同温度下的相变曲线
![phase diagram](images/phase.png)

从图中可以看出..."""
        figures = extract_figures_from_markdown(md)
        assert len(figures) == 1
        assert figures[0].caption == "图1-2: 不同温度下的相变曲线"

    def test_multiple_images(self):
        """多张图片"""
        md = """第一张图：

![fig1](images/fig1.png)
图1: 第一张图

中间文字...

![fig2](images/fig2.png)
图2: 第二张图"""
        figures = extract_figures_from_markdown(md)
        assert len(figures) == 2
        assert figures[0].caption == "图1: 第一张图"
        assert figures[1].caption == "图2: 第二张图"

    def test_no_caption(self):
        """无图注的图片"""
        md = """这里插入了一张图片但没有图注。

![logo](images/logo.png)

继续正文。"""
        figures = extract_figures_from_markdown(md)
        assert len(figures) == 1
        assert figures[0].caption == ""  # 没有图注
        assert figures[0].caption_type == ""

    def test_context_extraction(self):
        """上下文提取"""
        md = """前一段文字。
第二行前文。

第三行前文。

![img](images/test.png)

图1: 测试图片
后一段文字。"""
        figures = extract_figures_from_markdown(md)
        assert len(figures) == 1
        fig = figures[0]
        assert "前一段文字" in fig.context_above
        # 图注行应出现在 context_below 中但 caption 已提取
        assert "后一段文字" in fig.context_below

    def test_image_with_table_caption(self):
        """表注"""
        md = """![table](images/table1.png)

表1: 合金力学性能对比"""
        figures = extract_figures_from_markdown(md)
        assert len(figures) == 1
        assert figures[0].caption_type == "table"
        assert "表1" in figures[0].caption


class TestIsFigureItem:
    """测试有意义图表过滤"""

    def test_with_caption_is_figure(self):
        fig = FigureInfo(
            image_path="/tmp/test.png",
            image_filename="test.png",
            caption="图1: 微观组织",
        )
        assert is_figure_item(fig)

    def test_without_caption_but_keyword_alt(self):
        fig = FigureInfo(
            image_path="/tmp/test.png",
            image_filename="test.png",
            alt_text="SEM microstructure photo",
        )
        assert is_figure_item(fig)

    def test_decorative_image(self):
        fig = FigureInfo(
            image_path="/tmp/logo.png",
            image_filename="logo.png",
            alt_text="",
        )
        assert not is_figure_item(fig)


class TestBuildVisionPrompt:
    """测试 Prompt 构建"""

    def test_with_all_context(self):
        fig = FigureInfo(
            image_path="/tmp/test.png",
            caption="图1: 淬火组织",
            context_above="试样在 850°C 保温 30 分钟后水淬。",
            context_below="可见板条状马氏体组织。",
        )
        prompt = build_vision_prompt(fig, base_prompt="你是一个冶金专家。")
        assert "图1: 淬火组织" in prompt
        assert "水淬" in prompt
        assert "板条状马氏体" in prompt
        assert "你是一个冶金专家。" in prompt

    def test_without_context(self):
        """基础 Prompt + 无上下文"""
        fig = FigureInfo(image_path="/tmp/test.png")
        prompt = build_vision_prompt(fig, base_prompt="分析这张图片。")
        assert prompt.strip() == "分析这张图片。"

    def test_caption_only(self):
        fig = FigureInfo(
            image_path="/tmp/test.png",
            caption="图1: 测试",
        )
        prompt = build_vision_prompt(fig)
        assert "图1: 测试" in prompt
