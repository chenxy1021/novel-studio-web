# Novel Studio · 网页版

小说创作工作台，从 DSH 插件 `novel-studio` 独立出来：Vue 3 + Vite 前端，FastAPI 后端，书稿仍用原来那套磁盘格式。

## 起服务

```bash
cd dsh/novel-web
./scripts/dev.sh          # 或 make dev
```

- Web：http://127.0.0.1:5180
- API：http://127.0.0.1:8010/api/ping
- 端口写死：8010 / 5180（8000 / 5173 给别的项目用）。Vite 把 `/api` 代理到 8010。

只跑一边：

```bash
make api     # 后端
make web     # 前端
make test    # backend pytest + 前端 store 自测（make test-store 只跑前端）
```

状态归 store 管：localStorage 的 `ns.archived` 记账「已处理过的章」——自动存档和手动退回都记一笔，
所以退回某章后再进进度页，它会停在「待确认」而不是被自动存回去。key 缺失、坏 JSON、localStorage 被禁用都不影响页面可用。

## 目录

```
backend/
  pyproject.toml          # uv 管理，python >= 3.11
  app/main.py             # FastAPI，CORS 放行 5180
  app/api/                # ping / projects
  app/core/paths.py       # 书稿目录解析（书根、书目、最近打开）
  app/store/              # 文件层：project.json、chapters、ledger、锁、原子写
  app/store/README.md     # store 接口签名（领域逻辑照着接）
  app/domain/             # 领域逻辑（门控 / 体检 / 估算）由迁移方提供
  tests/
frontend/
  src/design/             # tokens.css + 组件库（Button/Card/Tag/Modal/Input/Table/EmptyState）
  src/views/              # 10 个页签
  src/mocks/              # 假数据（接真 API 的唯一替换点）
  src/stores/studio.ts    # 当前书、章节、体检结果、toast
  src/stores/studio.test.ts  # store 自测：自动存档 / 退回 / 跨刷新 / 坏 localStorage
  vitest.config.ts        # 复用 vite 配置（@ 别名），node 环境
```

## 书稿在哪

默认根目录 `~/Desktop/mine/xiaoshuo`，可用环境变量覆盖：

| 变量 | 作用 |
|---|---|
| `DSH_NOVEL_HOME` | 书目根目录 |
| `DSH_NOVEL_ALLOWED_ROOTS` | 额外允许新建项目的位置（`:` 分隔） |
| `DSH_NOVEL_RECENT_FILE` | 最近打开列表文件 |

现有两本书 `最后一座信号塔`（10 章）和 `猎场第一百层` 直接可读，不转换、不重写格式。

## 页面

概览 / 大纲 / 世界观 / 人物 / 设定 / 伏笔 / 细纲 / 进度 / 废章 / 设置。内容来自 `frontend/src/mocks/`，所有交互（存档、退回、按批体检、段落纲展开、伏笔落账…）在假数据上可点可用。设置页的模型配置已经接真 API。

## 迁移进度

领域层从 `novel-studio/lib/*.js` 逐模块移植到 `backend/app/domain/`，每个模块都有 golden 测试对着 JS 原版逐字段比对
（`scripts/gen_*_golden.mjs` 用原版生成、`backend/tests/fixtures/` 存档）。

| 模块 | 状态 | 校验范围 |
|---|---|---|
| `metrics.py` | ✅ 已接 | 182 个真实章节文件的字数/token/文风/AI 痕迹/体检结论 |
| `segment.py` | ✅ 已接 | 10 章段落纲：规划、落盘、重叠拒绝、删除（含错误文案） |
| `memory.py` | ✅ 已接 | 卷索引、章记忆、卷记忆、人物状态、关系表、关键词回查、技能路由、预算分配 |
| `text.py` | ✅ 已接 | 人名/别名/身份描述、硬规则、场景切分、地点轨迹 |
| `platforms.py` | ✅ 已接 | 平台字数区间与格式校验 |
| `npartner.py` | ✅ 已接 | novel-partner 文本体检桥（复读/POV/套话/别名） |
| 门控 · 大纲 · 伏笔账 | ⏳ 待搬 | — |
| 章节提交 · 存档 · 退回 | ⏳ 待搬 | — |
| 上下文包 · 连续性体检 · 按批体检 | ⏳ 待搬 | — |

```bash
make test        # 现在这里是验收门槛
```

## 生成模型

写作走 OpenAI 兼容接口，配置存在 `~/.dsh/novel-studio/gateway.json`（用户级，不写进书稿目录）。
设置页可直接改 Base URL / 正文模型 / 轻活模型，「测试连接」会请求 `{baseUrl}/models` 并列出可用模型。

| 接口 | 作用 |
|---|---|
| `GET /api/settings` | 读当前配置（不含 apiKey 明文） |
| `PUT /api/settings` | 写配置，`baseUrl` 必须是 `http(s)://` |
| `POST /api/settings/probe` | 拿页面上的值先探一次，不保存 |
