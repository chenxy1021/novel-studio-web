// 领域层：项目/设定集/伏笔/细纲/章节/上下文包/连续性体检。
// 全部确定性实现——同一份稿子跑两次，结论必须一模一样。
import { existsSync } from "node:fs";
import { copyFile, rm } from "node:fs/promises";
import path from "node:path";
import {
  LAYOUT, appendJsonl, chapterFilePath, ensureDir, listFiles, p, pad3,
  readJson, readJsonl, readText, withProjectLock, writeJson, writeText,
} from "./io.js";
import { countChars, detectAiTells, estimateTokens, textMetrics, verdict, checkChapterEndHook } from "./metrics.js";
import { novelPartnerFindings } from "./npartner.js";
import { checkPlatformFormat, platformRules } from "./platforms.js";
import { chapterFromSegment } from "./segment.js";
import {
  aliasesOf, appendMemory, buildEchoMemory, characterState, clampSummary, fitSections, loadVolumes,
  MEMORY_FILE, packBudget, refreshVolumes, relationLines, resolveCharacter, volumeMemory, volumeOf,
} from "./memory.js";

const now = () => new Date().toISOString();

export const EMPTY_BIBLE = () => ({
  characters: [],
  world: [],
  rules: [],
  style: { samples: [], banned: [], pov: "", tense: "" },
  // PRD v1：设定集扩到 7 类，但只保留有内容的类（老项目向后兼容）
  factions: [],
  locations: [],
  items: [],
  relations: [],
  infoGaps: [],
});

/** 文风库：选项只存 key，label/hint 给面板，skill 给写正文时加载用。 */
export const STYLE_PRESETS = {
  fenghuo: { label: "烽火戏诸侯", skill: "fenghuo-perspective", hint: "文白夹杂、留白、判词式人物" },
  maoni: { label: "猫腻", skill: "maoni-perspective", hint: "古今混搭、猫式幽默、人物复杂" },
  yuhua: { label: "余华", skill: "yuhua-perspective", hint: "冷峻克制、短句、把感受写成动作" },
  aiqianshuidewuzhe: {
    label: "爱潜水的乌贼",
    skill: "aiqianshuidewuzhe-perspective",
    hint: "克苏鲁神秘感、英伦书面腔、冷静叙事、细节惊悚",
    samples: [
      "壁炉里的火明明烧得正旺，房间里却冷得像深冬。他放下手里的报纸，注意到茶几上的茶杯又动了——不是被谁碰的，是那只杯子自己在缓慢地旋转，杯底压着的信纸上，一行他从未写过的字迹正一点点显现。",
      "\"你觉得那扇门后面是什么？\"她问，声音很轻，仿佛怕被门听见。\"我不知道。\"他说，\"但我确定一件事——不管它是什么，它已经知道我们站在这里了。\"",
    ],
    banned: ["网络烂梗、现代流行语（绝绝子、yyds、破防）", "无节制血腥猎奇与粗俗叫骂", "旁白式大段讲设定（info-dump）", "夸张的爽文打脸喊口号"],
  },
  chendong: {
    label: "辰东",
    skill: "chendong-perspective",
    hint: "东方玄幻、气势磅礴、热血悲壮、苍凉宿命",
    samples: [
      "万古如一瞬，星河俱寂。他立在那座崩塌的废墟之上，衣袍猎猎，身后是无尽白骨铺成的长路。他抬头望向天穹，那双眼深处，仿佛有整部纪元在燃烧。",
      "\"值得吗？\"老者问，\"为了一段早该被埋葬的执念。\"他没有回头，只淡淡开口：\"等我做完这件事，再谈值不值得。\"",
    ],
    banned: ["现代网络梗、口语化吐槽破坏苍凉基调", "细腻琐碎的日常流", "小格局的职场宫斗式勾心斗角", "平铺直叙的白开水叙述"],
  },
  sanjiuyinyu: {
    label: "三九音域",
    skill: "sanjiuyinyu-perspective",
    hint: "都市异能、神明神话、中二热血、爽点密集、画面感强",
    samples: [
      "病院的灯一盏接一盏灭了。走廊尽头，那双不属于人类的金色瞳孔，在黑暗里缓缓睁开。他笑了。\"不好意思，今天，医生不上班。\"",
      "那一拳落下的瞬间，空气炸开一圈白色的气浪。围观的修士全部后退，脸色煞白。有人声音发抖：\"他……他才什么境界？\"没有人回答。因为答案就站在他们面前，浑身浴血，却在笑。",
    ],
    banned: ["拖沓文青式抒情和长篇环境描写", "晦涩难懂的设定堆叠", "主角一路无敌无挫败的平淡", "打脸写成纯耍嘴炮不落地"],
  },
  enyang: {
    label: "恩养",
    skill: "enyang-perspective",
    hint: "短篇悬疑志怪、民间技艺、冷峻反转、中式诡异",
    samples: [
      "相术师说过，人的命写在一张脸上，五官是笔，气色是墨，改不了的才是真。可那天来的客人，脸上一笔都没有。她把手收回袖子里，平静地说：\"你的面相，被人擦过了。\"客人笑了。那笑停在脸上，很久都没有动。",
      "执梭师这一行有条规矩：梭子走线，一声一线，断了就要停手。他数到第七声时，听见了第八声。屋里只有他和一台织机。",
    ],
    banned: ["冗长大场面描写和喧闹爽点", "甜宠狗血无脑反转", "网络流行语、口语吐槽", "纯血腥恐怖"],
  },
  liucixin: {
    label: "刘慈欣",
    skill: "liucixin-perspective",
    hint: "硬科幻、宇宙社会学、冷酷理性、宏大尺度、苍凉美学",
    samples: [
      "探测器在太阳系边缘减速的那一刻，数据传回地面用了六个小时。没有人说话。屏幕上那个单一的、微小的点，正以一种不符合任何已知物理规律的方式，安静地悬停。它在等一个答复。",
      "「我们该恐慌吗？」她问。「不。」他把手里的记录本合上，声音很平，「恐慌是留给还有选择的文明的。我们只剩下一个问题——要、还是不要。」",
    ],
    banned: ["华丽堆砌的辞藻和滥情的抒情", "网络梗、口语化俏皮话破坏冷峻科幻想像的庄重感", "科学上经不起推敲的魔法设定", "家长里短的生活流与职场狗血", "巧合和「天降神兵」解决危机"],
  },
};

/* ------------------------------ 门控状态机 ------------------------------ */
// PRD v1 §2.3：concept → bible → outline → writing(N) → awaiting_review(N) → writing(N+1)
// 用 project.gate 保存当前阶段；gate 只由工具推进，面板只读。

export const GATES = ["concept", "outline_accept", "bible", "outline", "writing", "awaiting_review"];
// PRD：去 AI 味最多 2 轮，超了必须人工介入（approve 收稿 或 direction 改方向），不许无限自动重试。
export const MAX_REWRITE_ROUNDS = 2;

// 项目格式版本。改 project.json / bible.json 的结构时 +1，并在 migrateProject 里补一条迁移。
// 老项目打开时在内存里迁移（不写盘），novel_repair 才会把迁移结果落盘并留备份。
export const SCHEMA_VERSION = 2;
const SCHEMA_FIELDS_V2 = {
  gate: () => ({ phase: "concept", chapter: 0, reason: "", at: now() }),
  gates: () => ({}),
  directionHistory: () => [],
  concepts: () => [],
  rewriteCounts: () => ({}),
  wordsRange: () => null,
};

/** 把任意历史版本的对象补成当前结构；返回 { value, migrated, from }。 */
export function migrateProject(input) {
  if (!input || typeof input !== "object") return { value: input, migrated: false, from: null };
  const from = Number(input.schemaVersion) || 1;
  if (from >= SCHEMA_VERSION) return { value: input, migrated: false, from };
  const value = { ...input };
  // v1 → v2：补齐门控状态机、方向历史、选题数组等后来加上的字段
  for (const [key, make] of Object.entries(SCHEMA_FIELDS_V2)) {
    if (value[key] === undefined || value[key] === null) value[key] = make();
  }
  if (!Number.isFinite(Number(value.currentChapter))) value.currentChapter = 0;
  if (!Array.isArray(value.directionHistory)) value.directionHistory = [];
  if (!Array.isArray(value.concepts)) value.concepts = [];
  if (!value.gate || typeof value.gate !== "object") value.gate = SCHEMA_FIELDS_V2.gate();
  if (!GATES.includes(value.gate.phase)) value.gate.phase = value.currentChapter > 0 ? "writing" : "concept";
  value.schemaVersion = SCHEMA_VERSION;
  return { value, migrated: true, from };
}

export function migrateBible(input) {
  if (!input || typeof input !== "object") return { value: input, migrated: false };
  const value = { ...EMPTY_BIBLE(), ...input };
  value.style = { samples: [], banned: [], pov: "", tense: "", ...(input.style || {}) };
  let migrated = false;
  for (const key of ["characters", "world", "rules", "factions", "locations", "items", "relations", "infoGaps"]) {
    if (!Array.isArray(value[key])) { value[key] = []; migrated = true; }
  }
  return { value, migrated };
}

/* ------------------------------ 用量记账 ------------------------------ */
// 设计目标「上下文包把 token 降一半」必须能被量出来：每次组装上下文、每次提交都记一行。
// 只记估算值，模型返回真实 usage 时以真实值为准（面板的模型调用会补写 kind=model 行）。

export async function logUsage(root, row) {
  try {
    await appendJsonl(p(root, LAYOUT.usage), { at: now(), ...row });
  } catch { /* 记账失败不影响写作 */ }
}

export async function usageSummary(root) {
  const rows = (await readJsonl(p(root, LAYOUT.usage)).catch(() => []))
    .filter((r) => r && !r.__corrupt);
  const sum = (kind, field) => rows.filter((r) => r.kind === kind).reduce((a, r) => a + (Number(r[field]) || 0), 0);
  const contexts = rows.filter((r) => r.kind === "context");
  const commits = rows.filter((r) => r.kind === "commit");
  const lastContext = contexts[contexts.length - 1] || null;
  return {
    contextCalls: contexts.length,
    contextTokensTotal: sum("context", "tokens"),
    contextTokensLast: lastContext ? Number(lastContext.tokens) || 0 : 0,
    contextChapterLast: lastContext ? Number(lastContext.chapter) || 0 : 0,
    commitCalls: commits.length,
    outputTokensTotal: sum("commit", "tokens"),
    outputCharsTotal: sum("commit", "chars"),
    modelCalls: rows.filter((r) => r.kind === "model").length,
    modelPromptTokens: sum("model", "promptTokens"),
    modelCompletionTokens: sum("model", "completionTokens"),
    // 章均上下文 token：只统计有章节号的
    contextTokensPerChapter: contexts.length
      ? Math.round(sum("context", "tokens") / Math.max(1, new Set(contexts.map((r) => r.chapter)).size))
      : 0,
  };
}

export function gateState(project) {
  if (!project) return { phase: "none", chapter: 0 };
  const g = project.gate || {};
  return { phase: g.phase || "concept", chapter: Number(g.chapter) || 0, reason: g.reason || "" };
}

async function setGate(root, phase, chapter, reason = "") {
  const project = await loadProject(root);
  if (!project) return;
  project.gate = { phase, chapter: Number(chapter) || 0, reason, at: now() };
  // 兼容老字段：gates.brief/bible/outline 仍同步
  project.gates = project.gates || {};
  if (phase === "concept") project.gates.brief = true;
  if (["outline_accept", "bible", "outline", "writing", "awaiting_review"].includes(phase)) project.gates.brief = true;
  if (["bible", "outline", "writing", "awaiting_review"].includes(phase)) project.gates.bible = true;
  if (["writing", "awaiting_review"].includes(phase)) project.gates.outline = true;
  await saveProject(root, project);
}

/** 门控校验：某动作在当前 gate 下是否被允许。返回 {ok, error}。 */
export async function guardGate(root, action, args = {}) {
  const project = await loadProject(root);
  if (!project) return { ok: false, error: `不是小说项目（缺 project.json）：${root}` };
  const st = gateState(project);
  const phase = st.phase;
  if (action === "bible_write") {
    // 题未选不许建 bible；选了之后（outline_accept / bible / outline / writing）都可写设定。
    if ((phase === "concept" || phase === "none") && !project.conceptSelected) {
      return { ok: false, error: "还没选选题，先 concept_propose 出候选、concept_select 选一个，再写设定" };
    }
    return { ok: true };
  }
  if (action === "outline_plan") {
    // G2：选题未定不许排细纲。硬规则不再卡在这里——一部长篇的设定是排完大纲之后才慢慢补的，
    // 所以 outline_plan 只要求「已选题」即可（world/rule 可在 bible 阶段后再补）。
    if ((phase === "concept" || phase === "none") && !project.conceptSelected) {
      return { ok: false, error: "还没选选题，先 concept_propose 出候选、concept_select 选一个，再排细纲" };
    }
    return { ok: true };
  }
  if (action === "outline_accept") {
    // 作者确认大纲：已有第 1 章细纲，或已把大纲文本贴进来（project.outlineText）都算数
    const o = await getOutline(root, 1);
    if ((o && (o.beats || []).length) || (project.outlineText || "").trim()) return { ok: true };
    return { ok: false, error: "还没有大纲：先在向导里让 AI 生成大纲、把大纲贴进来，或 novel_outline 排第 1 章细纲，再确认" };
  }
  if (action === "context_pack") {
    const chapter = Number(args.chapter) || 1;
    // 批次段落纲可以替代逐章细纲：批内写作本来就没有每章 beats。
    const seg = await chapterFromSegment(root, chapter);
    const o = seg ? null : await getOutline(root, chapter);
    if (!seg && (!o || !(o.beats || []).length)) {
      return { ok: false, error: `第${chapter}章还没有细纲（也不在任何批次段落纲里），先 outline_plan ${chapter} 或 novel_segment op=plan` };
    }
    // ② 未确认不许写：上一章必须已通过（approved），否则连上下文包都不给——
    // 这是「一章一章确认」真正的闸门，卡在取上下文（开始写）而不是提交。
    // 批内（有段落纲）时上一章只要已经写了即可，整批写完再统一 review。
    if (chapter > 1) {
      const index = await getIndex(root);
      const prev = index.find((c) => Number(c.number) === chapter - 1);
      if (!prev) return { ok: false, error: `第${chapter - 1}章还没写，不能先写第${chapter}章` };
      if (!prev.approved && !seg) return { ok: false, error: `第${chapter - 1}章还没通过确认，先 novel_gate approve ${chapter - 1}，再开始写第${chapter}章` };
    }
    // ③ 设定阶段兜底：写第 1 章前至少要有 1 条硬规则，否则「建设定」等于空走一遍。
    if (chapter === 1) {
      const bible = await loadBible(root);
      if (!(bible.rules || []).length) {
        return { ok: false, error: "第1章还没有硬规则：先用 novel_bible（entity=rule）写至少 1 条硬规则，再取上下文包开始写" };
      }
    }
    return { ok: true };
  }
  if (action === "chapter_commit") {
    const chapter = Number(args.number) || 1;
    // waiting for author：任何 commit 都不许再动正文，先把当前章 approve / rewrite 掉。
    // 这条必须排在细纲检查之前，否则模型会先收到「没有细纲」的误导提示。
    if (phase === "awaiting_review") {
      const locked = Number(project.gate?.chapter) || 0;
      return { ok: false, error: `第${locked}章待确认（awaiting_review），不能提交新稿：要改请 novel_gate rewrite ${locked}，或 novel_gate approve ${locked} 后再写第${locked + 1}章` };
    }
    // G3：没选题不许提交正文
    if (phase === "concept" && !project.conceptSelected) {
      return { ok: false, error: "还没选选题，先 concept_propose / concept_select，再写正文" };
    }
    // G3：必须已有本章细纲；批次模式下整批共用一份段落纲，以 segment 存在代替逐章 beats。
    const seg = await chapterFromSegment(root, chapter);
    const o = seg ? null : await getOutline(root, chapter);
    if (!seg && args.batch) {
      return { ok: false, error: `第${chapter}章不在任何批次段落纲里，不能带 batch:true；先 novel_segment op=plan from=${chapter} to=${chapter + 9} 规划这一批` };
    }
    if (!seg && (!o || !(o.beats || []).length)) {
      return { ok: false, error: `第${chapter}章还没有细纲（也不在任何批次段落纲里），先 outline_plan ${chapter} 或 novel_segment op=plan 再写正文` };
    }
    // G4：一章一章确认——上一章必须已通过（approved），否则不许写这一章。
    // batch:true 是批量写模式：上一章只要已经写过（pending/approved）就放行，整批写完统一 review。
    if (chapter > 1) {
      const index = await getIndex(root);
      const prev = index.find((c) => Number(c.number) === chapter - 1);
      if (!prev) return { ok: false, error: `第${chapter - 1}章还没写，不能先写第${chapter}章` };
      if (!prev.approved && !(args.batch && seg)) return { ok: false, error: `第${chapter - 1}章还没通过确认，先 novel_gate approve ${chapter - 1}，再写第${chapter}章` };
    }
    // 去 AI 味最多 2 轮：同一章已重写满 2 轮仍不合格，必须人工介入，不能再自动重试。
    const rw = (project.rewriteCounts || {})[String(chapter)] || 0;
    // 被退回 drafts 的稿子也计入轮次，所以这里不再要求 index 里已有 needs_fix 条目。
    // 批内重写同一章不占用「改下一章」的轮次额度：批量写作时单章重写是常规动作，不是去 AI 味的死循环。
    if (rw >= MAX_REWRITE_ROUNDS && !args.force && !(args.batch && seg)) {
      return { ok: false, error: `第${chapter}章已重写 ${rw} 轮仍不合格（去 AI 味上限 ${MAX_REWRITE_ROUNDS} 轮）。别再自动重试，交给作者：novel_gate approve（收稿）、novel_gate rewrite ${chapter}（单章退回重写）或 novel_gate direction（改方向）处理；已有改好的新稿可加 force:true 收进正文（会标 needs_fix）。` };
    }
    return { ok: true };
  }
  return { ok: true };
}

/* ------------------------------ 选题（concept） ------------------------------ */
// PRD v1：project_create 后 concept_propose 出 3-5 个差异候选，作者选一个 → concept_select 锁定。
// 候选只存 project.json.concepts（账本里留痕），选中的写进 project.concept。

export async function proposeConcepts(root, { concepts } = {}) {
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  if (!Array.isArray(concepts) || !concepts.length) throw new Error("需要 concepts 数组（PRD 要求 3-5 个差异候选）");
  if (concepts.length < 3) throw new Error(`选题候选至少 3 个（PRD 要求 3-5 个差异候选），现在只有 ${concepts.length} 个`);
  if (concepts.length > 8) throw new Error(`选题候选最多 8 个，现在有 ${concepts.length} 个，先合并`);
  const norm = concepts.map((c, i) => ({
    id: c.id || `c${i + 1}`,
    title: c.title || `候选${i + 1}`,
    oneLine: c.oneLine || c.logline || "",
    genre: c.genre || "",
    platform: c.platform || project.platform || "",
    synopsis: c.synopsis || "",
    highlights: Array.isArray(c.highlights) ? c.highlights : (c.highlights ? [c.highlights] : []),
    titleOptions: Array.isArray(c.titleOptions) ? c.titleOptions : [],
    differentiation: c.differentiation || "",
    business: c.business || "",
    risk: c.risk || "",
    outlineHint: c.outlineHint || "",
  }));
  project.concepts = norm;
  project.conceptSelected = null;
  project.gate = { phase: "concept", chapter: 0, reason: `已出 ${norm.length} 个选题，等作者选`, at: now() };
  await saveProject(root, project);
  return { ok: true, count: norm.length, concepts: norm };
}

export async function selectConcept(root, { conceptId, title } = {}) {
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  const list = Array.isArray(project.concepts) ? project.concepts : [];
  if (!list.length) throw new Error("还没有候选选题，先 concept_propose");
  const hit = list.find((c) => c.id === conceptId) || (conceptId ? list.find((c) => c.title === conceptId) : null);
  if (!hit) throw new Error(`没有这个选题：${conceptId}（可选：${list.map((c) => c.id).join(", ")}）`);
  project.conceptSelected = hit.id;
  project.concept = hit;
  if (title || hit.title) project.title = title || hit.title;
  if (hit.genre) project.genre = hit.genre;
  if (hit.platform) project.platform = hit.platform;
  if (hit.oneLine) project.logline = hit.oneLine;
  if (hit.synopsis) project.synopsis = hit.synopsis;
  project.gate = { phase: "bible", chapter: 0, reason: "选题已定，开始建设定集", at: now() };
  project.gates = { ...(project.gates || {}), brief: true };
  await saveProject(root, project);
  return { ok: true, selected: hit };
}

/* ------------------------------ 初始化 ------------------------------ */

export async function initProject(root, cfg = {}) {
  return withProjectLock(root, () => initProjectLocked(root, cfg));
}

async function initProjectLocked(root, cfg = {}) {
  const projectFile = p(root, LAYOUT.project);
  if (existsSync(projectFile)) throw new Error(`项目已存在：${projectFile}`);
  // 平台字数：没显式给 wordsPerChapter 时，从平台规则推一个目标字数（取区间中位），不再硬编码 3000
  const pRules = platformRules(cfg.platform);
  const derivedWpc = Math.round(((pRules.wordsMin || 3000) + (pRules.wordsMax || 3000)) / 2) || 3000;
  const project = {
    version: 1,
    schemaVersion: SCHEMA_VERSION,
    title: cfg.title || "未命名作品",
    genre: cfg.genre || "未定",
    platform: cfg.platform || "未定",
    logline: cfg.logline || "",
    synopsis: cfg.synopsis || "",
    outlineText: cfg.outlineText || "",
    referenceBook: cfg.referenceBook || "",
    worldText: cfg.worldText || "",
    targetChapters: cfg.targetChapters ?? 120,
    wordsPerChapter: cfg.wordsPerChapter ?? derivedWpc,
    wordsRange: { min: pRules.wordsMin, max: pRules.wordsMax, name: pRules.name },
    totalWords: cfg.totalWords ?? (cfg.targetChapters ?? 120) * (cfg.wordsPerChapter ?? derivedWpc),
    currentChapter: 0,
    direction: cfg.direction || "",
    directionHistory: [],
    concepts: [],
    conceptSelected: null,
    gates: { brief: Boolean(cfg.logline), bible: false, outline: false },
    // 状态机：有选题就从 bible 起，否则 concept 起
    gate: { phase: cfg.conceptSelected ? "bible" : "concept", chapter: 0, reason: "", at: now() },
    createdAt: now(),
    updatedAt: now(),
  };
  await ensureDir(p(root, LAYOUT.chapters));
  await ensureDir(p(root, LAYOUT.ledger));
  await ensureDir(p(root, LAYOUT.review));
  await ensureDir(p(root, LAYOUT.drafts));
  await ensureDir(p(root, "exports"));
  await ensureDir(p(root, "platforms"));
  await writeJson(projectFile, project);
  await writeJson(p(root, LAYOUT.bible), EMPTY_BIBLE());
  await writeJson(p(root, LAYOUT.chapterIndex), []);
  await writeText(p(root, LAYOUT.foreshadow), "");
  await writeText(p(root, LAYOUT.timeline), "");
  await writeText(p(root, "ledger/outline.jsonl"), "");
  // 平台规则快照：项目自身留一份，校验不随插件升级漂移
  try {
    await writeJson(p(root, "platforms", `${platformRules(project.platform).id}.json`), platformRules(project.platform));
  } catch { /* 平台快照失败不阻塞建项目 */ }
  await writeText(
    p(root, "README.md"),
    `# ${project.title}\n\n> ${project.genre} · ${project.platform} · 目标 ${project.targetChapters} 章 × ${project.wordsPerChapter} 字\n\n` +
      `## 目录\n\n- \`bible.json\` 设定集（人物/世界/硬规则/文风）\n- \`ledger/\` 伏笔、时间线、细纲账本\n- \`chapters/\` 正文，编号即顺序\n- \`review/\` 审查报告\n\n` +
      `## 铁律\n\n1. 设定只通过 \`novel_bible\` 写入，账号本即权威。\n2. 伏笔只通过 \`novel_foreshadow\` 开工/回收。\n3. 写正文前先取 \`novel_context\`，不要凭记忆续写。\n4. 每章提交后跑 \`novel_continuity\`，有 high 级缺陷先修再写下一章。\n`,
  );
  return project;
}

export async function loadProject(root) {
  const raw = await readJson(p(root, LAYOUT.project), null);
  if (!raw) return null;
  const { value, migrated, from } = migrateProject(raw);
  // 迁移只改内存：读操作不写盘，避免两个读同时触发写。落盘走 novel_repair。
  if (migrated) value.__migratedFrom = from;
  return value;
}

export async function saveProject(root, project) {
  project.updatedAt = now();
  project.schemaVersion = SCHEMA_VERSION;
  delete project.__migratedFrom;
  await writeJson(p(root, LAYOUT.project), project);
}

/* ------------------------------ 设定集 ------------------------------ */

export async function loadBible(root) {
  const raw = await readJson(p(root, LAYOUT.bible), EMPTY_BIBLE());
  return migrateBible(raw).value;
}

export async function saveBible(root, bible) {
  await writeJson(p(root, LAYOUT.bible), bible);
}

/**
 * 把 bible.style 同步成 `设定/文风.md`：story-long-write 等技能只认这个文件，
 * 面板/写正文用的是 bible.json；两处必须同源，否则技能会报「文风.md 不存在」。
 */
export async function writeStyleFile(root) {
  const bible = await loadBible(root);
  const st = bible.style || {};
  const preset = STYLE_PRESETS[st.preset] || null;
  const pSamples = (preset && Array.isArray(preset.samples)) ? preset.samples : [];
  const pBanned = (preset && Array.isArray(preset.banned)) ? preset.banned : [];
  const samples = [...pSamples, ...(Array.isArray(st.samples) ? st.samples.filter(Boolean) : [])];
  const banned = [...pBanned, ...(Array.isArray(st.banned) ? st.banned.filter(Boolean) : [])];
  if (!preset && !st.pov && !st.tense && !samples.length && !banned.length) return false;
  const parts = ["# 文风", ""];
  if (preset) parts.push("## 文风基调", `${preset.label}（技能：${preset.skill}）— ${preset.hint}`, "");
  if (st.pov) parts.push("## 视角", st.pov, "");
  if (st.tense) parts.push("## 时态", st.tense, "");
  if (samples.length) parts.push("## 文风样本（模仿语感，不要抄句）", ...samples.flatMap((s) => [s, ""]));
  if (banned.length) parts.push("## 禁用表达", banned.join("、"), "");
  const dir = p(root, "设定");
  await ensureDir(dir);
  await writeText(p(dir, "文风.md"), parts.join("\n").trimEnd() + "\n");
  return true;
}

const ENTITY_KEY = {
  character: "characters", world: "world", rule: "rules",
  faction: "factions", location: "locations", item: "items",
};

// 同名判定：完全一致，或「老韩」被「同期新人·老韩」包含，都算同一个人。
// 设定里常写成「职位·简称」（别名 老韩），模型换个写法（老韩）就精确比不上了。
function normName(x) {
  return String(x || "").toLowerCase().replace(/[\s·・\/\-—_,，、()（）「」『』]/g, "");
}
// 身份描述（赵家长工、会院守井老汉）不是名字，不能靠包含关系认成同一人，也不能当别名
const ROLE_TAIL_RE = /(长工|老汉|伙计|丫鬟|家丁|车夫|掌柜|账房|守卫|门房|更夫|学徒|弟子|婆子|妇人|少年|少女|老人|汉子)$/;

// 已退场/死亡/失踪的人不再参与「该登场却缺席」和「提前登场」检查——他们本来就不该再出场。
const GONE_STATUS = new Set(["dead", "exited", "missing", "退场", "已死"]);
function isGoneCharacter(ch) {
  return GONE_STATUS.has(String(ch?.status || "").trim());
}

/** 身份描述里可再认一次的核心叫法：「新麻绳扣的猎团领头」→「猎团领头」，「会院守井老汉」→「守井老汉」。 */
function roleCoreNames(name) {
  const s = String(name || "").trim();
  if (!s) return [];
  const out = [];
  const cut = s.lastIndexOf("的");
  if (cut > 0 && cut < s.length - 1) out.push(s.slice(cut + 1));
  const m = ROLE_TAIL_RE.exec(s);
  if (m && m.index > 0) out.push(s.slice(m.index));
  return out.filter((x) => x && x !== s);
}

// 短别名防撞：2 字以内且不像人名的叫法（三指、生面孔、老头）可能是普通词，
// 只用于关系/检索，不参与登场判定；「老韩、阿箬、小满、多多」这类常见人名写法仍保留。
// 主名（ch.name）永远参与判定，不受这里影响。
const SHORT_ALIAS_STOP = new Set([
  "三指", "生面孔", "老头", "老汉", "少年", "少女", "老人", "汉子", "妇人", "婆子",
  "长工", "伙计", "掌柜", "账房", "守卫", "门房", "更夫", "学徒", "弟子", "丫鬟",
  "家丁", "车夫", "众人", "有人", "那人", "这人",
]);
const PERSON_LIKE_SHORT = /^(老|小|阿|大)[\p{Script=Han}]$/u;
const DOUBLE_CHAR_NAME = /^([\p{Script=Han}])\1$/u;
function isAppearanceAlias(name) {
  const s = String(name || "").trim();
  if (!s) return false;
  if (SHORT_ALIAS_STOP.has(s)) return false;
  if (s.length <= 2 && !PERSON_LIKE_SHORT.test(s) && !DOUBLE_CHAR_NAME.test(s)) return false;
  return true;
}

/** 登场判定用的写法：主名 + 可用别名 + 身份描述切出的核心叫法。 */
function appearanceNames(ch) {
  const out = [ch?.name, ...aliasesOf(ch || {}).filter(isAppearanceAlias)];
  return [...new Set(out.flatMap((nm) => [nm, ...roleCoreNames(nm)]).filter(Boolean))];
}

/** 硬规则冲突词：只认 forbiddenKeywords。trigger 是「这条规则何时适用」的上下文提示，不是禁用词。 */
function hardRuleHits(rules, text) {
  const out = [];
  for (const r of rules || []) {
    const kws = Array.isArray(r?.forbiddenKeywords) ? r.forbiddenKeywords : [];
    const hits = kws.map((w) => String(w || "").trim()).filter((w) => w && text.includes(w));
    if (hits.length) out.push({ rule: r.name || r.text || "硬规则", matched: hits.join("、") });
  }
  return out;
}

// 正文里认人名用的强归一化：去标点空白，再去掉高频虚词「的/了/着/地/得/个/一」等，
// 让设定「收废品老头」能认到正文「收废品的老头」这种写法差异（差一个「的」也算同一人）。
const NAME_FUZZ_RE = /[\s·・\/\-—_,，、()（）「」『』【】《》。.!！?？;；:：]"'“”‘’]/g;
const NAME_FILLER_RE = /[的了着地得个一之其吗呢啊吧嘛哦]/g;
function fuzzFold(s) {
  return String(s || "").toLowerCase().replace(NAME_FUZZ_RE, "").replace(NAME_FILLER_RE, "");
}
// 在一段正文里找一个名字（或任一别名）出现的位置，返回匹配起点数组（折叠后匹配，返回近似原位置用于语境判断）。
// names：待试的写法（含别名）；text：该章正文。
/**
 * 这个命中是不是「长名字的一部分」：正文里「陆青荷」不该算「陆青」出场，
 * 「小陆青」也不该算。只看前后各一个字，且只有已知长名在该位置确实需要这两个字时才排除。
 */
function isPartOfLongerName(text, at, name, knownNames = []) {
  const before = text.slice(Math.max(0, at - 1), at);
  const after = text.slice(at + name.length, at + name.length + 1);
  const longer = knownNames.filter((x) => x && x !== name && x.length > name.length && x.includes(name));
  return longer.some((long) => {
    const idx = long.indexOf(name);
    const wantBefore = idx > 0 ? long[idx - 1] : "";
    const wantAfter = long[idx + name.length] || "";
    return (!wantBefore || before === wantBefore) && (!wantAfter || after === wantAfter);
  });
}

/** 精确名字命中（不做折叠），并排除「长名字的一部分」。 */
export function namePositions(text, names, knownNames = []) {
  const t = String(text || "");
  const out = [];
  for (const raw of names || []) {
    const nm = String(raw || "").trim();
    if (nm.length < 2) continue; // 单字名误撞太多，宁漏不误
    let at = t.indexOf(nm);
    while (at >= 0) {
      if (!isPartOfLongerName(t, at, nm, knownNames)) out.push(at);
      at = t.indexOf(nm, at + nm.length);
    }
  }
  return [...new Set(out)].sort((a, b) => a - b);
}

function nameHitsInText(text, names) {
  const flat = String(text || "");
  const flatFold = fuzzFold(flat);
  const hits = [];
  for (const nm of names) {
    const key = fuzzFold(nm);
    if (!key || key.length < 2) continue; // 折叠后不足 2 字太容易误撞，跳过
    // 在折叠串里找；命中后按比例回推原串大致位置（够用来截上下文判定回忆/现实）
    let at = flatFold.indexOf(key);
    while (at >= 0) {
      const approx = Math.min(flat.length, Math.floor((at / Math.max(1, flatFold.length)) * flat.length));
      hits.push(approx);
      at = flatFold.indexOf(key, at + key.length);
    }
  }
  return hits;
}
export function isRoleDescriptor(name) {
  return ROLE_TAIL_RE.test(normName(name));
}
function cleanAliases(name, aliases) {
  const list = Array.isArray(aliases) ? aliases : (typeof aliases === "string" ? aliases.split(/[、,，/\s]+/) : []);
  return [...new Set(list.map((a) => String(a || "").trim()).filter(Boolean))]
    .filter((a) => a !== name && !isRoleDescriptor(a));
}
export function samePerson(a, b) {
  const x = normName(a), y = normName(b);
  if (!x || !y) return false;
  if (x === y) return true;
  if (isRoleDescriptor(x) || isRoleDescriptor(y)) return false;
  const short = x.length <= y.length ? x : y, long = x.length <= y.length ? y : x;
  // 单字名（镜）只认「无册者·镜」这种修饰·名字的写法，避免一个字对上就并错人
  if (short.length === 1) return /[·・\/\-—]/u.test(String(a).includes(short) ? a : b) && long.endsWith(short);
  return long.includes(short);
}
/** 在已有条目里找同一个人（名字或别名任一对上）。 */
export function findSame(list, name, aliases) {
  const cands = [name, ...cleanAliases(name, aliases)].filter(Boolean);
  return (list || []).find((x) => [x.name, ...(Array.isArray(x.aliases) ? x.aliases : [])]
    .some((have) => have && cands.some((c) => samePerson(have, c)))) || null;
}

export async function bibleUpsert(root, entity, data, opts = {}) {
  return withProjectLock(root, () => bibleUpsertLocked(root, entity, data, opts));
}

async function bibleUpsertLocked(root, entity, data, opts = {}) {
  // 确定性回填（登场章/别名）不是「写设定」动作，不该被概念/大纲门控挡住；
  // 这类调用方显式传 skipGate，仍然只合并已有条目、不改剧情。
  if (!opts.skipGate) {
    const g = await guardGate(root, "bible_write");
    if (!g.ok) throw new Error(g.error);
  }
  if (entity === "style") {
    const bible = await loadBible(root);
    bible.style = { ...bible.style, ...data };
    await saveBible(root, bible);
    return { ok: true, entity, style: bible.style };
  }
  const key = ENTITY_KEY[entity];
  if (!key) throw new Error(`未知实体类型：${entity}（可用 character | world | rule | style | faction | location | item）`);
  if (entity === "character" && (data?.importance !== undefined || data?.tier !== undefined)) {
    const legacy = { S: "核心", A: "主要", B: "次要", C: "龙套" };
    const raw = String(data.importance ?? data.tier ?? "").trim();
    const imp = legacy[raw.toUpperCase()] || raw;
    data = { ...data, importance: ["核心", "主要", "次要", "龙套"].includes(imp) ? imp : "主要" };
    delete data.tier;
  }
  const bible = await loadBible(root);
  if (!data?.name && !data?.id && data?.key) data = { ...data, name: data.key }; // 容错：AI 常用 key 当名字
  if (!data?.name && !data?.id) throw new Error("需要 name 或 id");
  if (!Array.isArray(bible[key])) bible[key] = []; // 老项目补齐新分类
  const list = bible[key];
  // 认成同一个人就并进那一条：缺的字段补上，已有的值不覆盖（别名合并，不是重复插入）
  const twin = data.id ? list.find((x) => x.id === data.id) || null : findSame(list, data.name, data.aliases);
  // 死亡锁：已死亡角色不能被普通 upsert 改回存活；必须显式带 revive:true（面板里确认解锁才会带）。
  if (entity === "character" && twin?.status === "dead" && data.status && data.status !== "dead" && !data.revive) {
    data = { ...data };
    delete data.status;
  }
  if (entity === "character" && data?.revive !== undefined) {
    data = { ...data };
    delete data.revive;
  }
  const id = twin ? twin.id : data.id || (entity === "character" ? slug(data.name) : `${entity}-${slug(data.name)}`);
  const idx = twin ? list.indexOf(twin) : -1;
  if (idx >= 0) {
    const prev = list[idx];
    const aliases = cleanAliases(prev.name, [...(prev.aliases || []), ...cleanAliases(prev.name, data.aliases)]).filter((a) => a !== data.name);
    list[idx] = { ...prev, ...data, name: prev.name, id, aliases: aliases.length ? aliases : prev.aliases, updatedAt: now() };
  }
  else list.push({ ...data, aliases: cleanAliases(data.name, data.aliases), id, status: data.status || (entity === "character" ? "active" : undefined), createdAt: now() });
  await saveBible(root, bible);
  return { ok: true, entity, id, existed: idx >= 0, total: list.length };
}

function slug(s) {
  return String(s).trim().toLowerCase().replace(/\s+/g, "-").replace(/[^\p{Script=Han}a-z0-9-]/gu, "");
}

/** 把同一分类里其实是同一个人的多条并成一条：保留最早那条的名字和已有值，缺的字段从后条目补，别名合并。 */
export async function mergeDuplicateEntities(root, { allow } = {}) {
  const g = await guardGate(root, "bible_write");
  if (!g.ok) throw new Error(g.error);
  const bible = await loadBible(root);
  const merged = [];
  // allow：只合并 AI 复核通过的这几对（按名字），没给就沿用名字规则全并
  const pairKey = (a, b) => [normName(a), normName(b)].sort().join("|");
  const allowed = allow ? new Set(allow.map(([a, b]) => pairKey(a, b))) : null;
  for (const key of ["characters", "factions", "locations", "items", "rules"]) {
    if (!Array.isArray(bible[key])) continue;
    let out = bible[key];
    // 合并会新增别名（「镜」并进来后又让「无册者·镜」和别的对上），循环到没有重复为止
    for (let changed = true; changed;) {
      changed = false;
      out = out.reduce((acc, item) => {
        const keep = acc.find((x) => [x.name, ...(x.aliases || [])].some((h) => [item.name, ...(item.aliases || [])].some((c) => samePerson(h, c)))
          && (!allowed || allowed.has(pairKey(x.name, item.name))));
        if (!keep) { acc.push(item); return acc; }
        // 留一份原条目，判错时可以从设定页一键拆回去
        keep.mergedFrom = [...(keep.mergedFrom || []), { name: item.name, item, at: now() }];
        for (const [k, v] of Object.entries(item)) {
          if (k === "mergedFrom") continue;
          if (keep[k] === undefined || keep[k] === null || keep[k] === "" || (Array.isArray(keep[k]) && !keep[k].length)) keep[k] = v;
        }
        keep.aliases = [...new Set([...(keep.aliases || []), ...(item.aliases || []), item.name].filter((a) => a && a !== keep.name))];
        merged.push(`${item.name}→${keep.name}`);
        changed = true;
        return acc;
      }, []);
    }
    bible[key] = out;
  }
  if (merged.length) await saveBible(root, bible);
  return { ok: true, merged, count: merged.length };
}

/** 列出按名字规则疑似同一人的配对（给 AI 复核用，不直接合并）。 */
export async function listMergePairs(root) {
  const bible = await loadBible(root);
  const out = [];
  for (const key of ["characters", "factions", "locations", "items", "rules"]) {
    const list = Array.isArray(bible[key]) ? bible[key] : [];
    for (let i = 0; i < list.length; i += 1) {
      for (let j = i + 1; j < list.length; j += 1) {
        const a = list[i], b = list[j];
        if ([a.name, ...(a.aliases || [])].some((h) => [b.name, ...(b.aliases || [])].some((c) => samePerson(h, c)))) {
          out.push({ key, a, b });
        }
      }
    }
  }
  return out;
}

/** 把之前误并的条目从合并记录里拆出来，恢复它自己的字段。 */
export async function splitMergedEntity(root, { name, mergedName } = {}) {
  const g = await guardGate(root, "bible_write");
  if (!g.ok) throw new Error(g.error);
  const bible = await loadBible(root);
  let list = null, keep = null;
  for (const key of ["characters", "factions", "locations", "items", "rules"]) {
    const rows = bible[key] || [];
    const hit = rows.find((x) => x.name === name);
    if (hit) { list = rows; keep = hit; break; }
  }
  if (!keep) throw new Error(`找不到「${name}」`);
  const rec = (keep.mergedFrom || []).find((r) => r.name === mergedName);
  if (!rec) throw new Error(`「${name}」里没有「${mergedName}」的合并记录`);
  if (list.some((x) => x.name === mergedName)) throw new Error(`已经有一条「${mergedName}」了`);
  list.push({ ...(rec.item || {}), name: mergedName, id: slug(mergedName), createdAt: now() });
  keep.mergedFrom = keep.mergedFrom.filter((r) => r !== rec);
  if (!keep.mergedFrom.length) delete keep.mergedFrom;
  await saveBible(root, bible);
  return { ok: true, restored: mergedName };
}

export async function bibleQuery(root, { query, entity } = {}) {
  const bible = await loadBible(root);
  const key = entity ? ENTITY_KEY[entity] : null;
  const groups = key ? { [key]: bible[key] || [] } : {
    characters: bible.characters || [], world: bible.world || [], rules: bible.rules || [],
    factions: bible.factions || [], locations: bible.locations || [], items: bible.items || [],
    relations: bible.relations || [], infoGaps: bible.infoGaps || [],
  };
  const q = (query || "").trim();
  const out = {};
  for (const [k, list] of Object.entries(groups)) {
    if (!Array.isArray(list)) continue;
    out[k] = q ? list.filter((item) => JSON.stringify(item).includes(q)) : list;
  }
  if (!q && !entity) out.style = bible.style;
  return out;
}

/* ------------------------------ 伏笔 ------------------------------ */

export async function plantForeshadow(root, args = {}) {
  return withProjectLock(root, () => plantForeshadowLocked(root, args));
}

async function plantForeshadowLocked(root, { name, plantedChapter, dueChapter, note, kind, source, plantBeat, revealWho, revealChange, hint, abandon }) {
  if (!name) throw new Error("需要伏笔名称");
  const planted = Number(plantedChapter) || 1;
  const dueRaw = dueChapter === undefined || dueChapter === null || dueChapter === "" ? null : Number(dueChapter);
  // 回收章必须晚于埋设章：等于或早于埋设章在时间线上不成立，后面「到期未回收」也永远判不准。
  if (dueRaw !== null && (!Number.isFinite(dueRaw) || dueRaw <= planted)) {
    throw new Error(`伏笔「${name}」的回收章必须晚于埋设章（埋在第${planted}章，回收章给的是 ${dueChapter}）`);
  }
  // 同名去重：已经有一条 open 伏笔用这个名字，就别再埋一条新的（否则账本里两条同名 open），
  // 直接返回已有 id 并提示——去重不再完全依赖调用方。
  const existingRows = await readJsonl(p(root, LAYOUT.foreshadow)).catch(() => []);
  const dup = foldForeshadow(existingRows).find((f) => f.status === "open" && String(f.name).trim() === String(name).trim());
  if (dup) return { ok: true, id: dup.id, name: dup.name, deduped: true, note: "同名伏笔已在账，未重复埋设" };
  const id = `fs-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
  await appendJsonl(p(root, LAYOUT.foreshadow), {
    id, op: "plant", name, plantedChapter: planted,
    dueChapter: dueRaw, status: "open", note: note || "",
    kind: kind || "", source: source || "", plantBeat: plantBeat || "",
    revealWho: revealWho || "", revealChange: revealChange || "", hint: hint || "", abandon: abandon || "",
    at: now(),
  });
  return { ok: true, id, name };
}

export async function payoffForeshadow(root, args = {}) {
  return withProjectLock(root, () => payoffForeshadowLocked(root, args));
}

async function payoffForeshadowLocked(root, { name, chapter, note }) {
  const rows = await readJsonl(p(root, LAYOUT.foreshadow));
  const open = foldForeshadow(rows).find((f) => f.name === name || f.id === name);
  if (!open) throw new Error(`没有在账的伏笔：${name}`);
  await appendJsonl(p(root, LAYOUT.foreshadow), {
    id: open.id, op: "payoff", name: open.name, plantedChapter: open.plantedChapter,
    dueChapter: open.dueChapter, status: "paid", payoffChapter: Number(chapter) || null, note: note || "", at: now(),
  });
  return { ok: true, id: open.id, name: open.name, plantedChapter: open.plantedChapter, payoffChapter: Number(chapter) || null };
}

/** 删掉一条伏笔（记一条 abandon 事件，折叠后状态变 abandoned，不再出现在未收列表） */
export async function deleteForeshadow(root, { name, id }) {
  const rows = await readJsonl(p(root, LAYOUT.foreshadow));
  const target = foldForeshadow(rows).find((f) => (id && f.id === id) || f.name === name);
  if (!target) throw new Error(`没有在账的伏笔：${name || id}`);
  await appendJsonl(p(root, LAYOUT.foreshadow), {
    id: target.id, op: "abandon", name: target.name, plantedChapter: target.plantedChapter,
    dueChapter: target.dueChapter, status: "abandoned", at: now(),
  });
  return { ok: true, id: target.id, name: target.name };
}

/** JSONL 事件折叠成当前状态（后写覆盖先写，只关心 status/开收章） */
export function foldForeshadow(rows) {
  const map = new Map();
  for (const r of rows) {
    if (r.__corrupt) continue;
    const cur = map.get(r.id) || { id: r.id, name: r.name, plantedChapter: r.plantedChapter, dueChapter: r.dueChapter, status: "open" };
    map.set(r.id, {
      ...cur,
      name: r.name ?? cur.name,
      plantedChapter: r.plantedChapter ?? cur.plantedChapter,
      dueChapter: r.dueChapter ?? cur.dueChapter,
      status: r.op === "payoff" ? "paid" : r.op === "abandon" ? "abandoned" : cur.status,
      payoffChapter: r.payoffChapter ?? cur.payoffChapter,
      note: r.note || cur.note || "",
      kind: r.kind ?? cur.kind ?? "",
      source: r.source ?? cur.source ?? "",
      plantBeat: r.plantBeat ?? cur.plantBeat ?? "",
      revealWho: r.revealWho ?? cur.revealWho ?? "",
      revealChange: r.revealChange ?? cur.revealChange ?? "",
      hint: r.hint ?? cur.hint ?? "",
      abandon: r.abandon ?? cur.abandon ?? "",
      lastAt: r.at,
    });
  }
  return [...map.values()];
}

export async function listForeshadow(root, currentChapter) {
  const rows = await readJsonl(p(root, LAYOUT.foreshadow));
  const all = foldForeshadow(rows);
  const open = all.filter((f) => f.status === "open");
  const scored = open.map((f) => ({
    ...f,
    overdue: f.dueChapter ? currentChapter >= f.dueChapter : false,
    remaining: f.dueChapter ? f.dueChapter - currentChapter : null,
    age: currentChapter - (f.plantedChapter || 0),
  }));
  return {
    open: scored.sort((a, b) => (b.overdue - a.overdue) || ((a.remaining ?? 1e9) - (b.remaining ?? 1e9))),
    paid: all.filter((f) => f.status === "paid"),
    total: all.length,
  };
}

/* ------------------------------ 细纲 ------------------------------ */

/**
 * 「本章必须埋设的伏笔」：plantedChapter === 本章 的所有伏笔（含已收的也列出，因为正文里埋的动作必须在埋设章发生）。
 * 给 buildContext 写正文时用，也用于体检「漏埋伏笔」检查。
 */
export async function foreshadowsToPlant(root, chapter) {
  const n = Number(chapter);
  const rows = await readJsonl(p(root, LAYOUT.foreshadow));
  const all = foldForeshadow(rows);
  return all.filter((f) => Number(f.plantedChapter) === n);
}

/**
 * 把本章正文里的设定补进骨架账本（人物/地点/物品/势力/硬规则）。
 * 新增没有的条目；已有条目只填空白字段，已填的值绝不覆盖。
 * 返回 {added:{...}, filled:[{entity,name,fields}]}。
 * 由 AI 或作者在存档后调用（前端「补全本章设定」按钮 → POST setting-sync）。
 */
export async function syncSettingFromChapter(root, { entities } = {}) {
  const bible = await loadBible(root);
  const have = (key) => bible[key] || [];
  const added = { characters: [], locations: [], items: [], factions: [], rules: [] };
  const filled = [];
  const ENTITY_OF = { characters: "character", locations: "location", items: "item", factions: "faction", rules: "rule" };
  const FILL_FIELDS = [
    "importance", "rolePosition", "role", "age", "gender", "race", "callRules", "appearance", "personality",
    "want", "fear", "bottomLine", "flaw", "secret", "voice",
    "ability", "abilityLimit", "abilityCost", "status", "location", "currentGoal",
    "knowledge", "ignorance", "misconception", "changeLog",
    "firstChapter", "exitChapter", "text", "note", "keywords",
    "slang", "nature", "economy", "openRules", "hiddenRules", "relations", "emblem", "representatives", "power", "leader", "attitude", "misjudge",
    "geo", "structure", "senses", "owner", "accessRules", "occupied", "state", "events", "familiar",
    "appearance", "origin", "function", "limit", "cost", "type", "holder", "whoKnows", "transferLog",
    "judge", "boundary", "level", "source", "belief", "tested", "exploited", "violationLog",
  ];
  const blank = (v) => v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length);
  const buckets = {
    characters: entities?.characters || [],
    locations: entities?.locations || [],
    items: entities?.items || [],
    factions: entities?.factions || [],
    rules: entities?.rules || [],
  };
  for (const key of Object.keys(buckets)) {
    const existing = have(key);
    for (const raw of buckets[key]) {
      const e = typeof raw === "string" ? { name: raw } : raw;
      const name = String((e && e.name) || "").trim();
      if (!name) continue;
      const twin = findSame(existing, name, e.aliases);
      if (twin) {
        // 只填空着的字段：作者/AI 已经写过的不动，免得后一章把设定改跑偏
        const patch = { name: twin.name };
        const fields = [];
        for (const f of FILL_FIELDS) {
          if (blank(twin[f]) && !blank(e[f])) { patch[f] = e[f]; fields.push(f); }
        }
        const aliases = [...new Set([...cleanAliases(twin.name, twin.aliases), ...cleanAliases(twin.name, [...(Array.isArray(e.aliases) ? e.aliases : []), name])])];
        if (aliases.length && JSON.stringify(aliases) !== JSON.stringify(twin.aliases || [])) { patch.aliases = aliases; fields.push("aliases"); }
        if (!fields.length) continue;
        await bibleUpsert(root, ENTITY_OF[key], patch);
        Object.assign(twin, patch);
        filled.push({ entity: key, name: twin.name, fields });
        continue;
      }
      await bibleUpsert(root, ENTITY_OF[key], e);
      existing.push(e);
      added[key].push(name);
    }
  }
  // 人物关系网：整批补完再一起落账（批尾一次补，不是一章一次），已有那一对/那个秘密只补空列
  const rel = { relations: [], infoGaps: [] };
  const rowsRel = Array.isArray(entities?.relations) ? entities.relations : [];
  const rowsGap = Array.isArray(entities?.infoGaps) ? entities.infoGaps : [];
  if (rowsRel.length || rowsGap.length) {
    const book = await loadBible(root);
    const str = (v) => String(v ?? "").trim();
    if (rowsRel.length) {
      const map = new Map((book.relations || []).map((r) => [`${str(r.a)}→${str(r.b)}`, r]));
      for (const it of rowsRel) {
        const row = { a: str(it?.a), b: str(it?.b), state: str(it?.state), note: str(it?.note) };
        if (!row.a || !row.b || row.a === row.b) continue;
        const cur = map.get(`${row.a}→${row.b}`);
        if (cur) { if (!str(cur.state) && row.state) cur.state = row.state; if (!str(cur.note) && row.note) cur.note = row.note; continue; }
        if (!row.state && !row.note) continue;
        map.set(`${row.a}→${row.b}`, row); rel.relations.push(`${row.a}→${row.b}`);
      }
      book.relations = [...map.values()];
    }
    if (rowsGap.length) {
      const map = new Map((book.infoGaps || []).map((g) => [str(g.secret), g]));
      for (const it of rowsGap) {
        const row = { secret: str(it?.secret), knows: str(it?.knows), doesntKnow: str(it?.doesntKnow), thinksKnows: str(it?.thinksKnows) };
        if (!row.secret) continue;
        const cur = map.get(row.secret);
        if (cur) { for (const f of ["knows", "doesntKnow", "thinksKnows"]) if (!str(cur[f]) && row[f]) cur[f] = row[f]; continue; }
        map.set(row.secret, row); rel.infoGaps.push(row.secret);
      }
      book.infoGaps = [...map.values()];
    }
    await saveBible(root, book);
  }
  return { ok: true, added, filled, relations: rel };
}

export async function setOutline(root, args = {}) {
  return withProjectLock(root, () => setOutlineLocked(root, args));
}

async function setOutlineLocked(root, { chapter, beats, mustInclude, mustAvoid, detail, volume, title, openingState, endingState, pressure }) {
  const g = await guardGate(root, "outline_plan", { chapter });
  if (!g.ok) throw new Error(g.error);
  // 一拍就是一句话。整段大纲/整节摘要被当成节拍写进来（几百字一条）时在这里拦住，
  // 否则上下文包会把整本大纲当「本章细纲」塞给正文，写出来必然发散。
  const beatList = (Array.isArray(beats) ? beats : []).map((b) => String(b ?? "").trim()).filter(Boolean);
  const tooLong = beatList.find((b) => b.length > 180);
  if (tooLong) {
    throw new Error(`这不是节拍，是整段大纲（有一条 ${tooLong.length} 字）。细纲每一拍要一句话、写「谁→想要什么→被什么挡住→结果」；排细纲请用 novel_outline op=generate，只想存大纲正文就只传 outlineText。`);
  }
  if (beatList.length > 8) {
    throw new Error(`细纲 3-6 拍，现在 ${beatList.length} 条，像是把大纲整节贴进来了。用 novel_outline op=generate 生成，或自己压到 6 拍以内。`);
  }
  // 注意：细纲是下游产物，任何时候都允许重排（含大纲已确认后的第 1 章）。
  // 删除后重新 set 会追加一条新的非 deleted 记录，listOutlines 取最新一条，即完成「重新生成细纲」。
  await appendJsonl(p(root, "ledger/outline.jsonl"), {
    chapter: Number(chapter), beats: beatList, mustInclude: mustInclude || [],
    mustAvoid: mustAvoid || [], detail: typeof detail === "string" ? detail : "",
    // 卷信息：{"title":"第2卷 白塔","to":240}（本卷到第几章），用来补全卷索引、生成卷记忆
    volume: volume && Number(volume.to) ? volume : (detail && typeof detail === "object" ? (detail.volume || null) : null),
    title: String(title || "").slice(0, 40),
    openingState: String(openingState || "").slice(0, 800),
    endingState: String(endingState || "").slice(0, 800),
    // 动机三件套：写这一章时「为什么此刻必须动」的来源，不是文笔问题而是结构问题
    pressure: pressure && typeof pressure === "object" ? {
      deadline: String(pressure.deadline || "").slice(0, 120),
      stake: String(pressure.stake || "").slice(0, 160),
      opponent: String(pressure.opponent || "").slice(0, 120),
    } : null,
    at: now(),
  });
  const project = await loadProject(root);
  if (project) {
    project.gates = { ...(project.gates || {}), outline: true };
    const phase = project.gate?.phase;
    // 排了细纲：若还在前面阶段，进入「等作者确认大纲」（outline_accept）；
    // 已经确认过大纲（outlineAccepted）或已在写作阶段，则不动 gate。
    if (!project.outlineAccepted && (!phase || phase === "concept" || phase === "outline" || phase === "bible")) {
      project.gate = { phase: "outline_accept", chapter: Number(chapter) || 1, reason: "大纲已生成，等你确认后再补全书设定、开始写", at: now() };
    }
    await saveProject(root, project);
    // 细纲带了卷信息（本卷到第几章）就顺手刷新卷索引
    if (volume || (detail && typeof detail === "object" && detail.volume)) {
      await refreshVolumes(root, async () => (await listOutlines(root)));
    }
  }
  return { ok: true, chapter: Number(chapter), beats: beatList.length };
}

/** 作者确认大纲 → 进入 bible 阶段（之后 AI 补全设定，再开写）。 */
export async function acceptOutline(root) {
  return withProjectLock(root, () => acceptOutlineLocked(root));
}

async function acceptOutlineLocked(root) {
  const g = await guardGate(root, "outline_accept", {});
  if (!g.ok) throw new Error(g.error);
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目（缺 project.json）：${root}`);
  if (project.outlineAccepted) {
    throw new Error("大纲已经确认过了，不要重复确认；要改大纲请走 novel_gate direction（改方向）");
  }
  // 已经有正文（写过的章），再「确认大纲」绝不能把 gate 砸回 bible/0——那样会让已写章节的
  // 门控状态与进度脱节（approveChapter 卡死、进度页显示成 bible 阶段）。此时只补标记，不动 gate。
  const idxNow = await loadIndex(root).catch(() => []);
  const maxWritten = idxNow.reduce((m, c) => Math.max(m, Number(c.number) || 0), 0);
  if (maxWritten > 0) {
    project.outlineAccepted = true;
    project.outlineAcceptedAt = now();
    project.gates = { ...(project.gates || {}), outline: true, bible: true };
    if (!["writing", "awaiting_review"].includes(project.gate?.phase)) {
      const nextNum = (Number(project.currentChapter) || maxWritten) + 1;
      project.gate = { phase: "writing", chapter: nextNum, reason: `已有 ${maxWritten} 章正文，门控保持在写第${nextNum}章`, at: now() };
    }
    await saveProject(root, project);
    return { ok: true, gate: project.gate, note: "已有正文，仅确认大纲、不改动进度" };
  }
  project.outlineAccepted = true;
  project.outlineAcceptedAt = now();
  project.gates = { ...(project.gates || {}), outline: true, bible: true };
  project.gate = { phase: "bible", chapter: 0, reason: "大纲已确认，可以让 AI 补全书设定，然后开写第 1 章", at: now() };
  await saveProject(root, project);
  return { ok: true, gate: project.gate };
}

/**
 * 删除某章细纲（走追加事件覆盖，不改历史行）——用于「重新生成细纲」前清掉旧的。
 * 实现：追加一条 {chapter, deleted:true} 事件；listOutlines/getOutline 会把它视为不存在。
 * 已确认大纲且锁定第 1 章细纲时同样禁止（与 setOutline 一致）。
 */
export async function deleteOutline(root, { chapter } = {}) {
  const n = Number(chapter);
  if (!Number.isFinite(n) || n < 1) throw new Error("要删除哪一章的细纲？给 chapter");
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目（缺 project.json）：${root}`);
  // 细纲是「下游产物」，任何时候都允许删除重生成（包括大纲已确认后的第 1 章）。
  // 删掉的是本章的分镜/节拍，不是大纲本身；大纲与世界观不受影响。
  await appendJsonl(p(root, "ledger/outline.jsonl"), { chapter: n, deleted: true, at: now() });
  return { ok: true, chapter: n };
}

export async function getOutline(root, chapter) {
  const rows = await readJsonl(p(root, "ledger/outline.jsonl"));
  const hit = rows.filter((r) => Number(r.chapter) === Number(chapter)).pop();
  if (!hit || hit.deleted) return null;
  return hit;
}

/** 细纲列表：把 outline.jsonl 按章号聚合成一列，供「细纲」页展示。 */
export async function listOutlines(root) {
  const rows = await readJsonl(p(root, "ledger/outline.jsonl"));
  const byChapter = new Map();
  for (const r of rows) {
    if (!r || r.__corrupt) continue;
    const n = Number(r.chapter);
    if (!Number.isFinite(n)) continue;
    byChapter.set(n, r); // 同章多次写入取最新（含 deleted 事件）
  }
  return [...byChapter.values()]
    .filter((r) => !r.deleted)
    .sort((a, b) => Number(a.chapter) - Number(b.chapter))
    .map((r) => ({
      chapter: Number(r.chapter),
      beats: Array.isArray(r.beats) ? r.beats : [],
      mustInclude: Array.isArray(r.mustInclude) ? r.mustInclude : [],
      mustAvoid: Array.isArray(r.mustAvoid) ? r.mustAvoid : [],
      detail: typeof r.detail === "string" ? r.detail : "",
      title: r.title || "",
      openingState: r.openingState || "",
      endingState: r.endingState || "",
      pressure: r.pressure || null,
      at: r.at || "",
    }));
}

/* ------------------------------ 章节 ------------------------------ */

export async function loadIndex(root) {
  return readJson(p(root, LAYOUT.chapterIndex), []);
}
const getIndex = loadIndex;
async function rmQuiet(file) { try { await rm(file, { force: true }); } catch { /* ignore */ } }

/** drafts/ 清理：同一章只保留最近 KEEP 份草稿（按文件名里的时间戳排序），超了删旧的。
 *  文件名形如 `007-标题-<base36时间戳>.md`，也可带 -discard- 段；按章号前缀分组。 */
const DRAFT_KEEP = 3;
async function pruneDrafts(root, chapter) {
  try {
    const draftDir = p(root, "drafts");
    if (!existsSync(draftDir)) return;
    const prefix = pad3(Number(chapter));
    const all = await listFiles(draftDir);
    // 取该章前缀、以 .md 结尾的草稿；文件名里含 base36 时间戳（末段 6+ 位）
    const mine = all
      .filter((n) => n.startsWith(prefix + "-") && n.endsWith(".md"))
      .map((n) => {
        // 时间戳：文件名去掉 .md 后，最后一个 '-' 后的段（若是 discard 结构则取倒数第二段前）
        const stem = n.slice(0, -3);
        const segs = stem.split("-");
        let stamp = segs[segs.length - 1];
        // 若是 discard 备份 `NNN-title-discard-<stamp>` 结构不变，末段仍是时间戳
        return { name: n, stamp: stamp.length >= 6 ? stamp : "" };
      })
      .sort((a, b) => (a.stamp < b.stamp ? 1 : a.stamp > b.stamp ? -1 : 0)); // 新→旧
    for (const f of mine.slice(DRAFT_KEEP)) await rmQuiet(p(draftDir, f.name));
  } catch { /* 清理失败不影响主流程 */ }
}

export async function commitChapter(root, args) {
  return withProjectLock(root, () => commitChapterLocked(root, args));
}

/** 长篇每章硬下限：1800 字；全书目标 ≤50 章（短篇/短故事）的项目不设下限，返回 0。 */
export function chapterMinChars(project) {
  const target = Number(project?.targetChapters) || 0;
  if (target > 0 && target <= 50) return 0;
  // shortcut: 设 DSH_NOVEL_MIN_CHARS=0 可整体关掉硬下限（只给测试/评测用），正式环境别设
  return Number(process.env.DSH_NOVEL_MIN_CHARS ?? 1800) || 0;
}

async function commitChapterLocked(root, { number, title, text, inWorldDay, summary, characters, wordsPerChapter, force = false, batch = false }) {
  const n = Number(number) || 1;
  const g = await guardGate(root, "chapter_commit", { number: n, force, batch });
  if (!g.ok) throw new Error(g.error);
  // 章号闸：只能提交当前 gate 指向的章（writing/awaiting_review 的 chapter）。
  // 第 1 章是特例：从 bible/outline_accept 进入写作时 gate.chapter 还是 0，此时允许先落第 1 章。
  // 目的是禁止覆盖已存档正文，也避免同号不同名留下孤儿文件。
  const st = gateState(await loadProject(root));
  const indexNow = await getIndex(root);
  const firstChapterBootstrap = n === 1 && indexNow.length === 0
    && ["concept", "bible", "outline", "outline_accept"].includes(st.phase);
  if (!firstChapterBootstrap) {
    // awaiting_review 表示这一章已经落进正文、等作者拍板：任何 commit 都不许覆盖，
    // 否则改个标题就能悄悄替换待确认的稿子，A1 的章号闸等于没设。
    if (st.phase === "awaiting_review") {
      throw new Error(`第${st.chapter}章待确认（awaiting_review），不能再次提交：要改请 novel_gate rewrite ${st.chapter}，或 novel_gate approve ${st.chapter} 后再写第${Number(st.chapter) + 1}章`);
    }
    if (st.phase !== "writing" || n !== (Number(st.chapter) || 0)) {
      throw new Error(`第${n}章不是当前待写章（当前 gate 在第${st.chapter}章，阶段 ${st.phase}）；要改已存档章请先 novel_gate rewrite ${n}`);
    }
  }
  // batch:true 只对已落账的批次段落纲生效：没有段落纲就没有「整批一次 review」的边界，不许拿它绕过逐章确认。
  const batchSeg = batch ? await chapterFromSegment(root, n) : null;
  if (batch && !batchSeg) {
    throw new Error(`第${n}章不在任何批次段落纲里，不能带 batch:true。先 novel_segment op=plan from=${n} to=${n + 9} 规划这一批。`);
  }
  if (!text || countChars(text) < 200) throw new Error("正文太短（<200 字），不像一章，先别提交");
  // 强制 summary 与 characters 非空：它们是后续连续性/检索的唯一依据，空着等于堵死体检与伏笔核对（第十二条的破口）。
  const summaryStr = String(summary || "").trim();
  const charsArr = Array.isArray(characters) ? characters.map((c) => String(c || "").trim()).filter(Boolean) : [];
  if (!summaryStr) throw new Error("提交必须带 summary（本章剧情摘要，一两句话即可），否则后续检索与连续性检查无从依据");
  if (!charsArr.length) throw new Error("提交必须带 characters（本章出场人物名列表，至少一个），否则人物一致性无法核对");
  summary = summaryStr; characters = charsArr;
  const bible = await loadBible(root);
  const project0 = await loadProject(root);
  const metrics = textMetrics(text);
  const tells = detectAiTells(text);
  const judge = verdict(metrics, tells);

  // 平台格式校验（PRD v1）：把"是否符合平台"也变成确定性判定
  const rules = platformRules(project0?.platform);
  // 长篇每章硬下限 1800 字；50 章以内的短篇项目不设下限（平台建议字数仍照常提示）
  const minChars = chapterMinChars(project0);
  const platform = checkPlatformFormat(text, title, metrics, rules, { minChars });

  const index0 = await loadIndex(root);
  // 只有「严重」问题才退稿：AI 痕迹判"差"、命中硬规则/禁用表达。
  // 字数偏离等平台/节奏问题降为提示（info），记进平台 issues 但不整章退回——真人写网文本来就是分批写的。
  // 闸门口径只认 metrics.verdict 的「差」（high≥2 或密度 >2.5），不在 domain 再叠一层。
  const aiBad = judge.level === "差";
  const bannedHits = (bible.style?.banned || []).filter((b) => b && text.includes(b));
  // keywords 只用于「这条规则要不要进本章上下文」；trigger 是适用时机提示，不是禁用词。
  // 冲突只认 forbiddenKeywords（与 continuityCheck 共用 hardRuleHits，口径一致）。
  const ruleHits = hardRuleHits(bible.rules, text);
  const tooShort = minChars > 0 && metrics.chars < minChars;
  const hardBad = aiBad || bannedHits.length > 0 || ruleHits.length > 0 || tooShort;
  const chapterVerdict = hardBad ? "needs_fix" : "pass";

  // PRD 失败策略：不合格稿子不进正文索引、不占章号，直接落到 drafts/ 等重写。
  // 作者确认要收（force）时才落盘进正文并标 needs_fix。
  if (chapterVerdict === "needs_fix" && !force) {
    const draftDir = p(root, "drafts");
    await ensureDir(draftDir);
    const existing = index0.find((c) => Number(c.number) === Number(number));
    const draftName = `${String(number).padStart(3, "0")}-${(title || existing?.title || "draft").replace(/[\\/:*?"<>|]/g, "-")}-${Date.now().toString(36)}.md`;
    const draftFile = p(draftDir, draftName);
    await writeText(draftFile, text.trim() + "\n");
    await pruneDrafts(root, number);
    await logUsage(root, {
      kind: "commit", chapter: Number(number), chars: metrics.chars, tokens: estimateTokens(text),
      verdict: chapterVerdict, rejected: true, density: judge.density,
    });
    // 被退回 drafts 也算走过一轮重写：否则反复投稿不合格永远不会触发 MAX_REWRITE_ROUNDS。
    const projectRej = await loadProject(root);
    if (projectRej) {
      projectRej.rewriteCounts = projectRej.rewriteCounts || {};
      const rk = String(Number(number));
      projectRej.rewriteCounts[rk] = (Number(projectRej.rewriteCounts[rk]) || 0) + 1;
      await saveProject(root, projectRej);
    }
    return {
      chapter: { number: Number(number), title: title || existing?.title, verdictDraft: true },
      metrics, tells, judge, platform, chapterVerdict,
      bannedHits: (bible.style?.banned || []).filter((b) => b && text.includes(b)),
      rejected: true,
      draftFile: draftFile.replace(root + "/", ""),
      reason: [
        aiBad ? `AI 痕迹判定「差」（密度 ${judge.density}/千字）` : null,
        bannedHits.length ? `命中禁用表达：${bannedHits.join("、")}` : null,
        ruleHits.length ? `硬规则冲突：${ruleHits.map((h) => `${h.rule}(命中「${h.matched}」)`).join("；")}` : null,
        tooShort ? `正文 ${metrics.chars} 字，低于每章硬下限 ${minChars} 字（补戏再交；全书 ≤50 章的项目不设下限）` : null,
      ].filter(Boolean).join("；"),
      hint: "稿子已存 drafts/，章号没有前进。按上面的问题改完重新 novel_chapter commit；确实要收进正文可加 force:true（会标 needs_fix）。",
      file: null,
    };
  }

  const prevEntry = index0.find((c) => Number(c.number) === Number(number));
  // 章名没给就沿用旧标题，避免重交时无端生成「未命名.md」
  const file = chapterFilePath(root, number, title || prevEntry?.title);
  await writeText(file, text.trim() + "\n");
  // 章名变了会换文件名；旧文件必须跟着删，否则 chapters/ 里留孤儿
  if (prevEntry?.file && path.resolve(p(root, prevEntry.file)) !== path.resolve(file)) {
    await rmQuiet(p(root, prevEntry.file));
  }

  const index = index0;
  const entry = {
    number: Number(number),
    title: title || `第${number}章`,
    file: file.replace(root + "/", ""),
    chars: metrics.chars,
    dialogueRatio: metrics.dialogueRatio,
    verdict: judge.level, // 良/中/差（AI 痕迹维度，保留老字段）
    chapterVerdict,        // pass/needs_fix（PRD 门控维度）
    fixReasons: chapterVerdict === "needs_fix"
      ? [
          aiBad ? `AI 痕迹判定「差」（密度 ${judge.density}/千字）` : null,
          bannedHits.length ? `命中禁用表达：${bannedHits.join("、")}` : null,
          ruleHits.length ? `硬规则冲突：${ruleHits.map((h) => `${h.rule}(命中「${h.matched}」)`).join("；")}` : null,
        ].filter(Boolean)
      : [],
    aiTellDensity: judge.density,
    platformIssues: platform.issues.length,
    summary: summary || "",
    characters: characters || [],
    endHook: checkChapterEndHook(text),
    committedAt: now(),
  };
  const at = index.findIndex((c) => Number(c.number) === Number(number));
  if (at >= 0) index[at] = { ...index[at], ...entry };
  else index.push(entry);
  index.sort((a, b) => a.number - b.number);
  await writeJson(p(root, LAYOUT.chapterIndex), index);
  await rmQuiet(p(root, "review", "rewrite-request.md"));

  // 位置轨迹：本章收在哪儿就记一笔「第N章｜地点」。写下一章时按这个取当前位置，
  // 比让人物卡写一个横跨全书的「南街—城楼一线」可靠得多。
  try {
    const names = new Set(characters || []);
    const known = knownPlaceNames(bible);
    const valid = locationNameSet(bible);
    const chapterBase = lastKnownBase(text, known);
    const learned = [];
    let changed = false;
    for (const c of bible.characters || []) {
      const all = [c.name, ...(c.aliases || [])].filter(Boolean);
      if (!all.some((x) => names.has(x))) continue;
      const scenes = chapterScenes(text, all, known);
      const places = formatScenes(scenes, c.location || chapterBase, valid);
      learned.push(...places);
      const place = places[places.length - 1] || detectPlace(text.slice(-600));
      if (!place) continue;
      const trail = (Array.isArray(c.locationTrail) ? c.locationTrail : []).slice();
      const at2 = trail.findIndex((x) => Number(x.chapter) === Number(number));
      const row = { chapter: Number(number), place, places: places.length ? places : [place] };
      if (at2 >= 0) trail[at2] = row; else trail.push(row);
      trail.sort((a, b) => Number(a.chapter) - Number(b.chapter));
      c.locationTrail = trail.slice(-80);
      c.location = place;
      changed = true;
    }
    if (learnSpots(bible, learned)) changed = true;
    if (changed) await saveBible(root, bible);
  } catch { /* 轨迹记不上不影响收稿 */ }

  if (inWorldDay !== undefined && inWorldDay !== null) {
    // 同一章重写只留最新一条，否则反复提交会留下多行同一章，时间线检查会拿它跟自己对撞
    const tlRows = (await readJsonl(p(root, LAYOUT.timeline)).catch(() => []))
      .filter((r) => r && !r.__corrupt && Number(r.chapter) !== Number(number));
    tlRows.push({
      chapter: Number(number), inWorldDay: Number(inWorldDay), summary: summary || "", characters: characters || [], at: now(),
    });
    tlRows.sort((a, b) => Number(a.chapter) - Number(b.chapter));
    await writeText(p(root, LAYOUT.timeline), tlRows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  }

  const project = await loadProject(root);
  let rewriteRound = 0;
  if (project) {
    project.currentChapter = Math.max(project.currentChapter || 0, Number(number));
    // 计重写轮次：同一章此前已提交过（force 收 needs_fix 稿）就算走过一轮
    project.rewriteCounts = project.rewriteCounts || {};
    const key = String(Number(number));
    const prevHad = (project.rewriteCounts[key] || 0);
    // needs_fix 的收稿（force）每收一次算走过一轮重写
    if (chapterVerdict === "needs_fix") rewriteRound = prevHad + 1;
    project.rewriteCounts[key] = Math.max(prevHad, rewriteRound);
    // 状态机：普通模式提交后进 awaiting_review(N)；批量模式在批内继续 writing(N+1)，
    // 整批最后一章写完才进 awaiting_review，让作者一次 review。
    const segInfo = batchSeg;
    if (segInfo) {
      // 批内单章重写（novel_gate rewrite）交回来时，回到本批原本写到的位置；其余情况按顺序往下写。
      // index0 是提交「前」的快照，重交的章在里面是缺的，所以回位判断要把这一章算进去。
      const resume = project.batchResume && Number(number) < Number(project.batchResume);
      let next = Number(number) + 1;
      if (resume) {
        const have = new Set([...index0.map((c) => Number(c.number)), Number(number)]);
        const missing = [];
        for (let k = Number(segInfo.from); k <= Number(segInfo.to); k += 1) if (!have.has(k)) missing.push(k);
        // 批里还有没交的章：按顺序往下写，回位点留到批尾；全批补齐才按回位点走并清掉
        if (!missing.length) {
          next = Number(project.batchResume);
          delete project.batchResume;
          // 回位点那一章已经在正文里（例如批尾退中间章），直接收批进 review
          if (next >= Number(segInfo.to) && [...have].some((c) => c >= next)) next = Number(segInfo.to) + 1;
        }
      }
      project.gate = next > Number(segInfo.to)
        ? { phase: "awaiting_review", chapter: Number(segInfo.to), reason: `本批第${segInfo.from}-${segInfo.to}章已写完，等作者一次 review`, at: now() }
        : { phase: "writing", chapter: next, reason: `批量写作中（第${segInfo.from}-${segInfo.to}章），本批写完再 review`, at: now() };
    } else {
      project.gate = { phase: "awaiting_review", chapter: Number(number), reason: chapterVerdict === "pass" ? "等作者确认" : "有需修问题，等作者决定重写或通过", at: now() };
      delete project.batchResume;
    }
    project.gates = { ...(project.gates || {}), brief: true, bible: true, outline: true };
    // 已经写出正文，视作大纲早已确认——避免之后任何一次 acceptOutline 把 gate 砸回 bible/0
    if (!project.outlineAccepted) { project.outlineAccepted = true; project.outlineAcceptedAt = now(); }
    await saveProject(root, project);
  }
  // 提交即把该章的「全书级体检」也跑一遍（must-include-missed / 漏埋伏笔 / early-appear 等
  // 只在 continuityCheck 里才有的检查）——这样"写完提交"这一刻就能看到问题，不必等到存档后再体检。
  let chapterCheck = null;
  try { chapterCheck = await checkChapter(root, Number(entry.number)); } catch { chapterCheck = null; }
  await logUsage(root, {
    kind: "commit", chapter: Number(number), chars: metrics.chars, tokens: estimateTokens(text),
    verdict: chapterVerdict, rejected: false, density: judge.density,
  });
  return { chapter: entry, metrics, tells, judge, platform, chapterVerdict, bannedHits, ruleHits, file, rewriteRound, chapterCheck };
}

export async function readChapter(root, number) {
  const index = await loadIndex(root);
  const hit = index.find((c) => Number(c.number) === Number(number));
  if (!hit) throw new Error(`没有第 ${number} 章`);
  return { entry: hit, text: await readText(p(root, hit.file)) };
}

/**
 * 体检通过后重算本章的提交判定：AI 痕迹、禁用表达、硬规则（都是确定性检查）。
 * 都过了就把 needs_fix 改回 pass，章节标签不再一直挂着「待修」。
 */
export async function refreshChapterVerdict(root, number) {
  let index = await getIndex(root);
  const at = index.findIndex((c) => Number(c.number) === Number(number));
  if (at < 0) return null;
  const row = index[at];
  if (row.chapterVerdict !== "needs_fix") return row.chapterVerdict;
  let text = "";
  try { text = await readText(p(root, row.file)); } catch { return row.chapterVerdict; }
  const bible = await loadBible(root);
  const judge = verdict(textMetrics(text), detectAiTells(text));
  const bannedHits = (bible.style?.banned || []).filter((b) => b && text.includes(b));
  const ruleHit = hardRuleHits(bible.rules, text).length > 0;
  if (judge.level !== "差" && !bannedHits.length && !ruleHit) {
    index[at] = { ...row, chapterVerdict: "pass", verdict: judge.level, aiTellDensity: judge.density, fixClearedAt: now() };
    await writeJson(p(root, LAYOUT.chapterIndex), index);
    return "pass";
  }
  return "needs_fix";
}

/* ------------------------------ 作者三决定门 ------------------------------ */
// PRD v1 §2.3：awaiting_review(N) 停在等作者点「通过 / 重写 / 改方向」。

/** 通过本章 → writing(N+1)。必须真的存在该章，且把 index 里的 approved 置 true。 */
/**
 * 从章节索引反推「首次登场章」，补进人物卡（确定性，不调模型）。
 * - 只看 index 里每章提交时登记的 characters，不靠模型猜；
 * - 只补空值或比正文更晚的值，已经写对的绝不改；
 * - 顺带把正文里的叫法记进 aliases（「老黄」→「灯油账房老黄」）。
 * 每次 approve 都会跑一遍，所以存档后人物卡的 firstChapter 不会一直空着。
 */
export async function backfillFirstAppearances(root, index) {
  const rows = Array.isArray(index) ? index : await getIndex(root);
  const bible = await loadBible(root);
  const chars = Array.isArray(bible.characters) ? bible.characters : [];
  if (!chars.length) return [];
  // canonical(name) -> { first, alias }
  const earliest = new Map();
  for (const row of rows) {
    const n = Number(row?.number) || 0;
    if (!n) continue;
    for (const raw of row.characters || []) {
      const name = String(raw || "").trim();
      if (!name) continue;
      const hit = findSame(chars, name);
      if (!hit || !hit.name) continue;
      const cur = earliest.get(hit.name);
      if (!cur || n < cur.first) earliest.set(hit.name, { first: n, alias: name });
    }
  }
  const filled = [];
  for (const [name, info] of earliest) {
    const hit = findSame(chars, name);
    if (!hit) continue;
    const patch = { name: hit.name };
    const fields = [];
    if (!hit.firstChapter || Number(hit.firstChapter) > info.first) {
      patch.firstChapter = info.first;
      fields.push("firstChapter");
    }
    if (info.alias && info.alias !== hit.name && !isRoleDescriptor(info.alias)) {
      const aliases = [...new Set([...(hit.aliases || []), info.alias].filter(Boolean))];
      if (aliases.length !== (hit.aliases || []).length) {
        patch.aliases = aliases;
        fields.push("aliases");
      }
    }
    if (!fields.length) continue;
    await bibleUpsert(root, "character", patch, { skipGate: true });
    Object.assign(hit, patch);
    filled.push({ entity: "characters", name: hit.name, fields, firstChapter: info.first });
  }
  return filled;
}

export async function approveChapter(root, args = {}) {
  return withProjectLock(root, () => approveChapterLocked(root, args));
}

async function approveChapterLocked(root, { number, force = false } = {}) {
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  const st = gateState(project);
  let index = await getIndex(root);
  // 默认批"最后一章已提交但未通过"的章
  let n = Number(number) || 0;
  if (!n) {
    const last = [...index].sort((a, b) => b.number - a.number)[0];
    if (!last) throw new Error("还没有任何章节可确认");
    n = last.number;
  }
  let hit = index.find((c) => Number(c.number) === n);
  if (!hit) throw new Error(`第${n}章不存在，无法确认通过`);
  // 作者可以直接确认「任何还没存档的章」：先收进正文，问题按体检结果逐章 rewrite 修。
  // 不再要求必须是 gate 停的那一章——批量写到一半、前一章被退回时，后面已写好的章也能先存档。
  // （已存档的章由 index 的 approved 标记保护，不允许被再收一次覆盖。）
  if (hit.approved) {
    throw new Error(`第${n}章已经存档过了，不用再确认。要改请用 novel_gate rewrite ${n} 退回重写。`);
  }
  // needs_fix 的稿子不让"一键通过"——先改到 pass，或作者明确 force 收稿。避免不合格稿被悄悄收进正文。
  if (hit.chapterVerdict === "needs_fix" && !force) {
    // 标记可能是旧稿留下的：先按当前正文重算，正文已经干净就正常通过
    const fresh = await refreshChapterVerdict(root, n);
    if (fresh !== "pass") {
      // 只报真正导致 needs_fix 的原因（AI 痕迹差 / 硬规则冲突），字数不足只是提示，不算 needs_fix 原因
      const why = hit.verdict === "差" ? `AI 痕迹判定「差」` : `硬规则 / 禁用表达冲突`;
      throw new Error(`第${n}章是 needs_fix（${why}），不能直接通过。先按 novel_continuity 改到 pass；确实要收进正文请加 force:true。`);
    }
    index = await getIndex(root);
    hit = index.find((c) => Number(c.number) === n) || hit;
  }
  // 连续性 high 级问题 + 登场硬闸门：本章的 high（吃书/时间线倒退/伏笔到期未收等）
  // 和该登场却缺席的重要角色都直接拦下——作者确认「就这样」时用 force:true 放行。
  if (!force) {
    let chk = null;
    try { chk = await checkChapter(root, n); } catch { chk = null; }
    const highs = ((chk && Array.isArray(chk.findings)) ? chk.findings : [])
      .filter((f) => f.severity === "high" && Number(f.chapter) === Number(n));
    if (highs.length) {
      const list = highs.map((f) => `${f.code}（${f.hint || f.message}）`).join("；");
      throw new Error(`第${n}章还有 ${highs.length} 条 high 级连续性问题：${list}。先按 novel_continuity 修，确认要照收请加 force:true。`);
    }
    const misses = (chk && Array.isArray(chk.debutMisses)) ? chk.debutMisses : [];
    if (misses.length) {
      const list = misses.map((f) => `「${String(f.message || "").replace(/^.*?「|」.*$/g, "")}」`).join("、");
      throw new Error(`第${n}章有重要角色该登场却未登场/迟到（${list}）。先补戏或改设定登场章；确认就是背景板、要照收请加 force:true。`);
    }
  }
  // 通过范围：以要确认的这一章为终点，往前收「连续已写」的那一串。
  // 中间遇到缺口就停在缺口前一章——缺的章永远不许被静默跳过；
  // 但批首之前就缺的章（例如第1章还没写、第2章已写好）不拦第2章的确认。
  const seg = await chapterFromSegment(root, n);
  const have = new Set(index.map((c) => Number(c.number)));
  let batchNums = [n];
  if (seg) {
    const from = Number(seg.from);
    if (!have.has(Number(n))) {
      throw new Error(`第${n}章不在正文里，没法确认（被退回还没重写）。先 novel_gate rewrite ${n} 写回来再确认。`);
    }
    // 只有确认「本批最后一章」时才整批一起收；确认中间/开头的某章就只收这一章，
    // 这样作者可以先单独存档第 1 章，后面 2-10 章按各自体检结果逐章决定。
    if (Number(n) === Number(seg.to)) {
      const run = [];
      for (let k = Number(seg.to); k >= from; k -= 1) { if (!have.has(k)) break; run.unshift(k); }
      batchNums = run.length ? run : [n];
    }
  }
  if (!force && batchNums.length > 1) {
    const bad = index.filter((c) => batchNums.includes(Number(c.number)) && c.chapterVerdict === "needs_fix");
    if (bad.length) {
      throw new Error(`这一批还有 needs_fix 的章：第${bad.map((c) => c.number).join("、")}章。先按 novel_continuity 改到 pass；确认要照收请加 force:true。`);
    }
  }
  // 写回 approved 标记（批量时整批一起写）
  for (const num0 of batchNums) {
    const i0 = index.findIndex((c) => Number(c.number) === num0);
    if (i0 >= 0) index[i0] = { ...index[i0], approved: true, approvedAt: index[i0].approvedAt || now() };
  }
  await writeJson(p(root, LAYOUT.chapterIndex), index);
  if (project.rewriteCounts) {
    // 通过即清零该章（整批）重写轮次
    for (const num0 of batchNums) delete project.rewriteCounts[String(num0)];
  }
  // 下一章 = 这批里第一个还没写、也没通过确认的章；整批都收了才跳到批尾之后。
  const lastDone = Math.max(...batchNums);
  // 缺口 = 这批里第一个「正文里还没有」的章（真缺的章要先写）；
  // 整批收完才看「还没通过确认」的章，否则单个确认完又会把 gate 拉回同批最早一章。
  const approvedNow = new Set(index.filter((c) => c.approved).map((c) => Number(c.number)));
  const missingFirst = seg
    ? (() => { for (let k = Number(seg.from); k <= Number(seg.to); k += 1) if (!have.has(k)) return k; return null; })()
    : null;
  const unapprovedFirst = seg
    ? (() => { for (let k = Number(seg.from); k <= Number(seg.to); k += 1) if (!approvedNow.has(k)) return k; return null; })()
    : null;
  const firstHole = missingFirst || (batchNums.length > 1 ? unapprovedFirst : null);
  const nextChapter = firstHole || (batchNums.length > 1 ? Number(seg.to) + 1 : n + 1);
  project.gate = {
    phase: "writing", chapter: nextChapter,
    reason: firstHole
      ? `${batchNums[0] === lastDone ? `第${lastDone}章` : `第${batchNums[0]}-${lastDone}章`}已通过，接着写第${nextChapter}章（本批还剩到第${seg.to}章）`
      : batchNums.length > 1 ? `第${seg.from}-${seg.to}章一次 review 通过，开始写第${nextChapter}章` : `第${n}章已通过，开始写第${n + 1}章`,
    at: now(),
  };
  await saveProject(root, project);
  // 通过即写本章记忆：工具和界面都从这里走，不依赖前端再补一刀。
  // 批量通过时每章都写一条；模型精炼之后会覆盖，模型失败时至少还有摘要级记忆。
  for (const num0 of batchNums) {
    const row = index.find((c) => Number(c.number) === num0) || hit;
    await appendMemory(root, {
      chapter: num0,
      title: row.title || "",
      summary: clampSummary(row.summary || "", 240),
      events: [],
      state: "",
      characters: row.characters || [],
      source: "index",
    }).catch(() => null);
  }
  // 存档即补登场章：确定性反推，不依赖模型；失败不影响通过。
  const debutFilled = await backfillFirstAppearances(root, index).catch(() => []);
  return {
    ok: true, approved: n, nextChapter,
    batchApproved: batchNums.length > 1 ? batchNums : undefined,
    // 调用方据此决定「补设定」的范围：整批通过就整批一起补，逐章通过就补这一章
    approvedChapters: batchNums,
    forced: hit.chapterVerdict === "needs_fix", debutFilled,
  };
}

/** 重写请求：真退稿——把该章从正文索引移除（章号与文件都释放），稿子存 drafts；不占章号。 */
export async function requestRewrite(root, args = {}) {
  return withProjectLock(root, () => requestRewriteLocked(root, args));
}

async function requestRewriteLocked(root, { number, note } = {}) {
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  const st = gateState(project);
  const n = Number(number) || (st.phase === "awaiting_review" ? Number(st.chapter) : 0) || project.currentChapter || 0;
  const index0 = await getIndex(root);
  // 批内单章重写：本批还在写（writing）或已写到批尾（awaiting_review 最后一章）时，
  // 都允许把本批任意一章退回去重写。gate 指回那一章，其余章原样留在正文，重写完再回批尾。
  const segOf = (c) => (c > 0 ? chapterFromSegment(root, c) : Promise.resolve(null));
  const seg0 = st.phase === "awaiting_review" ? await segOf(Number(st.chapter)) : await segOf(n);
  const batchMid = Boolean(seg0 && n >= seg0.from && n <= seg0.to
    && ((st.phase === "writing" && n < Number(st.chapter)) || (st.phase === "awaiting_review" && n <= Number(st.chapter))));
  // 只能重写「真的存在且当前待确认」的那一章，否则状态会被改错（比如第1章待确认时说重写第2章）。
  const target = index0.find((c) => Number(c.number) === n);
  if (!target) throw new Error(`第${n}章不存在，没有可重写的稿子。当前待确认的是${st.phase === "awaiting_review" ? `第${st.chapter}章` : "无"}`);
  if (!batchMid && (st.phase !== "awaiting_review" || Number(st.chapter) !== n)) {
    const cur = st.phase === "awaiting_review" ? `第${st.chapter}章` : "（当前没有待确认的章）";
    throw new Error(`只能重写当前待确认的那一章。现在待确认的是${cur}，不是第${n}章。`);
  }
  // 批内重写：gate 回到该章，写完 commit 后要接着写本批原本的下一章，而不是只 +1
  const resumeChapter = batchMid ? Number(seg0.to) : 0;
  const noteText = (note || "").trim();
  await writeText(
    p(root, "review", "rewrite-request.md"),
    `# 第${n}章重写请求\n\n- 时间：${now()}\n\n## 必须改掉的问题\n${noteText || "（作者没附具体问题，按体检结果改）"}\n\n重新写这一章，只改命中的段落，不要整章推倒重来，不要改情节走向。\n`,
  );
  // 真退稿：从 index 移除，文件移到 drafts/，项目 currentChapter 回退
  const index = await getIndex(root);
  const at = index.findIndex((c) => Number(c.number) === n);
  if (at >= 0) {
    const entry = index[at];
    try {
      const src = p(root, entry.file);
      const draftDir = p(root, "drafts");
      await ensureDir(draftDir);
      const draftFile = p(draftDir, `${String(n).padStart(3, "0")}-${entry.title || "draft"}-${Date.now().toString(36)}.md`);
      await writeText(draftFile, await readText(src));
      await rmQuiet(src);
      await pruneDrafts(root, n);
    } catch { /* 文件已不在就跳过 */ }
    index.splice(at, 1);
    await writeJson(p(root, LAYOUT.chapterIndex), index);
  }
  project.currentChapter = Math.max(0, n - 1);
  project.gate = { phase: "writing", chapter: n, reason: `第${n}章已重写中：${noteText || "按体检问题改"}${batchMid ? `（批内单章重写，写完继续第${resumeChapter}章）` : ""}`, at: now() };
  if (batchMid) project.batchResume = resumeChapter;
  // 与批次无关的退回（单章模式）要清掉旧回位点，免得下一次提交被带到别的章
  else if (!seg0 && project.batchResume) delete project.batchResume;
  // 批内重写不占用去 AI 味的自动重试额度，否则第 3 轮就写不进去了
  if (batchMid && project.rewriteCounts) delete project.rewriteCounts[String(n)];
  await saveProject(root, project);
  return { ok: true, rewriteOf: n, note: noteText, revertedTo: project.currentChapter, batchResume: batchMid ? resumeChapter : undefined };
}

/** 改方向：写 directionHistory + bible.style，仅后续章生效（不回改已写章）。 */
export async function changeDirection(root, args = {}) {
  return withProjectLock(root, () => changeDirectionLocked(root, args));
}

async function changeDirectionLocked(root, { direction, style } = {}) {
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  const dir = (direction || "").trim();
  if (!dir) throw new Error("需要 direction（新的方向说明）");
  const awaiting = project.gate?.phase === "awaiting_review";
  project.directionHistory = Array.isArray(project.directionHistory) ? project.directionHistory : [];
  project.directionHistory.push({ direction: dir, atChapter: project.currentChapter || 0, at: now() });
  project.direction = dir;
  await saveProject(root, project);
  if (style && typeof style === "object") await bibleUpsert(root, "style", style);
  const n = project.currentChapter || 0;
  // 待确认时改方向只影响后续章：本章稿子还在等作者通过/重写，gate 不能跳到 writing(N+1)，
  // 否则 approve 和 commit 都会因为「当前没有待确认章」/「不是当前待写章」而卡死。
  if (awaiting) {
    return { ok: true, direction: dir, effectiveFrom: n + 1, gate: project.gate, note: "方向只对后续章生效，本章仍待确认" };
  }
  project.gate = { phase: "writing", chapter: n + 1, reason: `方向已调整，从第${n + 1}章起生效`, at: now() };
  await saveProject(root, project);
  return { ok: true, direction: dir, effectiveFrom: n + 1 };
}

/** 伏笔改期（reschedule）。 */
export async function rescheduleForeshadow(root, args = {}) {
  return withProjectLock(root, () => rescheduleForeshadowLocked(root, args));
}

async function rescheduleForeshadowLocked(root, { name, dueChapter, note }) {
  const rows = await readJsonl(p(root, LAYOUT.foreshadow));
  const open = foldForeshadow(rows).find((f) => f.name === name || f.id === name);
  if (!open) throw new Error(`没有在账的伏笔：${name}`);
  const due = Number(dueChapter) || open.dueChapter;
  await appendJsonl(p(root, LAYOUT.foreshadow), {
    id: open.id, op: "reschedule", name: open.name, plantedChapter: open.plantedChapter,
    dueChapter: due, status: "open", note: note || `改期到第${due}章`, at: now(),
  });
  return { ok: true, id: open.id, name: open.name, dueChapter: due };
}

/* ------------------------------ 章节导出 ------------------------------ */
// PRD v1 §4.7：导出 txt；单章去掉 Markdown、段首缩进两格；全书按卷合并 + 设定集附录（可开关）。

function deMarkdown(text) {
  // 段落：按空行切，去 Markdown 标记，段首补两个全角空格
  return String(text)
    .replace(/\r\n/g, "\n")
    .replace(/^#{1,6}\s*/gm, "")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/[*_`]/g, "")
    .split(/\n\s*\n/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => "　　" + s.replace(/\n/g, ""))
    .join("\n\n");
}

export async function exportChapters(root, { from = 1, to, scope = "single", includeBible = false } = {}) {
  // 说明：导出文件名固定为「第NNN章-标题.txt」（连字符）。正文读取请用 novel_chapter op=read，
  // 不要去 exports/ 读 txt（那是给作者下载用的成品，不是账本）。
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  const index = await loadIndex(root);
  if (!index.length) throw new Error("还没有章节可导出");
  const outDir = p(root, "exports");
  await ensureDir(outDir);
  const written = [];

  const range = index.filter((c) => c.number >= from && (to === undefined || c.number <= to));
  // 章名多半只存标题，导出时补上章号，成品 txt 才不会看不出顺序
  const heading = (c) => {
    const t = c.title || "";
    return /^第\s*\d+\s*章/.test(t) ? t : `第${c.number}章 ${t}`.trim();
  };

  if (scope === "single" || range.length === 1) {
    const one = range[range.length - 1] || index[index.length - 1];
    const c = await readChapter(root, one.number);
    const name = `第${pad3(one.number)}章-${(one.title || "未命名").replace(/[\\/:*?"<>|]/g, "-")}.txt`;
    const file = p(outDir, name);
    await writeText(file, `${heading(one)}\n\n${deMarkdown(c.text)}\n`);
    written.push(file);
    return { ok: true, files: written, count: 1 };
  }

  // 全书 / 多章：合并到一个文件
  const parts = [];
  for (const c of range) {
    const ch = await readChapter(root, c.number);
    parts.push(`## ${heading(c)}\n\n${deMarkdown(ch.text)}`);
  }
  let body = `# ${project.title}\n\n> ${project.genre || ""} · ${project.platform || ""}\n\n` + parts.join("\n\n");
  if (includeBible) {
    const bible = await loadBible(root);
    const dump = [
      ["人物", bible.characters], ["世界观", bible.world], ["硬规则", bible.rules],
      ["势力", bible.factions || []], ["地点", bible.locations || []], ["物品", bible.items || []],
    ].map(([label, list]) => (list && list.length ? `### ${label}\n` + list.map((x) => `- ${x.name || x.id}${x.role ? `｜${x.role}` : ""}${x.text ? `：${x.text}` : ""}`).join("\n") : "")).filter(Boolean).join("\n\n");
    if (dump) body += `\n\n---\n\n# 设定集附录\n\n${dump}`;
  }
  const file = p(outDir, `${project.title}-全书.txt`.replace(/[\\/:*?"<>|]/g, "-"));
  await writeText(file, body + "\n");
  written.push(file);
  return { ok: true, files: written, count: range.length };
}

/* ------------------------------ 上下文包 ------------------------------ */

const tail = (s, n) => (s.length <= n ? s : s.slice(-n));

/**
 * 长期记忆（叙事记忆）核心：把「已经写过的每一章」压成可检索的档案。
 * 每章档案包含：章号/标题/摘要/出场人物/该章发生的关键事件/该章推进到的状态。
 * 目的——写第 N 章之前，能明确知道第 2..N-1 章到底写了什么，而不是只给一个大纲切片和上一章结尾。
 *
 * 数据源优先级：index（summary/characters）为主；ledger/memory.jsonl（AI 精炼的章节传记）为辅。
 */
/**
 * 场景切分（确定性）：把一章正文按「场景跳转」切成若干段。
 * 判据：空行（>=2 换行）分节；或出现时间/地点跳转词（次日/翌日/片刻后/三小时后/回到/来到/走进/离开…）另起一段。
 * 这不是语义理解，只是给「叙事断层检查」和「上下文注入」提供可读的段边界。返回 [{i, text}]。
 */
const SCENE_SHIFT_RE = /(次日|翌日|第二天|当夜|当晚|片刻后|半[个]?小时[后之]|数小时后|三小时后|几小时后|稍后|稍顷|与此同时|另一边|另一头|回到|回到了|来到|赶往|走进|走进|踏进|离开|出了|走进|推门|跨进|转场|傍晚|清晨|深夜|午后)/;
export function splitScenes(text) {
  const raw = String(text || "").replace(/\r\n/g, "\n");
  const paras = raw.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  // 场景 = 连续段落合并；遇到「段首出现场景跳转词」的段落就在它之前切一刀。
  // 这样一段几百字的长夜戏不会被拆成 70 段，而"次日/回到/来到/走进…"这类真正的转场会切开。
  const HEAD_SHIFT_RE = /^(次日|翌日|第二天|当晚|当夜|片刻后|半[个]?小时[后之]|数小时后|几个小时后|三小时后|几小时后|一小时后|十分钟后|稍后|稍顷|与此同时|另一边|另一头|回到|回到家|回家|来到|赶往|走进|踏进|推门|跨进|离开|出了|走出|到了|赶到|傍晚|清晨|深夜|午后|天亮了|天亮时|后来|第二天一早|警局|医院|门口)/;
  const scenes = [];
  let cur = [];
  for (const para of paras) {
    if (cur.length && HEAD_SHIFT_RE.test(para)) { scenes.push(cur.join("\n")); cur = []; }
    cur.push(para);
  }
  if (cur.length) scenes.push(cur.join("\n"));
  // 若转场太少（场景数偏少），按字数补充切分，保证长章至少有 ~800 字/段，便于逐段做断层比对
  const totalLen = paras.join("").length;
  const wantMin = Math.max(2, Math.min(8, Math.round(totalLen / 900)));
  if (scenes.length < wantMin) {
    const flat = paras;
    const per = Math.ceil(flat.length / wantMin);
    const out = [];
    for (let i = 0; i < flat.length; i += per) out.push(flat.slice(i, i + per).join("\n"));
    return out.map((t, i) => ({ i: i + 1, text: t }));
  }
  if (scenes.length <= 1) {
    const flat = paras;
    const target = Math.max(3, Math.min(6, Math.ceil(flat.length / 8)));
    const per = Math.ceil(flat.length / target);
    const out = [];
    for (let i = 0; i < flat.length; i += per) out.push(flat.slice(i, i + per).join("\n"));
    return out.map((t, i) => ({ i: i + 1, text: t }));
  }
  return scenes.map((t, i) => ({ i: i + 1, text: t }));
}

/**
 * 提取「某一章结尾」的在场者与地点（确定性启发式，供写下一章前对齐用）。
 * 取最后 2 段：出现的人名（与 bible 角色名求交）+ 末段里的地点词（含"在/到了/进了/警局/家中/门口…"附近名词）。
 * 返回 { chars:[], place:"", tail:"" }。粗糙但够提示用。
 */
/** 正文结尾最后出现的地点；「门槛/台阶」这类站位退一格取前面的地点名。 */
function detectPlace(tail) {
  const placeRe = /(?:在|到了|来到|进了|走进|走回|回到|回了|守在|坐在|蹲在|站在)([\u4e00-\u9fa5]{0,8}(?:局|院|家|楼|室|房|店|铺|街|路|站|桥|巷|庙|衙署|码头|门口|门槛|台阶|墙根|墙|街口|大厅|办公室|现场))/g;
  const hits = [...String(tail || "").matchAll(placeRe)].map((m) => m[1]).filter(Boolean);
  let place = hits.length ? hits[hits.length - 1] : "";
  if (["门槛", "台阶", "墙根", "街口", "门口"].includes(place) && hits.length > 1) place = hits[hits.length - 2];
  return place;
}

// 章内轨迹只认设定里的地点名，不从正文瞎抽「这堂」「柳承影站」这类词。
// 一地点名 2 字起，单字地点（堂/院/街）太容易撞普通用词，直接不收。
function knownPlaceNames(bible) {
  const rows = [];
  const push = (s, label, spot) => {
    const v = String(s || "").trim();
    if (v.length >= 2) rows.push({ s: v, label, spot: spot || "" });
  };
  for (const l of bible.locations || []) {
    const base = String(l.name || "").trim();
    if (!base) continue;
    push(base, base);
    for (const a of l.aliases || []) push(a, base);
    // 细分位置：堂门口、木牌底下、夹道…；正文只写细分名字也能落到父地点上
    const spots = Array.isArray(l.spots) ? l.spots : String(l.spots || "").split(/[、,，/｜|\s]+/);
    for (const sp of spots) {
      const v = String(sp || "").trim();
      push(v, base, v);
    }
  }
  // 长名优先，避免「堂口」先吃掉「第一堂口」
  return rows.sort((a, b) => b.s.length - a.s.length);
}

// 地点后面的细分位置：联审堂（堂门口）、联审堂（木牌下）
const SUB_PLACE_RE = /的?(?:(?:堂|院|楼|屋|店|铺|庙|厅|廊|窗|门)?(?:门口|门前|门内|门外|门边|堂下|堂前|堂后|堂外|院内|院中|院外|楼下|楼上|屋里|屋外|廊下|廊前|窗下|台阶|门槛|墙根|后院|前厅|侧厅|偏厅)|(?:木牌|牌子|牌|门|堂|树|墙)?底下|木牌下|牌子下|牌下)/;
// 正文里没写父地点、只写了「廊口 / 木牌底下 / 堂侧」时，至少把这一拍记下来。
// 只在动词/介词后面抓，且要求 2 字以上，避免「身后」「时候」这类误伤。
const SPOT_RE = /(?:走到|走进|走入|走过|走近|来到|赶到|回到|退回|退到|进了|入了|出了|站在|坐在|蹲在|守在|靠在|停在|穿过|转进|转向|上了|下了|从|沿|往|向|在)((?:(?!坐|站|走|跑|看|说|笑|问|答|抬|转|伸|退|进)[\u4e00-\u9fa5]){1,4}(?:口|尾|尽头|底下|之下|侧|后|前|内|外|上|下))/g;
const SPOT_NOISE = new Set([
  "之后", "以前", "以上", "以下", "以后", "身后", "背后", "眼下", "手下", "脚下", "头上",
  "身上", "心里", "面上", "世上", "天下", "地下", "底下", "边上", "中途", "其中",
  "案上", "案下", "瓦上", "簿上", "纸上", "桌上", "床上", "椅上", "柜上", "架上", "凳上",
  "榻上", "席上", "手上", "膝上", "肩上", "背上", "膝下",
  "最上", "最下", "最前", "最后",
]);

function spotsIn(para) {
  const out = [];
  for (const m of String(para || "").matchAll(SPOT_RE)) {
    let w = String(m[1] || "").replace(/^的/, "");
    if (/^[他她我你]/.test(w)) w = w.slice(1);
    if (w.length < 2 || SPOT_NOISE.has(w)) continue;
    if (/^[这那该每各此]/.test(w)) continue;
    // 「就把我扣下」「哪本簿子上」这类是整个短句，不是位置
    if (/[我你他她它这那哪就都把被本]/.test(w)) continue;
    // 身体部位和器物表面不是地点
    if (/[身体心眼手脚头脸胸背腰膝腿肩肋额嘴鼻耳脖腕颈穴眉喉腹臀颧鬓痕案桌床椅柜架凳瓦纸笔簿册伞]/.test(w.replace(/(?:尽头|底下|之下|口|尾|侧|后|前|内|外|上|下)$/, ""))) continue;
    if (w !== out[out.length - 1]) out.push(w);
    if (out.length >= 10) break;
  }
  return out;
}

export function spotScenes(text, names) {
  const paras = String(text || "").split(/\n+/).map((s) => s.trim()).filter(Boolean);
  const wanted = (names || []).filter(Boolean);
  const scan = (paragraphs, limit) => {
    const out = [];
    for (const para of paragraphs) {
      for (const w of spotsIn(para)) {
        if (w !== out[out.length - 1]) out.push(w);
        if (out.length >= limit) break;
      }
      if (out.length >= limit) break;
    }
    return out;
  };
  // 先只看提到这个人的段落；太少就退到整章（POV 章节里同一场戏常不重复点人名）
  const own = scan(paras.filter((p) => !wanted.length || wanted.some((n) => p.includes(n))), 10);
  return own.length >= 3 ? own : scan(paras, 10);
}

/** 一章里按出现顺序排出的地点序列；给了 names 就只看提到这些人的段落。 */
function chapterScenes(text, names, known) {
  const paras = String(text || "").split(/\n+/).map((s) => s.trim()).filter(Boolean);
  const wanted = (names || []).filter(Boolean);
  const out = [];
  let lastBase = "";
  for (const para of (known && known.length ? paras : [])) {
    if (wanted.length && !wanted.some((n) => para.includes(n))) continue;
    const scenes = knownScenesIn(para, known, lastBase);
    if (scenes.length) {
      for (const sc of scenes) {
        if (sc.base) lastBase = sc.base;
        const last = out[out.length - 1];
        if (!last || last.base !== sc.base || last.spot !== sc.spot) out.push(sc);
      }
    } else {
      // 这一段只写了「牌后 / 廊尾」这种具体位置，父地点由上一拍或上一章补
      for (const w of spotsIn(para)) {
        const hit = known.find((n) => n.s !== w && w.startsWith(n.s) && n.label);
        out.push(hit ? { base: hit.label, spot: w.slice(hit.s.length).replace(/^的/, "") } : { base: "", spot: w });
      }
    }
    if (out.length >= 12) break;
  }
  if (out.length) return out.slice(0, 12);
  return spotScenes(text, wanted).map((w) => {
    const hit = known.find((n) => n.s !== w && w.startsWith(n.s) && n.label);
    return hit ? { base: hit.label, spot: w.slice(hit.s.length).replace(/^的/, "") } : { base: "", spot: w };
  });
}

/** 一段里出现的设定地点；「带着街上的潮气」「回忆阴司档房」这类不算。 */
function knownScenesIn(para, known, lastBase) {
  const out = [];
  let i = 0;
  while (i < para.length) {
    let best = null;
    for (const n of known) {
      const at = para.indexOf(n.s, i);
      if (at < 0) continue;
      if (!best || at < best.at || (at === best.at && n.s.length > best.s.length)) best = { at, s: n.s, label: n.label, spot: n.spot };
    }
    if (!best) break;
    const sub = ((para.slice(best.at + best.s.length, best.at + best.s.length + 14).match(SUB_PLACE_RE) || [""])[0] || "").replace(/^的/, "");
    const before = para.slice(Math.max(0, best.at - 2), best.at);
    const after = para[best.at + best.s.length] || "";
    const isSpot = best.label !== best.s;
    if (!sub && (after === "的" || /[着的地得]$/.test(before))) { i = best.at + best.s.length; continue; }
    const near = para.slice(Math.max(0, best.at - 8), best.at + best.s.length + 8);
    if (!isSpot && !/[在进到回出来去走跑站坐蹲守望看等穿过跨退转靠沿往向离]/.test(near) && !sub) {
      i = best.at + best.s.length; continue;
    }
    // 学到的细分位置不能反过来把别的章节硬拽到自己名下：
    // 只写「牌后」而没写父地点、也不是当前场景时，按无父地点处理
    const spotOnly = isSpot && best.label !== lastBase && !para.includes(best.label);
    out.push(spotOnly ? { base: "", spot: best.spot } : { base: best.label, spot: sub || best.spot || "" });
    i = best.at + best.s.length;
  }
  return out;
}

/** 「档房（牌后）」里的父地点，用来接住只有细分位置的那些拍。 */
const baseOf = (place) => String(place || "").replace(/（.*?）\s*$/, "").trim();

/** 写成显示用的「父地点（细分）」；没有父地点时退回上一章的地点。 */
function formatScenes(scenes, prevPlace, validNames) {
  const prevBase = baseOf(prevPlace);
  let lastBase = validNames && validNames.has(prevBase) ? prevBase : "";
  return scenes.map((s) => {
    if (s.base) {
      lastBase = s.base;
      return s.spot ? `${s.base}（${s.spot}）` : s.base;
    }
    return lastBase ? `${lastBase}（${s.spot}）` : s.spot;
  });
}

function locationNameSet(bible) {
  const set = new Set();
  for (const l of bible.locations || []) {
    if (l.name) set.add(String(l.name).trim());
    for (const a of l.aliases || []) if (a) set.add(String(a).trim());
  }
  return set;
}

/** 整章最后提到的那个设定地点，用来给「只有细分位置」的拍当父地点。 */
function lastKnownBase(text, known) {
  let at = -1;
  let label = "";
  for (const n of known) {
    if (n.spot) continue;
    const i = String(text || "").lastIndexOf(n.s);
    if (i > at) { at = i; label = n.label; }
  }
  return label;
}

/** 正文里学到的细分位置写回地点设定，下次同一個词能直接挂到父地点上。 */
function learnSpots(bible, places) {
  let changed = false;
  for (const p of places || []) {
    const m = String(p || "").match(/^(.+?)（(.+)）$/);
    if (!m) continue;
    const [, base, spot] = m;
    const loc = (bible.locations || []).find((l) => l.name === base || (l.aliases || []).includes(base));
    if (!loc) continue;
    const list = Array.isArray(loc.spots) ? loc.spots.slice() : String(loc.spots || "").split(/[、,，/｜|\s]+/).filter(Boolean);
    if (!list.includes(spot)) {
      list.push(spot);
      loc.spots = list.slice(-20);
      changed = true;
    }
  }
  return changed;
}

export async function endSceneState(root, { chapter } = {}) {
  const n = Number(chapter) || 0;
  if (!n) return { chars: [], place: "", tail: "" };
  let text = "";
  try { text = (await readChapter(root, n)).text; } catch { return { chars: [], place: "", tail: "" }; }
  const tail = text.slice(-600);
  const bible = await loadBible(root);
  const names = bible.characters.flatMap((c) => [c.name, ...aliasesOf(c)]).filter(Boolean);
  const chars = [...new Set(names.filter((nm) => nm && tail.includes(nm)))];
  // 优先用设定里的地点名，取正文中最靠后出现的那个；设定没登记才退回启发式
  let place = "";
  let at = -1;
  for (const n of knownPlaceNames(bible)) {
    const i = text.lastIndexOf(n.s);
    if (i > at) { at = i; place = n.label; }
  }
  if (!place) place = detectPlace(tail);
  return { chars, place, tail: tail.replace(/\s+/g, " ").slice(-160) };
}

/** 老项目一次性回填位置轨迹：按已收章节的章内地点序列补，跑过一次就记 flag 不再读全本。 */
export async function backfillLocationTrail(root) {
  const project = await loadProject(root);
  // 之前版本存的「这堂」「柳承影站」是噪声；flag 不到 13 就整表重建
  if (!project || Number(project.locationTrailBackfilled) >= 13) return false;
  const bible = await loadBible(root);
  if (!(bible.characters || []).length) return false;
  const index = await loadIndex(root);
  if (!index.length) return false;
  const known = knownPlaceNames(bible);
  const valid = locationNameSet(bible);
  let changed = false;
  const fresh = new Map((bible.characters || []).map((c) => [c, []]));
  const learned = [];
  const prevPlace = new Map();
  for (const row of index) {
    let text = "";
    try { text = (await readChapter(root, row.number)).text; } catch { continue; }
    const names = new Set(Array.isArray(row.characters) ? row.characters : []);
    const chapterBase = lastKnownBase(text, known);
    for (const c of bible.characters) {
      const all = [c.name, ...(c.aliases || [])].filter(Boolean);
      if (!all.some((x) => names.has(x))) continue;
      const scenes = chapterScenes(text, all, known);
      const places = formatScenes(scenes, prevPlace.get(c) || chapterBase, valid);
      learned.push(...places);
      const place = places[places.length - 1] || detectPlace(text.slice(-600));
      if (!place) continue;
      prevPlace.set(c, place);
      fresh.get(c).push({ chapter: Number(row.number), place, places: places.length ? places : [place] });
      changed = true;
    }
  }
  for (const [c, rows] of fresh) {
    rows.sort((a, b) => Number(a.chapter) - Number(b.chapter));
    c.locationTrail = rows.slice(-80);
    if (rows.length) c.location = rows[rows.length - 1].place;
  }
  // 清掉上一版误挂到别的父地点下的细分位置（如把「候判廊尽头」挂给第一堂口）
  for (const l of bible.locations || []) {
    const list = Array.isArray(l.spots) ? l.spots.slice() : String(l.spots || "").split(/[、,，/｜|\s]+/).filter(Boolean);
    const cleaned = list.filter((sp) => !SPOT_NOISE.has(String(sp)) && ![...valid].some((n) => n && n !== l.name && String(sp).includes(n)));
    if (cleaned.length !== list.length) { l.spots = cleaned; changed = true; }
  }
  if (learnSpots(bible, learned)) changed = true;
  project.locationTrailBackfilled = 13;
  if (changed) await saveBible(root, bible);
  await saveProject(root, project);
  return changed;
}

export async function buildMemoryLedger(root) {
  const index = await loadIndex(root);
  const memRows = await readJsonl(p(root, "ledger/memory.jsonl")).catch(() => []);
  const memByNum = new Map();
  for (const r of memRows) if (r && !r.__corrupt && r.chapter != null) memByNum.set(Number(r.chapter), r);
  return index
    .slice()
    .sort((a, b) => a.number - b.number)
    .map((c) => {
      const m = memByNum.get(Number(c.number)) || {};
      return {
        number: c.number,
        title: c.title || "",
        summary: (c.summary || m.summary || "").trim(),
        characters: Array.isArray(c.characters) ? c.characters : (m.characters || []),
        events: Array.isArray(m.events) ? m.events : [],
        state: m.state || "",
      };
    });
}

/**
 * 生成「到第 N 章之前」的叙事记忆摘要（写新章前必须看）。
 * 近 STRONG 章给全摘要；更早的章压成一行（章号+标题+摘要首句）；再加「累计状态」。
 * 这样不管写到第几章，上下文都稳定在预算内，且记得住前情。
 */
const MEM_STRONG = 6;   // 最近 6 章给完整摘要
const MEM_FAR_LINE = 60; // 更早的章每章一句
export async function narrativeMemory(root, { chapter } = {}) {
  const n = Number(chapter) || 0;
  const ledger = await buildMemoryLedger(root);
  const before = ledger.filter((c) => Number(c.number) < n);
  if (!before.length) return { text: "", chars: 0, covered: 0 };
  const strongFrom = Math.max(1, n - MEM_STRONG);
  const far = before.filter((c) => c.number < strongFrom);
  const strong = before.filter((c) => c.number >= strongFrom);
  const lines = [];
  if (far.length) {
    lines.push("### 前情提要（更早章节，一句一章）");
    lines.push(`${far.length} 章，从第 ${far[0].number} 章到第 ${far[far.length - 1].number} 章：`);
    for (const c of far) {
      const one = (c.summary || "").split(/[。！？\n]/)[0].slice(0, MEM_FAR_LINE);
      lines.push(`- 第${c.number}章《${c.title}》：${one || "（无摘要）"}`);
    }
  }
  lines.push("\n### 最近几章（完整摘要，写新章必须接得上）");
  for (const c of strong) {
    lines.push(`- 第${c.number}章《${c.title}》（${(c.characters || []).join("、") || "未记人物"}）`);
    if (c.summary) lines.push(`  摘要：${c.summary}`);
    if (c.events.length) lines.push(`  关键事件：${c.events.join("；")}`);
    if (c.state) lines.push(`  结束时状态：${c.state}`);
  }
  const text = lines.join("\n");
  return { text, chars: text.length, covered: before.length };
}

export async function buildContext(root, { chapter, budgetChars, characters } = {}) {
  const g = await guardGate(root, "context_pack", { chapter });
  if (!g.ok) throw new Error(g.error);
  const project = await loadProject(root);
  const bible = await loadBible(root);
  const stylePreset = STYLE_PRESETS[bible.style?.preset] || null;
  const n = Number(chapter) || 1;
  const prevNo = n - 1;
  let prevText = "";
  let prevEntry = null;
  if (prevNo >= 1) {
    try {
      const c = await readChapter(root, prevNo);
      prevEntry = c.entry;
      prevText = c.text.trim();
    } catch { /* 第一章 */ }
  }
  const fsState = await listForeshadow(root, n);
  // 批次模式：整批共用一份段落纲，本章不再有 beats；老模式继续用逐章细纲。
  const segInfo = await chapterFromSegment(root, n);
  const outline = segInfo ? null : await getOutline(root, chapter);
  const index = await loadIndex(root);
  // 「必须回避」里点名的角色不能算出场——否则前几章就会把几十章后才登场的人塞进上下文
  const outlineFull = [outline?.beats || [], outline?.mustInclude || [], segInfo ? segInfo.text : []].flat().join(" ");
  // PRD §上下文包收窄：只给「本章真要出场」的角色——上章出场 + 本章细纲点名 + 作者显式指定。
  // 不再把所有角色卡一股脑塞进去（那是"上下文膨胀"的主要来源）。
  const named = new Set(prevEntry?.characters || []);
  const relevant = new Set();
  for (const x of named) relevant.add(String(x));
  // 细纲里写的是别名（小默/默哥）也算点名
  for (const c of bible.characters) if (c.name && aliasesOf(c).some((a) => outlineFull.includes(a))) relevant.add(c.name);
  for (const x of characters || []) relevant.add(String(x));
  const cast = [];
  for (const name of relevant) {
    const c = resolveCharacter(bible, name);
    if (!c) continue;
    // 人物卡说某人第 N 章才登场，就绝不提前把他的卡喂给正文
    if (c.firstChapter != null && c.firstChapter !== "" && Number(c.firstChapter) > n) continue;
    if (!cast.some((x) => x.name === c.name)) cast.push(c);
  }
  // 硬规则全量给：既然叫"硬规则"，就一条都不能漏，不能按关键词筛掉。
  const hardRules = bible.rules || [];

  const volumes = await loadVolumes(root);
  const curVol = volumeOf(volumes, n);
  const mem = await buildEchoMemory(root, { chapter: n, focus: cast.map((c) => c.name) });
  const volMem = await volumeMemory(root, { chapter: n, volumes });
  // L0：出场人物截至上一章「知道什么、和谁什么关系」；L0 关系边给本章同场人物
  const castState = await characterState(root, { chapter: n, names: cast.map((c) => c.name) });
  // 只补「出场人物与其他人」的边；两人都在场的关系上面已经列过，不再重复
  const relText = (await relationLines(root, cast.map((c) => c.name)))
    .split("\n").filter((l) => {
      const m = l.match(/^- (\S+) ↔ (\S+)：/u);
      return !(m && cast.some((c) => c.name === m[1]) && cast.some((c) => c.name === m[2]));
    }).join("\n");
  // 作者在「人物 → 关系矩阵」里手填的关系边，写正文时也要带上
  const names = new Set(cast.map((c) => c.name));
  const matrixRel = (bible.relations || [])
    .filter((r) => r && (names.has(r.a) || names.has(r.b)))
    .map((r) => `- ${r.a} ↔ ${r.b}：${r.state || "—"}${r.note ? `（${r.note}）` : ""}`)
    .join("\n");
  const infoGapRel = (bible.infoGaps || [])
    .filter((g) => g && [g.knows, g.doesntKnow, g.thinksKnows].some((v) => String(v || "").split(/[、,，/ ]+/u).some((n) => names.has(n))))
    .map((g) => `- ${g.secret || "未命名秘密"}｜知道：${g.knows || "—"}｜不知道：${g.doesntKnow || "—"}｜误以为知道：${g.thinksKnows || "—"}`)
    .join("\n");
  // 章级记忆：近章全摘要 + 更早一句一章（memory.js）
  const esState = prevNo >= 1 ? await endSceneState(root, { chapter: prevNo }) : { chars: [], place: "", tail: "" };
  const worldTextOld = (project?.worldText || "").trim();
  const toPlant = fsState.open.filter((f) => Number(f.plantedChapter) === n);
  // 退回重写时留下的问题清单：只对同一章生效，写完提交时清掉
  const rewriteReq = await readText(p(root, "review", "rewrite-request.md")).catch(() => "");
  const rewriteHit = new RegExp(`^# 第\\s*${n}\\s*章重写请求`, "m").test(rewriteReq);
  // —— 必守段：整段保留，不参与「谁字多谁让路」 ——
  const critical = [
    {
      key: "header", title: "作品与本章", critical: true, max: 700,
      text: [
        `作品：《${project?.title || ""}》 · ${project?.genre || ""} · ${project?.platform || ""} · 目标 ${project?.wordsPerChapter || "?"} 字/章 · 全书 ${project?.targetChapters || "?"} 章`,
        `本章：第 ${n} 章${curVol ? `（${curVol.title}，第${curVol.from}-${curVol.to}章）` : ""}；已写 ${index.filter((c) => c.number < n).length} 章`,
        bible.style?.pov || bible.style?.tense ? `叙事：${bible.style.pov || "未定"} / ${bible.style.tense || "未定"}` : "",
        project?.direction ? `方向（第${project.currentChapter || 0}章后生效）：${clampSummary(project.direction, 300)}` : "",
      ].filter(Boolean).join("\n"),
    },
    {
      key: "outline", title: segInfo ? "本批段落纲（10 章一段，按台阶推进）" : "本章细纲（必须按拍推进）", critical: true, max: segInfo ? 2500 : 2800,
      text: segInfo ? segInfo.text : ([
        `第 ${n} 章${outline?.title ? `《${outline.title}》` : ""}`,
        (outline?.beats || []).map((b, i) => `${i + 1}. ${b}`).join("\n"),
        outline?.mustInclude?.length ? `必须出现：${outline.mustInclude.join("；")}` : "",
        outline?.mustAvoid?.length ? `必须回避：${outline.mustAvoid.join("；")}` : "",
        outline?.openingState ? `开场须接上：${clampSummary(outline.openingState, 300)}` : "",
        outline?.endingState ? `本章结束时必须达成：${clampSummary(outline.endingState, 300)}` : "",
        outline?.pressure
          ? `本章动机来源（每一拍都要落到其中一条，不许凭气氛推进）：${[
              outline.pressure.deadline ? `期限：${outline.pressure.deadline}` : "",
              outline.pressure.stake ? `代价：${outline.pressure.stake}` : "",
              outline.pressure.opponent ? `谁在逼：${outline.pressure.opponent}` : "",
            ].filter(Boolean).join("；")}`
          : "",
        outline?.expands ? `本章揭示/使用的前置信息：${Array.isArray(outline.expands) ? outline.expands.join("、") : outline.expands}` : "",
      ].filter(Boolean).join("\n") || `第 ${n} 章还没有细纲——先补细纲再写正文。`),
    },
    {
      key: "cast", title: "本章出场角色（只列真要出场的；言行符合设定）", critical: true, max: 2400,
      text: cast.length
        ? cast.map((c) => {
            const legacy = { S: "核心", A: "主要", B: "次要", C: "龙套" };
            const impRaw = String(c.importance || c.tier || "").trim();
            const importance = legacy[impRaw.toUpperCase()] || impRaw || "主要";
            const tier = { 核心: "S", 主要: "A", 次要: "B", 龙套: "C" }[importance] || "A";
            const alias = aliasesOf(c).length > 1 ? `（也叫：${aliasesOf(c).filter((a) => a !== c.name).join("、")}）` : "";
            const status = c.status === "dead" ? "已死亡（不可复活）" : c.status === "missing" ? "失踪" : c.status === "exited" || c.exitChapter ? `已退场${c.exitChapter ? `（第${c.exitChapter}章）` : ""}` : "在场";
            const head = `- ${c.name}${alias}｜定位：${c.rolePosition || c.role || "—"}｜重要性：${importance}｜${status}`;
            // C 级只防重名；B 级只给功能与一个记忆点，别把龙套写细。
            if (tier === "C") return `${head}（龙套，只登记名字，不要擅自加戏）`;
            if (tier === "B") return `${head}\n  记忆点：${c.appearance || c.personality || "—"}`;
            // 优先用位置轨迹里「本章之前最后一笔」；没有轨迹才退回 location。
            // 范围式位置（「南街—城楼一线」）对写具体一场戏没用，直接不喂。
            const trail = (Array.isArray(c.locationTrail) ? c.locationTrail : [])
              .filter((x) => Number(x.chapter) < n && x.place)
              .sort((a, b) => Number(a.chapter) - Number(b.chapter));
            const lastTrail = trail.length ? trail[trail.length - 1] : null;
            const loc = lastTrail ? (lastTrail.place || (Array.isArray(lastTrail.places) ? lastTrail.places[lastTrail.places.length - 1] : ""))
              : (esState.place || (/[—～~]|一线|沿线/.test(String(c.location || "")) ? "" : c.location));
            const base = `  年龄：${c.age || "—"}｜性别：${c.gender || "—"}｜种族：${c.race || "—"}｜位置（上一章收尾）：${loc || "—"}｜当前目标（本章起点）：${c.currentGoal || "—"}`;
            const voice = `  语言指纹：${c.voice || "—"}｜称呼规则：${c.callRules || "—"}`;
            const core = `  性格：${c.personality || "—"}｜欲望：${c.want || "—"}｜恐惧：${c.fear || "—"}｜底线：${c.bottomLine || "—"}｜缺陷：${c.flaw || "—"}`;
            const info = `  知道：${c.knowledge || "—"}｜不知道：${c.ignorance || "—"}｜误以为：${c.misconception || "—"}`;
            if (tier === "A") return [head, base, voice, core, info].join("\n");
            const ability = `  能力：${c.ability || "—"}｜限制：${c.abilityLimit || "—"}｜代价：${c.abilityCost || "—"}`;
            const body = `  体貌记忆点：${c.appearance || "—"}｜秘密：${c.secret || "—"}`;
            // 变更日志常被 AI 补成整本书的走向，喂给正文等于剧透；当前状态字段已经够用
            return [head, base, body, voice, core, info, ability].filter(Boolean).join("\n");
          }).join("\n")
        : "（细纲和上一章都没点名具体角色；按需安排，别凭空加设定外的关键人物）",
    },
    {
      key: "rules", title: "世界硬规则（按与本章相关度排序，不可违反）", critical: true, max: 3000,
      text: (() => {
        // 66 条规则全量注入会挤掉前情记忆：先按「本章提到 / 重要性」排序，再按 2850 字截尾；
        // 被截掉的只影响“这章带不带”，不影响规则本身仍然有效，末尾明确告诉模型还剩几条。
        const needles = [outlineFull, prevText, cast.map((c) => c.name).join(" ")].filter(Boolean).join(" ");
        const score = (r) => {
          const imp = String(r?.importance || r?.tier || "").trim();
          const impScore = ["核心", "主要", "S", "A", "high"].includes(imp) ? 3 : imp ? 1 : 0;
          const keys = [r?.name, ...(Array.isArray(r?.keywords) ? r.keywords : []), r?.trigger].filter(Boolean).map(String);
          return impScore + (keys.some((k) => k && needles.includes(k)) ? 4 : 0);
        };
        const ordered = hardRules
          .map((r, i) => ({ r: r || {}, i }))
          .sort((a, b) => score(b.r) - score(a.r) || a.i - b.i)
          .map((x) => x.r);
        const lines = ordered.map((r) => {
          const text = String(r.text || "").trim();
          const head = r.name && text ? `- ${r.name}：${text}` : `- ${text || r.name || ""}`;
          // text 里已经写了「代价/判定/边界/以为」就不再重复拼一遍，避免同一句话出现两次。
          const bits = [
            r.judge && !text.includes("判定") && !text.includes(String(r.judge)) ? `判定者：${r.judge}` : "",
            r.cost && !text.includes("代价") && !text.includes(String(r.cost)) ? `代价：${r.cost}` : "",
            r.boundary && !text.includes("边界") && !text.includes(String(r.boundary)) ? `边界/漏洞：${r.boundary}` : "",
            r.belief && !text.includes("以为") && !text.includes(String(r.belief)) ? `主角以为：${r.belief}` : "",
          ].filter(Boolean);
          return bits.length ? `${head}（${bits.join("；")}）` : head;
        });
        let keep = lines.length;
        let total = lines.reduce((a, line) => a + line.length + 1, 0);
        while (keep > 0 && total > 2850) {
          keep -= 1;
          total -= lines[keep].length + 1;
        }
        const omitted = lines.length - keep;
        return lines.slice(0, keep).join("\n")
          + (omitted ? `\n（另 ${omitted} 条硬规则因上下文预算未注入；需要时用 novel_bible list 查看，别当作不存在。）` : "");
      })(),
    },
    {
      key: "style", title: "禁用表达 / 文风", critical: true, max: 2200,
      text: [
        stylePreset ? `文风基调：${stylePreset.label}（${stylePreset.hint}）。动笔前先加载 ${stylePreset.skill} 技能，按它的语感写，不许写成默认网文腔。` : "",
        stylePreset?.banned?.length ? `这个文风要避开：${stylePreset.banned.join("；")}` : "",
        bible.style?.banned?.length ? `禁用表达：${bible.style.banned.join("、")}` : "",
        bible.style?.bannedPatterns?.length ? `禁用句式：${bible.style.bannedPatterns.join("；")}` : "",
        (() => {
          const preset = STYLE_PRESETS[bible.style?.preset] || null;
          const pS = (preset && Array.isArray(preset.samples)) ? preset.samples : [];
          const all = [...pS, ...((bible.style?.samples) || [])].filter(Boolean);
          return all.length ? `文风样本（模仿语感，不要抄句）：\n${all.slice(0, 2).join("\n---\n").slice(0, 1400)}` : "";
        })(),
      ].filter(Boolean).join("\n"),
    },
    {
      key: "plant", title: "本章必须埋设的伏笔（漏埋=吃书）", critical: true, max: 1600,
      text: toPlant.map((f) =>
        `- ${f.name}｜埋在哪一拍：${f.plantBeat || "（细纲里指定）"}｜怎么顺带一提：${f.hint || f.note || "自然带出，不要特意强调"}${f.source ? `｜来源：${f.source}` : ""}`).join("\n"),
    },
    {
      key: "payoff", title: "该收 / 超期的伏笔", critical: true, max: 2000,
      text: (() => {
        const others0 = fsState.open.filter((f) => Number(f.plantedChapter) !== n);
        const due = others0.filter((f) => Number(f.dueChapter) === n);
        const over = others0.filter((f) => f.overdue && Number(f.dueChapter) !== n);
        return [
          [...due.map((f) => `- 【到期应收】${payoffLine(f)}`), ...over.map((f) => `- 【已超期】${payoffLine(f)}`)].join("\n"),
          others0.filter((f) => !due.includes(f) && !over.includes(f)).slice(0, 8).map((f) => `- ${f.name}（第${f.plantedChapter}章埋${f.dueChapter ? `，计划第${f.dueChapter}章收` : ""}）`).join("\n"),
        ].filter(Boolean).join("\n");
      })(),
    },
    { key: "prev", title: "上一章结尾原文（接住语气与动作，不要复述）", critical: true, max: 900, text: prevText ? tail(prevText, 900) : "" },
    {
      key: "prevstate", title: "上一章收尾状态（不能凭空瞬移）", critical: true, max: 800,
      text: [
        [esState.chars.length ? `在场人物：${esState.chars.join("、")}` : "", esState.place ? `地点：${esState.place}` : "", esState.tail ? `收尾片段："…${esState.tail}"` : ""].filter(Boolean).join("；"),
        "写作要求：地点与在场人物要接住上一章收尾；人物要离开某地、并在正文里写出移动，才允许出现在别处，不许无故走回刚离开的地点。",
        "开局纪律：正文前 200 字内要出现一个具体的人在做一件具体的事、并带出一个具体的麻烦或悬念；不要用大段背景、空镜或纯氛围开场。这个人是副角、路人也可以，不必是主角。",
      ].filter(Boolean).join("\n"),
    },
    {
      key: "rewrite", title: "作者的退回重写要求（逐条改掉，别再犯）", critical: true, max: 4000,
      text: rewriteHit ? rewriteReq.replace(/^# 第\s*\d+\s*章重写请求\s*$/m, "").trim() : "",
    },
  ];
  // —— 可选段：参考性内容，按权重分剩下的预算 ——
  const volsMap = volumes.length ? volumes.map((v) => `- ${v.title}（第${v.from}-${v.to}章）${v === curVol ? " ← 本章" : ""}`).join("\n") : "";
  const sideBits = [];
  if ((bible.factions || []).length) sideBits.push("势力：\n" + bible.factions.map((x) =>
    `- ${x.name}${x.hiddenRules ? `｜潜规则：${x.hiddenRules}` : ""}${x.misjudge ? `｜他们以为主角：${x.misjudge}` : ""}${x.attitude ? `｜此刻态度：${x.attitude}` : ""}`).filter(Boolean).join("\n"));
  if ((bible.locations || []).length) sideBits.push("地点：\n" + bible.locations.map((x) =>
    `- ${x.name}${x.geo ? `｜位置：${x.geo}` : ""}${x.accessRules ? `｜进出规矩：${x.accessRules}` : ""}${x.occupied ? `｜现在：${x.occupied}` : ""}${x.state ? `｜状态：${x.state}` : ""}`).filter(Boolean).join("\n"));
  if ((bible.items || []).length) sideBits.push("关键物品：\n" + bible.items.map((x) =>
    `- ${x.name}${x.holder ? `｜持有人：${x.holder}` : ""}${x.state ? `｜状态：${x.state}` : ""}${x.whoKnows ? `｜谁知道：${x.whoKnows}` : ""}`).filter(Boolean).join("\n"));
  if ((bible.world || []).length) sideBits.push("世界观：" + bible.world.map((w) => (w.name && w.text ? `${w.name}（${w.text}）` : w.name || w.text)).filter(Boolean).join("；"));
  const bookOutline = (project?.outlineText || "").trim();
  const optional = [
    { key: "caststate", title: "出场人物记得的事（截至上一章，别让他说漏/说错）", weight: 2.4, max: 1800, text: [castState.text, relText ? `现有关系：\n${relText}` : "", matrixRel ? `设定关系：\n${matrixRel}` : "", infoGapRel ? `关键信息差：\n${infoGapRel}` : ""].filter(Boolean).join("\n") },
    { key: "memory", title: `前情记忆（已写 ${mem.covered} 章）`, weight: 4.5, min: 1600, max: 3400, text: mem.text },
    { key: "volmem", title: "前卷记忆", weight: 1.2, max: 1200, text: volMem.text },
    { key: "bookoutline", title: curVol ? "全书大纲（本卷切片）" : "全书大纲（把握走向）", weight: 2, max: 2600, text: bookOutline ? (curVol ? localOutlineSlice(bookOutline, curVol) : clampSummary(bookOutline, 2600)) : "" },
    { key: "threads", title: "世界观遗留钩子（可择机带一笔，不必这章就揭）", weight: 1, max: 700, text: Array.isArray(project?.openThreads) ? project.openThreads.filter(Boolean).slice(0, 12).join("\n") : "" },
    { key: "world", title: "世界观设定（不可与之矛盾）", weight: 2, max: 3000, text: worldCore(worldTextOld) },
    { key: "volumes", title: "全书卷地图", weight: 0.8, max: 1400, text: volsMap },
    { key: "worldItems", title: "势力 / 地点 / 物品", weight: 0.6, max: 900, text: sideBits.join("；") },
  ].filter((s) => s.text);

  const fitted = fitSections([...critical, ...optional], packBudget(budgetChars, project?.wordsPerChapter));
  const head = `# 第 ${n} 章写作上下文包\n> 由 novel_context 确定性组装。必守段（细纲/角色/硬规则/伏笔/上一章）永远保留；其余按预算取舍，超出的段末尾标「…」。\n`;
  const lost = fitted.dropped.length ? `\n---\n⚠ 这些必守段太长被压短：${fitted.dropped.join("、")}（建议精简细纲或设定）` : "";
  const text = head + fitted.sections.filter((s) => s.text).map((s) => `\n## ${s.title}\n${s.text}`).join("\n") + lost + "\n";
  const tokens = estimateTokens(text);
  await logUsage(root, { kind: "context", chapter: n, chars: text.length, tokens, budget: fitted.budget });
  return {
    text,
    chars: text.length,
    tokens,
    budget: fitted.budget,
    openForeshadow: fsState.open.length,
    cast: cast.map((c) => c.name),
    volume: curVol,
    memoryCovered: mem.covered,
  };
}

const payoffLine = (f) => `${f.name}（第${f.plantedChapter}章埋${f.dueChapter ? `，计划第${f.dueChapter}章收` : ""}）${f.revealChange ? `｜揭开后：${f.revealChange}` : ""}${f.revealWho ? `｜谁来揭：${f.revealWho}` : ""}`;

/** 大纲正文变了就重算卷索引（保存大纲 / 生成大纲处调用）。 */
export async function outlineVolume(root) {
  return refreshVolumes(root, () => listOutlines(root));
}

/** 世界观里「硬规则/人物」那几节才值得每章都带；世界基底前面已有短版。 */
function worldCore(w) {
  const s = String(w || "").trim();
  if (!s) return "";
  // 世界观现在只放叙事（规则/人物已进 bible），整段带上有上下文价值；按预算截断即可。
  return s.slice(0, 3000);
}

/** 全书写到几百章时，大纲全文每次进 prompt 既贵又会被截；只给本卷切片。 */
export function localOutlineSlice(outlineText, vol) {
  const s = String(outlineText || "");
  const lines = s.split("\n");
  const norm = (t) => String(t || "").replace(/\s+/g, "");
  const key = norm(String(vol.title || "").split(/[·:：]/).pop()).slice(0, 10);
  const isHead = (l) => /^#{2,4}\s/.test(l.trim());
  // 「第 11-20 章」这类区间行：卷名写法一变（空格、标题层级）也能按章号找回本卷
  const lineRange = (l) => {
    const m = /第?\s*(\d+)\s*[-–—~～至到]\s*(\d+)\s*章/.exec(String(l || ""));
    return m ? { from: Number(m[1]), to: Number(m[2]) } : null;
  };
  const covers = (r) => r && Number(vol.from) >= r.from && Number(vol.from) <= r.to;
  let idx = key ? lines.findIndex((l) => isHead(l) && norm(l).includes(key)) : -1;
  if (idx < 0) idx = lines.findIndex((l) => covers(lineRange(l)));
  if (idx < 0) return s.slice(0, 2400);
  const isPart = (l) => isHead(l) && /第?\s*[0-9一二三四五六七八九十百千]+\s*[卷部篇]/.test(l);
  let start = idx;
  // 命中的行本身不是卷头时，才往前找本卷的卷头（否则会把上一卷的标题也切进来）
  if (!isPart(lines[idx])) for (let i = idx - 1; i >= 0; i -= 1) if (isPart(lines[i])) { start = i; break; }
  let end = lines.length;
  for (let i = idx + 1; i < lines.length; i += 1) {
    const r = lineRange(lines[i]);
    if (isPart(lines[i]) || (isHead(lines[i]) && /一致性约束|自检/.test(lines[i])) || (r && r.from > Number(vol.to))) { end = i; break; }
  }
  return lines.slice(start, end).join("\n").slice(0, 2600);
}

/* ------------------------------ 连续性体检 ------------------------------ */

// 说话人启发式：只认"句首/引号后 + 2-3 字 + 说话动词"，且同章重复出现，
// 目的是低召回高精度——宁可漏报，不要给作者一堆"门弟子"式误报。
// 章首「只是在续写上一章最后一个动作」的确定性判法：两边取 2 字实词，交集 ≥2 且没有新时空/新人物。
// 不做开头类型分类、不检测主角名——用户明确反对把开头模板化，这里只抓「同一动作被复述」。
const CONTENT_FUNC_RE = /[的了是在和与及或就都也而把被这那个么要用说不没有就还又很太他她它我你]/;
const NEW_SCENE_RE = /(天|日|夜|晨|清早|清晨|傍晚|黄昏|午|雪|雨|风|雾|霜|街|巷|院|屋|门|窗|城|河|山|路|桥|店|堂|宫|府|营|码头|车站|广场|楼|房|厅|仓)/;
function contentBigrams(text) {
  const s = String(text || "").replace(/[^\p{Script=Han}]/gu, "");
  const out = new Set();
  for (let i = 0; i + 2 <= s.length; i += 1) {
    const g = s.slice(i, i + 2);
    if (!CONTENT_FUNC_RE.test(g)) out.add(g);
  }
  return out;
}

const SPEAK_VERB = /(?<![\p{Script=Han}])([\p{Script=Han}]{2,3})(?=(说道|说|道|问道|问|答道|答|喊道|喊|笑道|笑|叫道))/gu;
const BAD_TAIL = /(们|的|了|着|过|是|在|有|个|这|那|就|也|都|还|又|才|很|太|更|最|不|没|要|会|能|想|子|声|手|人|事|话|里|上|下|前|后|中|来|去|出|起|开|住|完|到|给|对|把|被|让|从|向|知|道|说|问|答|看|听|觉|笑|哭|疼|累|怒|气|懂|信|猜|忘|记|走|跑|站|坐|躺|醒|睡|等|找|扔|拿|放|递|推|拉|撞|望|盯|点|摇|点|哼|嗯|哎|哦|喂)$/u;
// 「别多问」会被当成「别多」在说话：句首是指令/否定/情态词的，不可能是人名
const BAD_HEAD = /^(别|不|没|莫|勿|休|就|才|还|也|都|又|很|太|更|最|先|再|可|要|想|该|敢|肯|能|会|让|把|被|从|向|对|给)/u;
const STOP = new Set(`他说 她说 我说 你说 它说 众人 有人 那人 这人 男人 女人 老人 少年 少女 对方 两人 三人 大家 谁都 一声 忽然 这时 只是 于是 接着 随即 然后 因此 所以 但是 可是 不过 而且 并且 同时 最后 终于 竟然 居然 果然 依旧 仍然 还是 已经 曾经 正在 马上 立刻 顿时 突然 猛地 缓缓 轻轻 淡淡 默默 微微 低声 高声 轻声 冷声 沉声 笑着 皱眉 抬头 低头 回头 点头 摇头 说完 说罢 一边 一面 不知 只见 只闻 声音 一个 两个 那个 这个 什么 怎么 为何 因为 如果 虽然 尽管 无论 只要 只有 除非 不但 反而 甚至 尤其 何况 况且 否则 不然 随后 半晌 良久 许久 片刻 一会 过了 此时 此刻 当下 没人 无人 谁也没`.split(/\s+/));

// 判定某伏笔在本章正文里「有没有埋点」：抽关键名词 + 引号台词做证据，命中过半即算埋了。
// 目的：正文常把细纲里的书面描述换成自然叙述（"只落在一件能被他指着的东西上" vs "只能靠可指出的证据推理"），
// 整串字面匹配会大量误报。这里按「名词命中率」判，明显更贴近"到底写没写"。
// 判断正文里「有没有写到」某个必须出现项（短语/短句）。
// 不按整串字面比（正文会换说法：「杨槐只能靠可指出的证据推理」→「能被手指着的才算证据」），
// 而是把该短语拆成内容 2-3 字词，正文命中足够多（>=3 个不同词，或短短语命中>=2）即算写到。
function textHasContent(text, phrase) {
  const t = String(text || "");
  const p = String(phrase || "").trim();
  if (!p) return true;
  if (t.includes(p)) return true; // 原样出现当然算
  const clean = p.replace(/[『』「」（）()，,。；;：:、\s]/g, "");
  const FUNC = /[的了是在和与及或就都也而把被这那个么要用说不没有就还又很太他她它我你]/g;
  const grams = new Set();
  for (let n = 2; n <= 3; n++) {
    for (let i = 0; i + n <= clean.length; i++) {
      const g = clean.slice(i, i + n);
      if ((g.match(FUNC) || []).length >= 1) continue;
      grams.add(g);
    }
  }
  const pool = [...grams];
  if (!pool.length) return t.includes(p);
  // 去重归一：只统计"不同意思"的命中，避免「编号」「号重」算两次
  const hits = pool.filter((w) => t.includes(w));
  // 阈值：短语越长，容错越高；短词（<=4字）要 2 个命中，长短语命中 2 个关键内容词即可算"写到了意思"
  const need = clean.length <= 4 ? 2 : 2;
  return hits.length >= need;
}

function foreshadowPlanted(text, f, { names = [] } = {}) {
  const t = String(text || "");
  const name = String(f.name || "").trim();
  const beat = String(f.plantBeat || "");
  // ① 伏笔名原样出现 → 埋了。但不能被更长的名字吃掉：
  //   伏笔叫「陆青」，正文写的是「陆青荷」，不能算埋了（这正是老版 t.includes 的误报源）。
  if (name && name.length >= 2 && namePositions(t, [name], names).length) return true;
  // ② 埋点里『…』「…」引号内的台词/名词，原样出现即强证据
  const quotes = [...beat.matchAll(/[『「]([^』」]{2,24})[』」]/g)].map((m) => m[1].trim()).filter(Boolean);
  if (quotes.some((q) => t.includes(q))) return true;
  // ③ 抽「实体/动作关键 2-3 字词」，正文里命中足够多（>=3 个不同的）即认为这一段落地了。
  //    长埋点常把"埋设+含义"写在一起，只要核心几个名词/动作出现在正文里，就算写了。
  const clean = beat.replace(/[『』「」（）()，,。；;：:、\s]/g, "");
  const FUNC = /[的了是在和与及或就都也而把被这那个么要用说不没有就还又很太他她它我你]/g;
  const grams = new Set();
  for (let n = 2; n <= 3; n++) {
    for (let i = 0; i + n <= clean.length; i++) {
      const g = clean.slice(i, i + n);
      const funcCount = (g.match(FUNC) || []).length;
      if (funcCount >= 1) continue; // 2-3 字窗里只要含虚词就跳过（保持为实词/名词动作）
      grams.add(g);
    }
  }
  const hits = [...grams].filter((w) => t.includes(w));
  return hits.length >= 3;
}

const DISMISS_FILE = "ledger/dismissed.jsonl";
/** 体检条目的稳定标识：同一条问题重复出现时，作者只需要标记一次。 */
// 标记合理按「章 + 问题类型」记账：同一章同一类问题只提示一次，
// 不依赖 message 里会变的数字/引文（否则下次措辞一变就又冒出来）。
function chapterOfMessage(text) {
  const m = /第\s*(\d+)\s*章/.exec(String(text || ""));
  return m ? m[1] : "";
}
export function continuityKey(f) {
  // 显式 chapter 优先：跨章问题的 message 里常顺带提到别的章号，只靠正则会挂错章。
  const explicit = Number(f?.chapter);
  const ch = Number.isFinite(explicit) && explicit > 0 ? String(explicit) : chapterOfMessage(f?.message);
  return ch ? `continuity|${f?.code || ""}|ch${ch}` : `continuity|${f?.code || ""}|${f?.message || ""}`;
}
/** 断层条目的稳定标识（章 + 段 + 问题）。 */
export function logicKey(chapter, x) {
  return `logic|${Number(chapter) || 0}|${x?.between || ""}|${x?.issue || ""}`;
}
export async function loadDismissedSet(root) {
  const rows = await readJsonl(p(root, DISMISS_FILE)).catch(() => []);
  const set = new Set();
  for (const r of rows) {
    if (!r || !r.key) continue;
    set.add(r.key);
    // 兼容老记录（key 里带整条 message）：同时收一个按章归一的 key
    if (r.kind !== "logic" && r.code) {
      const ch = chapterOfMessage(r.message);
      set.add(ch ? `continuity|${r.code}|ch${ch}` : `continuity|${r.code}|${r.message || ""}`);
    }
  }
  return set;
}
/** 作者点「标记为合理」：记下来，之后同一条体检/断层不再报。 */
export async function dismissFinding(root, { kind = "continuity", code, message, chapter, between, issue } = {}) {
  const key = kind === "logic"
    ? logicKey(chapter, { between, issue })
    : continuityKey({ code, message, chapter });
  if (!String(code || between || "").trim() || !String(message || issue || "").trim()) {
    throw new Error("需要 code+message（体检）或 chapter+between+issue（断层）");
  }
  const rows = await readJsonl(p(root, DISMISS_FILE)).catch(() => []);
  if (rows.some((r) => r && r.key === key)) return { ok: true, key, duplicate: true };
  await appendJsonl(p(root, DISMISS_FILE), {
    key, kind, code: code || "", message: message || "",
    chapter: Number(chapter) || 0, at: new Date().toISOString(),
  });
  return { ok: true, key };
}

export async function continuityCheck(root) {
  const project = await loadProject(root);
  // 假绿：非项目目录曾被当成"空项目"判通过。体检必须知道自己在体检什么。
  if (!project) throw new Error(`不是小说项目（缺 project.json）：${root}；先用 novel_init 初始化`);
  const bible = await loadBible(root);
  const index = await loadIndex(root);
  const findings = [];
  // chapter 是「该问题的属主章」：跨章问题（断档/退场再出场/时间线倒退/伏笔超期）必须显式带它，
  // 否则 checkChapter 只凭 message 里的「第N章」匹配，会把问题误挂到 message 顺带提到的无关章。
  const add = (severity, code, message, hint, chapter) => findings.push({ severity, code, message, hint, ...(Number.isFinite(Number(chapter)) ? { chapter: Number(chapter) } : {}) });
  const dismissed = await loadDismissedSet(root);

  if (!index.length) {
    return {
      ok: true,
      chapters: 0,
      currentChapter: project?.currentChapter || 0,
      findings: [{ severity: "info", code: "empty", message: "还没有章节", hint: "先 novel_chapter commit" }],
      counts: { high: 0, mid: 0, info: 1 },
    };
  }

  const names = bible.characters.map((c) => c.name).filter(Boolean);
  // 所有已知名字（含别名）：用来排除「陆青」命中「陆青荷」这类长名字吃掉短名字的误报
  const knownNames = [...new Set(bible.characters.flatMap((c) => aliasesOf(c)).filter(Boolean))];
  // 正文常直接叫职务（族老、长工），设定里却只存了名字；把角色身份短词也算已知，免得好人天天被报「未登记」
  const roleWords = bible.characters.flatMap((c) => String(c.role || "").split(/[、,，/\s]+/))
    .map((w) => w.trim()).filter((w) => w.length >= 2 && w.length <= 6);
  const known = new Set([...names, ...roleWords, ...bible.world.map((w) => w.name).filter(Boolean)]);
  const chapters = [];
  for (const c of index) {
    try {
      chapters.push({ ...c, text: await readText(p(root, c.file)) });
    } catch {
      add("high", "missing-file", `第${c.number}章索引存在但文件丢失：${c.file}`, "重新提交该章", c.number);
    }
  }

  // 1) 章节断档
  const nums = index.map((c) => c.number).sort((a, b) => a - b);
  for (let i = 1; i < nums.length; i++) {
    if (nums[i] - nums[i - 1] > 1) add("mid", "chapter-gap", `第${nums[i - 1]}章到第${nums[i]}章之间缺 ${nums[i] - nums[i - 1] - 1} 章`, "补章或修正编号", nums[i]);
  }

  // 2) 已退场角色再出场——区分语境：回忆/梦/想起/幻觉/闪回里的提及不算违规；
  //    引号里的提及（「谷主当年……」）也只是被人说起，不等于本人登场。
  const MEMORY_RE = /(回忆|梦中|梦里|梦到|想起|回想|幻觉|闪回|记忆里|往事|当年|生前)/;
  const insideQuotes = (text, idx) => {
    const before = text.slice(0, idx);
    const opens = (before.match(/[「『“]/g) || []).length;
    const closes = (before.match(/[」』”]/g) || []).length;
    return opens > closes;
  };
  // 「真出场」：排除回忆/梦/闪回语境和引号里的提及。登场缺席/迟到/提前都要用同一把尺。
  // 回忆提示词只看名字所在的同一句：「他想起阿禾」不算出场；上一句里的「想起」不影响这一句。
  const realAppearPositions = (text, names) => nameHitsInText(text, names).filter((idx) => {
    const before = text.slice(Math.max(0, idx - 40), idx);
    const clause = before.split(/[。！？!?…\n]/).pop();
    return !MEMORY_RE.test(clause) && !insideQuotes(text, idx);
  });
  for (const ch of bible.characters) {
    if (!["dead", "exited", "退场", "已死"].includes(String(ch.status))) continue;
    const hasExit = ch.exitChapter !== undefined && ch.exitChapter !== null && ch.exitChapter !== "";
    if (!hasExit) {
      // 没写退场章就无从判断哪一章之后算违规；绝不能拿 0 当退场章，否则第 1 章也会被报
      add("info", "missing-exit-chapter", `「${ch.name}」标了「${ch.status}」但没写退场章，已跳过再出场检查`, "在人物卡补 exitChapter（第几章死亡/退场）；开篇前就死了填 0");
      continue;
    }
    const from = Number(ch.exitChapter) || 0;
    if (from === 0) continue; // 开篇前已死：全书都不算“死后再出场”
    const aliases = aliasesOf(ch);
    for (const c of chapters) {
      if (c.number <= from) continue;
      const positions = namePositions(c.text, aliases, knownNames);
      if (!positions.length) continue;
      let realAppear = false;
      for (const idx of positions) {
        const win = c.text.slice(Math.max(0, idx - 40), Math.min(c.text.length, idx + 40));
        if (!MEMORY_RE.test(win) && !insideQuotes(c.text, idx)) { realAppear = true; break; }
      }
      if (realAppear) {
        add("high", "dead-returns", `「${ch.name}」在第${from}章已退场，却在第${c.number}章以非回忆方式出现`, "改成回忆/幻觉并标注，或删掉这段", c.number);
      } else {
        add("info", "dead-in-memory", `「${ch.name}」在第${c.number}章以回忆/提及方式出现（已退场，属正常）`, "确认是回忆/闪回即可忽略", c.number);
      }
    }
  }

  // 3) 疑似未登记人物（低置信，只报同章出现 ≥2 次的候选）
  for (const c of chapters) {
    const counter = new Map();
    for (const m of c.text.matchAll(SPEAK_VERB)) {
      const n = m[1];
      if (STOP.has(n) || BAD_TAIL.test(n) || BAD_HEAD.test(n)) continue;
      if (known.has(n)) continue;
      if ([...known].some((k) => k && (k.includes(n) || n.includes(k)))) continue;
      counter.set(n, (counter.get(n) || 0) + 1);
    }
    const found = [...counter.entries()].filter(([, n]) => n >= 2).map(([n, n2]) => `${n}×${n2}`);
    if (found.length) add("info", "unknown-speaker", `第${c.number}章疑似未登记人物：${found.join("、")}`, "确认是新人就 novel_bible upsert character；是称呼/误报就忽略");
  }

  // 4) 时间线倒退
  // 老数据里同一章可能有多行（反复重写），每章取最后一条再按章号比，避免「第11章早于第11章」这种假报警
  const tlByChapter = new Map();
  for (const r of await readJsonl(p(root, LAYOUT.timeline))) {
    if (r.__corrupt || !Number.isFinite(r.inWorldDay)) continue;
    tlByChapter.set(Number(r.chapter), r);
  }
  const tl = [...tlByChapter.values()].sort((a, b) => Number(a.chapter) - Number(b.chapter));
  for (let i = 1; i < tl.length; i++) {
    if (tl[i].inWorldDay < tl[i - 1].inWorldDay) {
      add("high", "timeline-backwards", `第${tl[i].chapter}章的世界日 ${tl[i].inWorldDay} 早于第${tl[i - 1].chapter}章的 ${tl[i - 1].inWorldDay}`, "确认是倒叙（需在正文标注）还是写错", tl[i].chapter);
    }
  }

  // 5) 伏笔超期
  const current = Math.max(project?.currentChapter || 0, nums[nums.length - 1]);
  const fsState = await listForeshadow(root, current);
  for (const f of fsState.open) {
    if (f.overdue) add("mid", "foreshadow-overdue", `伏笔「${f.name}」计划第${f.dueChapter}章回收，现已第${current}章`, "本章回收，或 novel_foreshadow 改期/放弃", current);
  }
  if (fsState.open.length > 12) add("info", "foreshadow-hoard", `未回收伏笔 ${fsState.open.length} 条`, "超过 12 条读者会失忆，先回收再埋新的");

  // 6) 字数偏离：按平台目标区间判定（不在区间外 10% 才报警，避免番茄 2000-3500 被 3000 误报）
  const range = project?.wordsRange || (project?.wordsPerChapter ? { min: Math.round(project.wordsPerChapter * 0.85), max: Math.round(project.wordsPerChapter * 1.15), name: "目标" } : null);
  // 硬下限（长篇 1800）之下单独报 high：commit 已拦，这里防旧稿/旧项目里残留的短章
  const floor = chapterMinChars(project);
  if (floor > 0) {
    for (const c of index) {
      if (c.chars < floor) add("high", "length-below-floor", `第${c.number}章 ${c.chars} 字，低于每章硬下限 ${floor} 字`, "退回重写（novel_gate rewrite）补戏到 " + floor + " 字以上");
    }
  }
  if (range && range.max) {
    const lo = Math.max(Math.floor(range.min * 0.9), floor);
    const hi = Math.ceil(range.max * 1.1);
    for (const c of index) {
      if (c.chars < lo) add("mid", "length-drift", `第${c.number}章 ${c.chars} 字，低于${range.name}区间 ${range.min}-${range.max} 的下限（<${lo}）`, "拆章或补戏");
      else if (c.chars > hi) add("mid", "length-drift", `第${c.number}章 ${c.chars} 字，高于${range.name}区间 ${range.min}-${range.max} 的上限（>${hi}）`, "拆章或精简");
    }
  }

  // 7) 设定缺席：逐章查语境——该角色在「首次登场章（firstChapter，默认1）」之前就从未出现，
  // 才提示；一旦在任何一章正文里出现过就闭嘴（避免"在第3章出现一次就永远不提示"的反向漏报，
  // 也避免把回忆里的提及当成真正登场）。
  for (const ch of bible.characters) {
    if (!ch.name) continue;
    // 已死亡/退场/失踪的人本来就不该再出场，不参与「该登场却缺席」检查。
    if (isGoneCharacter(ch)) continue;
    // 没在设定里写 firstChapter 的角色 = 作者没规定登场章，不强行要求第1章就出场。
    // 只有明确写了 firstChapter 的才做「该登场却没登场」检查，否则会误报一堆配角。
    if (ch.firstChapter == null || ch.firstChapter === "") continue;
    // firstChapter=0 表示「开篇前就已存在/已发生」，不是第 1 章要登场的约定。
    const firstNeed = Number(ch.firstChapter);
    if (!Number.isFinite(firstNeed) || firstNeed <= 0) continue;
    if (firstNeed > current) continue; // 还没写到它该登场的章
    // 身份描述会额外切出核心叫法（「新麻绳扣的猎团领头」→「猎团领头」），短别名防撞在 appearanceNames 里统一处理。
    const names = appearanceNames(ch);
    // 只有核心/主要角色的缺席才拦 approve；次要/龙套降为 info，只提示不判废。
    // S/A 是旧档的层级写法，等同核心/主要。
    const hardDebut = ["核心", "主要", "S", "A"].includes(String(ch.importance || "").trim());
    const sev = hardDebut ? "mid" : "info";
    // 「出现」只认真出场：回忆/梦/引号里的提及不算。
    const appearedChapters = chapters.filter((c) => realAppearPositions(c.text, names).length > 0).map((c) => c.number).sort((a, b) => a - b);
    // 登场时点对不上时给两条可执行路：改设定（回写 firstChapter）或重写章节按序登场
    if (appearedChapters.length === 0) {
      add(sev, "never-appears", `设定里的「${ch.name}」应第${firstNeed}章前登场，但到第${current}章正文里从未出现`, hardDebut
        ? `二选一：① 回写设定——他其实更晚登场，就 novel_bible upsert character ${ch.name} firstChapter=<实际要出场的章>；② 按序登场——novel_gate rewrite ${firstNeed} 把这一章重写成他到场（或在第${firstNeed}章前后补一场戏）。次要/龙套也可以直接标成背景板（firstChapter 留空）`
        : `二选一：① 回写设定——novel_bible upsert character ${ch.name} firstChapter=<实际出场章>；② 按序登场——novel_gate rewrite ${firstNeed} 补戏。次要/龙套不拦通过`);
    } else if (appearedChapters[0] > firstNeed) {
      add(sev, "late-appear", `「${ch.name}」设定应第${firstNeed}章前登场，实际第${appearedChapters[0]}章才出现（晚了 ${appearedChapters[0] - firstNeed} 章）`, hardDebut
        ? `二选一：① 回写设定——把登场章改成实际章：novel_bible upsert character ${ch.name} firstChapter=${appearedChapters[0]}；② 按序登场——novel_gate rewrite ${firstNeed}（或 ${firstNeed}-${appearedChapters[0] - 1} 之间的某一章）让他按设定时间提前出场，并删掉第${appearedChapters[0]}章里"第一次见/初次认识"的写法`
        : `二选一：① 回写设定 firstChapter=${appearedChapters[0]}；② 提前到第${firstNeed}章。次要/龙套不拦通过`);
    }
  }

  // 8) 禁用表达
  const banned = bible.style?.banned || [];
  for (const b of banned) {
    if (!b) continue;
    for (const c of chapters) {
      const n = c.text.split(b).length - 1;
      if (n) add("mid", "banned-phrase", `第${c.number}章出现禁用表达「${b}」×${n}`, "改写");
    }
  }

  // 9) 漏埋伏笔：该章是某条伏笔的埋设章，但正文里没写出它的「埋点关键词/来源」
  {
    const rows = await readJsonl(p(root, LAYOUT.foreshadow));
    const allFs = foldForeshadow(rows);
    const byPlant = new Map();
    for (const f of allFs) {
      const k = Number(f.plantedChapter);
      if (!Number.isFinite(k) || k <= 0) continue;
      if (!byPlant.has(k)) byPlant.set(k, []);
      byPlant.get(k).push(f);
    }
    for (const c of chapters) {
      const list = byPlant.get(Number(c.number)) || [];
      for (const f of list) {
        // 判定「埋了没有」：从「伏笔名 + 埋点」里抽关键名词（去掉引号/标点/虚词），
        // 命中过半即算埋了；另把埋点里『…』引号内的台词单独作为强证据（原样出现即算命中）。
        if (foreshadowPlanted(c.text, f, { names: knownNames })) continue;
        add("mid", "foreshadow-not-planted", `第${c.number}章是伏笔「${f.name}」的埋设章，但正文里没找到它的埋点（${f.plantBeat || f.source || "见细纲"}）`, "在这一章补写这处伏笔，或把该伏笔改到别的埋设章");
      }
    }
  }

  // 9b) 伏笔到期章：该章是某伏笔的「回收章」（dueChapter），但正文里没出现回收关键词 → high（读者等不到兑现）
  {
    const rows = await readJsonl(p(root, LAYOUT.foreshadow));
    const allFs = foldForeshadow(rows);
    for (const f of allFs) {
      if (f.paid || f.abandon) continue;
      const due = Number(f.dueChapter) || 0;
      if (!due) continue;
      const ch = chapters.find((c) => Number(c.number) === due);
      if (!ch) continue; // 这章还没写
      // 回收关键词：伏笔名 + revealChange/revealWho 里的关键词 + source
      const keys = [f.name, f.source].filter(Boolean);
      const revealWords = String(f.revealChange || "").split(/[，,。；;\s、]/).filter((w) => w.length >= 2).slice(0, 6);
      const hitAny = [...keys, ...revealWords].some((w) => w && ch.text.includes(w));
      if (!hitAny) {
        // 显式带属主章：approve 的 high 拦截只看 chapter===N，靠 message 里提章号不够稳。
        add("high", "foreshadow-due-missed", `第${due}章是伏笔「${f.name}」的计划回收章，但正文里没看到回收（${f.revealChange || f.note || "见伏笔表"}）`, "在本章兑现这条伏笔，或 novel_foreshadow 改期到后面", due);
      }
    }
  }

  // 9c) 细纲「必须出现」项在该章正文里没找到 → mid（细纲承诺的东西没兑现）
  {
    const outlines = await listOutlines(root);
    const byChapter = new Map(outlines.map((o) => [Number(o.chapter), o]));
    for (const c of chapters) {
      const o = byChapter.get(Number(c.number));
      if (!o || !Array.isArray(o.mustInclude)) continue;
      for (const item of o.mustInclude) {
        const w = String(item || "").trim();
        if (w.length < 2) continue;
        if (textHasContent(c.text, w)) continue;
        add("mid", "must-include-missed", `第${c.number}章细纲要求「必须出现：${w}」，但正文里没找到`, "补写这一项，或从细纲里删掉这条要求");
      }
    }
  }

  // 10) 骨架冲突：正文里出现的「已退场/未登场」人物、以及违反硬规则关键词的句子，粗筛提示
  {
    // 10a 未登场人物提前当面出场（firstChapter 晚于本章，但正文里以非回忆方式出现）
    for (const ch of bible.characters) {
      if (ch.firstChapter == null || ch.firstChapter === "") continue;
      if (isGoneCharacter(ch)) continue; // 已退场/死亡/失踪的人不参与「提前登场」
      const fc = Number(ch.firstChapter);
      if (!Number.isFinite(fc) || fc <= 0) continue; // 0 = 开篇前，不检查
      const names = appearanceNames(ch);
      for (const c of chapters) {
        if (c.number >= fc) continue; // 还没到该章，正常
        if (!ch.name) continue;
        // 回忆/引号里的提及不算提前登场，与 dead-returns 用同一把尺
        if (!realAppearPositions(c.text, names).length) continue;
        add("mid", "early-appear", `「${ch.name}」设定第${fc}章才登场，却在第${c.number}章就出现`, "改到该登场之后，或调整设定里的登场章，或以回忆/提及处理", c.number);
      }
    }
    // 10b 硬规则关键词命中：与 commit/refresh 共用 hardRuleHits，只认 forbiddenKeywords。
    for (const c of chapters) {
      for (const h of hardRuleHits(bible.rules, c.text)) {
        add("mid", "rule-conflict", `第${c.number}章正文出现「${h.matched}」，可能触碰硬规则「${h.rule}」`, "核对是否违规；若合规请给该规则补一个例外说明");
      }
    }
    // 10c 规则规模：硬规则每章全量注入，堆到一定量就会挤压前情记忆
    const ruleChars = (bible.rules || []).reduce((a, r) => a + String(r.name || "").length + String(r.text || "").length, 0);
    if ((bible.rules || []).length > 80 || ruleChars > 5000) {
      add("info", "rules-too-many", `硬规则已 ${(bible.rules || []).length} 条 / ${ruleChars} 字，每章都会全量带给模型`,
        "删掉只影响某一章或一次性事件的条目（它们更适合写进细纲），同类规则合并");
    }
  }

  // 11) AI 痕迹复检
  for (const c of chapters) {
    const j = verdict(textMetrics(c.text), detectAiTells(c.text));
    if (j.level === "差") add("mid", "ai-tell", `第${c.number}章 AI 痕迹密度 ${j.density}/千字（high ${j.high}）`, "跑 story-deslop 或按 novel-continuity 清单重写该段");
  }

  // 11b) 章首只是续写上一章最后一个动作（opening-restart）
  {
    const coreNames = bible.characters
      .filter((c) => ["核心", "主要", "S", "A"].includes(String(c.importance || c.tier || "").trim()))
      .map((c) => String(c.name || "").trim()).filter(Boolean);
    for (let i = 1; i < chapters.length; i += 1) {
      const cur = chapters[i];
      const prev = chapters[i - 1];
      if (Number(cur.number) !== Number(prev.number) + 1) continue;
      const first = cur.text.replace(/\s+/g, "").slice(0, 40);
      const prevTail = prev.text.split(/\n+/).filter(Boolean).slice(-2).join("").replace(/\s+/g, "");
      if (first.length < 8 || prevTail.length < 8) continue;
      const shared = [...contentBigrams(first)].filter((g) => prevTail.includes(g));
      if (shared.length < 2) continue;
      // 引入了新的时间/天气/地点，就不是「同一段续写」
      const newScene = [...new Set(first.match(NEW_SCENE_RE) || [])].some((w) => !prevTail.includes(w));
      if (newScene) continue;
      // 引入了上一章结尾没出现的新核心人物，也不算续写
      const newPerson = coreNames.some((nm) => first.includes(nm) && !prevTail.includes(nm));
      if (newPerson) continue;
      add("mid", "opening-restart", `第${cur.number}章开头在复述上一章结尾的动作（共同实词：${shared.slice(0, 5).join("、")}）`, "本章是从上一章的动作接着写，读者会以为是同一段的续写；换一个现场起点", cur.number);
    }
  }

  // 11c) 批次段落纲的现场漂移（segment-drift）：只看有段落纲的批次，至少写了 3 章才判
  {
    const bySeg = new Map();
    for (const c of chapters) {
      const info = await chapterFromSegment(root, c.number);
      if (!info) continue;
      const key = `${info.from}-${info.to}`;
      if (!bySeg.has(key)) bySeg.set(key, { info, written: [] });
      bySeg.get(key).written.push(c);
    }
    for (const { info, written } of bySeg.values()) {
      if (written.length < 3) continue;
      const stages = info.segment?.stages || [];
      for (let i = 0; i < stages.length; i += 1) {
        const st = stages[i];
        const places = (st.places || []).map((x) => String(x || "").trim()).filter(Boolean);
        if (!places.length) continue;
        const stageNums = (st.chapters || []).map(Number);
        const inStage = written.filter((c) => stageNums.includes(Number(c.number)));
        if (!inStage.length) continue;
        if (inStage.some((c) => places.some((pl) => c.text.includes(pl)))) continue;
        const last = inStage[inStage.length - 1].number;
        add("mid", "segment-drift", `第${stageNums.join("、")}章属于第${i + 1}台阶，段落纲预计现场「${places.join("、")}」，但正文里完全没出现`, "确认这批的实际场景；段落纲写错了就重写这一段，正文走偏了就拉回本台阶的现场", last);
      }
    }
  }

  // 12) 章尾钩子（report-only info）：最后两段没有常见的追读钩子 → 提示不判废
  if (platformRules(project?.platform).chapterEndHook) {
    for (const c of chapters) {
      // 一律按当前正文重算：索引里存的可能是旧版判法
      const h = checkChapterEndHook(c.text || "");
      if (h && h.ok === false) add("info", "no-end-hook", `第${c.number}章${h.reason}`, "补一个发现/反转、意外动作、被打断、倒计时或短句留白收尾");
    }
  }

  // novel-partner 的文本级检查（字数/复读/复读行/套话/POV/疑似别名）。
  // 不移植、不重写：调它的 np.py，保证两套东西口径一致。失败只会多一条 info。
  try {
    findings.push(...await novelPartnerFindings(bible, chapters));
  } catch (err) {
    add("info", "np-unavailable", `novel-partner 检查未运行：${err?.message || err}`, "体检其余部分不受影响");
  }

  const kept = findings.filter((f) => !dismissed.has(continuityKey(f)));
  const rank = { high: 0, mid: 1, info: 2 };
  kept.sort((a, b) => rank[a.severity] - rank[b.severity]);
  return {
    ok: !kept.some((f) => f.severity === "high"),
    chapters: chapters.length,
    currentChapter: current,
    findings: kept,
    counts: {
      high: kept.filter((f) => f.severity === "high").length,
      mid: kept.filter((f) => f.severity === "mid").length,
      info: kept.filter((f) => f.severity === "info").length,
    },
  };
}

/**
 * 按批体检：一次看整批（段落纲覆盖的连续章），结果分两半——
 * perChapter：要给哪几章重写（按章重写）；blocking：批尾 approve 会被拦的整批问题（断档、批次缺口）。
 * 判断口径与 continuityCheck / checkChapter 一致，只是按段落纲分组汇总。
 */
export async function checkBatch(root, { from, to } = {}) {
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  const check = await continuityCheck(root);
  const index = await loadIndex(root);
  let a = Number(from) || 0;
  let b = Number(to) || 0;
  if (!a || !b) {
    // 没给范围：取 gate 所在章所属的段落纲；没有段落纲就取当前批（最近 10 章）
    const cur = Number(project.currentChapter) || index.length || 1;
    const seg = await chapterFromSegment(root, cur).catch(() => null);
    if (seg) { a = Number(seg.from); b = Number(seg.to); }
    else { b = cur; a = Math.max(1, b - 9); }
  }
  if (b < a) [a, b] = [b, a];
  const inBatch = (n) => Number(n) >= a && Number(n) <= b;
  const inNums = (msg) => {
    const r = String(msg || "").match(/第\s*(\d+)(?:[-–](\d+))?\s*章/g) || [];
    for (const m of r) {
      const mm = m.match(/(\d+)(?:[-–](\d+))?/);
      const lo = Number(mm[1]);
      const hi = Number(mm[2] || mm[1]);
      for (let k = lo; k <= hi; k += 1) if (inBatch(k)) return true;
    }
    return false;
  };
  const perChapter = new Map();
  const blocking = [];
  for (const f of check.findings || []) {
    const owner = Number.isFinite(Number(f.chapter)) ? Number(f.chapter) : null;
    const code = f.code || "";
    // 登场类问题只归到「该登场的那一章」（firstNeed）：message 里还写着「实际第X章才出现」，
    // 不能因此挂到第X章，否则已登场的那章自己也判迟到，还会被推进 blocking 而不是本章。
    if (code === "never-appears" || code === "late-appear") {
      const mm = String(f.message || "").match(/第\s*(\d+)\s*章前?登场/);
      const firstNeed = mm ? Number(mm[1]) : null;
      if (firstNeed != null) {
        if (inBatch(firstNeed)) {
          if (!perChapter.has(firstNeed)) perChapter.set(firstNeed, []);
          perChapter.get(firstNeed).push(f);
        }
      } else if (inNums(f.message)) blocking.push(f);
      continue;
    }
    const sceneCode = code === "opening-restart" || code === "segment-drift" || code === "length-drift" || code === "length-below-floor" || code === "no-end-hook";
    if (code === "foreshadow-overdue" || code === "foreshadow-hoard" || code === "rules-too-many" || code === "np-unavailable") continue;
    if (owner != null && inBatch(owner)) {
      if (!perChapter.has(owner)) perChapter.set(owner, []);
      perChapter.get(owner).push(f);
      continue;
    }
    if (sceneCode && inNums(f.message)) {
      const nums = [...String(f.message).matchAll(/第\s*(\d+)/g)].map((m) => Number(m[1])).filter(inBatch);
      for (const n of nums.length ? nums : [a]) {
        if (!perChapter.has(n)) perChapter.set(n, []);
        perChapter.get(n).push(f);
      }
      continue;
    }
    if (inNums(f.message)) blocking.push(f);
  }
  const rows = [...perChapter.entries()].sort((x, y) => x[0] - y[0]).map(([number, fs]) => ({
    number,
    approved: Boolean((index.find((c) => Number(c.number) === number) || {}).approved),
    counts: {
      high: fs.filter((f) => f.severity === "high").length,
      mid: fs.filter((f) => f.severity === "mid").length,
      info: fs.filter((f) => f.severity === "info").length,
    },
    findings: fs,
    // 「要动笔改」= high 硬错、登场时点不对、章首复述上一章动作、本批偏离段落纲。
    // 这几类光看一眼没用，必须重写；其余 mid/info 只提示。
    action: fs.some((f) => f.severity === "high" || f.code === "never-appears" || f.code === "late-appear"
      || f.code === "opening-restart" || f.code === "segment-drift") ? "rewrite" : fs.length ? "review" : "ok",
    // 有没有 mid/info 级提醒（前端据此给「看过即可」的提示）
    notes: fs.filter((f) => f.severity !== "high").length,
  }));
  // 批内每章都要有一行：写好的没毛病也要列（「没问题」），没写的标出来，别让作者以为漏检了。
  const haveNums = new Set(index.map((c) => Number(c.number)));
  for (let k = a; k <= b; k += 1) {
    if (rows.some((r) => r.number === k)) continue;
    const written = haveNums.has(k);
    rows.push({
      number: k,
      approved: Boolean((index.find((c) => Number(c.number) === k) || {}).approved),
      counts: { high: 0, mid: 0, info: 0 },
      findings: [],
      notes: 0,
      missing: !written,
      action: written ? "ok" : "missing",
    });
  }
  rows.sort((x, y) => x.number - y.number);
  return {
    ok: blocking.length === 0 && !rows.some((r) => r.action === "rewrite" || r.action === "missing"),
    from: a, to: b,
    chapters: rows,
    blocking,
    counts: check.counts,
  };
}

/**
 * 单章体检（进度页每章的「体检」按钮用）。
 * 复用连续性体检，但只返回与该章相关的 findings（message 里含「第N章」或该章缺失/断档），
 * 这样按钮点下去只聚焦这一章的问题，不把全书问题都摊开。
 */
export async function checkChapter(root, number) {
  const n = Number(number);
  if (!Number.isFinite(n) || n <= 0) throw new Error("章节号不合法");
  // 正文里没有这一章（被退回重写 / 没写过）：不能拿「全书没有它的毛病」当成它通过了，
  // 否则批尾 approve 会把这种空章当合格章收进去。
  const exists = (await getIndex(root)).some((c) => Number(c.number) === n);
  if (!exists) return { ok: false, chapter: n, findings: [], counts: { high: 0, mid: 0, info: 0 }, pass: false, missing: true, debutMisses: [] };
  const full = await continuityCheck(root);
  const hit = (f) => {
    const m = String(f.message || "");
    // 登场类问题只归属到「该登场的那一章」（firstNeed），不能因为 message 里顺带写了
    // "实际第X章才出现" 就把它也挂到第X章——那会让已登场的章自己被判迟到。
    if (f.code === "never-appears" || f.code === "late-appear") {
      const mm = m.match(/第\s*(\d+)\s*章前登场/);
      const firstNeed = mm ? Number(mm[1]) : null;
      if (firstNeed != null) return firstNeed === n;
    }
    // 跨章问题带显式属主章（f.chapter）时，只归属到那一章——避免只凭 message 里的「第N章」
    // 把「第3章退场的角色第10章又出现」「第2到第3章断档」这类问题误挂到无关章，把好章判废。
    if (Number.isFinite(Number(f.chapter))) return Number(f.chapter) === Number(n);
    return new RegExp(`第\\s*${n}\\s*章`).test(m) || new RegExp(`第\\s*${n}\\s*章`).test(String(f.hint || ""));
  };
  const findings = (full.findings || []).filter(hit);
  const counts = {
    high: findings.filter((f) => f.severity === "high").length,
    mid: findings.filter((f) => f.severity === "mid").length,
    info: findings.filter((f) => f.severity === "info").length,
  };
  // 「没通过」= high 硬错（吃书/时间线倒退/文件丢失等）任一，
  // 或与本章相关的「重要角色到点未登场」(mid 级 never-appears/late-appear) —— 这两类必须拦，
  // 字数偏离/禁用词/AI 痕迹仍是 mid/info，只提醒不判废（真人写网文本来就分批写）。
  const debutMisses = findings.filter(
    (f) => f.severity === "mid" && (f.code === "never-appears" || f.code === "late-appear"),
  );
  const hardFail = counts.high > 0 || debutMisses.length > 0;
  return {
    ok: !hardFail,
    chapter: n,
    findings,
    counts,
    pass: !hardFail,
    debutMisses, // 明确列出：正是这几条把本章拦下，前端可直接展示"谁没登场"
    bookCounts: full.counts,
  };
}

/**
 * 列出被废弃/退回的章节（读 ledger/review.jsonl 里 kind=discard 的记录 + drafts/ 里的稿子）。
 * 返回 [{number,title,reason,note,draftFile,at}] 按时间倒序。
 */
export async function listDiscarded(root) {
  const rows = await readJsonl(p(root, "ledger/review.jsonl"));
  const restoredNums = new Set(
    rows.filter((x) => x && !x.__corrupt && x.kind === "restore").map((x) => Number(x.number)),
  );
  const purgedFiles = new Set(
    rows.filter((x) => x && !x.__corrupt && x.kind === "purge").map((x) => x.draftFile),
  );
  const out = [];
  for (const r of rows) {
    if (!r || r.__corrupt) continue;
    if (r.kind !== "discard") continue;
    if (purgedFiles.has(r.draftFile)) continue;
    if (restoredNums.has(Number(r.number))) continue;
    let lead = "", chars = 0, exists = false;
    if (r.draftFile) {
      try {
        const body = await readText(p(root, r.draftFile));
        const flat = String(body).replace(/\s+/g, " ").trim();
        chars = flat.length;
        lead = flat.slice(0, 60);
        exists = true;
      } catch { /* 草稿可能已被手动删 */ }
    }
    // 草稿文件已不存在（手动删了）则视为已清理
    if (r.draftFile && !exists) continue;
    out.push({
      number: Number(r.number) || 0,
      title: r.title || "",
      reason: r.reason || "",
      draftFile: r.draftFile || "",
      lead, chars,
      at: r.at || "",
    });
  }
  // 按时间倒序（新的在前）
  out.sort((a, b) => String(b.at).localeCompare(String(a.at)));
  return out;
}

/**
 * 读某条废章的草稿全文（废章页展开查看用）。
 * draftFile 是相对项目根的路径（ledger 里记录的）。禁止越界到项目外。
 */
export async function readDiscarded(root, { draftFile } = {}) {
  if (!draftFile || typeof draftFile !== "string") throw new Error("缺少 draftFile");
  const abs = p(root, draftFile);
  const rel = path.relative(root, abs);
  if (rel.startsWith("..") || path.isAbsolute(rel)) throw new Error("非法的草稿路径");
  let text = "";
  try { text = await readText(abs); } catch { throw new Error("草稿文件不存在，可能已被手动删除"); }
  return { ok: true, draftFile, text };
}

/**
 * 永久删除一条废章：把草稿文件删掉 + 记一条 purge 事件（之后 listDiscarded 会跳过该条）。
 * 用于废章太多占空间时清理。既没恢复价值、也不想再看它的时候用。
 */
export async function purgeDiscarded(root, args = {}) {
  return withProjectLock(root, () => purgeDiscardedLocked(root, args));
}

async function purgeDiscardedLocked(root, { draftFile } = {}) {
  if (!draftFile || typeof draftFile !== "string") throw new Error("缺少 draftFile");
  const abs = p(root, draftFile);
  const rel = path.relative(root, abs);
  if (rel.startsWith("..") || path.isAbsolute(rel)) throw new Error("非法的草稿路径");
  let removed = false;
  try { await rm(abs, { force: true }); removed = true; } catch { /* 文件可能已不存在 */ }
  await appendJsonl(p(root, "ledger/review.jsonl"), { kind: "purge", draftFile, at: now() });
  return { ok: true, removed, draftFile };
}

/**
 * 把废章草稿恢复成正文（重新走一遍 commit 的质量判定）。
 * 恢复后从 review.jsonl 记一条 restore，草稿保留不删（可重复恢复）。
 */
export async function restoreDiscarded(root, args = {}) {
  return withProjectLock(root, () => restoreDiscardedLocked(root, args));
}

async function restoreDiscardedLocked(root, { draftFile, number, title } = {}) {
  const { text } = await readDiscarded(root, { draftFile });
  const project = await loadProject(root);
  const n = Number(number) || (await getIndex(root)).length + 1;
  const r = await commitChapter(root, { number: n, title: title || `第${n}章`, text });
  await appendJsonl(p(root, "ledger/review.jsonl"), { kind: "restore", number: n, draftFile, at: now() });
  return { ok: true, restored: n, chapter: r };
}

/**
 * 把某章标记为废章：从正文章节索引里摘掉、文件挪进 drafts/，章号释放、currentChapter 回退。
 * 与 requestRewrite 的区别：废章不需要「待确认」前置条件，用于「体检没过」或「去味后旧稿作废」。
 * 返回 { ok, discarded, draftFile }。
 */
export async function discardChapter(root, args = {}) {
  return withProjectLock(root, () => discardChapterLocked(root, args));
}

async function discardChapterLocked(root, { number, reason } = {}) {
  const n = Number(number);
  if (!Number.isFinite(n) || n <= 0) throw new Error("章节号不合法");
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目（缺 project.json）：${root}`);
  const index = await getIndex(root);
  const at = index.findIndex((c) => Number(c.number) === n);
  if (at < 0) throw new Error(`第 ${n} 章不存在于正文索引，无法作废`);
  const row = index[at];
  // 先备份到 drafts/
  const draftsDir = p(root, LAYOUT.drafts);
  await ensureDir(draftsDir);
  const stamp = Date.now().toString(36);
  const draftName = `${pad3(n)}-${(row.title || "未命名")}-discard-${stamp}.md`;
  let draftFile = "";
  try {
    const body = await readText(p(root, row.file));
    await writeText(p(root, `${LAYOUT.drafts}/${draftName}`), body);
    draftFile = `${LAYOUT.drafts}/${draftName}`;
  } catch { /* 文件缺失也继续摘索引 */ }
  // 摘索引 + 删正文文件
  index.splice(at, 1);
  await writeJson(p(root, LAYOUT.chapterIndex), index);
  await rmQuiet(p(root, row.file));
  // 记一条作废账
  await appendJsonl(p(root, "ledger/review.jsonl"), { kind: "discard", number: n, title: row.title || "", reason: reason || "", draftFile, at: now() });
  // 回退进度
  const remaining = index.map((c) => Number(c.number)).filter(Number.isFinite);
  const maxLeft = remaining.length ? Math.max(...remaining) : 0;
  project.currentChapter = maxLeft;
  project.rewriteCounts = project.rewriteCounts || {};
  delete project.rewriteCounts[String(n)];
  // 作废后回到「写作中」，章号指向被作废的那一章，方便立刻重写它
  project.gate = { phase: "writing", chapter: n, reason: `第 ${n} 章已作废，可重写这一章`, at: now() };
  await saveProject(root, project);

  // 记忆跟着正文走：这一章的章记忆、覆盖它的卷记忆一并清掉，重写前不拿旧内容喂上下文。
  const memFile = p(root, MEMORY_FILE);
  const memRows = await readJsonl(memFile).catch(() => []);
  const keptMem = memRows.filter((r) => r && !r.__corrupt && !(Number(r.chapter) === n) && !(r.kind === "volume" && Number(r.from) <= n && Number(r.to) >= n));
  if (keptMem.length !== memRows.length) {
    await writeText(memFile, keptMem.map((r) => JSON.stringify(r)).join("\n") + (keptMem.length ? "\n" : ""));
  }

  // 伏笔/登场章不动正文账，先报给作者确认要不要一起清
  const fsRows = await readJsonl(p(root, LAYOUT.foreshadow)).catch(() => []);
  const foreshadows = foldForeshadow(fsRows).filter((f) => Number(f.plantedChapter) === n && f.status === "open").map((f) => f.name);
  const bible = await loadBible(root);
  const characters = (bible.characters || []).filter((c) => Number(c.firstChapter) === n).map((c) => c.name);

  return { ok: true, discarded: n, draftFile, impacts: { foreshadows, characters } };
}

/** 作废后按作者确认，清掉这一章挂着的伏笔（移出未收）和人物登场章。 */
export async function cleanupAfterDiscard(root, args = {}) {
  return withProjectLock(root, () => cleanupAfterDiscardLocked(root, args));
}

async function cleanupAfterDiscardLocked(root, { number, foreshadow = true, settings = true } = {}) {
  const n = Number(number);
  if (!Number.isFinite(n) || n <= 0) throw new Error("章节号不合法");
  const out = { ok: true, foreshadows: [], characters: [] };
  if (foreshadow) {
    const rows = await readJsonl(p(root, LAYOUT.foreshadow)).catch(() => []);
    for (const f of foldForeshadow(rows).filter((x) => Number(x.plantedChapter) === n && x.status === "open")) {
      await appendJsonl(p(root, LAYOUT.foreshadow), {
        id: f.id, op: "abandon", name: f.name, plantedChapter: f.plantedChapter,
        dueChapter: f.dueChapter, status: "abandoned", at: now(),
      });
      out.foreshadows.push(f.name);
    }
  }
  if (settings) {
    const bible = await loadBible(root);
    let changed = false;
    for (const c of bible.characters || []) {
      if (Number(c.firstChapter) === n) {
        delete c.firstChapter;
        changed = true;
        out.characters.push(c.name);
      }
      // 作废某一章，位置轨迹里那一笔也要删掉，否则下一章会按废稿的地点开写
      if (Array.isArray(c.locationTrail) && c.locationTrail.some((x) => Number(x.chapter) === n)) {
        c.locationTrail = c.locationTrail.filter((x) => Number(x.chapter) !== n);
        c.location = c.locationTrail.length ? c.locationTrail[c.locationTrail.length - 1].place : "";
        changed = true;
      }
    }
    if (changed) await saveBible(root, bible);
  }
  return out;
}

/**
 * 人设漂移抽样（最轻版，只报不拦）：每 10 章抽一次。
 * 取该章对话（引号内文本，按说话人归属尽量就近取），返回给 AI 逐句对照 bible 里各角色 voice 打标记用。
 * 本函数只做「抽取 + 组装配料」，判定交给 AI（report-only，不进 continuity 判废）。
 * 返回 { sample:{chapter, dialogue:[{who,line}]}, voices:[{name,voice}] }，章号不足或无对话时 dialogue 为空。
 */
export async function sampleVoiceDrift(root, { chapter } = {}) {
  const project = await loadProject(root);
  if (!project) throw new Error(`不是小说项目：${root}`);
  const bible = await loadBible(root);
  const n = Number(chapter) || Number(project.currentChapter) || 0;
  if (!n) return { sample: { chapter: 0, dialogue: [] }, voices: [] };
  // 抽对话：引号内文本；说话人用最近的「XX说/道/问」启发式归属，取不到就标「未知」
  const LINES = /[“"]([^”"]{2,200})[”"]/g;
  const extract = (text) => {
    const out = [];
    for (const m of text.matchAll(LINES)) {
      const line = m[1].trim();
      if (!line) continue;
      const before = text.slice(Math.max(0, m.index - 16), m.index);
      const who = (before.match(/([\u4e00-\u9fa5]{2,3})(?:[^。！？\n]{0,6})?(说道|说|道|问道|问|答道|答|喊道|喊|笑道|笑|叫道)[：:，,]?\s*$/) || [])[1] || "";
      out.push({ who: who || "未知", line });
    }
    return out;
  };
  let text = "";
  try { text = (await readChapter(root, n)).text; } catch { /* 该章可能不在正文 */ }
  const entry = (await loadIndex(root)).find((c) => Number(c.number) === n);
  const cast = entry?.characters || [];
  const dialogue = extract(text);
  const voices = bible.characters
    .filter((c) => c.name && (cast.length ? cast.includes(c.name) : true))
    .map((c) => ({ name: c.name, voice: c.voice || "（未设 voice）", role: c.role || "" }));
  return { sample: { chapter: n, dialogue: dialogue.slice(0, 40) }, voices };
}

/* ------------------------------ 项目修复（novel_repair） ------------------------------ */

async function backupFile(file, stamp) {
  if (!existsSync(file)) return "";
  const to = `${file}.bak-${stamp}`;
  await copyFile(file, to);
  return to;
}

/**
 * 从正文文件重建 chapters/index.json。
 * 索引是派生数据：只要 chapters/*.md 还在，就能按文件名和正文重算出来。
 * 老索引里的人工字段（summary / characters / approved）按章号保留。
 */
async function rebuildIndex(root, project, bible, stamp) {
  const dir = p(root, LAYOUT.chapters);
  const files = (await listFiles(dir)).filter((n) => /^\d{3,4}-.*\.md$/u.test(n));
  const old = await readJson(p(root, LAYOUT.chapterIndex), []);
  const byNumber = new Map((Array.isArray(old) ? old : []).map((c) => [Number(c.number), c]));
  const rules = platformRules(project?.platform);
  const out = [];
  for (const name of files.sort()) {
    const m = /^(\d{3,4})-(.*)\.md$/u.exec(name);
    if (!m) continue;
    const number = Number(m[1]);
    const fileTitle = m[2] || `第${number}章`;
    const prev = byNumber.get(number) || {};
    const text = await readText(p(dir, name));
    const metrics = textMetrics(text);
    const judge = verdict(metrics, detectAiTells(text));
    const bannedHits = (bible.style?.banned || []).filter((b) => b && text.includes(b));
    const ruleHits = hardRuleHits(bible.rules, text);
    const chapterVerdict = (judge.level === "差" || bannedHits.length || ruleHits.length) ? "needs_fix" : "pass";
    out.push({
      number,
      title: prev.title || fileTitle,
      file: `chapters/${name}`,
      chars: metrics.chars,
      dialogueRatio: metrics.dialogueRatio,
      verdict: judge.level,
      chapterVerdict: prev.chapterVerdict || chapterVerdict,
      fixReasons: Array.isArray(prev.fixReasons) ? prev.fixReasons : [],
      aiTellDensity: judge.density,
      summary: prev.summary || "",
      characters: Array.isArray(prev.characters) ? prev.characters : [],
      endHook: prev.endHook || checkChapterEndHook(text),
      approved: Boolean(prev.approved),
      committedAt: prev.committedAt || now(),
      repairedAt: stamp,
    });
  }
  out.sort((a, b) => a.number - b.number);
  await writeJson(p(root, LAYOUT.chapterIndex), out);
  return out;
}

/** 清掉 JSONL 里解析不了的行：坏行单独留证，好行原样写回。 */
async function cleanJsonl(file, stamp) {
  if (!existsSync(file)) return 0;
  const raw = await readText(file);
  const good = [];
  const bad = [];
  for (const [i, line] of raw.split("\n").entries()) {
    const t = line.trim();
    if (!t) continue;
    try {
      JSON.parse(t);
      good.push(t);
    } catch {
      bad.push({ line: i + 1, raw: t });
    }
  }
  if (!bad.length) return 0;
  await writeText(`${file}.corrupt-${stamp}`, bad.map((b) => JSON.stringify(b)).join("\n") + "\n");
  await writeText(file, good.length ? good.join("\n") + "\n" : "");
  return bad.length;
}

export async function repairProject(root) {
  return withProjectLock(root, () => repairProjectLocked(root));
}

async function repairProjectLocked(root) {
  if (!existsSync(p(root, LAYOUT.project))) {
    throw new Error(`不是小说项目（缺 project.json）：${root}`);
  }
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const backups = [];
  backups.push(await backupFile(p(root, LAYOUT.project), stamp));
  backups.push(await backupFile(p(root, LAYOUT.chapterIndex), stamp));
  backups.push(await backupFile(p(root, LAYOUT.bible), stamp));

  const raw = await readJson(p(root, LAYOUT.project), null);
  const { value: project, migrated, from } = migrateProject(raw);
  const bible = await loadBible(root);

  // 目录补齐（老项目可能缺 metrics/ review/ drafts/ 等）
  for (const d of [LAYOUT.chapters, LAYOUT.ledger, LAYOUT.review, LAYOUT.drafts, "exports", "platforms"]) {
    await ensureDir(p(root, d));
  }

  const index = await rebuildIndex(root, project, bible, stamp);

  // 老书补登场章：不依赖模型，按已存档正文反推（空着或比正文晚才写）。
  const debutFilled = await backfillFirstAppearances(root, index).catch(() => []);

  // 账本坏行清理
  const ledger = [];
  for (const rel of [LAYOUT.foreshadow, LAYOUT.timeline, "ledger/outline.jsonl", LAYOUT.usage, "ledger/dismissed.jsonl"]) {
    const removed = await cleanJsonl(p(root, rel), stamp);
    if (removed) ledger.push({ file: rel, removed });
  }

  // 门控与正文对齐：只修「不可能的状态」，不替作者做决定
  const before = { ...(project.gate || {}) };
  const max = index.length ? index[index.length - 1].number : 0;
  const phase = project.gate?.phase || "concept";
  const at = Number(project.gate?.chapter) || 0;
  let next = { ...project.gate };
  if (!max) {
    if (["writing", "awaiting_review"].includes(phase)) next = { ...next, phase: "outline", chapter: 0, reason: "修复：还没有正文，回到排细纲" };
  } else if (phase === "awaiting_review" && (!at || at > max || !index.some((c) => c.number === at))) {
    next = { ...next, phase: "writing", chapter: max + 1, reason: `修复：待确认的第${at || "?"}章不存在，回到写第${max + 1}章` };
  } else if (phase === "writing" && at && at <= max) {
    next = { ...next, phase: "awaiting_review", chapter: max, reason: `修复：第${max}章已存在正文，改为待作者确认` };
  } else if (["concept", "outline_accept", "bible", "outline"].includes(phase) && max > 0) {
    next = { ...next, phase: "writing", chapter: max + 1, reason: `修复：已有 ${max} 章正文，门控同步到写第${max + 1}章` };
  }
  project.schemaVersion = SCHEMA_VERSION;
  project.gate = next;
  project.currentChapter = Math.max(Number(project.currentChapter) || 0, max);
  project.gates = { ...(project.gates || {}) };
  if (max > 0) { project.gates.bible = true; project.gates.outline = true; }
  delete project.__migratedFrom;
  await saveProject(root, project);

  return {
    ok: true,
    schema: { from, to: SCHEMA_VERSION, migrated },
    chapters: index.length,
    indexRebuilt: true,
    debutFilled,
    ledger,
    gate: { before, after: next },
    backups: backups.filter(Boolean),
  };
}

/** 作者点过「标记为合理」的条目统计：按 code 聚合，用来判断哪条规则噪音最大。 */
export async function dismissedStats(root) {
  const rows = await readJsonl(p(root, DISMISS_FILE)).catch(() => []);
  const byCode = {};
  for (const r of rows) {
    if (!r || r.__corrupt) continue;
    const key = r.code || (r.kind === "logic" ? "logic" : "unknown");
    byCode[key] = (byCode[key] || 0) + 1;
  }
  return { total: rows.filter((r) => r && !r.__corrupt).length, byCode };
}
