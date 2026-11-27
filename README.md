<div align="center">

<img src="frontend/public/favicon.svg" width="84" height="84" alt="Novel Studio Logo" />

<h1>Novel Studio · 网文写作工作台</h1>

<p>
  <strong>面向中文长篇连载的开源 AI 写作工作台</strong><br />
  把「选题 → 大纲 → 设定 → 伏笔 → 细纲 → 正文 → 体检 → 存档 → 记忆回写」串成一条<strong>可回退、可审计、不靠模型记性</strong>的生产线，而不是又一个聊天框。
</p>

<p>
  <a href="README.md"><strong>简体中文</strong></a> ·
  <a href="README.en.md">English</a>
</p>

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-e0357f?style=flat-square" alt="License: AGPL-3.0" /></a>
  <img src="https://img.shields.io/badge/Vue-3%20%2B%20Pinia%20%2B%20Vite-42b883?style=flat-square&logo=vuedotjs&logoColor=white" alt="Vue 3" />
  <img src="https://img.shields.io/badge/FastAPI-Python%203.11%2B-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Storage-Markdown%20%2B%20SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="Markdown + SQLite" />
  <img src="https://img.shields.io/badge/LLM-OpenAI%20Compatible-1c1a17?style=flat-square" alt="OpenAI Compatible" />
  <a href="https://github.com/chenxy1021/novel-studio-web/stargazers"><img src="https://img.shields.io/github/stars/chenxy1021/novel-studio-web?style=flat-square&color=e0357f" alt="GitHub Stars" /></a>
</p>

<p>
  <a href="#-界面预览">界面预览</a> ·
  <a href="#-为什么不是又一个聊天框">解决什么痛点</a> ·
  <a href="#-快速开始">快速开始</a> ·
  <a href="#-核心机制">核心机制</a> ·
  <a href="#-参考资料包与模型配置">模型配置</a>
</p>

<br />

<img src="docs/screenshots/01-overview.png" alt="Novel Studio 今日工作台" width="96%" />

<sub>虚构演示书《雾城夜邮》工作台首页 · 支持浅色 / 深色 / 跟随系统三种主题</sub>

</div>

---

## ✨ 为什么不是又一个聊天框？

用大模型写长篇连载，真正的瓶颈从来不是“能不能生成 2000 字”，而是**写到第 50 章之后开始吃书、人物瞬移、死人复活、满篇 AI 腔、伏笔只埋不收、自己手改完上下文就断链**。

| 长篇 AI 写作常见痛点 | 传统聊天框 / 简单提示词工具 | Novel Studio 的工程解法 |
|---|---|---|
| **写后忘前 / 吃书** | 靠长上下文硬塞，死人复活、物品凭空消失 | **连续性由账本推导**：人物三态切片、位置轨迹、物品转手链、信息差、已离场名单自动约束 |
| **满篇 AI 味 / 越改越平** | 只靠“请写得像真人”玄学提示词 | **两层体检 + 防变平门禁**：离线检测 13 类中文 AI 腔、跨章 6 字复读与节奏方差；改写变平自动拒写 |
| **伏笔烂尾 / 剧情发散** | 写到哪算哪，前面埋的线彻底忘光 | **伏笔强门禁 + 章脉图谱**：没有伏笔禁止写正文；核心/卷级/情节三层追踪，到期自动提醒收线 |
| **手改后上下文断链** | 在外部编辑器改了正文，AI 记忆还停在旧稿 | **正文永远是本地 Markdown + 手改回灌**：按 `sha256` 指纹自动扫出改动并重算章记忆与人物状态 |
| **超长篇上下文稀释** | 设定越堆越长，模型顾头不顾尾 | **实体解析 + 阶段预算收口**：写前解析本章实体，装不下的折成名录，正文阶段自动收紧背景段预算 |

---

## 📸 界面预览

> 以下截图均来自虚构演示书《雾城夜邮》，所有数据本地存储，无任何云端绑定。

<table>
  <tr>
    <td width="50%" align="center">
      <img src="docs/screenshots/02-review-checkup.png" alt="进度审阅与确定性体检" />
      <br />
      <strong>进度审阅 · 离线确定性体检与段落改写</strong><br />
      <sub>精准定位 AI 套话到段号/字偏移，支持单段改写、忽略误报与审美五项评审</sub>
    </td>
    <td width="50%" align="center">
      <img src="docs/screenshots/03-chapter-graph.png" alt="大纲章脉图谱" />
      <br />
      <strong>大纲 · 章脉图谱（伏笔埋收 + 同场弧线）</strong><br />
      <sub>全部由现有账本整理：上方弧线看伏笔埋收，下方弧线看十章内同场人物</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <img src="docs/screenshots/04-memory-dark.png" alt="记忆时间线与前情回查（深色模式）" width="96%" />
      <br />
      <strong>记忆页 · 自动回写时间线与叙事记忆（深色模式）</strong><br />
      <sub>每章落盘自动提炼故事内时间、出场人物、关键事件与伏笔标记，支持关键词回查与缺口补齐</sub>
    </td>
  </tr>
</table>

---

## 🔄 创作流水线

```mermaid
flowchart LR
  A["1. 选题"] --> B["2. 大纲 + 世界观"]
  B --> C["3. 设定 / 组织架构"]
  C --> D["4. 三层伏笔网"]
  D --> E["5. 段落纲 → 批次细纲"]
  E --> F["6. 流式生成正文"]
  F --> G["7. 确定性体检 + AI 复检"]
  G -->|按技能/单段改写| F
  G -->|批量确认| H["8. 存档 + 记忆回写"]
  H -->|更新人物/位置/物品/关系| E
```

- **正文永远是磁盘上的 Markdown**：`chapters/NNN-标题.md`，随时用 Obsidian / Typora / VS Code 打开，支持**一键导出整本 TXT**（`exports/`）。
- **结构化账本存 SQLite**：跨书统一管理设定、细纲、伏笔、记忆与时间线，读写走同一套领域接口。
- **数据安全兜底**：覆盖正文前自动留存 `chapters/.versions/NNN/`（每章保留最近 20 份）；删书前整目录快照到 `data/deleted/`；旧稿与退稿进「废章」可随时恢复。

---

## 🚀 快速开始

### 环境要求

- **Python ≥ 3.11** 与 **[uv](https://docs.astral.sh/uv/)**
- **Node.js ≥ 18** 与 **npm**
- 任意 **OpenAI 兼容接口**（DeepSeek、OpenAI、OpenRouter、本地 Ollama / vLLM 等）

### 一键启动

```bash
git clone https://github.com/chenxy1021/novel-studio-web.git
cd novel-studio-web

./scripts/dev.sh open     # 启动 API (8010) + Web (5180) 并打开浏览器
```

首次启动会自动执行 `uv sync` 与 `npm install`。打开页面后进入 **「设置」** 填写 Base URL、正文模型与轻活模型并点击「测试连接」即可开写（配置保存在本地 `data/gateway.json`，已 gitignore）。

<details>
<summary><strong>常用开发与测试命令</strong></summary>

```bash
./scripts/dev.sh          # 前台启动 API + Web，Ctrl-C 一起停
./scripts/dev.sh status   # 查看端口、健康检查与日志位置
./scripts/dev.sh stop     # 按端口停止（孤儿进程也能回收）

make api                  # 单独启动后端（8010）
make web                  # 单独启动前端（5180）
make test                 # 运行全量后端 pytest + 前端 vitest（离线替身，不耗 token）
make build                # 前端 TypeScript 类型检查 + 生产构建
```

</details>

---

## 🧠 核心机制

### 1. 人物三态、复活支持与回忆隔离
人物状态拆成三层，互不覆盖：
- **出场状态**（`appearanceStatus` + `firstChapter`）：首次登场时的状态。
- **当前状态**（`status` + `statusAt` / `statusLog`）：按章流水推进，只认正文已写到的事实。
- **退场与结局**（`exitChapter` + `finalStatus`）：区分「已发生」与「大纲计划」。计划第 76 章死亡的人，写第 56 章时仍显示「在场（第76章起死亡）」。

针对长篇常见边界场景做了专门处理：
- **修仙 / 奇幻复活**：正文明确交代手段与代价的复活、重生、夺舍或重塑肉身不会被误判为吃书；细纲或强调点名已离场人物时，写前约束会提示交代清楚依据。
- **回忆 / 倒叙隔离**：整章回忆（`isFlashback=true`）与局部闪回（`flashback=true`）回写时自动跳过当下位置、首次登场与生死更新；上一章为回忆章时，「上一章结尾」会自动向前衔接最近主线章，避免误续到过去时间线。

### 2. 两层体检 + 审美五项 + 防变平改写
- **离线确定性体检（0 token）**：字数、平台格式、13 类中文 AI 痕迹（定位到段号与字符偏移）、章尾 7 类钩子、硬规则碰撞、离场人物复活、跨章 6 字复读、句段节奏方差与细纲节拍检查。误报支持逐条「忽略」。
- **AI 语义复检**：只对照固定清单逐项判定（细纲必做/回避、伏笔埋收、设定一致、人物状态、限知视角），判不过必须引原文。
- **审美五项**：对文字质感、节奏、对话、画面、情绪各打 1–5 分，强制引原文 8–30 字 + 给出可执行改法，只给意见不拦存档。
- **按技能 / 单段改写**：落盘前重跑硬校验，若改写导致字数跌破下限、撞规则或句段/对话/用字明显变平（`flattening`），自动拒绝落盘，旧稿一字不动。

### 3. 四级世界规则与组织体系
- **规则四级**：`铁律`（只能绕不能破）、`契约`（可破但当场付代价）、`惯例`（社会性代价）、`谣言`（打破即揭示真相），每条带 `cost`、`boundary` 与 `enforcer`。
- **势力 / 组织 / 职业分工**：势力管阵营关系与暗规，组织（`bible.organizations`）管内部上下级汇报，职业（`bible.careers`）管晋升台阶；支持从已有设定一键整理且不覆盖手写内容。

### 4. 滚动规划、章脉图谱与手改回灌
- **滚动规划**：已写章号越过最后一卷时，结合作者罗盘（`compassText`）+ 全书层 + 最近六章记忆，只追加下一卷大纲与批次细纲，不重写已有内容。
- **章脉图谱与相关章节**：纯规则计算伏笔埋收、人物重合与状态延续，生成可视化章节关系图与远章推荐。
- **手改回灌**：在外部编辑器修改正文后，按 `sha256` 内容指纹识别 `edited / untracked / memory-stale`，一键 `undo → 重提记忆 → reapply` 保持账本同步。

---

## 📦 参考资料包与模型配置

- **写前实体解析 + 阶段预算收口**：生成前自动从细纲、台阶、近章记忆与作者强调中解析本章实体（可在面板逐条排除）；超预算时整条装入、装不下的折成名录。正文阶段自动收紧本卷大纲、其他未收伏笔、卷摘要、社会常识、大事记等背景段落预算，防止上下文稀释注意力。
- **全流程 SSE 流式输出**：选题、大纲、设定、伏笔、细纲、正文、改写均支持流式输出与思考过程推送，写作带 `runId` 并发保护。
- **按阶段路由思考强度**：蓝图/概念/设定 `high`，细纲/伏笔/正文/改写 `medium`，记忆提炼 `none`（可用 `NOVEL_STUDIO_REASONING` 覆盖）。非流式正文支持 `candidates: 1–3` 多稿择优。

---

## 📚 完整参考（点击展开）

<details>
<summary><strong>1. 工作台 14 个页面导航</strong></summary>

| 分组 | 页面 |
|---|---|
| **工作台** | **今日**（现在该做什么）、**开书**（流水线）、**文风**（书级默认 + 作家参照） |
| **写作** | **进度**（逐章审阅/体检/改写/存档）、**废章**（旧稿与退稿恢复） |
| **规划** | **大纲**（结构大纲/世界观/地图/章脉 + 滚动规划）、**细纲**（段落纲 + 参考资料）、**伏笔** |
| **资料** | **人物**（人物卡/关系矩阵/关系图/位置轨迹）、**组织**（组织架构/职业等级）、**记忆**（时间线/前情/回查）、**设定**（规则/世界纵深/势力/地点/物品/信息差） |
| **系统** | **设置**（外观/自动存档/模型/修复/用量） |

</details>

<details>
<summary><strong>2. 存储结构与目录说明</strong></summary>

| 数据 | 存储位置 |
|---|---|
| 书设置、人物、世界观、势力/地点/物品/规则、文风、细纲、伏笔、记忆、时间线 | SQLite：`data/studio.db` |
| 正文 | 书目录 `chapters/NNN-标题.md` |
| 章节索引与指纹 | `chapters/index.json`（含正文 `sha256`） |
| 正文历史版本 | `chapters/.versions/NNN/*.md`（每章最近 20 份） |
| 审美五项评语 / 导出件 | `ledger/aesthetic.jsonl` / `exports/书名-时间.txt` |
| 提示词模块 | `prompts/*.md`（书目录下同名文件可覆盖） |
| 删书前快照 | `data/deleted/` |

```text
backend/
  app/api/          # FastAPI 路由：books / studio / review / memory / style / extras / settings
  app/core/         # 数据目录、书稿路径、删书与快照
  app/store/        # 文件层 + SQLite 兼容路由（原子写与项目锁）
  app/domain/       # 领域层：writing、review、memory、continuity、quality、metrics、references…
  app/llm/          # OpenAI 兼容客户端、设置、阶段路由
  tests/            # pytest（含 golden 对照，全离线）
frontend/
  src/views/        # 14 个页面
  src/components/   # 写作面板、体检面板、记忆组件、章脉图谱、命令面板…
  src/stores/       # Pinia 状态管理
  src/design/       # light-dark() 主题 token 与组件库
prompts/            # 可复用的中文写作方法模块
```

</details>

<details>
<summary><strong>3. 环境变量</strong></summary>

| 变量 | 作用 |
|---|---|
| `NOVEL_STUDIO_HOME` | 系统数据目录（SQLite / `gateway.json` / `recent.json`），默认 `<仓库>/data` |
| `DSH_NOVEL_HOME` | 书目根目录，默认 `~/Desktop/mine/xiaoshuo` |
| `DSH_NOVEL_ALLOWED_ROOTS` | 额外允许新建项目的位置（`:` 分隔） |
| `DSH_NOVEL_DB` | 覆盖 SQLite 文件路径 |
| `DSH_NOVEL_RECENT_FILE` | 覆盖最近打开列表文件 |
| `DSH_NOVEL_AUTO_MEMORY` | 设为 `0` 关闭正文落盘后的自动记忆回写 |
| `NOVEL_STUDIO_SNAPSHOT_DIR` | 整本删除前的快照目录，默认 `<数据目录>/deleted` |
| `NOVEL_STUDIO_REASONING` | 按阶段覆盖思考强度，JSON（如 `'{"prose":"high"}'`） |

</details>

<details>
<summary><strong>4. 键盘快捷键</strong></summary>

- `⌘K` / `Ctrl K` 或 `/`：打开命令面板，搜页面、章节、人物、伏笔与动作
- `W`：打开开写面板 · `T`：切换浅色/深色主题 · `?`：查看全部快捷键
- `G` 后按 `H/P/X/O/D/F/M/W/C/G/S/,`：快速跳转页面（第二个 `G` 为「组织」）
- 进度页：`J/K` 切章、`Space` 勾选、`↵` 展开/存档、`R` 退回、`B` 按批体检

</details>

---

## 📄 开源许可

本项目基于 [AGPL-3.0](LICENSE) 开源。你可以自由使用、修改和分发；如果将修改后的版本作为网络服务对外提供，请按同一许可公开源代码。

如果这个工作台对你的长篇创作或 AI 写作工程有帮助，欢迎点一个 ⭐ **Star** 支持！
