# 🦄 Autonomous Paper Reviewer

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.135-009688?logo=fastapi&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.6-37814A?logo=celery&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Queue-DC382D?logo=redis&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991)
![Streamlit](https://img.shields.io/badge/Streamlit-UI-FF4B4B?logo=streamlit&logoColor=white)
![Unstructured](https://img.shields.io/badge/Unstructured-hi__res-blue)

一个面向学术论文审阅场景的异步、多智能体、多模态 RAG 系统。项目不再停留在“上传 PDF + 做文本摘要”的传统范式，而是把论文解析、视觉证据绑定、检索增强、外部事实核查、结构化审稿输出，以及前端实时状态追踪，整合成一条完整的工程化流水线。

---

## 1. 执行摘要

`Autonomous Paper Reviewer` 的目标不是生成泛化的“论文点评”，而是尽可能模拟一名严谨 reviewer 的工作流：

- 先把论文拆解成**可检索的文本证据**与**可感知的图表证据**
- 再由 Planner Agent 规划“应该审什么”
- 然后由 Reviewer Agent 结合论文内部证据与外部 ArXiv 相关工作，完成**基于证据的审稿判断**
- 最终以严格 Pydantic Schema 输出稳定 JSON，供 API、Celery Worker 与 Streamlit UI 一致消费

这套系统的核心价值不在于“LLM 接了几个 API”，而在于它把几个工程上真正困难的问题串了起来并落地：

- 长耗时任务如何做到**前后端解耦**且可观测
- 多模态 PDF 解析后，图表如何与最近的语义 chunk 建立可追踪关系
- Agent 如何在内部 RAG 不足时，**自主决定**是否调用外部工具补足事实核查
- 多进程 Worker 场景下，SQLAlchemy Session 和模型注册如何保持稳定
- UI 如何把复杂的后端状态机变成可理解、可跟踪、可演示的产品体验

如果把它作为工程作品来评估，这个项目展示的是：**系统设计能力、异步任务编排、RAG 深化、多模态推理接线能力，以及把“研究原型”做成“能跑、能恢复、能演示”的工程收敛能力。**

---

## 2. 系统架构

### 2.1 总体设计

系统采用标准的**事件驱动解耦架构**：

```mermaid
flowchart LR
    UI[Streamlit UI] -->|POST /documents| API[FastAPI]
    UI -->|POST /reviews| API
    UI -->|GET /reviews/{task_id}| API

    API --> DB[(PostgreSQL + pgvector)]
    API -->|delay(task_id)| CELERY[Celery Worker]
    CELERY --> REDIS[(Redis Broker/Backend)]
    CELERY --> DB
    CELERY --> OPENAI[OpenAI Responses API]
    CELERY --> ARXIV[ArXiv API]
    CELERY --> MEDIA[media/documents/.../images]
```

其中每一层职责非常明确：

- **FastAPI**
  - 负责上传 PDF、创建 review task、返回轮询状态
  - 不承担长耗时解析、向量化、推理任务
- **Celery + Redis**
  - 负责消费异步 review task
  - Redis 同时承担 broker 与 result backend
- **PostgreSQL + pgvector**
  - 保存文档、任务、evidence、vector chunk
  - 以向量召回支撑 claim-to-evidence 检索
- **Streamlit**
  - 作为人类操作者视角的控制台
  - 通过长轮询将后端 FSM 转译为实时进度体验

### 2.2 API 到 Worker 的调用链

代码层面的主链路如下：

1. `POST /api/v1/documents`
   - `api/v1/documents.py`
   - 调用 `document_service.create_document(...)`
   - 将 PDF 保存到本地 `uploads/`
   - 在 `documents` 表中写入文档记录，状态为 `UPLOADED`

2. `POST /api/v1/reviews`
   - `api/v1/reviews.py`
   - 调用 `review_service.create_review_task(...)`
   - 创建 `review_tasks` 行，初始状态为 `PENDING`
   - 通过 `run_review_task.delay(str(review_task.id))` 投递到 Celery

3. Celery Worker 执行 `workers/review_tasks.py`
   - 解析 PDF
   - 切 chunk 并生成 embedding
   - 调用 Planner Agent 构造 review plan
   - 召回证据与视觉上下文
   - 调用 Reviewer Agent 生成最终结构化报告

4. `GET /api/v1/reviews/{task_id}`
   - Streamlit 每 2 秒轮询一次
   - 返回当前状态、重试计数、错误信息、最终 `result_json`

### 2.3 七阶段有限状态机（FSM）

项目中最关键的工程控制器是 `ReviewTaskStatus`，定义于 [`schemas/enums.py`](/home/chan/projects/Academic_Paper_Analyzer/schemas/enums.py)。

| 阶段 | 含义 | 关键动作 |
| --- | --- | --- |
| `PENDING` | 已创建、待执行 | API 已接单，等待 Worker 处理 |
| `PARSING_DOC` | 文档解析 | PDF 结构解析、页面文本与图表抽取 |
| `VECTORIZING` | 向量化 | chunk 切分、embedding 生成、`vector_chunks` 写库 |
| `AGENT_PLANNING` | 审稿规划 | Planner Agent 生成检索导向的审稿计划 |
| `EVIDENCE_RETRIEVAL` | 证据召回 | 结合 pgvector 与关键词重叠召回支撑证据 |
| `REPORT_GENERATING` | 报告生成 | Reviewer Agent 多模态推理，必要时调用 ArXiv 工具 |
| `COMPLETED` | 任务完成 | 持久化 `result_json` 与 evidence，写入完成时间 |

失败时会落入终态 `FAILED`。因此从“生命周期控制”的角度看，任务实际具备 **7 个主流程状态 + 1 个失败终态**。

### 2.4 容错、重试与幂等性

`workers/review_tasks.py` 里真正体现了工程质量的不是“会不会调用 LLM”，而是“失败以后能不能安全重来”。

#### 分阶段重试上限

Worker 为不同阶段设置了不同重试预算：

- `PARSING_DOC`: 2 次
- `VECTORIZING`: 3 次
- `AGENT_PLANNING`: 2 次
- `EVIDENCE_RETRIEVAL`: 2 次
- `REPORT_GENERATING`: 2 次

#### 指数退避

`_retry_countdown(...)` 对 `VECTORIZING` 阶段使用指数退避：

- 第 1 次重试：`2^1`
- 第 2 次重试：`2^2`
- 第 3 次重试：`2^3`

向量化阶段通常最耗时，也最容易受外部模型、网络或资源抖动影响，因此该阶段采用更保守的 backoff 策略是合理的。

#### 幂等性设计

重试不是简单“再跑一遍”，而是配套做了幂等清理。

在 `VECTORIZING` 阶段失败后，Worker 会调用：

- `cleanup_vector_chunks(db, document_id=...)`

其本质是删除该文档已有的旧 `vector_chunks`，防止以下问题：

- 同一篇文档重复写入 chunk，导致召回结果污染
- 上一次失败留下“半成品索引”，本次重试又叠加新数据
- evidence 指针与 chunk 版本不一致

这个设计非常关键。它说明系统不是“尽量跑成功”，而是明确考虑了**重试安全性**和**数据一致性**。

#### 失败处理

任何阶段抛异常后，Worker 都会执行：

- `db.rollback()`
- 回读最新 `review_task` / `document`
- 增加 `retry_count`
- 记录 `error_message`
- 判断当前阶段是否达到重试上限

其中还有一层细节：

- 如果失败发生在 `PARSING_DOC` 且已达到上限，会把 `document.status` 也标记为 `FAILED`
- 如果 review task 已达到阶段上限，则直接写入 `FAILED`
- 否则通过 `self.retry(...)` 再次入队

这一套机制让整个流水线具备了“**可恢复，而不是脆性失败**”的特征。

---

## 3. 关键技术亮点

### 3.1 多模态 Vision RAG：从“文本切块”升级到“视觉锚定检索”

#### 为什么需要改造传统 RAG

论文审阅最大的盲区之一，是很多关键信息并不只存在于正文里：

- 模型结构图
- 消融实验表
- 复杂对比结果图
- pipeline 示意图

如果系统只能读纯文本，那么它对论文质量的判断天然是不完整的。

#### Unstructured `hi_res` 解析策略

[`rag/parser.py`](/home/chan/projects/Academic_Paper_Analyzer/rag/parser.py) 使用 `unstructured.partition.pdf.partition_pdf(...)`，关键参数包括：

- `strategy="hi_res"`
- `infer_table_structure=True`
- `extract_image_block_types=["Image", "Table"]`
- `extract_image_block_output_dir=...`

这意味着系统不只是“提取文字”，而是把 PDF 里的视觉元素拆成显式的结构块：

- 文本块 `text_blocks`
- 视觉块 `visual_blocks`

同时，它为每个文档创建隔离的媒体目录：

```text
media/documents/{document_id}/images/
```

解析器会把图片或表格资产规范化保存为本地文件，并在元数据里写入：

- `figure_count`
- `table_count`
- `visual_asset_count`
- `media_dir`
- `parser: "unstructured_hi_res"`

#### Visual Anchoring：把图表绑定到最接近的语义 chunk

真正有技术含量的部分在 [`rag/chunker.py`](/home/chan/projects/Academic_Paper_Analyzer/rag/chunker.py)。

该模块并不是简单地“给图片随便找个最近段落”，而是实现了一个可解释的**视觉锚定算法** `_link_visuals_to_page_chunks(...)`：

1. 先对页面文本块做 token 化，并记录每个文本块在整页中的 token span
2. 对视觉块记录其 `anchor_text_order`
3. 将 anchor 文本块映射为一个 `anchor_position`
4. 计算该位置到每个 chunk token window 的距离
5. 选取**token distance 最短**的 chunk 作为首选绑定对象
6. 如有并列，再用 block order 的中点距离作 tie-break

这比“按页面最近段落”更精细，因为它绑定的是**token 级邻近关系**，而不是粗粒度页面关系。

#### Synthetic Chunk：为孤立视觉内容兜底

论文里会出现一种难处理情况：

- 图或表存在
- 但附近没有足够自由文本 chunk 可绑定
- 或者最佳 chunk 已被其他视觉资产占用

此时系统不会丢弃该视觉元素，而是创建一个**Synthetic Visual Chunk**。

也就是说，即使视觉内容在文本上是“孤岛”，它仍然会被强制注入到向量索引中，避免：

- 表格信息完全缺席召回
- 图像只被抽出却从未进入下游推理
- 视觉证据与最终审稿结论脱节

#### `linked_image_path` 让视觉证据穿透整个链路

`VectorChunk` 模型在 [`models/vector_chunk.py`](/home/chan/projects/Academic_Paper_Analyzer/models/vector_chunk.py) 中新增了：

- `linked_image_path: TEXT | NULL`

这个字段非常重要，因为它让视觉上下文不仅存在于解析阶段，也会继续流经：

- `vector_chunks` 持久化
- `rag/retriever.py` 证据召回
- `agents/reviewer.py` 多模态 prompt 组装

最终 Reviewer Agent 不只是“知道某段文本提到了 Figure 2”，而是能真正接收到该图表的 base64 图像输入。

---

### 3.2 Multi-Agent 协作：Planner 先规划，Reviewer 再推理

#### Planner Agent：把“审稿”先转成可检索问题

[`agents/orchestrator.py`](/home/chan/projects/Academic_Paper_Analyzer/agents/orchestrator.py) 不是泛泛写提纲，而是输出一个**检索导向的审稿计划** `ReviewPlanSchema`：

- `plan_summary`
- `focus_areas`
- `queries[]`
  - `aspect`
  - `claim`
  - `rationale`
  - `search_keywords`
  - `priority`

这样做的意义在于：把开放式审稿任务转译成一组**可以召回证据的 query spec**。  
下游 `rag/retriever.py` 会把这些 query spec 展平，并以 claim 为中心执行向量召回。

#### Evidence Retrieval：不是纯向量分数，而是轻量融合排序

在 [`rag/retriever.py`](/home/chan/projects/Academic_Paper_Analyzer/rag/retriever.py) 中，召回并非只看 pgvector 距离，还融合了关键词重叠：

```text
confidence = 0.8 * vector_similarity + 0.2 * keyword_overlap
```

这是一种非常实用的工程折中：

- 向量相似度保证语义覆盖
- 关键词重叠降低“语义像，但术语不对”的误召回

并且证据 payload 中包含：

- `chunk_id`
- `claim`
- `confidence_score`
- `evidence_type`
- `linked_image_path`

意味着后续 Agent 能同时拿到文本证据与视觉证据。

---

### 3.3 ReAct + Function Calling：让 Reviewer 自主决定是否核查 ArXiv

#### 为什么需要外部工具

论文审阅中的“创新性判断”和“是否缺少相关工作对比”通常不能只靠作者自己写的正文。  
因此 Reviewer Agent 被升级为一个**具备工具使用能力的 Agent**，而不是纯静态 RAG summarizer。

#### 本地工具：`search_arxiv`

[`tools/arxiv_search.py`](/home/chan/projects/Academic_Paper_Analyzer/tools/arxiv_search.py) 使用 Python 标准库完成轻量集成：

- `urllib` 请求 `http://export.arxiv.org/api/query`
- `xml.etree.ElementTree` 解析 Atom XML
- 提取：
  - `Title`
  - `Authors`
  - `Published`
  - `Summary`

之所以选择标准库实现，而不是引入更重的 SDK，优点很明确：

- 本地依赖更少
- 故障域更小
- 在单机场景下更稳定、可控

#### Reviewer 的两阶段推理

[`agents/reviewer.py`](/home/chan/projects/Academic_Paper_Analyzer/agents/reviewer.py) 实际上实现了一个简化版 ReAct 流程。

##### 第一阶段：Reasoning & Tool Execution

`_run_reasoning_and_tools(...)` 会先发起一次模型调用，告诉模型：

- 先判断当前论文是否需要外部 novelty / related-work 验证
- 如果需要，调用 `search_arxiv`
- 如果不需要，不要盲目用工具
- 这一轮不要直接输出最终报告

这一步使用 OpenAI Responses API 的工具定义，并显式声明严格 schema：

- `query`
- `max_results`

模型一旦返回 `function_call`，本地就会执行 `search_arxiv(...)`，然后把结果作为 `function_call_output` 回填给第二阶段。

##### 第二阶段：Final Structured Review

拿到工具结果后，再由 Reviewer 发起最终生成：

- 若调用了工具，则综合论文内部证据 + ArXiv 外部结果
- 若没有调用工具，则优雅回退到纯内部证据模式

最终输出被强约束为 [`schemas/review.py`](/home/chan/projects/Academic_Paper_Analyzer/schemas/review.py) 中的 `ReviewResultSchema`：

- `summary`
- `strengths`
- `weaknesses`
- `missing_evidence`
- `questions_for_authors`
- `external_references_checked`

这让系统具备两个很强的工程特性：

- **输出稳定**：上游 UI / API 不必防御“自由文本格式飘移”
- **可追踪**：外部事实核查结果会显式落库并展示在前端

#### 多模态 Prompt：Reviewer 真的“看见了”图表

Reviewer 的 prompt 不是简单字符串，而是通过 `_build_multimodal_user_content(...)` 组装成 Responses API 内容块：

- `input_text`
- `input_image`

当 evidence 带有有效 `linked_image_path` 时，系统会：

1. 读取本地图片
2. base64 编码
3. 构造 data URL
4. 连同文本 evidence 一起发送给 GPT-4o / GPT-4o-mini

这意味着：

- 图表不再只是“文本提及”
- Reviewer 可以把视觉材料纳入判断
- 报告阶段真正实现了 **Vision RAG**

---

### 3.4 并发、容错与工程性修复

#### SQLAlchemy 在多进程 Worker 中的稳定性处理

多进程 Celery Worker 场景下，ORM 最常见的问题包括：

- Session 跨进程污染
- commit 后对象过期导致访问异常
- fork 后 mapper registry 未完整注册

该项目做了几项非常务实的修复。

##### `expire_on_commit=False`

[`core/db.py`](/home/chan/projects/Academic_Paper_Analyzer/core/db.py) 中的 `SessionLocal` 明确设置：

```python
expire_on_commit=False
```

这减少了 commit 后 ORM 对象被动失效带来的额外刷新成本，也降低了异步/多阶段流水线中对象状态访问不稳定的问题。

##### 显式 Session 生命周期

系统没有把 DB Session 当成“全局单例”滥用，而是分成两条作用域：

- **FastAPI 请求内**
  - 通过 `get_db()` generator 创建并关闭 Session
- **Celery Worker 内**
  - 通过 `get_worker_session()` 显式创建独立 Session
  - 每个阶段按需 `commit / rollback / refresh`

这能有效避免：

- 请求线程与 worker 线程共享连接
- 失败阶段把脏状态带入下一阶段
- 长链路任务中的隐式事务边界失控

##### 显式模型注册

`workers/review_tasks.py` 在启动侧引入相关模型，确保 prefork worker 进程在真正查询前完成 mapper 注册，规避了典型的 SQLAlchemy “字符串关系名解析失败”问题。

#### 结果持久化不是“最后再说”

Worker 在成功路径里会把：

- `review_task.result_json`
- `evidences`
- `completed_at`

一起持久化，形成完整的任务结果快照。  
失败路径也会尽量保留：

- 当前阶段
- 错误信息
- 重试计数

这让 UI 可以清晰展示“正在做什么、失败在哪里、是否还会重试”。

---

### 3.5 Streamlit UI：把复杂后端状态机做成可演示产品

[`app.py`](/home/chan/projects/Academic_Paper_Analyzer/app.py) 并不是一个简单 demo 页面，它承担了“系统可解释性”的一部分。

#### 侧边栏驱动的操作流

所有输入都收敛到 sidebar：

- PDF 上传
- `focus_areas` 输入
- `Start Review` 提交

这让主视图专注于状态展示和结果阅读，交互上更接近真实产品，而不是脚本页。

#### 长轮询追踪 FSM

UI 每 2 秒轮询一次：

- `GET /api/v1/reviews/{task_id}`

并把返回的 `status`、`retry_count`、`error_message`、`result_json` 映射到：

- `st.status(...)`
- 进度条
- 阶段时间线
- 终态结果页

这意味着后端不是“黑盒跑完再给结果”，而是一个**可观察的状态机系统**。

#### 视觉设计不是默认 Streamlit 皮肤

项目在 `inject_styles()` 中注入了完整的自定义 CSS，包含：

- 设计变量：`--ink`、`--lavender`、`--blue`、`--mint`、`--peach`
- Glassmorphism 风格卡片
- 渐变 hero 区块
- 自定义按钮 hover、卡片阴影、圆角 tab

从代码层面看，这不是简单“美化一下”，而是在把技术系统包装成更成熟的工程展示件：

- Header 讲述产品定位
- 状态区解释当前阶段在做什么
- 结果区按 Tab 分成 Summary / Strengths / Weaknesses / Questions / ArXiv

对于招聘方而言，这能直观体现开发者并不只关注“模型跑起来”，而是同时具备：

- 工程实现能力
- 信息架构能力
- 面向演示和交付的产品意识

---

## 4. 为什么这个实现有工程含金量

相比常见的“AI 项目仓库”，这个项目的亮点不在于堆技术名词，而在于多个细节都体现了成熟工程思路：

- **不是同步阻塞式调用链**
  - 前端、API、Worker、数据库职责清晰分层
- **不是纯文本 RAG**
  - 图表经过解析、存储、锚定、召回、再进入 vision prompt
- **不是死板的单次 LLM 调用**
  - Agent 会先规划，再决定是否使用外部工具
- **不是脆性批处理**
  - FSM、分阶段重试、指数退避、错误信息持久化全部具备
- **不是“输出随缘”**
  - Pydantic 严格约束最终 JSON 结构
- **不是“只能跑一次的 demo”**
  - UI、日志、后台启动脚本、迁移脚本、媒体目录管理都已形成基本工程闭环

---

## 5. 快速开始

### 5.1 先决条件

建议本地环境满足以下条件：

- Python 3.12+
- Docker / Docker Compose
- Linux / WSL2 本地环境
- OpenAI API Key

多模态 PDF 解析依赖 `unstructured[pdf]`，建议安装以下系统包：

```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr libmagic1 libgl1
```

### 5.2 环境变量

在项目根目录创建 `.env`：

```env
OPENAI_API_KEY=your_real_key_here
OPENAI_PLANNING_MODEL=gpt-4o-mini
OPENAI_REVIEW_MODEL=gpt-4o-mini
OPENAI_PLANNING_TIMEOUT_SECONDS=60
OPENAI_REVIEW_TIMEOUT_SECONDS=90
```

当前代码中的配置事实需要如实说明：

- `start_servers.sh` 会自动 `source .env`
- `agents/orchestrator.py` 与 `agents/reviewer.py` 会读取 `OPENAI_*` 相关环境变量
- `core/db.py` 与 `core/celery_app.py` 当前默认使用本地单机连接：
  - PostgreSQL: `postgresql+psycopg://user:pass@localhost:5432/paper_db`
  - Redis: `redis://localhost:6379/0`

如果你希望切换数据库或 Redis 地址，当前版本建议同步修改：

- [`core/db.py`](/home/chan/projects/Academic_Paper_Analyzer/core/db.py)
- [`core/celery_app.py`](/home/chan/projects/Academic_Paper_Analyzer/core/celery_app.py)

### 5.3 安装依赖

```bash
cd /home/chan/projects/Academic_Paper_Analyzer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install streamlit requests
```

说明：

- `requirements.txt` 已包含 FastAPI、Celery、SQLAlchemy、pgvector、OpenAI、Unstructured
- 当前仓库中的 Streamlit UI 运行还需要 `streamlit` 与 `requests`

### 5.4 启动基础设施

```bash
docker compose up -d
```

确认以下服务可用：

- PostgreSQL + pgvector on `localhost:5432`
- Redis on `localhost:6379`

### 5.5 初始化数据库

首次启动建议确保 `vector` 扩展与表结构存在。

```bash
source .venv/bin/activate
python - <<'PY'
from sqlalchemy import text

from core.db import engine
from models.base import Base
from models.document import Document
from models.evidence import Evidence
from models.review_task import ReviewTask
from models.user import User
from models.vector_chunk import VectorChunk

with engine.begin() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
Base.metadata.create_all(bind=engine)
print("Database initialized.")
PY
```

如果你已经启用了多模态升级后的字段，还需要执行：

```bash
source .venv/bin/activate
python scripts/migrate_add_linked_image_path.py
```

### 5.6 启动后端与 Worker

有两种方式。

#### 方式 A：使用项目脚本

```bash
./start_servers.sh --bootstrap
./start_servers.sh --background
```

其中：

- `--bootstrap` 会安装多模态解析所需系统依赖、Python 依赖，并执行迁移脚本
- `--background` 会后台启动 FastAPI 与 Celery，并把日志写到 `logs/`

#### 方式 B：开发模式分终端启动

终端 1：

```bash
cd /home/chan/projects/Academic_Paper_Analyzer
source .venv/bin/activate
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

终端 2：

```bash
cd /home/chan/projects/Academic_Paper_Analyzer
source .venv/bin/activate
celery -A core.celery_app:celery_app worker -l info
```

### 5.7 启动 Streamlit UI

```bash
cd /home/chan/projects/Academic_Paper_Analyzer
source .venv/bin/activate
streamlit run app.py
```

默认访问：

- API: `http://127.0.0.1:8000/docs`
- UI: `http://127.0.0.1:8501`

### 5.8 核心 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/v1/documents` | 上传 PDF，返回 `document_id` |
| `POST` | `/api/v1/reviews` | 创建 review task，返回 `task_id` |
| `GET` | `/api/v1/reviews/{task_id}` | 查询任务状态与最终 `result_json` |
| `GET` | `/api/v1/reviews/{task_id}/evidences` | 查询审稿证据列表 |

---

## 6. 核心排错与边界处理

### 6.1 多模态图文锚定算法的边界修复

这次修复集中发生在 [`rag/chunker.py`](/home/chan/projects/Academic_Paper_Analyzer/rag/chunker.py) 的 `_distance_to_window(...)` 与 `_link_visuals_to_page_chunks(...)`。

#### 问题复盘

在早期版本中，视觉锚定算法存在两个容易被忽略、但影响非常实质的边界问题：

- **Token 距离存在 off-by-one 风险**
  - 旧逻辑将 token window 近似按闭区间处理，容易把边界 token 误判为“仍在窗口内”或“距离为 0”
- **缺失锚点时错误默认 `anchor_position = 0`**
  - 当视觉图表找不到合法的 `anchor_text_order`，系统会危险地退化为页首位置
  - 这会导致本应孤立处理的图表，被强行绑定到页面顶部 chunk，制造错误的图文耦合关系

这个问题之所以关键，是因为多模态 RAG 的可信度不只取决于“能否提取图表”，更取决于**图表被绑定到哪个语义上下文**。一旦锚定错位，下游检索、推理与审稿判断都会受到污染。

#### 解决方案

修复方案分为两层：

1. **严格修正 token window 语义**
   - 将窗口统一定义为半开区间 `[start, end)`
   - 当 `start <= position < end` 时距离为 `0`
   - 当 `position >= end` 时距离修正为 `position - end + 1`

2. **移除危险默认值，改为显式降级**
   - 当 `anchor_order` 无法解析到合法 span 时，不再强行参与距离计算
   - 系统直接把该视觉块视作 orphan visual
   - 立即触发降级策略，为其生成独立的 **Synthetic Visual Chunk（合成视觉锚点）**

#### 工程收益

这次修复带来的改进并不只是“少一个 bug”，而是显著提升了多模态链路的语义可靠性：

- 避免边界 token 误判导致的错误最近邻选择
- 避免孤立图表被错误吸附到页面头部
- 保证无上下文视觉资产以隔离形式进入索引，而不是污染正常文本 chunk
- 让 Vision RAG 在“信息缺失”场景下仍然保持可解释、可审计的行为

### 6.2 工具调用的优雅降级

这次修复发生在 [`tools/arxiv_search.py`](/home/chan/projects/Academic_Paper_Analyzer/tools/arxiv_search.py)，目标是让外部工具故障不再上升为系统级故障。

#### 问题复盘

Reviewer Agent 在执行 ArXiv 外部检索时，依赖 `urllib` 发起网络请求，并使用 `xml.etree.ElementTree` 解析返回内容。  
在这种模式下，如果外部服务出现以下异常：

- 网络超时（timeout）
- 连接失败
- 返回非预期 HTML / 无效 XML
- XML 解析错误

底层异常可能直接击穿工具调用边界，并进一步传播到 Celery Worker 的执行链路中。其结果不是“该次工具调用失败”，而是**整个异步任务进程可能异常中断**。

#### 解决方案

当前实现将网络请求与 XML 解析整体包裹在 `try/except Exception` 中，并遵循一个非常明确的策略：

- **不向上抛异常**
- **记录错误信息**
- **返回一段自然语言 fallback 文本**

返回信息的语义类似于：

> ArXiv search failed due to network or parsing error ... Please rely solely on the provided internal PDF context to complete your review.

换句话说，工具失败不再表现为“系统崩溃”，而是被转化为一条可被大模型理解的上下文信号。

#### 工程收益

这种设计体现的是典型的 **Graceful Degradation（优雅降级）** 思维：

- 第三方 API 波动不再击穿 Celery Worker
- LLM 可以根据 fallback 文本切换为“仅依赖内部 PDF 证据”的保守模式
- 工具从“硬依赖”变为“增强能力”
- 系统整体可用性不再被外部服务单点故障绑定

从架构角度看，这类处理非常值得强调，因为它说明该系统不是把 Agent 当成“会调工具的脚本”，而是把工具调用视作**带故障边界的工程组件**。

---

## 7. 结语

这个项目最值得展示的，不是“把 GPT 接进来了”，而是把一个本来容易停留在 notebook / demo 层面的方向，推进成了一个具备以下特征的完整系统：

- 异步任务编排
- 可恢复的有限状态机
- 多模态视觉检索
- Agent 工具调用
- 严格结构化输出
- 可观测、可演示的现代前端

对于招聘方或高级工程师评审而言，它展示的是一种非常清晰的工程能力画像：

- 能拆系统
- 能处理失败路径
- 能把模型能力落到可靠的服务链路
- 能从后端、数据层、Agent 层一路收敛到最终用户体验

如果你正在寻找一份能体现“系统设计 + AI 工程 + 交付感”的代码作品，这个仓库就是为此而构建的。
