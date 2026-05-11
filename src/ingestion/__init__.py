"""
P1: Ingestion Pipeline — 数据入库管线

职责：PDF 上传 → 解析 → 分块 → 向量化 → ES/Neo4j 写入
独立性：不依赖 Agent/Tools/Delivery 管线
触发点：upload API / CLI 脚本

模块清单：
  - pipeline.py:          统一入库管线编排器
  - status_tracker.py:    入库进度追踪 + SSE 推送
  - dedup.py:             PDF 去重检测
  - pdf_parser.py:        Marker-PDF 解析 (迁移自 src/pipeline/)
  - es_indexer.py:        ES 索引写入 (迁移自 src/pipeline/)
  - figure_extractor.py:  图注提取 (迁移自 src/pipeline/)
  - graph_extractor.py:   知识图谱三元组抽取 (迁移自 src/pipeline/)
  - image_analyzer.py:    VLM 入库分析 (迁移自 src/pipeline/)
"""
