# 长篇记忆检索（L3）设计

> 状态：设计稿 · 2026-11-24
> 关联：[写作工作台 UX 规格](./ux/writing-workbench.md) §7（记忆页）、§4.8（参考资料清单）
> 代码落点：`backend/app/domain/memory.py`、`memory_gen.py`、`references.py`、`backend/app/db.py`、`frontend/src/views/MemoryView.vue`
> 视觉：[架构图](./diagrams/memory-architecture.html) · [界面稿](./mockups/memory-page.html)

## 0. 现状与要解决的问题

当前是「窗口式记忆 + 确定性关键词回查」：

| 层 | 覆盖 | 内容 |
| --- | --- | --- |
| 最近 8 章 | 精确 | 摘要 + 关键事件 + 结束状态 |
| 再往前 80 章 | 一章一句 | `第N章《标题》：首句` |
| 更早 | 兜底 | 卷摘要 + 最近 20 条时间线 + 「记忆」页手动关键词回查 |
| 全书设定 | 全量 | bible 全部条目（按段预算截断） |

实测（本仓库合成书）：写第 200 章时整包 9.9k 字符、前情段 2.8k 字符，**不会随章节数膨胀**。
但第 89 章以前的普通细节（一句台词、一次转手、一个只在当时出现的物件）不会自动进入上下文。

要补的是**按本章需要，把远章的相关片段自动调出来**，并且让作者看得见「调了什么、为什么」。

## 1. 目标 / 非目标

**目标**

1. 写第 N 章时，自动召回 88 章以前的 4–8 段相关记忆，带章号出处。
2. 召回是**确定性、可解释**的：同输入同输出，每条命中给出理由（实体 / 伏笔 / 关键词 / 时间）。
3. 预算硬上限：默认 2400 字，超出按规则裁剪，不挤占近章记忆。
4. 作者可干预：某章可「固定包含 / 排除」，写下一章立即生效。
5. 索引增量维护，400 章规模重建 < 1 秒、单次召回 < 50ms，不调用模型。

**非目标（本轮不做）**

- 不索引正文全文（只索引已提炼的结构化记忆；引文在命中后按章读取）。
- 不引入外部向量库 / embedding 服务；向量召回留作 P3 的可选增强。
- 不改写、不合并已有的章记忆与卷摘要。
- 不做跨书检索。

## 2. 设计原则

1. **确定性优先**：实体匹配（名字 + 别名）与 n-gram 检索都是可复现的；模型只负责已经写好的提炼，不参与召回排序。
2. **只补缺口**：召回只覆盖「近 8 章 + 80 章一句」窗口之外，不重复已在上下文里的章。
3. **可解释**：每条命中都带 `why`，UI 与提示词都写清楚「为什么在这一章被调出」。
4. **预算先行**：先分配字数，再挑条目；宁可少调，不挤掉近章。
5. **索引可丢弃**：索引是派生数据，删掉可从 `ledger/` 重建，不影响正文与记忆本身。

## 3. 分层模型（在现有 L0–L2 上加 L3）

```
L0 设定事实   bible：人物/物品/地点/势力/规则/力量/社会/大事记/术语
L1 卷记忆     ledger/memory.jsonl(kind=volume)：每卷一段摘要 + 六维度
L2 章记忆     ledger/memory.jsonl(kind=chapter)：最近 8 章详细 + 80 章一句
L3 远端召回   索引 → 按本章查询 → 4–8 段远章片段（本轮新增）
```

L3 的输出并入参考包的新段 `recall`，分组「前情」，位置在 `chapter-memory` 之后、`volume-memory` 之前。

## 4. 索引

### 4.1 存储

复用全局 SQLite（`backend/app/db.py`，WAL），以 `books.dir` 规范路径对应的 `book_id` 为键。新增四张表：

```sql
CREATE TABLE IF NOT EXISTS memory_docs (
  book_id  TEXT NOT NULL,
  chapter  INTEGER NOT NULL,
  kind     TEXT NOT NULL,          -- chapter | timeline | foreshadow | outline | volume
  title    TEXT,
  chars    INTEGER NOT NULL DEFAULT 0,
  text     TEXT NOT NULL,          -- 摊平的检索文本（不是原文）
  updated_at TEXT NOT NULL,
  PRIMARY KEY (book_id, kind, chapter)
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  text,
  book_id UNINDEXED,
  chapter UNINDEXED,
  kind    UNINDEXED,
  tokenize = 'trigram'
);

CREATE TABLE IF NOT EXISTS memory_entities (
  book_id   TEXT NOT NULL,
  chapter   INTEGER NOT NULL,
  kind      TEXT NOT NULL,         -- character | item | location | faction | rule | foreshadow
  name      TEXT NOT NULL,         -- 正文里出现的写法
  canonical TEXT NOT NULL,         -- 统一后的名字
  PRIMARY KEY (book_id, chapter, kind, name)
);
CREATE INDEX IF NOT EXISTS idx_mem_entity ON memory_entities(book_id, canonical, chapter);

CREATE TABLE IF NOT EXISTS memory_index_meta (
  book_id        TEXT PRIMARY KEY,
  built_at       TEXT NOT NULL,
  source_hash    TEXT NOT NULL,    -- index.json + memory.jsonl + bible.json + foreshadow + outline
  schema_version INTEGER NOT NULL
);
```

`memory_docs.text` 的拼法（全部来自已有数据，不新增模型调用）：

- `chapter`：`标题 + 摘要 + 关键事件 + 结束状态 + 谁知道什么 + 关系变化 + 地点`
- `timeline`：`故事时间 + 地点 + 事件`
- `foreshadow`：`名称 + 埋点 + 提示 + 揭开后变化 + 状态`
- `outline`：`节拍 + 必须出现 + 开场/结束状态`
- `volume`：`卷摘要 + 六维度`

### 4.2 中文检索策略

SQLite FTS5 的 `trigram` 分词只命中 ≥3 字的查询（已实测：`旧码头` 命中，`阿雾`、`船` 不命中）。因此用三路并联：

| 查询形态 | 通道 | 说明 |
| --- | --- | --- |
| 实体名 / 别名（任意长度） | 实体表精确匹配 | 主力通道；人物、物品、地点、势力、规则、伏笔名 |
| ≥3 字关键词 | `memory_fts MATCH`（trigram） | 覆盖非实体的短语 |
| 2 字关键词 | `memory_docs.text LIKE '%词%'` | 400 章约 12 万字，全扫 < 10ms |

三路结果按章合并，同一章只保留得分最高的一条（可拼接两段不同来源的文本）。

### 4.3 维护时机

| 触发 | 动作 |
| --- | --- |
| `generate_chapter_memory` 成功落盘后 | upsert 该章 `chapter` + 本章相关 `timeline` 文档与实体 |
| `apply_continuity` / 保存 bible 后 | 刷新实体别名（只改实体表，不动文档） |
| 伏笔 / 细纲写入后 | upsert 对应 `foreshadow` / `outline` 文档 |
| 打开记忆页 / 首次召回 | 校验 `source_hash`；不一致则后台增量重建 |
| `POST /memory/index/rebuild` | 全量重建（先建临时表再原子替换，失败保留旧索引） |

索引缺失或 SQLite 不可用 → 召回返回空，面板显示「索引未建立」，写作照常（只是回到当前行为）。

## 5. 查询构造

输入：第 N 章的细纲、作者强调项（focus）、本章应埋/应收伏笔、上一章结尾。

```
entities = 最长匹配(bible 全部 name + aliases, 细纲 beats + focus + prev_tail)
terms    = 实体名 + 伏笔名 + 细纲关键词（去掉停用词，保留 2–8 字）
filters  = 1 <= chapter <= N-89            # 只看窗口外
```

- 实体识别是纯字符串最长匹配，不做模型调用；别名表已在 `memory.resolve_character` / `aliases_of`。
- 停用词表：的/了/在/是/和/与/他/她/它/这/那/一个/没有 等约 30 个。
- 查询结果在 UI 里以 chip 形式展示，作者能看懂「这一章按哪些词去找」。

## 6. 排序

```
score = 3.0 * entity_hits
      + 2.0 * fts_hits
      + 1.5 * foreshadow_hits
      + 1.0 * recency            # max(0, 1 - (N - chapter) / 200)
      + 0.5 * same_volume
```

- `pinned` 的章直接置顶（得分记为 +∞），`excluded` 的章直接丢弃。
- 去重：同章只留一条；同一卷最多 2 条，除非有实体命中（防止一卷刷屏）。
- 多样性：相邻两条来自同一卷时，优先换下一卷的次高分条。
- 返回前 8 条，每条含 `chapter / title / excerpt(≤360 字) / why[] / score / pinned`。

## 7. 预算装配

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `RECALL_BUDGET` | 2400 字 | 整段召回的上限 |
| `RECALL_MAX_ITEMS` | 8 | 条数上限 |
| `RECALL_ITEM_CHARS` | 360 | 单条摘录上限 |

裁剪顺序：先丢无实体命中的最低分条 → 再把单条压到 240 字 → 仍超则整段置空并记录 `recall.dropped`。
召回段与 `chapter-memory` 互不挤占：两者各自有预算，整包仍受 `pack` 总量约束。

## 8. 提示词注入

在 `build_reference_pack` 中新增 section：

```
key: recall | group: 前情 | label: 远端回查（按本章自动召回）
source: ledger/ + memory_index
```

渲染进正文/细纲提示词时：

```
【远端回查（较早章节，按本章自动召回；只作事实依据，不得改写其设定）】
- 第37章《旧码头》｜实体命中：断桨；伏笔到期：断桨
  ……摘录……
- 第52章《夜渡》｜关键词：转手
  ……摘录……
（另 6 条未展开：预算已满）
```

同时在 `ledger/runs` 或本次生成记录里落一份 `recall` 快照（章号 + why），写作完成后可以回溯「这一章参考了哪些远章」。

## 9. API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/memory/coverage` | 每章记忆层级（详细 / 一句 / 卷 / 缺 / 未写），给记忆带用 |
| GET | `/memory/recall/preview?chapter=N` | 预演：写第 N 章会召回什么（含 why / score / 预算占用） |
| POST | `/memory/index/rebuild` | 全量重建索引，返回耗时与文档数 |
| POST | `/memory/recall/pin` | `{chapter, refChapter, pin: true\|false}` 固定/排除 |
| GET | `/memory/recall` | 保留现有手动回查，不动契约 |

`preview` 与真实生成共用 `recall_for_chapter()`，保证「预演看到的 = 提示词里的」。

## 10. 界面重设计

### 10.1 记忆页：新增「记忆带」

在工具条上方加一条 400 章宽度的层级带（`mem-ribbon`）：

- 每章一格 3px，按卷分组，组间 8px 空隙；卷标签在下方。
- 四档颜色：详细（近 8 章，accent 实心）/ 一句（再往前 80 章，ink 60%）/ 卷摘要（更早，ink 25%）/ 缺记忆（warn 斜纹）/ 未写（line）。
- 当前写作章用 accent 竖线标记，右侧文字「第 201 章 · 将召回 6 段」。
- 悬停 / 键盘聚焦：`第 37 章 · 一句记忆 · 单击定位`。
- 图例一行：详细 8 · 一句 80 · 卷摘要 12 · 缺 3。
- 点击某格 → 左栏定位；点击「将召回 6 段」→ 右栏「召回」tab。

### 10.2 右栏新增「召回」tab

`卷摘要 / 人物 / 关系 / 召回 / 回查`。

- 顶部：`预演：写第 [201] 章会自动调出` + `重算`。
- 查询 chip 行：`实体 断桨 ×2`、`伏笔 断桨（第 205 章到期）`、`关键词 转手`。
- 命中列表，每条：
  - 左：排名、`第 37 章《旧码头》`
  - 中：摘录（最多 3 行，展开看全文）
  - 右：`固定` / `排除` 小按钮
  - 底：why chips + 分数条（相对最高分）
- 页脚：`预算 1.8k / 2.4k 字 · 索引 2026-11-24 09:12 · 重建索引`。
- 空态：`这一章还不需要远端召回` / `近 88 章已经覆盖了所有相关章；写得更久后，这里会显示被调出的远章。`
- 索引缺失：`索引未建立` + `建立索引`。

### 10.3 开写面板参考资料

参考资料清单新增一行 `远端回查`：条数 + 「为什么」按钮（popover 列出 why）。固定项带 📌，排除项不显示。面板条数与提示词 section 同源（沿用本轮已修好的 skills/pack 同源约定）。

### 10.4 交互与无障碍

- 记忆带不是图表：用 `role="img"` + `aria-label` 概述，键盘可聚焦到当前章。
- 命中列表支持 `J/K` 上下移动、`P` 固定、`X` 排除。
- 窄屏（<900）：记忆带保留（横向滚动），召回 tab 与回查 tab 合并为 `召回`（顶部 segmented：预演 / 手动回查）。

## 11. 评估

离线脚本 `scripts/eval_recall.py`，用合成 200 章书 + 30 个「第 N 章需要旧事实」问题：

| 指标 | 目标 |
| --- | --- |
| 关键事实召回率 @8 | ≥ 85% |
| 无关命中占比 | ≤ 30% |
| 单次召回耗时 | < 50ms（400 章） |
| 索引重建 | < 1s（400 章） |
| 召回段字数 | ≤ 2400 |

测试（pytest）：

1. 200 章书，写第 201 章：第 20 章的独有物件出现在召回里，且 why 含实体。
2. 2 字实体（`阿雾`）与 3 字关键词（`旧码头`）都能命中。
3. 近章窗口内的章不会进入召回（去重）。
4. pin / exclude 生效且可撤销。
5. 预算超限时按顺序裁剪，不抛错。
6. 索引缺失时召回为空、写作不受影响。

## 12. 分期

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| P0 | 索引表 + 构建/重建 + `recall_for_chapter()` + 测试 | 合成 200 章召回正确 |
| P1 | 并入 pack / 提示词 / 生成记录 | 面板条数 == 提示词段 |
| P2 | 记忆带 + 召回 tab + pin/exclude + 预览 API | UX 走查通过 |
| P3（可选） | 向量召回（配置了 embedding 端点才启用），与确定性通道加权合并 | 召回率提升且延迟 < 200ms |

## 13. 风险

| 风险 | 应对 |
| --- | --- |
| FTS5 在旧 SQLite 不可用 | 启动时探测；不可用则只走实体 + LIKE 通道 |
| 索引与 ledger 漂移 | `source_hash` 校验 + 每次写记忆后增量 upsert |
| 召回噪声挤占上下文 | 硬预算 + 同卷上限 + 无实体命中不置顶 |
| 作者不信任自动召回 | 全部可解释、可固定/排除、预演与真实同源 |
| 多线程写索引 | 复用 `db.write_tx()` 的进程锁；单库单写者 |
