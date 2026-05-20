# 冶金领域高质量知识图谱构建与 Graph-Enhanced HyDE 实施路线图

## 核心痛点：如何获取高质量的冶金领域图谱 (Neo4j)?

在垂直工业领域（如材料学、冶金），直接获取现成的、可直接下载的开源高质量图谱（如通用领域的 DBpedia 或 百度百科图谱）是几乎不可能的。通用的开源图谱对“调质处理”、“回火索氏体”、“1Cr18Ni9Ti”等冶金特有概念的颗粒度支持极差。

因此，**高质量的冶金知识图谱必须由我们自己从底向上（Bottom-up）构建**。具体实施手段可分为以下三种并行路线：

### 1. 基于大模型的信息抽取 (LLM-based Information Extraction)

这是目前最主流且契合我们现有管线的方式。

* **机制**：在我们现有的 `IngestionPipeline` (PDF 入库管线) 中增加一个“图谱抽取”节点。在切分 Chunk 后，不直接存入 ES，而是先将 Chunk 文本喂给大模型（如 Qwen），让大模型按严格的 JSON 格式抽取知识三元组（Triples）。
* **抽取目标**：`(实体A)-[关系]->(实体B)`。
  * 例如：`(304不锈钢)-[包含元素]->(Cr)`
  * 例如：`(调质处理)-[产生机理]->(碳化物析出)`
* **写入 Neo4j**：将抽取出的三元组清洗、对齐后，通过 Cypher 语句持久化到 Neo4j 数据库中。随着入库 PDF 数量的增多，图谱会自动交织成网。

### 2. 权威标准与手册的结构化导入 (Top-down Ontology Mapping)

利用大模型抽取会带有一定的“幻觉”和噪声，图谱的“骨架”必须由绝对真实的数据支撑。

* **数据源**：  等教科书中的附录表格。
* **实施**：编写 Python 脚本解析表格，将牌号、化学成分百分比、力学性能直接转化为固定关系的 Graph 节点。这部分作为图谱的**强逻辑基石**，大模型抽取的三元组只能附加在这层基石之上。

### 3. 利用规则引擎进行词典关联 (Rule-based Dictionary)

对于同义词（如“屈服强度”和“Yield Strength”）、缩写（如“马氏体”和“M”），可以通过本地词典强制映射为图谱中的 `[alias]` 关系。

---

## 实施架构：Graph-Enhanced HyDE (KG-HyDE) 工作流

一旦我们在 Neo4j 中建立起了初步的冶金图谱，接下来的检索流程（Retrieval Pipeline）将迎来革命性的重构：

### Step 1: 意图抽象 (Entity Extraction)

用户输入问题：“阐述时效处理对钛合金硬度的提升机理。”
大模型提取出搜索起点：`['时效处理', '钛合金', '硬度']`。

### Step 2: 图数据库游走 (Graph Traversal & Context Retrieval)

通过 `neo4j-driver` 执行 Cypher 语句，查找上述节点在 2 跳范围内的关联知识：

* `钛合金` -> `[包含相]-> α相, β相`
* `时效处理` -> `[微观作用]-> 析出强化, 细小弥散相析出`
* 返回图谱上下文：`"钛合金包含α相和β相；时效处理会引起细小弥散相的析出强化。"`

### Step 3: 图谱锚定生成 (KG-Anchored HyDE)

将原始问题与 Step 2 获取的精准图谱上下文拼接，作为 Prompt 喂给大模型：

* **Prompt**: "请利用以下图谱背景知识，详细撰写一段解答用户问题的学术段落。背景知识：钛合金包含α和β相，时效产生弥散相析出..."
* **输出**：大模型生成一篇完美融合了“α相、β相、弥散析出”等高阶冶金黑话的**假想答案文档 (HyDE)**。

### Step 4: 终极召回 (ES Dense Vector Search)

将这篇极具专业深度的 HyDE 文档进行 `text-embedding-v3` 向量映射，拿到拥有极其锐利特征的矩阵 A，去 Elasticsearch `metallurgy_chunks` 索引中执行 Cosine 相似度检索。

---

## 下一步实施重点 (Next Steps Action Plan)

结合项目现状，下一步我们将把精力聚焦于以下实施阶段：

- [ ] **Phase 1: 图谱 Schema 设计**
  - 定义冶金领域的基础节点类型（`Material`, `Process`, `Property`, `Microstructure` 等）。
  - 定义核心关系类型（`HAS_COMPONENT`, `CAUSES`, `IMPROVES`, `DEGRADES` 等）。
- [ ] **Phase 2: Ingestion 管线升级**
  - 重构 `src/ingestion/pipeline.py`，在完成 Marker 解析后，新增 `GraphExtractor` 模块。
  - 使用 LangChain 的 `GraphCypherQAChain` 或手写提取提示词，自动构建 Neo4j 数据并查重。
- [ ] **Phase 3: Retrieval 引擎重构**
  - 在 `src/retrieval/semantic_search.py` 中引入 `HyDESearcher`。
  - 实现 `(LLM -> Neo4j -> LLM(HyDE) -> ES)` 的四步流水线调用链。
- [ ] **Phase 4: Agent 工具注册**
  - 在 `src/tooling/definitions.py` 中封装全新的 `search_metallurgy_kg_enhanced` 工具供大模型 Agent 直接调用。

---

## 落地关键挑战与避坑指南（核心痛点延伸）

在进入实际编码和管线搭建时，建议重点关注并提前防御以下问题：

### 1. 实体对齐（Entity Alignment）的灾难

* **痛点**：手册导入的官方牌号是 `06Cr19Ni10`，但 PDF 论文中专家可能会写 `304`、`18-8钢` 或 `304不锈钢`。如果直接写入 Neo4j，会导致图谱中出现大量孤立、同义但未融合的节点，图游走（Step 2）就会断裂。
* **解法**：在 Step 1 抽取时，利用你的“规则引擎与词典”，在 Prompt 中引入一个 Entity Linker 环节。强迫 LLM 在抽取实体时，必须参考你从手册里提炼的标准词典进行“归一化（Normalization）”。如果无法归一化，则打上 `alias` 标签。

### 2. 稠密节点的“图爆炸”与上下文噪音

* **痛点**：在冶金领域，某些节点（如 奥氏体、热处理、硬度）是绝对的“超级节点（Super Nodes）”，连接了成千上万个关系。如果你在 Step 2 盲目执行不加限制的 “2跳（2-hop）游走”，将会召回海量的无关上下文，不仅撑爆大模型的 Context Window，还会引入极大的噪音。
* **解法**：
  * **关系裁剪与权重化**：在 Cypher 查询时，限制特定高频关系的传播，或者对关系建立权重（例如根据 LLM 抽取时的频次）。
  * **定向游走**：利用 Step 1 提取的多个实体的交集进行游走。例如，不要单独从硬度出发游走，而是寻找时效处理与硬度之间的最短路径或共享邻居。

### 3. 异步管线中的“增量更新”难题

* **痛点**：IngestionPipeline 是异步不断流入 PDF 的。如果 LLM 抽取的某个三元组和已有手册冲突，或者重复抽取了类似的关系，Neo4j 的数据清洗压力会极大。
* **解法**：严格区分图谱的层级。手册导入的节点设置为 `PrimaryNode`（不可被 LLM 修改属性），LLM 抽取的设置为 `ExtractedNode`。写入时使用 `MERGE` 语句代替 `CREATE`，并通过 `ON MATCH SET` 累加关系的 `weight`（置信度），只有当某条抽取的线索被不同文献提及多次（`weight > 3`）时，才认为该动态关系在图谱中正式生效。

---

## 演进建议：图向量结合（Graph Embedding）

如果你们的团队有进一步迭代的预算，在方案成熟后，可以考虑将 Step 4 升级为 **Hybrid Retrieval（混合检索）**：

目前你的 Step 4 完全依赖 ES 的 Dense Vector（文本向量）。但在未来，你可以利用 Neo4j 的 Graph Data Science (GDS) 插件，将图谱结构转化为 **Graph Embedding**（如 Node2Vec 或 GraphSAGE）。

**终极形态**：用“文本向量相似度” + “图拓扑结构相似度”双路并发检索，在 ES 召回 Chunk 的同时，计算这些 Chunk 所在的图节点在物理拓扑上的距离，通过 RRF（Reciprocal Rank Fusion）算法进行重排（Reranking）。这将让你们的系统具备极强的物理逻辑推理能力。
