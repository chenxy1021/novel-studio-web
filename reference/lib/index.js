// dsh-novel-studio —— DSH 小说创作 Agent 插件（cordis plugin）
// 只注册确定性工具 + 1 段系统提示 + 2 个自带技能（另从 ~/.dsh/skills 接入外部技能）。
import { readFile, readdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  approveChapter, bibleQuery, bibleUpsert, buildContext, changeDirection, commitChapter,
  continuityCheck, checkBatch, discardChapter, dismissedStats, exportChapters, gateState, getOutline, guardGate, initProject,
  listForeshadow, loadIndex, loadProject, MAX_REWRITE_ROUNDS, payoffForeshadow, plantForeshadow, proposeConcepts,
  readChapter, repairProject, requestRewrite, rescheduleForeshadow, saveProject, selectConcept, setOutline, acceptOutline,
  usageSummary,
} from "./domain.js";
import { DEFAULT_PROJECTS_DIR, assertWritableRoot } from "./io.js";
import { chapterFromSegment, deleteSegment, getSegment, listSegments, planSegment, segmentText, writeSegmentOutline } from "./segment.js";
import { mount as mountApi } from "./api.js";
import { loadMemoryRows, loadVolumes, recallMemory } from "./memory.js";
import { createHandler, distillMemory, generateOutlines, setTone, syncSettingFromChapterViaAI } from "./api.js";

export const name = "dsh-novel-studio";
export const inject = ["tools", "systemPrompt", "skills"];

const HERE = path.dirname(fileURLToPath(import.meta.url));

// 插件根 ctx：工具里要用模型（通过即精炼记忆）时从这里取 llm。
let pluginCtx = null;
const SKILLS_DIR = path.join(HERE, "..", "skills");

// 硬规则压缩：domain.js 里每条规则拼成「- name：text（判定者…；代价…）」，而 text 常以「能：<name>；不能：…；代价：…」开头，
// 名字与「能：」重复、judge/cost 与 text 内嵌的「代价：」重复。这里在注入上下文前逐条收敛，只去重复表述，不改语义。
function squeezeRules(text) {
  return String(text || "").split("\n").map((line) => {
    if (!line.startsWith("- ")) return line;
    // 「名：能：名；不能：…」→「名：能；不能：…」：去掉重复的名字本身，保留「能」这个词
    let out = line.replace(/^- ([^：]{2,80})：能：\1(?=[；，,])/u, "- $1：能");
    // 尾巴里重复的「；代价：X」在 text 已有「代价：X」时只留一份
    const tail = /（[^（）]*）$/u.exec(out)?.[0] || "";
    if (tail) {
      const inner = out.slice(0, out.length - tail.length);
      const costM = /代价：([^；）]+)/u.exec(tail);
      if (costM && inner.includes(`代价：${costM[1]}`)) {
        out = inner + tail.replace(/；?代价：[^；）]+/u, "");
      }
    }
    return out;
  }).join("\n");
}

// 段落纲的人读格式：plan / get 共用，避免把整份 JSON 甩给模型。
function segmentPlanText(seg) {
  const plan = seg?.plan || seg?.segment || seg || {};
  const from = seg?.from ?? plan.from;
  const to = seg?.to ?? plan.to;
  const lines = [`第${from}-${to}章 段落纲（${(plan.stages || []).length} 个台阶）`, `整段因果：${plan.spine || "—"}`];
  (plan.stages || []).forEach((s, i) => {
    const fs = s.foreshadow || {};
    lines.push(`\n台阶${i + 1}（第${(s.chapters || []).join("、")}章）｜节奏：${s.pace || "—"}`);
    lines.push(`- 目标：${s.goal || "—"}`);
    lines.push(`- 转折：${s.turn || "—"}`);
    if ((fs.plant || []).length) lines.push(`- 本台阶埋：${fs.plant.join("、")}`);
    if ((fs.payoff || []).length) lines.push(`- 本台阶收：${fs.payoff.join("、")}`);
    if ((s.places || []).length) lines.push(`- 预计现场：${s.places.join("、")}`);
  });
  return lines.join("\n");
}

const textOut = (fn) => ({
  schema: { type: "object", additionalProperties: true, properties: { text: { type: "string" } } },
  render: (_args, value) => [{ type: "text", text: String(value?.text ?? "") }],
});

async function resolveRoot(ctx, args = {}, { creating = false } = {}) {
  const root = args.project_dir || ctx?.config?.projectRoot || DEFAULT_PROJECTS_DIR;
  if (!path.isAbsolute(root)) throw new Error(`project_dir 必须是绝对路径：${root}`);
  // 写权限闸：新建项目只能落在允许的根目录内；已有项目允许原地读写；系统目录一律拒绝。
  return await assertWritableRoot(root, { creating, extraRoots: ctx?.config?.projectRoot ? [ctx.config.projectRoot] : [] });
}

// 会话里没有面板的 HTTP 上下文，直接借面板同一个处理函数落盘（不走网络）
async function sessionReturn(root, body) {
  const handler = createHandler({});
  const payload = Buffer.from(JSON.stringify({ ...body, dir: root }));
  // 只实现 readBody 用到的那条事件流：先 data 再 end
  const req = { method: "POST", url: "/novel/api/outline", on: (ev, fn) => { if (ev === "data") fn(payload); else if (ev === "end") fn(); return req; }, destroy() {} };
  let out = null;
  const res = { writeHead() { return res; }, setHeader() {}, end(t) { try { out = JSON.parse(String(t)); } catch { out = null; } } };
  await handler(req, res);
  if (!out || out.ok === false) throw new Error(out?.error || "交回面板失败");
  return out;
}

const PROMPT = `## 小说创作工作流（novel-studio）

你是小说创作 Agent，不是通用助手。门控由代码强制，被拒时按错误提示补做，不要绕过。

0. **守门控**：concept→bible→outline→writing(N)→awaiting_review(N)。没选题不许排大纲/提交；**硬规则至少 1 条，写第 1 章前校验**；提交的章必须落在已有段落纲（\`novel_segment\`）覆盖的区间里，或已有该章逐章细纲；**上一章没 approve 不许写下一章（批内除外）**。
1. **先读状态**：任何写作动作前先 \`novel_status\`；不知道写了几章、哪些伏笔开着、gate 在哪，就别动笔。
2. **开书顺序（按此执行）**：\`novel_init\` → \`novel_concept\` propose（一次给 3-5 个差异化候选）→ 等作者选 → \`novel_concept\` select → \`novel_outline\` 先出全书大纲（**先大纲，后设定**）→ 给作者过目 → 作者确认后 \`novel_outline\` op=accept（gate 进 bible）→ \`novel_bible\` 补全书设定 → \`novel_segment\` op=plan from=1 to=10 排第一段段落纲 → 再批量写第 1-10 章（见下节）。
3. **设定即权威**：人物/地点/规则/势力/物品只经 \`novel_bible\` 写入并以此为准；与记忆冲突时信设定。
每章正文硬下限 1800 字（全书 ≤50 章的短篇项目不限；长篇 commit 会直接拒收，这不是建议）：按台阶写足戏，场景/对话/动作都要落地，不要把一拍的戏一笔带过。
4. **写前取包**：每次写正文前必须 \`novel_context\`（章号），按里面的段落纲台阶（老书是逐章细纲节拍）、可用角色、未回收伏笔、必埋伏笔、上一章收尾状态写，不要凭记忆续写。
   - **没段落纲时**先 \`novel_segment\` op=plan（10 章一段）；只有作者明确要逐章细纲时才用 \`novel_outline\` op=generate（唯一生成路径），**不要手写 beats**（字段不全，\`op=set\` 只给作者手改）。
   - **登场章是硬约定**：人物卡 \`firstChapter\` 等于本章的人必须真出场；\`mustAvoid\` 只写信息/桥段/能力，不能写「某人不得出场」。
   - **前情只取该取的**：查更早细节用 \`novel_memory\` op=recall query=关键词（带章号命中），要原句再 \`novel_chapter\` op=read；**不要翻 exports/ 或 grep chapters/**；卷地图用 op=volumes。
   - **会话交回只交改过的正文**：真改了大纲/世界观的会话用 \`novel_studio_session\` op=return 交回**完整**正文（不是摘要）；伏笔网只传 source，**绝不传 outlineText/worldText**；字数腰斩会被拒。
5. **写后提交**：\`novel_chapter\` commit（长篇每章 ≥1800 字，短篇项目不限；number/title/text/summary/characters 均为必填，summary 空、characters 少于 1 人会直接报错；inWorldDay 用于时间线）。返回字数/对话比/平台格式/AI 痕迹/禁用词。**needs_fix（AI 痕迹判「差」/命中禁用词/硬规则冲突）的稿不进正文、不占章号，自动退回 drafts/**——改完再 commit，确实要收才加 \`force:true\`。
6. **提交即体检**：commit 返回里已带本章体检；跨章问题跑 \`novel_continuity\`，high 级先修。
7. **停在待确认**：逐章模式提交后 gate 变 awaiting_review(N)，**不要自己写下一章**；批量模式批内可继续写同一批（见下节）。报给作者等三个决定：\`novel_gate\` approve N（needs_fix 需 force:true）/ rewrite N（退回 drafts、章号释放）/ direction（仅后续章生效）。
8. **AI 痕迹判「差」= high≥2 或密度 > 2.5/千字**，按 novel-continuity 清单重写命中段落，不整章重来。重写走 \`novel_gate\` rewrite，不直接 commit 覆盖。**自动重写最多 2 轮**，仍不合格就停下让作者 approve（force）或 direction 决定。
9. **不替作者做决定**：选题/过不过/方向由作者拍板，你只把决定落成段落纲与正文。

## 批量写作（10 章一段）

一次写 10 章时走批次模式，不再逐章排细纲：

1. \`novel_segment\` op=plan from=1 to=10 出一份段落纲（3-5 个台阶，每台阶写目标/转折/本台阶埋收的伏笔/预计现场）；给作者过目。
2. 作者确认后 \`novel_segment\` op=write from=1 to=10 落账。
3. 从第 1 章起逐章 \`novel_context\`（包里的细纲节拍会换成整段段落纲 + 本章所在台阶）→ 写 → \`novel_chapter\` commit，**每章都带 \`batch:true\`**。批内不需要逐章 approve，也不许跳过中间章。
4. 写到本批最后一章，gate 停在 awaiting_review；作者一次 review 后 \`novel_gate\` approve（批内任一章 needs_fix 仍要 force:true）。approve 之后设定是一次补整批（工具会按 numbers 补），不要再一章一章补。批次里逐章「补设定」按钮也是补整批。批尾 review 先 novel_continuity scope=batch 一次看整批，只对 action=rewrite 的章按章 novel_gate rewrite。
5. 写完这一批再规划下一批（第 11 章起重新 op=plan）；两批不能重叠。

批次只解决「一次审一整段」的流程问题：每章仍按本台阶的目标→转折推进，不要把整批写成流水账。

## 四处 AI 生成的素材

- **大纲**：素材 = 故事梗概，只出全书层 + 卷层结构，不写规则/人物/势力。
- **世界观**：素材 = 已生成的大纲，只出叙事（基底/历史/地理/体系/恩怨/日常）。
- **设定账本**：scope=setup 拆势力/地点/物品/硬规则/文风（素材 = 大纲 + 世界观），scope=characters 只拆人物；是唯一写入口。**硬规则只收世界级、跨章有效、破了世界就不成立的；一次性约束进段落纲/细纲的 mustAvoid——硬规则每章全量注入，写多了挤掉前情记忆。**
- **伏笔**：素材 = 规则编号 + 卷划分；每条必须带全 kind/source/plantBeat/revealWho/revealChange/hint。
- **批次段落纲**（默认）：10 章一段、3-5 个台阶，每台阶写目标/转折/埋收伏笔/预计现场；写正文时按本章所在台阶推进。
- **逐章细纲**（只有作者要时才排）：本章在大纲中的位置 + 相关设定 + 上一章结尾 + 要埋/收的伏笔 + 必须登场角色。

**正文不再塞提示词**：只走 novel_context → 写 → commit；**体检/导出直接调工具**。提示词末尾的「自检」保留，输出过长靠「控制在 X 字以内」生效。

## 技能：6 个默认常驻 + 其余按下表按需加载

常驻（自动可见）：**novel-studio**（总流程与门控）、**novel-continuity**（写完就调：体检/去 AI 味/改节奏）、**story-long-write**（长篇节奏与结构）、**novel-creator**（世界观/角色心理）、**story-deslop**（成段重写去味）、**first-reader**（发布前模拟试读）。其余技能不在常驻里，**按需加载、一次只加载这一步要用的**：

| 你正在做的事 | 加载 | 它负责 |
|---|---|---|
| 拆卷纲、排段落纲 | \`story-long-write\` | 卷/章结构、每拍的目标-阻碍-变化 |
| 生成选题 | \`story-long-scan\` / \`story-short-scan\` | 平台趋势、题材与开篇钩子 |
| 审查一章/一卷 | \`story-review\` | 多视角挑刺 |
| 只想处理这一章（写/看/改/判） | \`novel-partner\` | 单章方法：场景卡写正文、只报风险、最小改动、读者视角 |
| 要作者视角点评 | \`maoni-perspective\` / \`fenghuo-perspective\` / \`yuhua-perspective\` | 只点评，不代笔 |
| 拆对标书 | \`story-long-analyze\` / \`story-short-analyze\` | 黄金三章、结构、节奏 |
| 导入旧书 | \`story-import\` | 反向解析成项目目录 |
| 做封面 / 环境自检 | \`story-cover\` / \`story-setup\` | 封面、技能可用性 |
| 查资料/读链接 | \`agent-reach\`（只读） | 网页搜索兜底 |

用法原则：**技法借技能，事实凭账本**。冲突时以账本（novel_* 的返回）为准。

工具是账本的唯一写入口。不要用 bash 直接改 bible.json / ledger 下的文件。`;

/* ------------------------------ 工具定义 ------------------------------ */

function toolDefs() {
  return [
    {
      name: "novel_init",
      description: "初始化一部小说项目：建目录骨架、project.json、空设定集与三本账。已存在则报错。开书第一步。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string", description: "项目绝对路径" },
          title: { type: "string" },
          genre: { type: "string", description: "题材，如 仙侠/悬疑/都市异能" },
          platform: { type: "string", description: "目标平台，如 起点/番茄/晋江" },
          logline: { type: "string", description: "一句话故事核" },
          target_chapters: { type: "number", default: 120 },
          words_per_chapter: { type: "number", default: 3000 },
        },
        required: ["project_dir", "title"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args, { creating: true });
        const project = await initProject(root, {
          title: args.title, genre: args.genre, platform: args.platform, logline: args.logline,
          targetChapters: args.target_chapters, wordsPerChapter: args.words_per_chapter,
        });
        return { text: `已初始化《${project.title}》\n目录：${root}\n目标：${project.targetChapters} 章 × ${project.wordsPerChapter} 字\n下一步：novel_concept propose 出 3-5 个选题候选 → 作者选定 → novel_outline 先出大纲（先大纲、后设定）。` };
      },
    },
    {
      name: "novel_status",
      description: "查看项目状态：章节进度、字数偏差、伏笔开收、AI 痕迹概览、下一步该做什么。任何写作动作前先调它。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: { project_dir: { type: "string" } },
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        const project = await loadProject(root);
        if (!project) throw new Error(`不是小说项目：${root}`);
        const index = await loadIndex(root);
        const totalChars = index.reduce((a, c) => a + (c.chars || 0), 0);
        const fsState = await listForeshadow(root, project.currentChapter || 1);
        const bad = index.filter((c) => c.verdict === "差");
        const usage = await usageSummary(root);
        const dismissed = await dismissedStats(root);
        const lines = [
          `《${project.title}》 ${project.genre} · ${project.platform}`,
          `进度：${index.length}/${project.targetChapters} 章，${totalChars} 字，当前第 ${project.currentChapter} 章`,
          index.length ? `最近：第${index[index.length - 1].number}章 ${index[index.length - 1].title}（${index[index.length - 1].chars}字，${index[index.length - 1].verdict}）` : "还没有正文",
          `伏笔：开 ${fsState.open.length} 条（超期 ${fsState.open.filter((f) => f.overdue).length}），已收 ${fsState.paid.length} 条`,
          `AI 痕迹不合格章节：${bad.length ? bad.map((c) => `第${c.number}章`).join("、") : "无"}`,
          `大纲门：${project.gates?.outline ? "已确认" : "未确认"}；设定门：${project.gates?.bible ? "已建" : "未建"}`,
          `上下文用量：本章 ≈${usage.contextTokensLast} tokens（${usage.contextCalls} 次组装，章均 ≈${usage.contextTokensPerChapter}）｜正文累计 ≈${usage.outputTokensTotal} tokens`,
          dismissed.total ? `作者标记为合理的体检：${dismissed.total} 条（${Object.entries(dismissed.byCode).map(([k, v]) => `${k}×${v}`).join("、")}）` : "",
        ].filter(Boolean);
        const next = !index.length
          ? "下一步：novel_outline 先出全书大纲 → novel_outline op=accept → novel_bible 补设定（写第1章前要 ≥1 条硬规则）→ novel_segment op=plan from=1 to=10 → 逐章 novel_context 写并 commit batch:true"
          : fsState.open.some((f) => f.overdue)
            ? "下一步：先回收超期伏笔，再开新线"
            : `下一步：novel_segment op=plan from=${project.currentChapter + 1} to=${project.currentChapter + 10}（若还没有覆盖这批的段落纲）→ novel_context ${project.currentChapter + 1} → 写正文（commit 带 batch:true）`;
        return { text: lines.join("\n") + `\n\n${next}` };
      },
    },
    {
      name: "novel_bible",
      description: [
        "设定集读写：op=upsert 写入实体（以 name 或 id 认人，重复写入会合并补字段），op=list/get 读取，给 query 做全文检索。",
        "entity 与最小字段：character=name/want/fear/flaw/voice/aliases/firstChapter（可选 rolePosition、importance、secret、ability/abilityLimit/abilityCost、status）；rule=name/text/judge/cost/boundary/forbiddenKeywords；world=name/text；faction=name/hiddenRules/attitude；location=name/geo/accessRules/occupied；item=name/holder/state/whoKnows；style=samples/banned/pov/tense。",
        "importance：核心=主角与核心 3–5 人，主要=常驻配角，次要=单卷功能角色，龙套=只登记名字。不要用它存一次性人物或本章临时道具；与记忆冲突时以本工具写入的为准。",
      ].join(" "),
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["get", "list", "upsert"], default: "list" },
          entity: { type: "string", enum: ["character", "world", "rule", "style", "faction", "location", "item"] },
          query: { type: "string" },
          data: { type: "object", description: "upsert 时的实体数据；style 支持 {samples,banned,pov,tense}" },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (args.op === "upsert") {
          if (!args.entity || !args.data) throw new Error("upsert 需要 entity 与 data");
          const r = await bibleUpsert(root, args.entity, args.data);
          // 回显「实际写进去的字段」与「没认出来的字段」：后者多半是拼错或该实体不支持，免得模型以为已落账
          const KNOWN = {
            character: ["name", "id", "rolePosition", "role", "importance", "tier", "aliases", "callRules", "age", "gender", "race", "appearance", "personality", "want", "fear", "bottomLine", "flaw", "secret", "voice", "ability", "abilityLimit", "abilityCost", "status", "location", "locationTrail", "currentGoal", "knowledge", "ignorance", "misconception", "changeLog", "firstChapter", "exitChapter", "note"],
            rule: ["name", "id", "text", "judge", "cost", "boundary", "belief", "forbiddenKeywords", "trigger", "keywords", "note"],
            world: ["name", "id", "text", "note"],
            faction: ["name", "id", "hiddenRules", "misjudge", "attitude", "note"],
            location: ["name", "id", "geo", "accessRules", "occupied", "state", "note"],
            item: ["name", "id", "holder", "state", "whoKnows", "note"],
            style: ["samples", "banned", "bannedPatterns", "pov", "tense", "preset"],
          };
          const dataKeys = Object.keys(args.data || {}).filter((k) => args.data[k] !== undefined && args.data[k] !== "");
          const allowed = KNOWN[r.entity];
          if (!allowed) return { text: `已写入 ${r.entity} ${r.id}（${r.existed ? "更新" : "新增"}）；已写字段：${dataKeys.join("、") || "（无）"}` };
          const wrote = dataKeys.filter((k) => allowed.includes(k));
          const ignored = dataKeys.filter((k) => !allowed.includes(k));
          return {
            text: [
              `已写入 ${r.entity} ${r.id}（${r.existed ? "更新" : "新增"}）`,
              `已写字段：${wrote.join("、") || "（无）"}`,
              ignored.length ? `未识别字段：${ignored.join("、")}——这些字段没落账，检查拼写或改用 ${r.entity} 支持的字段` : "",
            ].filter(Boolean).join("\n"),
          };
        }
        const res = await bibleQuery(root, { query: args.query, entity: args.entity });
        const dump = Object.entries(res).map(([k, v]) => {
          if (k === "style") return `## style\n${JSON.stringify(v, null, 2)}`;
          const arr = Array.isArray(v) ? v : [];
          const skip = new Set(["id", "createdAt", "updatedAt"]);
          return `## ${k}（${arr.length}）\n` + arr.map((x) => {
            const bits = Object.entries(x)
              .filter(([f, val]) => !skip.has(f) && val !== undefined && val !== null && val !== "" && !(Array.isArray(val) && !val.length))
              .map(([f, val]) => `${f}:${Array.isArray(val) ? val.join("、") : val}`);
            return `- ${bits.join("｜") || x.name || x.id}`;
          }).join("\n");
        });
        return { text: dump.join("\n\n") || "（空）" };
      },
    },
    {
      name: "novel_foreshadow",
      description: [
        "伏笔账本：op=plant 埋（name/planted_chapter/due_chapter + 详情 kind/source/plant_beat/reveal_who/reveal_change/hint/abandon），op=payoff 收（name/payoff_chapter），op=reschedule 改期（name/due_chapter），op=list 按紧迫度列出。",
        "伏笔页的「谁揭/揭开后/中途提示/来源」全靠这些详情字段，缺了那几列就是空的——plant 时一并给全。",
        "不要在正文里凭空埋一条不登记；改名/改章号用 reschedule，不要另 plant 一条重复的。",
      ].join(" "),
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["plant", "payoff", "reschedule", "list"], default: "list" },
          name: { type: "string" },
          planted_chapter: { type: "number" },
          due_chapter: { type: "number" },
          payoff_chapter: { type: "number" },
          kind: { type: "string", enum: ["main", "volume", "detail"], description: "主线（贯穿全书）/卷内/细节" },
          source: { type: "string", description: "这条伏笔从哪来：哪条硬规则、哪个人物的秘密、哪个卷事件" },
          plant_beat: { type: "string", description: "埋在哪些拍/怎么顺带一提" },
          reveal_who: { type: "string", description: "谁来揭" },
          reveal_change: { type: "string", description: "揭开后改变了什么" },
          hint: { type: "string", description: "中途怎么提示（后面章节可以带一句）" },
          abandon: { type: "string", description: "万一收不回来怎么退场" },
          note: { type: "string", description: "备注" },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (args.op === "plant") {
          const r = await plantForeshadow(root, {
            name: args.name, plantedChapter: args.planted_chapter, dueChapter: args.due_chapter, note: args.note,
            kind: args.kind, source: args.source, plantBeat: args.plant_beat,
            revealWho: args.reveal_who, revealChange: args.reveal_change, hint: args.hint, abandon: args.abandon,
          });
          const missing = [
            ["source", args.source], ["plant_beat", args.plant_beat],
            ["reveal_who", args.reveal_who], ["reveal_change", args.reveal_change], ["hint", args.hint],
          ].filter(([, v]) => !String(v || "").trim()).map(([k]) => k);
          const warn = missing.length ? `\n⚠ 缺详情字段：${missing.join("、")}——伏笔页那几列会是空的。重新 plant 同名条目补全（会覆盖），或直接用这几个参数补。` : "";
          return { text: `已埋「${r.name}」（${r.id}）${args.due_chapter ? `，计划第${args.due_chapter}章回收` : "，未定回收章"}${warn}` };
        }
        if (args.op === "payoff") {
          const r = await payoffForeshadow(root, { name: args.name, chapter: args.payoff_chapter, note: args.note });
          return { text: `已回收「${r.name}」：第${r.plantedChapter}章埋 → 第${r.payoffChapter ?? "?"}章收，跨度 ${r.payoffChapter ? r.payoffChapter - r.plantedChapter : "?"} 章` };
        }
        if (args.op === "reschedule") {
          const r = await rescheduleForeshadow(root, { name: args.name, dueChapter: args.due_chapter, note: args.note });
          return { text: `伏笔「${r.name}」已改期到第${r.dueChapter}章回收` };
        }
        const project = await loadProject(root);
        const s = await listForeshadow(root, project?.currentChapter || 1);
        const line = (f) => `- ${f.overdue ? "⚠" : "·"} ${f.name}（第${f.plantedChapter}章埋${f.dueChapter ? `，限第${f.dueChapter}章` : ""}${f.overdue ? "，已超期" : ""}${f.note ? "：" + f.note : ""}）`;
        return { text: `未回收 ${s.open.length} 条：\n${s.open.map(line).join("\n") || "（无）"}\n\n已收 ${s.paid.length} 条。` };
      },
    },
    {
      name: "novel_outline",
      description: [
        "大纲与逐章细纲：op=accept 作者确认全书大纲（gate 进 bible，之后补设定再开写）；op=get 读某一章细纲；op=generate 生成某一章细纲（唯一生成路径，不要自己手写 beats）；op=set 只给作者手改。",
        "默认批量写 10 章一段，用 novel_segment 排段落纲，不需要逐章细纲；只有作者明确要逐章细纲时才 generate。",
        "tone=contrast 只在作者要「反差大/意难平」时传：大纲会加反命题表。",
      ].join(" "),
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["generate", "set", "get", "accept"], default: "get" },
          chapter: { type: "number" },
          beats: { type: "array", items: { type: "string" } },
          must_include: { type: "array", items: { type: "string" } },
          must_avoid: { type: "array", items: { type: "string" } },
          tone: { type: "string", enum: ["contrast"], description: "作者要求「反差大/意难平」时传 contrast：大纲会加反命题表，每个核心角色结局被拧到反面，每卷写清拿走了谁的什么。不要求就别传" },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (args.op === "accept") {
          const r = await acceptOutline(root);
          return { text: `大纲已确认（gate → ${r.gate.phase}）。接下来：novel_bible 补全书设定（写第 1 章前要 ≥1 条硬规则）→ novel_segment op=plan from=1 to=10 排第一段段落纲 → 逐章 novel_context 写、commit 带 batch:true。` };
        }
        if (args.op === "generate") {
          if (!args.chapter) throw new Error("op=generate 需要 chapter（生成哪一章的细纲）");
          const r = await generateOutlines(pluginCtx, { dir: root, after: Number(args.chapter) - 1, count: 1 });
          if (args.tone === "contrast") setTone(root, "contrast");
          const one = (r.outlines || [])[0] || {};
          const warn = [
            one.truncated && one.ok
              ? `输出被截断：${(one.beats || []).length} 拍已落账，Markdown 细纲可能不完整（可调大环境变量 DSH_NOVEL_OUTLINE_TOKENS 后重新生成）`
              : "",
            one.motivationWarning,
            r.partial ? r.error : "",
          ].filter(Boolean).join("；");
          const used = r.model ? `，模型 ${r.provider || ""}/${r.model}` : "";
          return { text: one.ok
            ? `第${one.chapter}章细纲已生成（${(one.beats || []).length} 拍${one.title ? `《${one.title}》` : ""}${used}）。${warn}`
            : `第${args.chapter}章细纲没生成出来${warn ? `：${warn}` : "，换个模型或稍后再试"}。` };
        }
        if (args.op === "set") {
          const r = await setOutline(root, { chapter: args.chapter, beats: args.beats, mustInclude: args.must_include, mustAvoid: args.must_avoid });
          const project = await loadProject(root);
          if (project) { project.gates.outline = true; await saveProject(root, project); }
          return { text: `第${r.chapter}章细纲已存（${r.beats} 拍）。给作者过目，确认后用 novel_outline op=accept 进入补设定阶段。` };
        }
        const o = await import("./domain.js").then((m) => m.getOutline(root, args.chapter));
        return { text: o ? JSON.stringify(o, null, 2) : `第${args.chapter}章没有逐章细纲（批量模式正常）。直接 novel_context ${args.chapter}，按段落纲里本章所在的台阶写；只有作者要逐章细纲时才 novel_outline op=generate chapter=${args.chapter}。` };
      },
    },
    {
      name: "novel_segment",
      description: [
        "批次段落纲（批量写作 10 章一段的入口）：op=plan 按 from/to 规划 3-5 个台阶（每台阶含目标、转折、本台阶埋/收的伏笔、预计现场），只预览不落账；op=write 确认后落账到 ledger/segments.jsonl；op=get 读批次（from 给章号时返回该章所属段落纲与批内已写摘要）；op=delete 删掉还没开写的某段（已有正文的批次不能删，先作废那些章再重排）。",
        "一份段落纲覆盖连续 1-30 章，两批不能重叠；落账后批内各章 commit 时带 batch:true，不再需要逐章细纲与逐章 approve。",
      ].join(" "),
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["plan", "write", "get", "delete"], default: "get" },
          from: { type: "number", description: "起始章号；plan/write 必填" },
          to: { type: "number", description: "结束章号；不给默认 from+9（10 章一段）" },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (!(await loadProject(root))) throw new Error(`不是小说项目：${root}`);
        const from = Number(args.from);
        if (args.op === "get") {
          if (from && args.to !== undefined && args.to !== null && args.to !== "") {
            const seg = await getSegment(root, { from, to: Number(args.to) });
            return { text: seg ? segmentPlanText(seg) : `没有第${from}-${args.to}章的段落纲。` };
          }
          if (from) {
            const info = await chapterFromSegment(root, from);
            return { text: info ? info.text : `第${from}章不在任何批次段落纲里（老模式按逐章细纲写）。` };
          }
          const rows = await listSegments(root);
          return { text: rows.length
            ? rows.map((s) => `第${s.from}-${s.to}章｜${s.stages} 个台阶｜${s.at || ""}\n  ${s.spine || ""}`).join("\n")
            : "还没有批次段落纲。→ novel_segment op=plan from=1 to=10" };
        }
        if (!from) throw new Error(`op=${args.op} 需要 from（起始章号，≥1）`);
        if (args.op === "delete") {
          const r = await deleteSegment(root, { from, to: args.to === undefined || args.to === null || args.to === "" ? from + 9 : args.to });
          return { text: `已删掉第${r.from}-${r.to}章的段落纲。→ 需要这一段就重新 novel_segment op=plan from=${r.from} to=${r.to}` };
        }
        const plan = await planSegment(root, { from, to: args.to });
        if (args.op === "plan") {
          return { text: `${segmentPlanText(plan)}\n\n确认无误后 novel_segment op=write from=${plan.from} to=${plan.to} 落账。` };
        }
        const r = await writeSegmentOutline(root, plan);
        return { text: `已落账：第${r.from}-${r.to}章段落纲（${r.stages} 个台阶）→ ledger/segments.jsonl\n下一步：从第${r.from}章起 novel_context → 写 → novel_chapter commit（每章带 batch:true）。` };
      },
    },
    {
      name: "novel_context",
      description: [
        "组装本章写作上下文包（本批段落纲与本章所在台阶 + 出场角色卡 + 未回收伏笔 + 硬规则 + 禁用表达 + 上一章结尾 + 文风样本；老书带逐章细纲节拍），写正文前必调；返回首部的元信息会写明预算、实际字数与被裁掉的段。",
        "必填 chapter；budget_chars 一般不用传（按目标字数自动算）。只管取包，不改任何账本。",
        "不要用它代替 novel_memory 查旧章细节——包只带本卷切片与近章记忆。",
      ].join(" "),
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          chapter: { type: "number" },
          budget_chars: { type: "number", description: "可选：覆盖自动预算（字符数）；一般不用传" },
        },
        required: ["chapter"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        const pack = await buildContext(root, { chapter: args.chapter, ...(Number(args.budget_chars) > 0 ? { budgetChars: Number(args.budget_chars) } : {}) });
        const packed = { ...pack, text: squeezeRules(pack.text) };
        // 元信息三行：模型据此知道「包没装满 / 哪段被砍」，不必猜记忆够不够
        const cut = [
          pack.dropped?.length ? `必守段被压短：${pack.dropped.join("、")}` : "",
          pack.shortened?.length ? `按预算截断：${pack.shortened.join("、")}` : "",
          pack.skipped?.length ? `预算不足整段略过：${pack.skipped.join("、")}` : "",
        ].filter(Boolean).join("；");
        const meta = [
          `<!-- 上下文包元信息：预算 ${pack.budget} 字｜实际 ${packed.chars} 字｜约 ${Math.ceil(packed.text.length/1.13)} tokens -->`,
          cut ? `<!-- ${cut} -->` : "<!-- 各段均在预算内，没有被截断的段 -->",
        ].join("\n");
        return { text: `${meta}\n${packed.text}` };
      },
    },
    {
      name: "novel_chapter",
      description: [
        "章节读写：op=commit 提交正文（number/title/text/summary/characters 为必填，summary 空或 characters 少于 1 人工具会直接拒绝；in_world_day 用于时间线），返回字数/对话比/节奏/AI 痕迹/禁用词/本章体检。",
        "op=list 列已写章节，op=read 读某章原文，op=discard 作废旧稿（进废章页可恢复，之后可重写同一章号）。",
        "不要用它直接覆盖已通过的章——返工走 novel_gate rewrite；needs_fix 的稿默认退回 drafts/ 不占章号。",
      ].join(" "),
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["commit", "list", "read", "discard"], default: "list" },
          number: { type: "number" },
          title: { type: "string" },
          text: { type: "string", description: "正文全文（commit 时必填）" },
          summary: { type: "string", description: "必填：本章剧情摘要（一两句话），供后续检索、记忆精炼与连续性检查；空值会被拒" },
          characters: { type: "array", items: { type: "string" }, description: "必填：本章出场人物名，至少 1 人；空数组会被拒" },
          in_world_day: { type: "number", description: "故事内第几天（填了才做时间线倒退检查）" },
          reason: { type: "string", description: "discard 时填：为什么作废" },
          force: { type: "boolean", description: "不合格稿（needs_fix）默认退回 drafts/ 不占章号；确实要收进正文才传 true（会标 needs_fix）" },
          batch: { type: "boolean", description: "批量写作模式：本章属于已落账的段落纲时传 true。批内不要求上一章已 approve，提交后 gate 继续指向下一章，整批最后一章写完才停 awaiting_review" },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (args.op === "commit") {
          if (!args.number || !args.text) throw new Error("commit 需要 number 与 text");
          const r = await commitChapter(root, {
            number: args.number, title: args.title, text: args.text, summary: args.summary,
            characters: args.characters, inWorldDay: args.in_world_day, force: Boolean(args.force),
            batch: Boolean(args.batch),
          });
          const t = r.tells.map((x) => `  ${x.severity === "high" ? "✗" : "·"} ${x.label} ×${x.count}（${x.per1000}/千字）${x.samples[0] ? ` 例：${x.samples[0].text}` : ""}`).join("\n");
          // 被退回 drafts：不合格稿不进正文、不占章号
          if (r.rejected) {
            return {
              text: [
                `⚠ 第${r.chapter.number}章未通过，已退回 ${r.draftFile}（章号没有前进，正文里没有这一章）`,
                `原因：${r.reason}`,
                `字数 ${r.metrics.chars}｜AI 痕迹密度 ${r.judge.density}/千字`,
                t ? `痕迹明细：\n${t}` : "痕迹明细：无命中",
                r.bannedHits.length ? `⚠ 禁用词命中：${r.bannedHits.join("、")}` : "禁用词：无",
                `处理：${r.hint}`,
              ].join("\n"),
            };
          }
          return {
            text: [
              `已提交第${r.chapter.number}章《${r.chapter.title}》→ ${r.file}`,
              `字数 ${r.chapter.chars}｜对话比 ${(r.metrics.dialogueRatio * 100).toFixed(0)}%｜段长均值 ${r.metrics.paragraphMean}（bustiness ${r.metrics.paragraphBurstiness}）｜句长均值 ${r.metrics.sentenceMean}（${r.metrics.sentenceBurstiness}）`,
              `判定：${r.judge.level}｜AI 痕迹密度 ${r.judge.density}/千字${r.judge.flatRhythm ? "｜节奏偏平（段落/句长起伏不足）" : ""}`,
              t ? `痕迹明细：\n${t}` : "痕迹明细：无命中",
              r.bannedHits.length ? `⚠ 禁用词命中：${r.bannedHits.join("、")}` : "禁用词：无",
              `章节判定：${r.chapterVerdict === "pass" ? "通过" : `需修（已 force 收稿${r.rewriteRound ? `，第 ${r.rewriteRound}/${MAX_REWRITE_ROUNDS} 轮重写` : ""}）`}`,
              r.platform && !r.platform.pass ? `平台格式问题：${r.platform.issues.map((i) => i.message).join("；")}` : "平台格式：符合",
              (r.chapterCheck && r.chapterCheck.findings && r.chapterCheck.findings.length)
                ? `\n本章体检（提交即查，${r.chapterCheck.counts.high} high / ${r.chapterCheck.counts.mid} mid）：\n` +
                  r.chapterCheck.findings.map((f) => `  ${f.severity === "high" ? "✗" : f.severity === "mid" ? "!" : "·"} [${f.severity}] ${f.message}`).join("\n") +
                  (r.chapterCheck.counts.high > 0 ? "\n⚠ 有硬性问题（high），先修再存档。" : "\n（都是提醒级，可自行取舍；要返工可 novel_gate rewrite。）")
                : "\n本章体检（提交即查）：没发现连续性问题。",
              args.batch
                ? (await chapterFromSegment(root, r.chapter.number))?.to > Number(r.chapter.number)
                  ? (r.chapterVerdict !== "pass"
                      ? `本章判定 needs_fix：直接按上面的 high 修完再 commit 同一章（batch:true）覆盖重写，不要 approve 也不要往下写。\n`
                      : "") + `批内继续：novel_context ${Number(r.chapter.number) + 1} → 写 → commit（batch:true）。本批写到最后一章再统一 review。`
                  : `本批各章已写完，gate 停在 awaiting_review。下一步：novel_gate approve ${r.chapter.number}（批内任一章 needs_fix 时加 force:true）；有 high 先修。`
                : `下一步：如无硬性问题可 novel_gate approve ${r.chapter.number} 存档；有 high 先修。不要直接写下一章。`,
            ].join("\n"),
          };
        }
        if (args.op === "discard") {
          const r = await discardChapter(root, { number: args.number, reason: args.reason });
          const hang = [
            (r.impacts?.foreshadows || []).length ? `该章埋的未收伏笔：${r.impacts.foreshadows.join("、")}` : "",
            (r.impacts?.characters || []).length ? `登场章指向该章的人物：${r.impacts.characters.join("、")}` : "",
          ].filter(Boolean).join("；");
          return { text: `第${r.discarded}章已作废，稿子存进废章（可恢复）；这一章的章记忆/卷记忆已清，重写后会重新生成。${hang ? "\n注意：" + hang + "。重写时要接着用就补埋/补登场，不用了就撤掉，别留下悬空线索。" : ""}\n现在可以重写第${r.discarded}章：novel_outline get / novel_context / 写 / commit。` };
        }
        if (args.op === "read") {
          try {
            const c = await readChapter(root, args.number);
            return { text: `# 第${c.entry.number}章 ${c.entry.title}\n\n${c.text}` };
          } catch {
            return { text: `第 ${args.number} 章不存在（不在正文里，可能在废章 drafts/ 或被退回重写）。先用 op=list 看现有章节。` };
          }
        }
        const index = await loadIndex(root);
        return { text: index.length ? index.map((c) => `第${c.number}章 ${c.title}｜${c.chars}字｜${c.verdict}｜对话${(c.dialogueRatio * 100).toFixed(0)}%`).join("\n") : "（还没有章节）" };
      },
    },
    {
      name: "novel_memory",
      description: "旧记忆回查（只在需要时用，不占每章上下文）：op=recall query=关键词 [from/to] 按关键词调出正文/章记忆/伏笔/细纲的相关段落，每条带章号；op=volumes 看卷地图与卷记忆做没做。查「那个东西哪章出现过」「这条线到哪了」用它，别靠猜，也别直接 grep chapters/。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["recall", "volumes"], default: "recall" },
          query: { type: "string", description: "关键词：人名/地名/物件/伏笔名/事件" },
          from_chapter: { type: "number" },
          to_chapter: { type: "number" },
          limit: { type: "number", default: 6 },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (!(await loadProject(root))) throw new Error(`不是小说项目：${root}`);
        if (args.op === "volumes") {
          const vs = await loadVolumes(root);
          if (!vs.length) return { text: "还没识别出卷：大纲里要把卷写成「第 a-b 章」的区间（或细纲带 volume.to）。" };
          const { volumes: mem } = await loadMemoryRows(root);
          const project = await loadProject(root);
          const cur = Number(project?.currentChapter) || 0;
          return { text: vs.map((v) => `${v.from <= cur && cur <= v.to ? "▶" : " "} ${v.title}（第${v.from}-${v.to}章）${mem.some((m) => Number(m.to) === v.to) ? "· 已盘点" : "· 未盘点"}`).join("\n") };
        }
        const r = await recallMemory(root, { query: args.query, from: args.from_chapter, to: args.to_chapter, limit: args.limit });
        return { text: r.text };
      },
    },
    {
      name: "novel_studio_session",
      description: "把这次会话改好的正文交回面板（面板开着会立刻刷新），深入调整大纲/世界观类会话结束时调一次；只回「改好了」面板拿不到。op=return，outlineText=完整大纲正文（只真改了大纲时传），worldText=完整世界观正文（只真改了世界观时传）。这是覆盖写：字数腰斩或不像大纲会被拒（整篇替换加 force:true）；伏笔网只传 source、不传正文。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["return"], default: "return" },
          outlineText: { type: "string", description: "完整的大纲 markdown 正文；没改大纲就不传" },
          worldText: { type: "string", description: "完整的世界观 markdown 正文；没改世界观就不传" },
          source: { type: "string", description: "这次会话在做什么：深入调整大纲 / 深入设计世界观 / 深入调整伏笔网" },
          force: { type: "boolean", description: "确实要把大纲/世界观整篇换成另一份文档时才传 true（默认有防误覆盖检查）" },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        const r = await sessionReturn(root, {
          op: "session-return",
          outlineText: args.outlineText, worldText: args.worldText, source: args.source, force: Boolean(args.force),
        });
        const p = r?.view?.setup || {};
        const marks = [args.outlineText ? `大纲 ${String(args.outlineText).length} 字` : "", args.worldText ? `世界观 ${String(args.worldText).length} 字` : ""].filter(Boolean);
        return { text: marks.length ? `已交回面板：${marks.join("、")}（当前大纲 ${(p.outlineText || "").length} 字）` : "已交回面板（这次没带正文）" };
      },
    },
    {
      name: "novel_continuity",
      description: "连续性体检（确定性）：章节断档、退场角色复活、未登记说话人、时间线倒退、伏笔超期、字数偏离、设定缺席、禁用表达、AI 痕迹、本章开头是否只是接着上一章最后的动作续写、批次偏离。返回 high/mid/info 三档。scope=batch 时按批体检：一次看整批（from/to，默认取 gate 所在章的段落纲），返回每章该不该重写（action=rewrite/ok）加整批拦截项（blocking，批尾 approve 会被拦的断档/缺口）。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          scope: { type: "string", enum: ["book", "batch"], default: "book", description: "batch=按批体检（一次看整批，每章给出该不该重写）" },
          from: { type: "number", description: "scope=batch 时的起始章（默认取 gate 所在章的段落纲）" },
          to: { type: "number", description: "scope=batch 时的结束章" },
        },
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (args.scope === "batch") {
          const b = await checkBatch(root, { from: args.from, to: args.to });
          const icon = { high: "✗", mid: "!", info: "·" };
          const rows = b.chapters.map((c) => {
            const head = `${c.action === "rewrite" ? "要重写" : c.action === "review" ? "看过即可" : "没问题"}｜第${c.number}章 ${c.approved ? "（已存档）" : ""}high ${c.counts.high}/mid ${c.counts.mid}`;
            const body = c.findings.slice(0, 6).map((f) => `    ${icon[f.severity]} ${f.message}${f.hint ? "\n      → " + f.hint : ""}`).join("\n");
            return `${head}${body ? "\n" + body : ""}`;
          }).join("\n");
          const block = b.blocking.length ? `\n\n整批问题（批尾 approve 会被拦）：\n${b.blocking.map((f) => `- [${f.severity}] ${f.message}${f.hint ? `（${f.hint}）` : ""}`).join("\n")}` : "";
          const todo = b.chapters.filter((c) => c.action === "rewrite").map((c) => c.number);
          return { text: `按批体检 第${b.from}-${b.to}章｜${b.ok ? "可以 review 通过" : "先处理再通过"}｜high ${b.counts.high} / mid ${b.counts.mid} / info ${b.counts.info}\n\n${rows || "（这批还没章）"}${block}\n\n下一步：${todo.length ? `按章重写第 ${todo.join("、")} 章（novel_gate rewrite N note=…），其它章不动；` : ""}整批确认无误后 novel_gate approve ${b.to}。` };
        }
        const r = await continuityCheck(root);
        const icon = { high: "✗", mid: "!", info: "·" };
        const body = r.findings.map((f) => `${icon[f.severity]} [${f.severity}] ${f.message}\n    → ${f.hint}`).join("\n");
        return {
          text: `${r.ok ? "体检通过（无 high）" : "体检未通过"}｜${r.chapters} 章｜high ${r.counts.high} / mid ${r.counts.mid} / info ${r.counts.info}\n\n${body || "（无发现）"}`,
        };
      },
    },
    {
      name: "novel_concept",
      description: "选题（开书第一步）：op=propose 出 3-5 个差异化候选（concepts 数组，每个含 title/oneLine/synopsis/genre/platform/highlights）；op=select 锁定一个（concept_id）→ 写进 project。选定后先 novel_outline 出大纲，再补设定。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          op: { type: "string", enum: ["propose", "select"], default: "propose" },
          concepts: { type: "array", items: { type: "object" }, minItems: 3, maxItems: 8, description: "propose 时的候选数组（PRD 要求 3-5 个差异候选）" },
          concept_id: { type: "string", description: "select 时选中的候选 id" },
          title: { type: "string", description: "select 时可覆盖书名" },
        },
        required: ["op"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        if (args.op === "propose") {
          const r = await proposeConcepts(root, { concepts: args.concepts });
          const lines = r.concepts.map((c) => `[${c.id}] 《${c.title}》 ${c.genre}·${c.platform}\n  ${c.oneLine}${c.highlights?.length ? "\n  卖点：" + c.highlights.join("、") : ""}`);
          return { text: `已出 ${r.count} 个选题候选：\n\n${lines.join("\n\n")}\n\n让作者选一个，然后 novel_concept select <id>` };
        }
        const r = await selectConcept(root, { conceptId: args.concept_id || args.conceptId, title: args.title });
        return { text: `已锁定选题《${r.selected.title}》\n接下来 novel_outline 先出全书大纲（先大纲、后设定），作者确认后 novel_outline op=accept，再用 novel_bible 补设定，最后 novel_segment op=plan 排第一段段落纲。` };
      },
    },
    {
      name: "novel_export",
      description: "导出章节为 txt（不改原稿）：scope=single 导出单章（去 Markdown、段首缩进两格），scope=book 合并全书、可附设定集附录，写到 exports/。纯导出，不改账本，不要用它代替保存。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          scope: { type: "string", enum: ["single", "book"], default: "single" },
          from: { type: "number", default: 1 },
          to: { type: "number" },
          include_bible: { type: "boolean", default: false },
        },
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        const r = await exportChapters(root, {
          from: args.from, to: args.to, scope: args.scope, includeBible: args.include_bible,
        });
        return { text: `已导出 ${r.count} 章 → \n${r.files.join("\n")}` };
      },
    },
    {
      name: "novel_gate",
      description: [
        "作者三决定门（写完停在 awaiting_review 时用）。",
        "approve：必填 number（本章章号），本章是 needs_fix 仍要收进正文才加 force:true；通过后进下一章。批量模式下在本批最后一章 approve，会把这一批一起通过（然后整批一次补设定，不要逐章补）。",
        "rewrite：必填 number + note（重写要求），稿子退回 drafts、章号释放；重写时按 novel_context 的完整上下文改，别只看问题清单。direction：必填 direction（只影响后续章）。",
      ].join(" "),
      parameters: {
        type: "object", additionalProperties: false,
        properties: {
          project_dir: { type: "string" },
          action: { type: "string", enum: ["approve", "rewrite", "direction"], default: "approve" },
          number: { type: "number", description: "approve / rewrite 必填：本章章号" },
          note: { type: "string", description: "rewrite 必填：作者的重写要求" },
          direction: { type: "string", description: "direction 必填：新的写法方向" },
          force: { type: "boolean", description: "仅 approve 用：本章是 needs_fix 仍要收进正文才传 true" },
        },
        required: ["action"],
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        // 逐动作校验必填，缺参直接给可读错误，免得模型传错动作后瞎试
        if (args.action === "approve" || args.action === "rewrite") {
          if (!Number.isFinite(Number(args.number)) || Number(args.number) <= 0) {
            throw new Error(`action=${args.action} 需要 number（第几章）；approve 用 novel_gate approve N，rewrite 用 novel_gate rewrite N note="…"`);
          }
        }
        if (args.action === "rewrite" && !String(args.note || "").trim()) {
          throw new Error("action=rewrite 需要 note（你要求怎么改）；只改个别句子不必走 rewrite，可让作者直接说改哪段");
        }
        if (args.action === "direction" && !String(args.direction || "").trim()) {
          throw new Error("action=direction 需要 direction（新的写法方向），只说「改方向」我不知道往哪改");
        }
        if (args.action === "approve") {
          const r = await approveChapter(root, { number: args.number, force: Boolean(args.force) });
          // 通过即记忆：模型可用就把本章精炼成叙事记忆（覆盖 approveChapter 写入的摘要级兜底），失败不阻塞。
          let memText = "本章记忆已按摘要记下（模型精炼没成功，不影响继续写）";
          try {
            const d = await distillMemory(pluginCtx, { dir: root, number: r.approved });
            memText = `本章记忆已精炼：${(d?.memory?.events || []).length} 个关键事件`;
          } catch { /* 摘要级兜底已在 approveChapter 写入 */ }
          // 顺手把本章新增设定补进 bible，和界面点「通过」走同一条路；失败只提示。
          let syncText = "";
          try {
            // 整批通过就整批一起补设定（不是一章一章补）
            const batchNums = Array.isArray(r.approvedChapters) && r.approvedChapters.length > 1 ? r.approvedChapters : null;
            const s = await syncSettingFromChapterViaAI(pluginCtx, batchNums ? { dir: root, numbers: batchNums } : { dir: root, number: r.approved });
            const a = s?.added || {};
            const got = [
              (a.characters || []).length ? `人物 ${a.characters.join("、")}` : "",
              (a.locations || []).length ? `地点 ${a.locations.join("、")}` : "",
              (a.items || []).length ? `物品 ${a.items.join("、")}` : "",
              (a.factions || []).length ? `势力 ${a.factions.join("、")}` : "",
              (a.rules || []).length ? `硬规则 ${a.rules.join("、")}` : "",
              (s?.filled || []).length ? `补全字段 ${s.filled.map((f) => f.name).join("、")}` : "",
            ].filter(Boolean);
            const rl = s?.relations || {};
            if ((rl.relations || []).length) got.push(`关系矩阵 +${rl.relations.length} 对`);
            if ((rl.infoGaps || []).length) got.push(`信息差 +${rl.infoGaps.length} 条`);
            syncText = got.length ? `已补进设定${batchNums ? `（整批 ${batchNums[0]}-${batchNums[batchNums.length - 1]} 章一次补）` : ""}：${got.join("；")}。` : "";
          } catch { syncText = ""; }
          const debut = Array.isArray(r.debutFilled) ? r.debutFilled : [];
          const debutText = debut.length
            ? `已按正文补首次登场：${debut.map((f) => `${f.name}（第${f.firstChapter}章${f.fields.includes("aliases") ? "，并记下别名" : ""}）`).join("、")}。`
            : "";
          const batchText = Array.isArray(r.batchApproved) && r.batchApproved.length > 1 ? `本批第${r.batchApproved[0]}-${r.batchApproved[r.batchApproved.length - 1]}章一起通过。` : "";
          return { text: `第${r.approved}章已通过${r.forced ? "（forced，本章原为 needs_fix）" : ""}，开始写第${r.nextChapter}章。${batchText}${memText}。${debutText}${syncText}` };
        }
        if (args.action === "rewrite") {
          const r = await requestRewrite(root, { number: args.number, note: args.note });
          return { text: `第${r.rewriteOf}章已退回重写${r.note ? `，作者要求：${r.note}` : ""}。重写后重新 novel_chapter commit 同一章号${args.batch ? "（batch:true）" : ""}。${r.batchResume ? `其余章不动，重写完继续写第${r.batchResume}章。` : ""}` };
        }
        const r = await changeDirection(root, { direction: args.direction });
        return { text: `方向已更新，从第${r.effectiveFrom}章起生效：${r.direction}` };
      },
    },
    {
      name: "novel_repair",
      description: "修复项目结构与账本：按 chapters/*.md 重建索引、迁移旧版 project.json、清掉 JSONL 坏行、对齐门控、按正文补人物首次登场章；改前自动备份。项目打不开、章节列表对不上、门控卡住时用；平时不要用它替代正常写账。",
      parameters: {
        type: "object", additionalProperties: false,
        properties: { project_dir: { type: "string" } },
      },
      output: textOut(),
      async execute(args) {
        const root = await resolveRoot(this, args);
        const r = await repairProject(root);
        const moved = r.gate.before?.phase !== r.gate.after?.phase || r.gate.before?.chapter !== r.gate.after?.chapter;
        const ledger = r.ledger.length ? r.ledger.map((x) => `${x.file} 清掉 ${x.removed} 行`).join("；") : "账本没有坏行";
        const debut = Array.isArray(r.debutFilled) ? r.debutFilled : [];
        return {
          text: [
            `修复完成：${r.chapters} 章，索引已按正文重建；格式 v${r.schema.from} → v${r.schema.to}`,
            ledger,
            debut.length ? `已按正文补首次登场：${debut.map((f) => `${f.name}（第${f.firstChapter}章）`).join("、")}` : "",
            moved ? `门控已对齐：${r.gate.before?.phase || "?"}(${r.gate.before?.chapter || 0}) → ${r.gate.after.phase}(${r.gate.after.chapter})` : `门控无需调整：${r.gate.after.phase}(${r.gate.after.chapter})`,
            r.backups.length ? `备份：${r.backups.join("、")}` : "",
            `下一步：novel_status 复核，再继续写。`,
          ].filter(Boolean).join("\n"),
        };
      },
    },
  ];
}

/* ------------------------------ 技能供给 ------------------------------ */

const BUNDLED_SKILL_RANK = 600; // 同 @deepseek-ai/dsh-skill 的 BUNDLED_SKILL_RANK

async function loadSkillBundle(skillName) {
  const dir = path.join(SKILLS_DIR, skillName);
  const raw = await readFile(path.join(dir, "SKILL.md"), "utf8");
  const fm = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u.exec(raw);
  if (!fm) throw new Error(`dsh-novel-studio: ${skillName}/SKILL.md 缺 YAML frontmatter`);
  const desc = /^description:\s*(.+)$/m.exec(fm[1])?.[1]?.trim();
  if (!desc) throw new Error(`dsh-novel-studio: ${skillName} 缺 description`);
  return {
    name: skillName,
    description: desc.replace(/^["']|["']$/g, ""),
    invocation: { modelInvocable: true, userInvocable: true },
    provider: "dsh-novel-studio",
    source: "bundled",
    rank: BUNDLED_SKILL_RANK,
    locator: path.join(dir, "SKILL.md"),
    content: raw.slice(fm[0].length).trim(),
    resourceBase: { kind: "directory", path: dir.split(path.sep).join("/") },
  };
}

// 本机已有的写小说相关技能（DSH 会自动发现 ~/.dsh/skills 里的这些，
// 这里再把它们纳入本插件的技能供给，让面板/Agent 明确知道"这套插件带着这些技能"）。
const EXTERNAL_SKILLS = [
  "novel-creator", "novel-continuity", "novel-partner",
  "story", "story-long-write", "story-long-analyze", "story-long-scan",
  "story-short-write", "story-short-analyze", "story-short-scan",
  "story-import", "story-deslop", "story-review", "story-cover", "story-setup",
  "fenghuo-perspective", "maoni-perspective", "yuhua-perspective",
  "first-reader", "humanizer",
  "agent-reach",
];

// 6 个默认常驻技能（其余 21 个外部技能按下表按需加载）：RESIDENT_SKILLS 与 PROMPT 里的「常驻」清单必须一致。
export const RESIDENT_SKILLS = ["novel-studio", "novel-continuity", "story-long-write", "novel-creator", "story-deslop", "first-reader"];

// 技能 → 调用时机（写进 summary 的 note 字段，也会喂进系统提示；面板设置页展示）。
export const SKILL_WHEN = {
  "novel-studio": "总流程：开书 / 选题 / 排细纲 / 续写 / 体检，走 novel_* 工具与五阶段门控",
  "novel-continuity": "写完每章后体检连续性、去 AI 味、诊断节奏",
  "novel-partner": "只想处理「这一章」时取它的单章方法（写/看/改/判四个动词）。注意：本插件已内置 np 检查（体检里的 np-* 项），不要照它的流程单独建 book/ 目录或跑 np.py init，正文与伏笔一律以 novel_* 账本为准",
  "novel-creator": "需要世界观/角色心理/情节逻辑的深度设计时，作为创作方法的参考",
  "story": "仅当作者明确说要「网文工具箱/看板/写作习惯」时才用；一般写作请求直接走 novel_* 流程，不要拿它当模糊请求的默认路由",
  "story-long-write": "取它的长篇结构与按章推进方法（只取方法论，结构与账本一律走 novel_outline/novel_context）",
  "story-long-analyze": "拆解对标长篇、分析黄金三章时",
  "story-long-scan": "扫榜选题材、看市场趋势时",
  "story-short-write": "写短篇时",
  "story-short-analyze": "拆解爆款短篇时",
  "story-short-scan": "扫短篇榜、找风口题材时",
  "story-import": "把已有小说导入成项目结构时（只取它的解析方法，导入后的正文/设定仍以 novel_* 账本为准）",
  "story-deslop": "正文 AI 味重、需要整段去味时（比 novel-continuity 更重）；它只给改写方法，改完仍用 novel_chapter commit 落账",
  "story-review": "多视角对抗式审查一章/一卷质量时",
  "story-cover": "生成封面时",
  "story-setup": "部署写作环境/检查技能可用性时",
  "fenghuo-perspective": "想要烽火式的网文大家点评（情节门槛、群像）时",
  "maoni-perspective": "想要猫腻式的点评（人物复杂性、个人 vs 体制）时",
  "yuhua-perspective": "想要余华式的点评（把感受翻成算术、用故事代替断言）时",
  "first-reader": "发布前模拟真人试读，看注意力在哪断、读者会记住什么",
  "humanizer": "通用去 AI 味改写（偏英文/散文，中文网文优先 story-deslop）",
  "agent-reach": "自带网页搜索不可用/查不到时，用 agent-reach 搜网页、读正文、取各平台内容（只读）",
};

async function loadExternalSkill(skillName) {
  const base = process.env.DSH_NOVEL_EXTRA_SKILLS_DIR
    || (skillName === "agent-reach" ? path.join(os.homedir(), ".agents", "skills") : path.join(os.homedir(), ".dsh", "skills"));
  if (skillName === "agent-reach") {
    // agent-reach 的入口是命令行，很多安装环境里不在 PATH 上；补跑时要用全路径
    const cli = process.env.DSH_NOVEL_REACH_BIN || path.join(os.homedir(), ".local", "bin", "agent-reach");
    process.env.PATH = `${path.dirname(cli)}:${process.env.PATH || ""}`;
  }
  const dir = path.join(base, skillName);
  const file = path.join(dir, "SKILL.md");
  const raw = await readFile(file, "utf8");
  const fm = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u.exec(raw);
  let desc = "";
  if (fm) {
    // description 可能是单行、也可能是 "|" 多行块
    const m = /^description:\s*(.*)$/m.exec(fm[1]);
    if (m) {
      let d = m[1].trim();
      if (d === "|" || d === ">" || d === "") {
        // 取 description 之后的缩进块
        const after = fm[1].split(/^description:.*$/m)[1] || "";
        d = after.split(/\n\w/m)[0].split("\n").map((l) => l.trim()).filter(Boolean).join(" ");
      }
      desc = d.replace(/^["']|["']$/g, "");
    }
  }
  if (!desc) desc = skillName;
  return {
    name: skillName,
    description: desc,
    invocation: { modelInvocable: true, userInvocable: true },
    provider: "dsh-novel-studio",
    source: "external",
    rank: 500,
    locator: file,
    content: fm ? raw.slice(fm[0].length).trim() : raw,
    resourceBase: { kind: "directory", path: dir.split(path.sep).join("/") },
    when: SKILL_WHEN[skillName] || "",
  };
}

// 列出插件供给的全部技能（自带 2 + 本机外部）。供 provider 与面板 ping 共用。
const BUNDLED_SKILL_NAMES = ["novel-studio", "novel-continuity"]; // 插件自带（在 skills/ 下）

export async function listAllSkills() {
  const BUNDLED = BUNDLED_SKILL_NAMES;
  const extraRoot = process.env.DSH_NOVEL_EXTRA_SKILLS_DIR || path.join(os.homedir(), ".dsh", "skills");
  const out = [];
  for (const n of BUNDLED) {
    try {
      const s = await loadSkillBundle(n);
      const { content: _c, ...summary } = s;
      out.push({ ...summary, when: SKILL_WHEN[n] || "" });
    } catch { /* 自带技能缺失时跳过，别让 provider 崩 */ }
  }
  let names = [];
  try {
    const ents = await readdir(extraRoot, { withFileTypes: true });
    names = ents.filter((e) => e.isDirectory()).map((e) => e.name);
  } catch { names = []; }
  // agent-reach 装在自己的目录（~/.agents/skills），不在 .dsh/skills 里
  const wanted = EXTERNAL_SKILLS.filter((n) => names.includes(n) || n === "agent-reach");
  for (const n of wanted) {
    try {
      const s = await loadExternalSkill(n);
      const { content: _c, ...summary } = s;
      out.push(summary);
    } catch { /* 单个技能读失败不影响其它 */ }
  }
  return out;
}

function registerSkills(ctx) {
  ctx.skills.registerProvider(() => ({
    name: "dsh-novel-studio",
    async list() { return await listAllSkills(); },
    async get(candidate) {
      let s;
      if (BUNDLED_SKILL_NAMES.includes(candidate.name)) s = await loadSkillBundle(candidate.name);
      else s = await loadExternalSkill(candidate.name);
      const { locator: _l, rank: _r, ...rest } = s;
      const { rank: _cr, locator: _cl, ...base } = candidate;
      return { ...base, ...rest };
    },
  }));
}

/* ------------------------------ 插件入口 ------------------------------ */

export function apply(ctx, config = {}) {
  pluginCtx = ctx;
  const cfg = { projectRoot: config.projectRoot || "", prompt: config.prompt !== false };
  // 不能写 ctx.config（cordis 的 config 是只读 provide 槽）；把配置挂在闭包里的假 ctx 上。
  const toolCtx = { config: cfg };

  for (const def of toolDefs()) {
    ctx.tools.register({
      ...def,
      execute: (args, exec) => def.execute.call(toolCtx, args, exec),
    });
  }

  if (cfg.prompt && ctx.systemPrompt?.section) {
    ctx.systemPrompt.section({
      name: "novel-studio/workflow",
      order: 4200,
      text: PROMPT,
    });
  }

  if (ctx.skills?.registerProvider) registerSkills(ctx);

  // 左栏「写小说」面板的数据面：只有 web 运行时才有 webServer。
  // 用嵌套 fiber 注入，headless 环境下自动不挂路由，也不阻塞插件本体。
  // llm / agentDefaultModel 是可选注入：有就用 DSH 默认模型给面板生成选题，没有就降级（面板提示）。
  if (typeof ctx.inject === "function") {
    // 让面板数据面能读 llm / agentDefaultModel（可选，缺了就降级）；get 用根 ctx 的 get。
    const rootCtx = ctx;
    ctx.inject(["webServer"], (web) => {
      web.effect(() => {
        const dispose = mountApi(web, rootCtx);
        if (process.env.DSH_NOVEL_DEBUG) console.log("[novel-studio] /novel/api/* mounted");
        return () => {
          if (process.env.DSH_NOVEL_DEBUG) console.log("[novel-studio] /novel/api/* unmounted");
          dispose();
        };
      }, "novel-studio: /novel/api/*");
    });
  }
}
