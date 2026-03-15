# 科研文献分析与评价系统
## 技术设计与实施文档 v1

---

## 1. 文档目的

本文档用于将前期的项目构想正式收敛为一份可执行的 **MVP 阶段技术设计与实施规范**。文档面向两个目标：

1. 为后续与 Agent 协作开发提供统一的系统边界、目录规范、状态机规范与数据契约。
2. 将项目从“概念设计”推进到“可拆任务、可写代码、可联调验证”的工程实施阶段。

本版本聚焦 **MVP v1**，强调以下原则：
- 先做单体，不做微服务拆分
- 先做异步任务流，不阻塞主 API
- 先做 evidence-aware 的 review pipeline，不追求过度功能扩张
- 先把审稿辅助主链路做通，再考虑多论文、跨领域迁移等增强能力

---

## 2. 项目目标与 MVP 范围

### 2.1 项目名称
**面向科研阅读与审稿辅助的 Agent-RAG 工作流系统**

### 2.2 MVP v1 核心目标
MVP v1 只解决一条最核心的业务闭环：

> 用户上传论文 → 系统异步解析论文 → 建立 chunk 与向量索引 → Agent 基于检索证据生成结构化审稿报告 → 用户轮询任务状态并查看 evidence 溯源

### 2.3 MVP v1 核心能力
MVP v1 聚焦以下能力：

1. 文档接入与状态管理
2. PDF 解析、chunking、向量化
3. 基于 Agent + RAG 的结构化审稿
4. evidence 记录与可追踪返回
5. 异步任务执行与轮询式 API 交互

### 2.4 MVP v1 非目标
为了控制复杂度，本版本明确不做以下内容：

- 不做多租户复杂权限系统
- 不做前后端分离产品化 UI（可先用 Swagger / Postman 验证）
- 不做多论文联合比较主流程
- 不做自动 acceptance score / reject score
- 不做论文价值判断或投稿预测
- 不做复杂 reviewer persona 模型
- 不引入独立向量数据库（Milvus / Qdrant）
- 不做微服务拆分

---

## 3. 技术栈选型（MVP 阶段）

本项目在 MVP 阶段 **坚决采用纯 Python 单体架构**，核心目标是：
- 以最低协作成本快速打通完整闭环
- 最大化 Agent / LLM / RAG 集成效率
- 在不牺牲工程边界的前提下，优先完成端到端可运行版本

### 3.1 总体选型结论

- **Web 框架**：FastAPI
- **Agent 编排**：LangGraph（首选）或纯代码状态机
- **数据库**：PostgreSQL + pgvector
- **异步任务队列**：Redis + Celery（或 ARQ）
- **ORM**：SQLAlchemy 2.x
- **数据校验**：Pydantic v2
- **迁移工具**：Alembic
- **Embedding / LLM Provider**：可插拔，先抽象接口
- **对象存储**：MVP 阶段可先用本地文件系统，后续切换 S3 兼容存储

### 3.2 FastAPI 作为核心框架的理由

选择 **FastAPI** 的原因如下：

1. **原生异步支持**
   - 审稿任务中涉及 PDF 解析、Embedding、LLM 调用、外部检索等大量 IO 密集型操作。
   - FastAPI 的 async/await 模型天然适合这种场景。

2. **自动生成 OpenAPI / Swagger 文档**
   - 对前后端联调、后续 Agent 协作定义接口契约非常有帮助。
   - 在 MVP 阶段无需额外维护接口文档站点。

3. **与 Pydantic/SQLAlchemy 生态耦合良好**
   - 数据校验、请求响应模型定义、依赖注入较成熟。

4. **适合单体架构快速演进**
   - 初期以模块化单体方式开发，后期若要拆 service，迁移成本较低。

### 3.3 LangGraph 作为 Agent 编排方案的理由

选择 **LangGraph** 作为首选 Agent 编排层，原因如下：

1. **适合图式工作流**
   - 审稿辅助不是一次性直线生成，而是“计划 → 检索 → 反思 → 补检索 → 生成”的带回路流程。
   - LangGraph 对节点状态和图结构表达优于普通链式编排。

2. **支持多 Agent 协作**
   - 主控 Agent、审稿 Agent、检索 Agent 可以在统一图中协同。

3. **便于显式状态控制**
   - 对后续和 review_tasks 状态机衔接更自然。

4. **可退化到纯代码状态机**
   - 若 LangGraph 在开发中引入不必要复杂度，可保留业务接口不变，替换为纯 Python 状态机实现。

### 3.4 PostgreSQL + pgvector 的理由

MVP 阶段采用 **PostgreSQL + pgvector 的 all-in-one 策略**。

原因如下：

1. **降低运维复杂度**
   - 不单独引入 Milvus/Qdrant，减少部署和维护成本。

2. **统一存储结构化与向量数据**
   - 用户、任务、文档、evidence 等关系型数据与论文 chunk 向量存储放在同一数据库中，利于事务控制和联合查询。

3. **支持混合检索路线**
   - 可在 PostgreSQL 内实现 metadata filter + pgvector 相似度召回，再与 BM25 / tsvector 结合形成混合检索。

4. **适合 MVP 体量**
   - 早期论文量有限，PG 足以支撑。

### 3.5 Redis + Celery 的理由

Agent 审稿任务通常耗时较长，必须做异步执行。

选择 **Redis + Celery** 的原因如下：

1. **任务解耦主请求链路**
   - `POST /reviews` 只负责入队并返回 task_id，不阻塞主 API。

2. **支持重试与失败恢复**
   - Celery 对超时、自动重试、任务状态追踪较成熟。

3. **便于水平扩展**
   - 后续若 Embedding 或 LLM 调用量上升，可增加 worker 数量。

4. **生态成熟**
   - 日志、监控、部署实践相对成熟。

> 备注：若更偏极简异步栈，也可考虑 ARQ；但本文档默认以 Celery 为基线设计。

---

## 4. 系统总体架构

### 4.1 架构风格
采用 **模块化单体（Modular Monolith）**。

核心思想：
- 物理上单进程/少量服务部署
- 逻辑上严格分层、分模块
- API 层、服务层、Agent 层、RAG 层、Worker 层职责清晰
- 不允许出现“路由里直接写检索逻辑”“Agent 里直接操作 HTTP 响应”这类跨层耦合

### 4.2 核心模块分层

1. **API 层**：接收请求、校验参数、返回响应
2. **Service 层**：编排业务流程、与数据库和异步任务层交互
3. **Worker 层**：执行耗时任务
4. **Agent 层**：负责审稿策略规划、论点生成与报告生成
5. **RAG 层**：负责解析、切块、向量化、检索
6. **Persistence 层**：ORM 模型与数据库访问
7. **Core 层**：配置、连接、通用基础设施

### 4.3 关键运行链路

主链路如下：

`POST /reviews -> 创建 review_task(PENDING) -> Celery worker 消费 -> 解析 PDF -> chunking -> embedding -> Agent planning -> evidence retrieval -> report generation -> 写回 result_json / evidences -> GET /reviews/{task_id} 轮询获取结果`

---

## 5. 目录结构设计（DDD 简化版）

要求整个项目严格按以下目录组织，禁止跨层乱调。

```text
app/
├── main.py
├── api/
│   ├── deps.py
│   ├── v1/
│   │   ├── router.py
│   │   ├── documents.py
│   │   └── reviews.py
│
├── core/
│   ├── config.py
│   ├── database.py
│   ├── logging.py
│   ├── security.py
│   ├── celery_app.py
│   └── llm.py
│
├── models/
│   ├── base.py
│   ├── user.py
│   ├── document.py
│   ├── vector_chunk.py
│   ├── review_task.py
│   └── evidence.py
│
├── schemas/
│   ├── common.py
│   ├── document.py
│   ├── review.py
│   ├── evidence.py
│   └── enums.py
│
├── agents/
│   ├── orchestrator.py
│   ├── reviewer.py
│   ├── planner.py
│   ├── prompts/
│   │   ├── planner.py
│   │   └── reviewer.py
│   └── tools/
│       ├── pdf_tools.py
│       ├── scholar_search.py
│       ├── retrieval_tool.py
│       └── citation_tool.py
│
├── rag/
│   ├── parser.py
│   ├── chunker.py
│   ├── embedder.py
│   ├── retriever.py
│   └── ranking.py
│
├── services/
│   ├── document_service.py
│   ├── review_service.py
│   ├── evidence_service.py
│   └── storage_service.py
│
├── workers/
│   ├── review_tasks.py
│   └── document_tasks.py
│
├── repositories/
│   ├── document_repository.py
│   ├── review_task_repository.py
│   ├── chunk_repository.py
│   └── evidence_repository.py
│
├── utils/
│   ├── time.py
│   ├── ids.py
│   └── exceptions.py
│
├── tests/
│   ├── api/
│   ├── services/
│   ├── rag/
│   └── agents/
│
└── migrations/
```

### 5.1 各目录职责说明

#### `api/`
- 只负责接收请求、校验入参、调用 service、返回 response schema
- 不直接写数据库操作
- 不直接执行 Agent / RAG 长耗时逻辑

#### `core/`
- 全局配置
- DB Session 初始化
- Celery 初始化
- LLM Client 初始化
- 日志与基础依赖

#### `models/`
- SQLAlchemy ORM 模型定义
- 数据库结构的唯一事实来源之一（另一来源为 migrations）

#### `schemas/`
- 请求响应模型
- 枚举类型
- API 契约定义

#### `agents/`
- Agent 逻辑中枢
- 主控 Agent 负责任务规划与子流程调度
- reviewer Agent 负责审稿内容生成
- tools 目录提供 agent 可调用工具封装

#### `rag/`
- 负责文档解析、chunk 切分、embedding 与检索
- 不关心 API 请求来源
- 不关心 review_task 状态更新

#### `services/`
- 系统业务逻辑层
- 负责串联 repository、worker 调度、状态更新
- 是 API 层的首要依赖

#### `workers/`
- Celery 任务入口
- 负责真正执行耗时任务并更新状态机

#### `repositories/`
- 对 ORM 的读写访问进一步封装
- 避免 service 层到处散落 Session query 逻辑

---

## 6. 核心业务流程设计

### 6.1 文档上传流程

#### 输入
用户上传 PDF 或提交文件引用

#### 处理步骤
1. API 层接收文件
2. `document_service` 存储文件
3. 写入 `documents` 记录，状态置为 `UPLOADED` 或 `PENDING_PARSE`
4. 返回 `document_id`

#### 输出
- `document_id`
- 文档基本状态

### 6.2 审稿任务提交流程

#### 输入
- `document_id`
- `focus_areas`

#### 处理步骤
1. API 校验 document 是否存在且属于当前用户
2. `review_service` 创建 `review_tasks` 记录，状态为 `PENDING`
3. 将 task_id 投递给 Celery 队列
4. 返回 task_id 和当前状态

#### 输出
- `task_id`
- `status=PENDING`

### 6.3 审稿执行主流程

Worker 消费任务后执行以下步骤：

1. `PARSING_DOC`
   - 解析 PDF
   - 抽取原始文本与初步 metadata

2. `VECTORIZING`
   - 切块
   - 生成 embedding
   - 写入 `vector_chunks`

3. `AGENT_PLANNING`
   - 主控 Agent 生成审稿计划
   - 确定需要审查的维度，如创新性表达、方法清晰性、实验充分性、局限性等

4. `EVIDENCE_RETRIEVAL`
   - 根据审稿维度发起检索
   - 召回支撑该维度判断的 chunk
   - 必要时进行二次检索或补检索

5. `REPORT_GENERATING`
   - reviewer Agent 综合 facts 与 evidences
   - 输出结构化审稿报告
   - 写入 `result_json`
   - 持久化 evidence 溯源记录

6. `COMPLETED`
   - 更新终态

若任何关键步骤失败，则写入 `FAILED`。

---

## 7. 核心数据表设计（Schema Design）

本节定义 MVP v1 核心表及关键字段。数据库为 PostgreSQL，向量字段使用 pgvector。

### 7.1 `users`

用于存储用户账户与额度层信息。

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | UUID / BIGINT | 主键 |
| `email` | VARCHAR(255) UNIQUE | 用户邮箱 |
| `tier` | VARCHAR(32) | 用户层级，例如 free / pro / admin |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

#### 设计说明
- `tier` 用于后续做额度限制、任务并发限制和文件上传限制。
- MVP 阶段可先不做完整 billing，只保留 tier 字段。

### 7.2 `documents`

存储用户上传的论文文档主记录。

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | UUID / BIGINT | 主键 |
| `user_id` | FK -> users.id | 文档归属用户 |
| `title` | VARCHAR(512) | 文档标题，可由解析后补全 |
| `file_url` | TEXT | PDF 存储路径或对象存储 URL |
| `status` | VARCHAR(32) | 文档解析状态 |
| `metadata_json` | JSONB | 作者、年份、会议、摘要等元数据 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

#### 推荐状态值
- `UPLOADED`
- `PARSED`
- `INDEXED`
- `FAILED`

#### 设计说明
- `metadata_json` 保存解析出的作者、年份、页数、关键词等半结构化信息。
- 文档状态与 review_task 状态分离，避免多个任务争用同一字段含义。

### 7.3 `vector_chunks`

存储 chunk 及其向量表示，是 RAG 的核心表。

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | UUID / BIGINT | 主键 |
| `document_id` | FK -> documents.id | 所属文档 |
| `chunk_text` | TEXT | chunk 内容 |
| `embedding` | VECTOR | pgvector 向量字段 |
| `page_number` | INTEGER | chunk 对应页码 |
| `section_name` | VARCHAR(128) | 所属章节，如 Introduction / Method |
| `chunk_index` | INTEGER | 文档内顺序 |
| `token_count` | INTEGER | chunk token 数 |
| `created_at` | TIMESTAMP | 创建时间 |

#### 设计说明
- `section_name` 与 `page_number` 对 evidence 返回很重要。
- `chunk_index` 可用于还原上下文邻接关系。
- 推荐后续对 `embedding` 建立 ivfflat 或 hnsw 索引（取决于 pgvector 版本与数据规模）。

### 7.4 `review_tasks`

核心任务表，是整个系统状态机的唯一业务主线。

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | UUID / BIGINT | 主键 |
| `document_id` | FK -> documents.id | 对应文档 |
| `user_id` | FK -> users.id | 发起用户 |
| `status` | VARCHAR(32) | 当前状态机节点 |
| `focus_areas` | JSONB | 用户指定的侧重点，如 methods / experiments / novelty |
| `result_json` | JSONB | 最终结构化审稿报告 |
| `error_message` | TEXT | 失败时错误摘要 |
| `retry_count` | INTEGER | 当前已重试次数 |
| `started_at` | TIMESTAMP | 任务开始时间 |
| `completed_at` | TIMESTAMP | 任务完成时间 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

#### 设计说明
- `status` 是整个工作流调度和前端轮询的关键字段。
- `result_json` 不仅保存最终报告，也可扩展保存中间统计信息。
- `retry_count` 用于 worker 失败控制。

### 7.5 `evidences`

保存支撑 Agent 某条评价的证据记录。

| 字段名 | 类型 | 说明 |
|---|---|---|
| `id` | UUID / BIGINT | 主键 |
| `review_task_id` | FK -> review_tasks.id | 归属审稿任务 |
| `chunk_id` | FK -> vector_chunks.id | 所引用原文 chunk |
| `claim` | TEXT | Agent 提出的论点或 concern |
| `confidence_score` | NUMERIC(3,2) / FLOAT | 置信度，0~1 |
| `evidence_type` | VARCHAR(32) | fact / concern / suggestion_support |
| `created_at` | TIMESTAMP | 创建时间 |

#### 设计说明
- 一条 claim 可关联多条 evidence，MVP 阶段可先允许一条记录表示 claim-chunk 映射，后续再引入 claim group 概念。
- `confidence_score` 必须明确是模型输出后的归一化分数，不等同于“真实性概率”。

---

## 8. ORM 模型建议

建议所有模型统一继承 `Base`，并具备以下通用字段约定：
- `id`
- `created_at`
- `updated_at`

推荐使用 SQLAlchemy 2.x declarative style。

模型文件拆分建议：
- `models/user.py`
- `models/document.py`
- `models/vector_chunk.py`
- `models/review_task.py`
- `models/evidence.py`

禁止把所有模型堆在一个文件中。

---

## 9. 状态机设计（review_tasks.status）

这是整个工作流稳定性的核心。系统必须严格实现以下状态流转：

1. `PENDING`
2. `PARSING_DOC`
3. `VECTORIZING`
4. `AGENT_PLANNING`
5. `EVIDENCE_RETRIEVAL`
6. `REPORT_GENERATING`
7. `COMPLETED`
8. `FAILED`

### 9.1 状态定义

#### `PENDING`
- 任务已创建，等待 worker 消费
- 允许重复排队保护和并发限制检查

#### `PARSING_DOC`
- 正在解析 PDF
- 包括文本抽取、metadata 抽取、章节粗分

#### `VECTORIZING`
- 正在切 chunk、生成 embedding、写入 pgvector

#### `AGENT_PLANNING`
- 主控 Agent 正在根据 focus_areas 和论文内容拆解审稿维度
- 产出 review plan，例如：
  - 方法是否清晰
  - 实验是否充分
  - baseline 是否充分
  - 是否有局限性讨论

#### `EVIDENCE_RETRIEVAL`
- 对各维度进行 evidence 检索
- 必要时可进行多轮 retrieval

#### `REPORT_GENERATING`
- 结合 extracted facts 与 evidence 生成最终结构化报告
- 写 result_json 与 evidences

#### `COMPLETED`
- 终态，表示报告已可读

#### `FAILED`
- 终态，表示任务失败且超出重试上限或遇到不可恢复错误

### 9.2 合法状态流转图

```text
PENDING
  -> PARSING_DOC
  -> VECTORIZING
  -> AGENT_PLANNING
  -> EVIDENCE_RETRIEVAL
  -> REPORT_GENERATING
  -> COMPLETED

任一中间状态
  -> FAILED
```

### 9.3 失败处理与重试策略

#### 通用原则
- 所有重试必须是 **幂等友好** 的
- 状态更新必须在数据库中落盘
- 每次失败必须写入 `error_message`
- `retry_count` 达到阈值后进入 `FAILED`

#### 各状态失败策略

##### `PARSING_DOC` 失败
可能原因：
- PDF 损坏
- 解析器异常
- OCR/文本抽取失败

处理策略：
- 自动重试 1~2 次
- 若仍失败，写入 `FAILED`
- `documents.status` 同步标记为 `FAILED`

##### `VECTORIZING` 失败
可能原因：
- embedding provider 超时
- 向量写入失败
- chunking 异常

处理策略：
- 对 embedding 调用做指数退避重试
- 若部分 chunk 已写入，重试前先清理该 `document_id` 旧 chunk，避免重复数据污染
- 超出阈值后置 `FAILED`

##### `AGENT_PLANNING` 失败
可能原因：
- LLM 输出 schema 不合法
- prompt 执行异常
- provider 响应失败

处理策略：
- 自动重试 2 次
- 若 JSON schema 校验失败，执行一次修复性 reformat 流程
- 仍失败则置 `FAILED`

##### `EVIDENCE_RETRIEVAL` 失败
可能原因：
- 检索结果为空
- pgvector 查询失败
- 相关工具异常

处理策略：
- 允许一次 fallback：由严格 focus retrieval 降级为 broader retrieval
- 若仍无法得到足够 evidence，可继续进入 REPORT_GENERATING，但将结果标记为 low confidence
- 仅当系统性故障时置 `FAILED`

##### `REPORT_GENERATING` 失败
可能原因：
- LLM 输出不符合 schema
- result_json 写库失败
- evidence 落库失败

处理策略：
- 自动重试 2 次
- 输出 schema 非法时执行 re-ask / repair
- 如果报告写入成功但 evidence 写入失败，不直接返回 COMPLETED，应整体回滚或显式重试 evidence persist

### 9.4 建议的重试阈值
- `PARSING_DOC`: 2 次
- `VECTORIZING`: 3 次
- `AGENT_PLANNING`: 2 次
- `EVIDENCE_RETRIEVAL`: 2 次
- `REPORT_GENERATING`: 2 次

---

## 10. Agent 设计

### 10.1 Agent 角色拆分

#### `orchestrator.py`
主控 Agent，职责：
- 接收 review context
- 生成审稿计划
- 调用 reviewer agent / retrieval tools
- 汇总输出为标准 schema

#### `reviewer.py`
审稿 Agent，职责：
- 根据 evidence 输出结构化 critique
- 生成 strengths / weaknesses / missing evidence / questions
- 控制风格：辅助评价，不做绝对裁决

#### `planner.py`
可选独立规划 Agent，职责：
- 将 focus_areas 转换为具体检索维度
- 生成 retrieval subqueries

### 10.2 Agent 输出约束
所有 Agent 输出必须可被 schema 验证，不允许把最终逻辑建立在自由文本上。

推荐审稿结果 schema 包含：
- `summary`
- `strengths`
- `weaknesses`
- `missing_evidence`
- `questions_for_authors`
- `confidence_overview`

### 10.3 Agent 设计原则
- Agent 不直接更新 HTTP response
- Agent 不直接管理数据库事务
- Agent 输出必须通过 service / worker 层落库
- Agent 的工具调用必须通过 `agents/tools/` 或 `rag/` 封装，不得直连随机库函数

---

## 11. RAG 设计

### 11.1 `parser.py`
职责：
- PDF 文本提取
- 尽可能处理双栏格式、参考文献干扰、页眉页脚噪声
- 输出结构化页级文本

### 11.2 `chunker.py`
职责：
- 按 section + token 长度切块
- 尽量避免打断公式说明或图表上下文
- 输出 chunk metadata

### 11.3 `embedder.py`
职责：
- 调用 embedding provider
- 返回标准向量格式

### 11.4 `retriever.py`
职责：
- 混合检索（BM25 + 向量召回）
- 支持 document_id filter
- 返回 top-k 证据 chunk

### 11.5 混合检索策略建议
MVP 推荐使用：
1. 关键词检索（可借助 PostgreSQL full-text search）
2. pgvector 相似度召回
3. 简单 rerank（按 keyword overlap + vector score 融合）

目标不是一次做到最优，而是先保证 evidence 质量可用。

---

## 12. API 契约设计（异步模式）

审稿任务耗时较长，必须使用 **提交任务 -> 轮询状态** 模式。

### 12.1 `POST /api/v1/reviews`
提交审稿请求。

#### 请求体
```json
{
  "document_id": "doc_123",
  "focus_areas": ["methods", "experiments", "limitations"]
}
```

#### 响应体
```json
{
  "task_id": "task_123",
  "status": "PENDING"
}
```

#### 约束
- 不同步返回审稿结果
- 仅完成：参数校验、任务创建、队列入队

### 12.2 `GET /api/v1/reviews/{task_id}`
轮询接口，前端每隔 3 秒请求一次。

#### 响应示例（处理中）
```json
{
  "task_id": "task_123",
  "status": "EVIDENCE_RETRIEVAL",
  "result_json": null
}
```

#### 响应示例（完成）
```json
{
  "task_id": "task_123",
  "status": "COMPLETED",
  "result_json": {
    "summary": "...",
    "strengths": ["..."],
    "weaknesses": ["..."],
    "missing_evidence": ["..."],
    "questions_for_authors": ["..."]
  }
}
```

### 12.3 `GET /api/v1/reviews/{task_id}/evidences`
溯源接口，用于返回某条审稿意见的支撑片段。

#### 响应示例
```json
{
  "task_id": "task_123",
  "evidences": [
    {
      "claim": "The paper lacks efficiency analysis.",
      "confidence_score": 0.89,
      "chunk_id": "chk_001",
      "page_number": 7,
      "chunk_text": "..."
    }
  ]
}
```

### 12.4 补充建议接口
虽然当前规范重点在 reviews，MVP 还建议加一个文档上传接口：

#### `POST /api/v1/documents`
- 上传 PDF
- 返回 `document_id`

否则 `POST /reviews` 无法形成完整业务闭环。

---

## 13. Pydantic Schema 设计建议

### 13.1 `schemas/enums.py`
定义以下枚举：
- `DocumentStatus`
- `ReviewTaskStatus`
- `UserTier`
- `EvidenceType`

### 13.2 `schemas/document.py`
建议包含：
- `DocumentCreateResponse`
- `DocumentReadResponse`

### 13.3 `schemas/review.py`
建议包含：
- `ReviewCreateRequest`
- `ReviewCreateResponse`
- `ReviewReadResponse`
- `ReviewResultSchema`

### 13.4 `schemas/evidence.py`
建议包含：
- `EvidenceRead`
- `EvidenceListResponse`

---

## 14. Service 层职责设计

### 14.1 `document_service.py`
职责：
- 保存上传文件
- 创建 `documents` 记录
- 查询文档所有权

### 14.2 `review_service.py`
职责：
- 创建 review_task
- 校验 document 状态和所有权
- 投递 Celery 任务
- 返回 task 查询结果

### 14.3 `evidence_service.py`
职责：
- 聚合 evidence 返回结构
- 支持 claim 维度或 task 维度查询

### 14.4 `storage_service.py`
职责：
- 抽象本地文件系统 / 对象存储读写
- 为后续云存储替换留接口

---

## 15. Worker 层设计

### 15.1 `workers/review_tasks.py`
建议至少包含：
- `run_review_task(task_id: str)`

该函数主流程：
1. 加载 review_task
2. 状态置为 `PARSING_DOC`
3. 调用 parser
4. 状态置为 `VECTORIZING`
5. 调用 chunker + embedder
6. 状态置为 `AGENT_PLANNING`
7. 调用 orchestrator 生成 plan
8. 状态置为 `EVIDENCE_RETRIEVAL`
9. 调用 retriever 取证据
10. 状态置为 `REPORT_GENERATING`
11. 调用 reviewer 生成报告
12. 写入 `result_json` 与 `evidences`
13. 状态置为 `COMPLETED`

### 15.2 事务边界建议
- 每完成一个关键状态切换，即刻提交数据库事务
- 不要把整条任务塞进一个超长事务
- 对 evidence 写入和 result_json 写入要保证一致性

---

## 16. 异常处理与可靠性策略

### 16.1 异常分类
建议将异常分为：
- `ValidationError`：输入非法
- `RecoverableTaskError`：可重试错误，如网络超时、provider 暂时不可用
- `NonRecoverableTaskError`：不可恢复错误，如 PDF 损坏、权限丢失
- `PersistenceError`：数据库写入失败

### 16.2 幂等性要求
以下操作必须尽量幂等：
- review_task 重试执行
- vector_chunks 重建
- evidences 重写入
- result_json 覆盖式更新

### 16.3 清理策略
- `VECTORIZING` 重试前，删除旧的该文档 chunk 记录
- `REPORT_GENERATING` 重试前，删除或覆盖旧 evidence 写入结果

---

## 17. 日志、监控与可观测性

MVP 虽是单体，也必须保留基础可观测性。

### 17.1 日志建议
每个 review_task 至少记录：
- task_id
- document_id
- user_id
- current_status
- latency_ms
- provider 调用次数
- retry_count

### 17.2 监控建议
MVP 可先做基础 metrics：
- 审稿任务总数
- 各状态耗时
- 平均 embedding 时长
- 平均 report generation 时长
- 失败率
- 重试率

### 17.3 Trace 建议
后续可为每个 task 保留 step trace，MVP 可先通过日志 + review_tasks 状态近似代替。

---

## 18. 安全与权限边界

### 18.1 所有权校验
任何 `document_id` 和 `task_id` 查询都必须校验 `user_id` 所有权。

### 18.2 文件限制
MVP 建议限制：
- PDF only
- 单文件大小限制
- 单用户并发任务数限制（由 tier 控制）

### 18.3 风险控制
- 避免在日志中打出全文 chunk_text
- 敏感配置通过环境变量注入
- provider key 不入库

---

## 19. 结果 JSON 结构建议

`review_tasks.result_json` 建议采用如下结构：

```json
{
  "summary": "...",
  "focus_areas": ["methods", "experiments"],
  "strengths": [
    {
      "text": "The method motivation is clearly articulated.",
      "confidence": 0.82
    }
  ],
  "weaknesses": [
    {
      "text": "The paper does not provide sufficient efficiency analysis.",
      "confidence": 0.91
    }
  ],
  "missing_evidence": [
    {
      "text": "No latency or computational cost comparison is included.",
      "confidence": 0.93
    }
  ],
  "questions_for_authors": [
    "How does performance change under a lower-compute setting?"
  ],
  "confidence_overview": {
    "overall": 0.84,
    "notes": "Several claims are well-supported by retrieved evidence, while novelty assessment remains tentative."
  }
}
```

---

## 20. 开发实施顺序建议

### 20.1 第一阶段：底座先行
目标：把最小系统骨架与基础链路打通。

交付：
- FastAPI 应用启动
- PostgreSQL 连接
- Alembic 迁移
- 基础 models / schemas
- 文档上传接口
- 审稿任务创建接口
- Celery 接入

### 20.2 第二阶段：文档处理链路
目标：打通文档解析与向量化。

交付：
- PDF parser
- chunker
- embedder
- vector_chunks 写库

### 20.3 第三阶段：Agent 审稿主链路
目标：实现 plan → retrieve → generate。

交付：
- orchestrator
- reviewer
- retrieval tool
- result_json 生成
- evidence 写入

### 20.4 第四阶段：增强与稳定性
目标：完善异常处理、重试与可观测性。

交付：
- retry policy
- logging
- metrics
- integration tests

---

## 21. MVP v1 开发 Issue Backlog

以下 backlog 按优先级和依赖关系拆分，可直接作为开发任务列表。

### Epic 1：项目初始化与基础设施

#### Issue 1.1 初始化项目骨架
- 创建 FastAPI 项目目录
- 建立 `api/core/models/schemas/services/workers/agents/rag` 目录
- 配置 `pyproject.toml` 或 `requirements.txt`
- 验收标准：应用可启动，目录结构完整

#### Issue 1.2 配置系统与环境变量
- 实现 `core/config.py`
- 支持 DB、Redis、LLM provider、文件存储路径等配置
- 验收标准：本地 `.env` 可驱动服务启动

#### Issue 1.3 数据库初始化
- 实现 `core/database.py`
- 接入 PostgreSQL
- 配置 SQLAlchemy Session
- 验收标准：应用可连通 PG

#### Issue 1.4 Alembic 迁移初始化
- 初始化 Alembic
- 建立首个 migration 模板
- 验收标准：可执行迁移命令

### Epic 2：核心数据模型与迁移

#### Issue 2.1 实现 `users` ORM 与迁移
- 定义 User 模型
- 建立 users 表迁移
- 验收标准：表结构与文档一致

#### Issue 2.2 实现 `documents` ORM 与迁移
- 定义 Document 模型
- 建立 documents 表迁移
- 验收标准：支持 metadata_json/status 字段

#### Issue 2.3 实现 `vector_chunks` ORM 与迁移
- 定义 VectorChunk 模型
- 接入 pgvector 字段
- 验收标准：向量字段可建表

#### Issue 2.4 实现 `review_tasks` ORM 与迁移
- 定义 ReviewTask 模型
- 加入 status/result_json/retry_count 等字段
- 验收标准：状态字段与文档一致

#### Issue 2.5 实现 `evidences` ORM 与迁移
- 定义 Evidence 模型
- 建立外键关联
- 验收标准：claim 与 confidence_score 可写入

### Epic 3：Schema 与 API 契约

#### Issue 3.1 定义枚举与公共 schema
- 定义状态枚举、tier 枚举、evidence type 枚举
- 验收标准：schema 可被 API 与 service 复用

#### Issue 3.2 实现文档上传接口 schema
- `DocumentCreateResponse`
- 验收标准：Swagger 中可见

#### Issue 3.3 实现审稿请求与轮询 schema
- `ReviewCreateRequest`
- `ReviewCreateResponse`
- `ReviewReadResponse`
- 验收标准：接口文档完整

#### Issue 3.4 实现 evidence 返回 schema
- `EvidenceRead`
- `EvidenceListResponse`
- 验收标准：字段与 evidences 表对应

### Epic 4：文档上传与存储

#### Issue 4.1 实现本地文件存储服务
- `storage_service.py`
- 保存 PDF 到本地目录
- 验收标准：上传后可返回 file_url

#### Issue 4.2 实现 `POST /api/v1/documents`
- 接收 PDF 上传
- 创建 documents 记录
- 验收标准：返回 document_id 与初始状态

#### Issue 4.3 实现文档所有权校验基础逻辑
- 校验 user_id 与 document_id 关联
- 验收标准：越权访问被拒绝

### Epic 5：异步任务基础设施

#### Issue 5.1 接入 Redis 与 Celery
- 创建 `core/celery_app.py`
- 验收标准：worker 可启动

#### Issue 5.2 实现 review task 入队逻辑
- `review_service.create_review_task()`
- 创建 review_tasks 记录并推送 Celery
- 验收标准：`POST /reviews` 返回 PENDING

#### Issue 5.3 实现轮询接口 `GET /api/v1/reviews/{task_id}`
- 查询 review_task 状态
- 返回 result_json
- 验收标准：处理中和完成态均可返回

### Epic 6：RAG 基础链路

#### Issue 6.1 实现 PDF parser
- 支持基础文本抽取
- 预留双栏增强接口
- 验收标准：可返回页级文本

#### Issue 6.2 实现 chunker
- 按 token/section 切块
- 输出 chunk metadata
- 验收标准：可生成 chunk 列表

#### Issue 6.3 实现 embedder
- 接入 embedding provider
- 验收标准：输入文本可返回向量

#### Issue 6.4 实现 vector chunk 写库
- 持久化到 `vector_chunks`
- 验收标准：某 document 可检索到 chunk 记录

#### Issue 6.5 实现基础 retriever
- document_id 过滤 + top-k 向量检索
- 验收标准：可返回相关 chunk

### Epic 7：Agent 审稿链路

#### Issue 7.1 定义审稿结果 schema
- 确定 result_json 最终结构
- 验收标准：可被 reviewer 输出复用

#### Issue 7.2 实现 planner / orchestrator
- 基于 focus_areas 生成审稿 plan
- 验收标准：输出合法 planning schema

#### Issue 7.3 实现 reviewer agent
- 基于 evidence 生成 summary/strengths/weaknesses
- 验收标准：输出符合 result schema

#### Issue 7.4 实现 evidence 持久化
- 把 claim-chunk-confidence 写入 evidences 表
- 验收标准：task 可查询 evidence 列表

#### Issue 7.5 实现 `GET /api/v1/reviews/{task_id}/evidences`
- 返回 evidence 溯源信息
- 验收标准：包含 chunk_text/page_number/confidence

### Epic 8：状态机与可靠性

#### Issue 8.1 在 worker 中实现状态流转
- 严格按 PENDING -> ... -> COMPLETED/FAILED 更新
- 验收标准：数据库中可观察状态变化

#### Issue 8.2 实现失败重试策略
- embedding / LLM / retrieval 异常重试
- 验收标准：retry_count 可正确递增

#### Issue 8.3 实现失败信息落库
- 写入 error_message
- 验收标准：FAILED 任务可查看错误原因

#### Issue 8.4 实现幂等清理逻辑
- vector_chunks 重建前清理旧数据
- evidence 重写前覆盖旧结果
- 验收标准：重跑不会产生脏重复数据

### Epic 9：测试与可观测性

#### Issue 9.1 API 基础测试
- 测试 documents/reviews/evidences 接口
- 验收标准：关键接口有自动化测试

#### Issue 9.2 RAG 单元测试
- parser/chunker/retriever 的最小测试
- 验收标准：核心模块可独立验证

#### Issue 9.3 Worker 集成测试
- 模拟完整 review task 执行
- 验收标准：任务能从 PENDING 跑到 COMPLETED

#### Issue 9.4 基础日志埋点
- task_id/status/latency 结构化日志
- 验收标准：可根据 task_id 追踪流程

---

## 22. 里程碑建议

### Milestone 1：项目可启动
- FastAPI + PG + Redis + Celery 连通
- 基础表迁移完成

### Milestone 2：文档可上传、任务可创建
- `POST /documents`
- `POST /reviews`
- `GET /reviews/{task_id}`

### Milestone 3：RAG 链路打通
- 解析、切块、向量化、检索可运行

### Milestone 4：审稿报告可生成
- result_json 可落库
- evidence 可查询

### Milestone 5：系统具备基本稳定性
- retry
- failed 状态
- integration test

---

## 23. 最终结论

本《技术设计与实施文档 v1》将项目正式收敛为一个 **基于 FastAPI + LangGraph + PostgreSQL/pgvector + Redis/Celery 的纯 Python 单体后端系统**。

MVP v1 的目标不是做一个“万能科研助手”，而是做成一个**可异步执行、可检索溯源、可状态追踪、可逐步扩展的科研审稿辅助后端**。

该版本已经具备以下工程特征：
- 清晰的模块边界
- 明确的数据表设计
- 可执行的任务状态机
- 明确的异步 API 契约
- 可直接拆分落地的开发 backlog

后续建议按本文档的 backlog 顺序推进开发，并优先保证：
**状态机稳定、evidence 可追踪、结果 schema 固定。**

