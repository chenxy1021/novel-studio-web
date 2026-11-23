// dsh-novel-studio / 宿主侧 HTTP API —— 给左栏「写小说」面板取数用。
//
// 只做两件事：把 domain.js 的确定性能力暴露成 JSON，以及记住最近打开的项目。
// 不调模型、不写正文、不做判断（判断在 domain.js 里）。
import { existsSync } from "node:fs";
import { cp, mkdir, readFile, readdir, realpath, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import {
  approveChapter, bibleUpsert, mergeDuplicateEntities, listMergePairs, splitMergedEntity, findSame, backfillFirstAppearances, buildContext, changeDirection, commitChapter, continuityCheck, writeStyleFile, backfillLocationTrail,
  exportChapters, gateState, getOutline, guardGate, initProject, loadBible, saveBible,
  listForeshadow, loadIndex, loadProject, payoffForeshadow, plantForeshadow, proposeConcepts, deleteForeshadow,
  readChapter, requestRewrite, rescheduleForeshadow, saveProject, selectConcept, setOutline, acceptOutline, outlineVolume,
  refreshChapterVerdict,
  localOutlineSlice,
  listOutlines, deleteOutline, checkChapter, discardChapter, listDiscarded, readDiscarded, restoreDiscarded, purgeDiscarded,
  cleanupAfterDiscard,
  syncSettingFromChapter, foreshadowsToPlant, sampleVoiceDrift, buildMemoryLedger, narrativeMemory,
  splitScenes, endSceneState, dismissFinding, logicKey, loadDismissedSet,
  repairProject, usageSummary, chapterMinChars, checkBatch,
} from "./domain.js";
import { platformRules } from "./platforms.js";
import { deleteSegment, listSegments } from "./segment.js";
import { DEFAULT_PROJECTS_DIR, assertBrowsableRoot, assertWritableRoot, realpathLoose, p, appendJsonl, readText } from "./io.js";
import { countChars, checkChapterEndHook } from "./metrics.js";

// 注意：webServer 的前缀匹配是 pathname === prefix || pathname.startsWith(`${prefix}/`)，
// 所以前缀不能带尾斜杠，否则 /novel/api/ping 永不命中。
import { listAllSkills } from "./index.js";
import { buildEchoMemory, loadMemoryRows, loadVolumes, refreshVolumes, volumeMemory, volumeOf } from "./memory.js";
import { buildVolumeDigest, appendMemory, clampSummary, SUMMARY_TARGET, updateRelations, skillBlock, SHORT_PLATFORMS } from "./memory.js";

export const API_PREFIX = "/novel/api";
/** 客户端拼 URL 用的前缀（带尾斜杠）。 */
export const API_BASE = `${API_PREFIX}/`;
export const PLUGIN_VERSION = "0.9.35";

const MAX_BODY = 4 * 1024 * 1024;
const RECENT_LIMIT = 20;

// 写请求必须同源 + JSON：插件路由绑在 loopback 上，但任意网页仍可用 text/plain 简单请求
// 盲打 POST（CORS 不拦），或靠 DNS rebinding 读回结果。这里不引入 token 存储，
// 只认「同源 Origin + JSON」，够挡住浏览器侧跨站写；本机其它进程本来就能直接读文件。
function checkWriteOrigin(req) {
  const method = String(req.method || "GET").toUpperCase();
  if (!["POST", "PUT", "PATCH", "DELETE"].includes(method)) return;
  const headers = req.headers;
  // 进程内调用（lib/index.js 的 sessionReturn 伪造 req）没有 headers，不属于浏览器跨站
  if (!headers) return;
  // 根本没有主体（null 原型）的调用同样来自进程内
  if (!headers["content-type"] && !headers.origin && !headers.referer) return;
  const ctype = String(headers["content-type"] || "").toLowerCase();
  if (!ctype.startsWith("application/json")) throw new HttpError(415, "写请求必须带 content-type: application/json");
  const origin = String(headers.origin || headers.referer || "");
  if (!origin) return;
  let host = "";
  try { host = new URL(origin).host; } catch { throw new HttpError(403, `拒绝跨站写入：Origin 无法解析（${origin}）`); }
  const self = String(headers.host || "");
  if (self && host !== self) throw new HttpError(403, `拒绝跨站写入：Origin ${origin} 与 Host ${self} 不同源`);
}

// 单章细纲的输出上限：7 节 Markdown + 机器块。3400 在信息量大的章（人物多、伏笔多）
// 会被截断，而且机器块排在最后，一截断就整章白生成。默认 8000，可用环境变量 DSH_NOVEL_OUTLINE_TOKENS 调大。
const OUTLINE_MAX_TOKENS = (() => {
  const raw = Number(process.env.DSH_NOVEL_OUTLINE_TOKENS);
  if (!Number.isFinite(raw) || raw < 2000) return 8000;
  return Math.min(Math.round(raw), 32000);
})();

function nameStyle() {
  return "人物取名按题材走：古风/玄幻/历史/武侠用古意、有身份感的名字（姓名总长 1-4 字，单姓配 1-3 字名，复姓才可 4 字，单姓不许四字全名）；现代/都市/末世/科幻用现代名、代号或外号（如「陈默」「K-7」「老鬼」），别一律起古风仙名，也别一堆生僻字。市井底层用俗名绰号，上位者用有分量的名字，一本里名字要有层次，不能人人仙气。禁止林凡、叶辰、苏辰、龙傲天这类模板名，也不要照搬现成小说里的名字。";
}

function titleStyle() {
  return "书名扣住全书的「核心矛盾或核心爽点」，2-10 字，具体、有画面、能记住、一眼想点进去。可以有一个记忆点物件，但别硬找一个物件/营生当钩子。禁止「XX行」「XX录」「XX记」「XX志」「XX传」「XX诀」这类模板结构；禁止四字成语堆砌和空泛的大词（如「逆天」「绝世」「苍穹」）；别一批里全是「《XX人》《XX粮》《XX灯》」这种单一物件/职业名词式取法；同一批候选的书名不许共用同一个字或同一种句式。";
}

const recentFile = () => process.env.DSH_NOVEL_RECENT_FILE
  || path.join(homedir(), ".dsh", "novel-studio", "recent.json");
const modelPrefFile = () => path.join(homedir(), ".dsh", "novel-studio", "model.json");

// 面板里选的模型存到服务端：Agent 工具调用（novel_outline generate 等）没有面板的
// localStorage，不记住就会退回“枚举所有模型”，很容易撞上一个不吐字的 provider。
async function readModelPref() {
  try { return JSON.parse(await readFile(modelPrefFile(), "utf8")); } catch { return null; }
}
async function writeModelPref(sel) {
  try {
    await mkdir(path.dirname(modelPrefFile()), { recursive: true });
    await writeFile(modelPrefFile(), JSON.stringify(sel));
  } catch { /* 记不住不影响生成 */ }
}

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

/* ------------------------------ 最近项目 ------------------------------ */

async function readRecent() {
  try {
    const raw = await readFile(recentFile(), "utf8");
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed?.projects) ? parsed.projects : [];
  } catch {
    return [];
  }
}

async function remember(dir, title) {
  try {
    const projects = await readRecent();
    const next = [{ dir, title: title || path.basename(dir), at: new Date().toISOString() },
      ...projects.filter((p) => p.dir !== dir)].slice(0, RECENT_LIMIT);
    await writeRecentSafe(next);
    return next;
  } catch {
    return [];
  }
}

// recent.json 有四个写点、还可能被两个 DSH 实例同时写：串行化 + 先写 .tmp 再 rename，
// 避免读到半截 JSON（读失败会静默退回空书架）。
let recentWriteChain = Promise.resolve();
function writeRecentSafe(projects) {
  const run = async () => {
    const file = recentFile();
    await mkdir(path.dirname(file), { recursive: true });
    const tmp = `${file}.${process.pid}.tmp`;
    await writeFile(tmp, JSON.stringify({ version: 1, projects }, null, 2) + "\n", "utf8");
    await rename(tmp, file);
  };
  const next = recentWriteChain.then(run, run);
  recentWriteChain = next.catch(() => {});
  return next;
}

/* ------------------------------ 书架 / 删除 ------------------------------ */

/** 书架：最近列表里的每个存活项目，给出轻量摘要（供左栏书架渲染）。 */
async function shelfPayload() {
  const projects = await readRecent();
  const books = [];
  const STALE_KEEP_MS = 30 * 24 * 3600 * 1000;
  let dirty = false;
  const next = [];
  for (const p of projects) {
    try {
      // recent 里可能是旧字面路径（/var vs /private/var、软链）：按真实路径再认一次
      const dir = await realpathLoose(p.dir).catch(() => p.dir);
      const project = await loadProject(dir);
      if (!project) {
        // 外接盘掉线/网盘没挂载时目录会暂时消失：先标记，别立刻把书从书架抹掉
        const since = p.missingSince || new Date().toISOString();
        if (Date.now() - new Date(since).getTime() > STALE_KEEP_MS) { dirty = true; continue; }
        next.push({ ...p, stale: true, missingSince: since });
        dirty = dirty || !p.missingSince;
        continue;
      }
      next.push({ ...p, stale: false, missingSince: undefined });
      if (p.stale || p.missingSince) dirty = true;
      const index = await loadIndex(dir);
      books.push({
        dir,
        title: project.title || "",
        genre: project.genre || "",
        platform: project.platform || "",
        currentChapter: project.currentChapter || 0,
        targetChapters: project.targetChapters || 0,
        totalChars: index.reduce((a, c) => a + (c.chars || 0), 0),
        lastOpenedAt: p.at || "",
      });
    } catch {
      const since = p.missingSince || new Date().toISOString();
      if (Date.now() - new Date(since).getTime() > STALE_KEEP_MS) { dirty = true; continue; }
      next.push({ ...p, stale: true, missingSince: since });
      dirty = dirty || !p.missingSince;
    }
  }
  if (dirty) await writeRecentSafe(next).catch(() => {});
  return { ok: true, books };
}

/**
 * 会话交回的防误覆盖检查：交回是整篇覆盖写，跑偏一次就把大纲/世界观换掉。
 * 两种情况拒绝：字数腰斩（< 原文 60%）、内容像伏笔清单却不是大纲。
 */
export function sessionOverwriteProblem(label, cur, next) {
  const a = String(cur || "").trim().length;
  const b = String(next || "").trim().length;
  if (!b) return "";
  if (a >= 1200 && b < a * 0.6) return `${label}从 ${a} 字变成 ${b} 字，像是换成了另一份文档`;
  if (/伏笔网|伏笔清单/.test(next) && !/(第\s*\d+[-–—~]\d+\s*章)/.test(next) && a > b) return `交回的内容像伏笔清单，不像${label}`;
  return "";
}

/** 删除：移进 ~/.dsh/novel-studio/trash/（可恢复），并把它清出 recent。 */
async function deleteProject(root) {
  await requireProject(root); // 只删真正的小说项目，别误伤别的目录
  const abs = await realpathLoose(root);
  // 最后一道闸：不许是家目录、磁盘根，也不许是项目的上级目录
  if (abs === path.resolve(homedir()) || abs === path.parse(abs).root) {
    throw new HttpError(400, "拒绝删除：这个路径不是小说项目目录");
  }
  // 直接 rm -rf 误点就永久丢稿；rename 进回收站，作者还能从用户目录里捞回来。
  const trashDir = path.join(homedir(), ".dsh", "novel-studio", "trash");
  await mkdir(trashDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/gu, "-").slice(0, 19);
  const target = path.join(trashDir, `${stamp}-${path.basename(abs)}`);
  try {
    await rename(abs, target);
  } catch (error) {
    // 跨分区 rename 会 EXDEV：退回复制再删
    if (error.code !== "EXDEV") throw error;
    await cp(abs, target, { recursive: true });
    await rm(abs, { recursive: true, force: true });
  }
  try {
    const projects = await readRecent();
    const next = projects.filter((p) => p.dir !== root && p.dir !== abs);
    await writeRecentSafe(next).catch(() => {});
  } catch { /* recent 清理失败不影响删除本身 */ }
  return { ok: true, dir: root, deleted: true, trash: target };
}

/* ------------------------------ 入参校验 ------------------------------ */

async function assertDir(value, { mustExist = true } = {}) {
  if (typeof value !== "string" || !value.trim()) throw new HttpError(400, "缺少 dir 参数（项目绝对路径）");
  if (!path.isAbsolute(value.trim())) throw new HttpError(400, `dir 必须是绝对路径：${value.trim()}`);
  // realpath 之后再判存在：软链指到别处时，后面的存在性/项目校验看的都是真实目标
  const abs = await realpathLoose(value.trim());
  if (!mustExist && !existsSync(abs)) return abs;
  if (!existsSync(abs)) throw new HttpError(404, `目录不存在：${abs}`);
  return abs;
}

async function requireProject(root) {
  const project = await loadProject(root);
  if (!project) throw new HttpError(404, `不是小说项目（缺 project.json）：${root}；先用「新建项目」或 novel_init 初始化`);
  return project;
}

/* ------------------------------ 组装视图数据 ------------------------------ */

async function summaryPayload(root) {
  const project = await requireProject(root);
  const index = await loadIndex(root);
  const fsState = await listForeshadow(root, project.currentChapter || 1);
  const totalChars = index.reduce((a, c) => a + (c.chars || 0), 0);
  // 只读：summary 每次刷新都会跑，这里顺手写 recent 会让「打开一本书」变成一次写盘
  const recent = await readRecent();
  const rules = platformRules(project.platform);
  const gate = gateState(project);
  // 老章可能没有 endHook 字段（v0.9.19 之前提交）：读一次正文补算，让进度页钩子提示对新旧章一致。
  // 作者标记过「合理」的章，进度页也不再挂这条提示。
  const dismissed = await loadDismissedSet(root);
  const hookByNum = new Map();
  for (const c of index) {
    if (dismissed.has(`continuity|no-end-hook|ch${c.number}`)) continue;
    if (c.endHook) { hookByNum.set(c.number, c.endHook); continue; }
    try {
      const { text } = await readChapter(root, c.number);
      hookByNum.set(c.number, checkChapterEndHook(text));
    } catch { /* 文件缺失就跳过 */ }
  }
  return {
    ok: true,
    dir: root,
    usage: await usageSummary(root),
    project: {
      title: project.title,
      genre: project.genre || "",
      platform: project.platform || "",
      platformName: rules.name,
      logline: project.logline || "",
      targetChapters: project.targetChapters || 0,
      wordsPerChapter: project.wordsPerChapter || 0,
      referenceBook: project.referenceBook || "",
      totalWords: project.totalWords || 0,
      currentChapter: project.currentChapter || 0,
      gates: project.gates || {},
      direction: project.direction || "",
      directionHistory: project.directionHistory || [],
    },
    wordRange: { min: rules.wordsMin, max: rules.wordsMax, name: rules.name },
    gate,
    concepts: Array.isArray(project.concepts) ? project.concepts : [],
    conceptSelected: project.conceptSelected || null,
    chapters: index.map((c) => ({
      number: c.number,
      title: c.title,
      chars: c.chars || 0,
      verdict: c.verdict || "",
      chapterVerdict: c.chapterVerdict || (c.verdict === "差" ? "needs_fix" : "pass"),
      fixReasons: Array.isArray(c.fixReasons) ? c.fixReasons : [],
      reviewed: Boolean(c.chapterVerdict || c.verdict),
      approved: Boolean(c.approved),
      platformIssues: c.platformIssues || 0,
      dialogueRatio: c.dialogueRatio ?? null,
      aiTellDensity: c.aiTellDensity ?? null,
      summary: c.summary || "",
      characters: Array.isArray(c.characters) ? c.characters : [],
      excerpt: String(c.summary || "").slice(0, 50),
      endHook: hookByNum.get(c.number) || c.endHook || null,
    })),
    totalChars,
    badChapters: index.filter((c) => c.verdict === "差").map((c) => c.number),
    foreshadow: {
      open: fsState.open.map((f) => ({
        name: f.name, plantedChapter: f.plantedChapter,
        dueChapter: f.dueChapter ?? null, overdue: Boolean(f.overdue), note: f.note || "",
        kind: f.kind || "", source: f.source || "", plantBeat: f.plantBeat || "",
        revealWho: f.revealWho || "", revealChange: f.revealChange || "",
        hint: f.hint || "", abandon: f.abandon || "",
      })),
      paid: fsState.paid.map((f) => ({
        name: f.name, plantedChapter: f.plantedChapter, payoffChapter: f.payoffChapter ?? null,
        kind: f.kind || "", source: f.source || "", plantBeat: f.plantBeat || "",
        revealWho: f.revealWho || "", revealChange: f.revealChange || "", hint: f.hint || "",
      })),
      paidCount: fsState.paid.length,
      overdueCount: fsState.open.filter((f) => f.overdue).length,
      plan: project.foreshadowPlan || "",
      planAt: project.foreshadowPlanAt || "",
    },
    nextChapter: (project.currentChapter || 0) + 1,
    next: index.length
      ? `novel_outline ${project.currentChapter + 1} → novel_context ${project.currentChapter + 1} → 写正文`
      : "novel_bible 建角色与硬规则 → novel_outline 1 → novel_context 1 → 写正文",
    team: buildTeam(project, index),
    recent,
  };
}

/* 把这本书的设定整理成「可以直接贴给 Agent」的任务书。
   面板的全部作用就是生成这段文本：用户填设定 → 复制/发送 → Agent 按它连写。
   这样面板不需要能直接调模型的权限，也不会和会话里的 Agent 抢方向盘。 */
function buildBrief(project, bible) {
  const lines = [];
  const chars = bible.characters || [];
  const world = bible.world || [];
  const rules = bible.rules || [];
  const style = bible.style || {};
  lines.push(`《${project.title}》${project.genre ? " · " + project.genre : ""}${project.platform ? " · " + project.platform : ""}`);
  if (project.targetChapters || project.wordsPerChapter) {
    lines.push(`规模：目标 ${project.targetChapters || "?"} 章，每章约 ${project.wordsPerChapter || "?"} 字。`);
  }
  if (project.logline) lines.push(`一句话故事：${project.logline}`);
  if (project.synopsis) lines.push(`故事梗概：${project.synopsis}`);
  if (chars.length) {
    lines.push("\n【人物】");
    for (const c of chars) {
      const bits = [
        c.rolePosition || "",
        c.importance ? `重要性：${c.importance}` : "",
        c.role,
        c.age ? `年龄：${c.age}` : "",
        c.gender ? `性别：${c.gender}` : "",
        c.race ? `种族：${c.race}` : "",
        c.want ? `想要：${c.want}` : "",
        c.fear ? `怕：${c.fear}` : "",
        c.bottomLine ? `底线：${c.bottomLine}` : "",
        c.flaw ? `缺陷：${c.flaw}` : "",
        c.secret ? `秘密：${c.secret}` : "",
        c.voice ? `说话方式：${c.voice}` : "",
      ].filter(Boolean);
      lines.push(`- ${c.name}${bits.length ? "｜" + bits.join("｜") : ""}`);
    }
  }
  if (world.length) {
    lines.push("\n【世界观】");
    for (const w of world) lines.push(`- ${w.name}：${w.text || w.note || ""}`.trim());
  }
  if (rules.length) {
    lines.push("\n【硬规则（不能违反）】");
    for (const r of rules) lines.push(`- ${r.name}：${r.text || ""}${[r.judge ? `判定者：${r.judge}` : "", r.cost ? `代价：${r.cost}` : "", r.boundary ? `边界：${r.boundary}` : "", r.belief ? `主角以为：${r.belief}` : ""].filter(Boolean).join("；")}`.trim());
  }
  if ((bible.factions || []).length) {
    lines.push("\n【势力】");
    for (const x of bible.factions) lines.push(`- ${x.name}：${[x.hiddenRules ? `潜规则：${x.hiddenRules}` : "", x.attitude ? `对主角：${x.attitude}` : "", x.misjudge ? `误以为：${x.misjudge}` : ""].filter(Boolean).join("；") || x.text || ""}`);
  }
  if ((bible.locations || []).length) {
    lines.push("\n【地点】");
    for (const x of bible.locations) lines.push(`- ${x.name}：${[x.geo ? `位置：${x.geo}` : "", x.accessRules ? `进出：${x.accessRules}` : "", x.occupied ? `现在：${x.occupied}` : ""].filter(Boolean).join("；") || x.text || ""}`);
  }
  if ((bible.items || []).length) {
    lines.push("\n【物品】");
    for (const x of bible.items) lines.push(`- ${x.name}：${[x.holder ? `持有人：${x.holder}` : "", x.state ? `状态：${x.state}` : "", x.whoKnows ? `谁知道：${x.whoKnows}` : ""].filter(Boolean).join("；") || x.text || ""}`);
  }
  if (style.pov || style.tense) lines.push(`\n【叙事】${[style.pov, style.tense].filter(Boolean).join(" · ")}`);
  if ((style.banned || []).length) lines.push(`禁用表达：${style.banned.join("、")}`);
  if ((style.samples || []).length) {
    lines.push("\n【文风样本】");
    for (const sample of style.samples.slice(0, 3)) lines.push(String(sample).slice(0, 400));
  }
  if ((project.outlineText || "").trim()) lines.push(`\n【大纲】\n${project.outlineText.trim()}`);
  return lines.join("\n");
}

/** 面板主界面要的那一份：设定 + 任务书 + 章节 + 进度。 */
async function studioPayload(root) {
  const sum = await summaryPayload(root);
  const project = await requireProject(root);
  await backfillLocationTrail(root).catch(() => false);
  const bible = await loadBible(root);
  const index = await loadIndex(root);
  // 每章正文开头 50 字（进度页列表直接显示，不用再点开读）
  const chapters = await Promise.all(
    (sum.chapters || []).map(async (c) => {
      let lead = c.excerpt || "";
      try {
        const row = index.find((x) => Number(x.number) === Number(c.number));
        if (row && row.file) {
          const body = await readFile(path.join(root, row.file), "utf8");
          lead = body.replace(/\s+/g, " ").trim().slice(0, 50);
        }
      } catch { /* 文件缺失就用 summary 兜底 */ }
      return { ...c, lead };
    }),
  );
  const outlines = await listOutlines(root);
  const volRows = await loadMemoryRows(root).catch(() => ({ volumes: [] }));
  return {
    ...sum,
    chapters,
    outlines,
    // 10 章一段的段落纲：面板「细纲」页要按批次显示，不再逐章
    segments: await listSegments(root).catch(() => []),
    // 大纲改过就按当前正文重算卷索引（算出来一样就不重复写盘）
    volumes: await refreshVolumes(root, async () => outlines).catch(() => loadVolumes(root)),
    volumeMemories: [...(volRows.volumes || []).reduce((m, v) => m.set(Number(v.to), {
      title: v.volume, from: v.from, to: v.to, chapters: v.chapters, summary: v.summary, at: v.at,
    }), new Map()).values()],
    discarded: await listDiscarded(root),
    setup: {
      logline: project.logline || "",
      synopsis: project.synopsis || "",
      outlineText: project.outlineText || "",
      worldText: project.worldText || "",
      openThreads: project.openThreads || [],
      direction: project.direction || "",
      targetChapters: project.targetChapters || 0,
      wordsPerChapter: project.wordsPerChapter || 0,
      characters: bible.characters || [],
      world: bible.world || [],
      rules: bible.rules || [],
      factions: bible.factions || [],
      locations: bible.locations || [],
      items: bible.items || [],
      relations: bible.relations || [],
      infoGaps: bible.infoGaps || [],
      style: bible.style || {},
    },
    brief: buildBrief(project, bible),
  };
}

/** 「交给 Agent」列表：每个是一段独立可复制的任务。 */
function buildTeam(project, index) {
  const n = (project.currentChapter || 0) + 1;
  const platform = platformRules(project.platform);
  const tasks = [];
  const hasConcept = Boolean(project.conceptSelected);
  const hasOutline = index.length || (project.gates && project.gates.outline);
  tasks.push({
    id: "concept",
    title: hasConcept ? "重新出选题候选" : "出 3 个选题候选",
    desc: "作者先挑方向，再往下写",
    prompt: `帮《${project.title || "这本新书"}》出 3-5 个差异化的选题候选。每个给：书名、一句话故事、题材、平台、180-260 字梗概（讲清主角、目标、阻碍和故事往哪走，不展开情节线）、3 个卖点、前 10 章大纲方向。用 concept 候选的形式回我，我看完选一个。方向参考：${project.direction || "（未填，先问我）"}`,
  });
  tasks.push({
    id: "write-next",
    title: `写第 ${n} 章`,
    desc: index.length ? "按大纲与上文续写下一章，写完就提交体检" : "开篇第一章",
    prompt: `写《${project.title}》第 ${n} 章。先 novel_status 看进度和 gate；这批还没有段落纲就先 novel_segment op=plan from=${n} to=${n + 9} 规划一批（旧的逐章模式用 novel_outline op=generate ${n} 生成细纲，不要手写 beats）；再 novel_context ${n} 取上下文包，按包里的段落纲或细纲、角色、未收伏笔、上一章结尾写完整一章（每章不少于 1800 字，硬下限；目标 ${platform.wordsMin}-${platform.wordsMax} 字，${platform.name}），用 novel_chapter 提交（批量写作时带 batch:true），然后 novel_continuity 体检，有 high 级缺陷先修；本批写完再 novel_continuity scope=batch 一次看整批，只重写其中的问题章。`,
  });
  tasks.push({
    id: "polish",
    title: "给最近一章去 AI 味",
    desc: index.length ? "只改命中段落，不动情节" : "还没有章节",
    prompt: `把《${project.title}》第 ${Math.max(1, project.currentChapter || 1)} 章按 novel_continuity 的 AI 痕迹清单改稿：只改命中的段落，不要整章重来，不要改情节走向。改完用 novel_chapter 重新提交同一章号并跑 novel_continuity 复检。`,
  });
  tasks.push({
    id: "bible",
    title: "把设定补齐 / 校准",
    desc: "补人物、硬规则、文风",
    prompt: `先 novel_status 和 novel_bible（list）看《${project.title}》现有设定，和我刚填的设定对账：缺的人物卡、硬规则、文风样本补上；冲突的以我填的为准并指出哪条冲突。`,
  });
  tasks.push({
    id: "outline",
    title: "排接下来 10 章的细纲",
    desc: "只排细纲，不写正文",
    prompt: `为《${project.title}》规划第 ${n}-第 ${n + 9} 章：用 novel_segment op=plan from=${n} to=${n + 9} 出一份段落纲（3-5 个台阶），给作者确认后 op=write 落账；旧的逐章模式用 novel_outline op=generate 逐章生成。不要写正文。排之前先 novel_status 看清现有伏笔与进度，别和已写的冲突。`,
  });
  return tasks;
}

/* ------------------------------ 路由分派 ------------------------------ */

async function dispatch(method, name, url, req, ctx) {
  const get = (k) => url.searchParams.get(k) ?? undefined;


const SKILL_TITLE = {
  "novel-studio": "小说创作总流程", "novel-continuity": "连续性与文风体检",
  "novel-creator": "世界/角色/情节三合一", "story": "网文工具箱总入口",
  "novel-partner": "单章方法（写/看/改/判）",
  "story-long-write": "长篇写作", "story-long-analyze": "长篇拆文", "story-long-scan": "长篇扫榜",
  "story-short-write": "短篇写作", "story-short-analyze": "短篇拆文", "story-short-scan": "短篇扫榜",
  "story-import": "逆向导入旧书", "story-deslop": "网文去 AI 味", "story-review": "多视角审查",
  "story-cover": "封面生成", "story-setup": "写作环境部署",
  "fenghuo-perspective": "烽火视角", "maoni-perspective": "猫腻视角", "yuhua-perspective": "余华视角",
  "first-reader": "模拟真人试读", "humanizer": "通用去 AI 味",
};
// ping 里给面板用的技能清单（自带 2 + 本机外部）。读不到就退回自带两个，避免面板报错。
async function skillListForPing() {
  try {
    const list = await listAllSkills();
    return list.map((s) => ({ name: s.name, title: SKILL_TITLE[s.name] || s.name, desc: s.when || s.description || "", when: s.when || "" }));
  } catch {
    return [
      { name: "novel-studio", title: "小说创作总流程", desc: "五阶段门控（选题→设定→细纲→正文→体检），用账本管住吃书与 AI 味" },
      { name: "novel-continuity", title: "连续性与文风体检", desc: "吃书九型、时间线/伏笔核对、AI 痕迹逐条改写法、节奏诊断" },
    ];
  }
}

  if (name === "ping") {
    return {
      ok: true, plugin: "dsh-novel-studio", version: PLUGIN_VERSION, api: API_BASE,
      defaultDir: DEFAULT_PROJECTS_DIR, home: homedir(),
      skills: await skillListForPing(),
      tools: [
        "novel_init", "novel_status", "novel_concept", "novel_outline", "novel_bible",
        "novel_context", "novel_chapter", "novel_continuity", "novel_foreshadow", "novel_gate",
        "novel_memory", "novel_export", "novel_repair", "novel_studio_session",
      ],
    };
  }

  if (name === "recent") {
    return { ok: true, defaultDir: DEFAULT_PROJECTS_DIR, projects: await readRecent() };
  }

  if (method === "GET" && name === "models") {
    return await listModelsPayload(ctx);
  }

  // 面板选中的模型落一份到服务端，Agent 工具调用才用得上（它读不到浏览器 localStorage）
  if (method === "POST" && name === "model") {
    const body = await readBody(req);
    const provider = String(body.provider || "").trim();
    const model = String(body.model || "").trim();
    if (!provider || !model) throw new HttpError(400, "需要 provider 和 model");
    await writeModelPref({ provider, model });
    return { ok: true, provider, model };
  }

  if (method === "POST" && name === "concepts") {
    const body = await readBody(req);
    return await generateConcepts(ctx, body);
  }

  if (method === "POST" && name === "outline-gen") {
    const body = await readBody(req);
    return await generateOutline(ctx, body);
  }

  if (method === "POST" && name === "world-gen") {
    const body = await readBody(req);
    return await generateWorld(ctx, body);
  }

  if (method === "POST" && name === "setup-gen") {
    const body = await readBody(req);
    return await generateSetup(ctx, body);
  }

  if (method === "POST" && name === "logic-check") {
    const body = await readBody(req);
    return await logicCheck(ctx, body);
  }

  if (method === "POST" && name === "memory-compile") {
    const body = await readBody(req);
    return await compileVolumeMemory(ctx, body);
  }

  if (method === "POST" && name === "memory-distill") {
    const body = await readBody(req);
    return await distillMemory(ctx, body);
  }

  if (method === "POST" && name === "setting-sync") {
    const body = await readBody(req);
    // numbers：整批一次补（批尾 review 后用），按 3 章一组切批，避免一次超长
    if (Array.isArray(body.numbers) && body.numbers.length) {
      const nums = [...new Set(body.numbers.map((x) => Number(x)).filter((x) => Number.isInteger(x) && x > 0))].sort((a, b) => a - b);
      if (!nums.length) throw new HttpError(400, "numbers 里没有有效章号");
      const merged = { ok: true, batches: [], characters: [], locations: [], items: [], factions: [], rules: [], filled: [], relations: [], infoGaps: [] };
      for (let i = 0; i < nums.length; i += 3) {
        const slice = nums.slice(i, i + 3);
        const r = await syncSettingFromChapterViaAI(ctx, { ...body, number: undefined, numbers: slice });
        const a = r.added || {};
        for (const k of ["characters", "locations", "items", "factions", "rules"]) merged[k].push(...((a[k]) || []));
        merged.filled.push(...(r.filled || []));
        if (r.relations) {
          merged.relations.push(...((r.relations.relations) || []));
          merged.infoGaps.push(...((r.relations.infoGaps) || []));
        }
        merged.batches.push({ chapters: slice, added: a });
      }
      merged.added = { characters: merged.characters, locations: merged.locations, items: merged.items, factions: merged.factions, rules: merged.rules };
      return merged;
    }
    return await syncSettingFromChapterViaAI(ctx, body);
  }

  if (method === "POST" && name === "voice-drift") {
    const body = await readBody(req);
    return await voiceDrift(ctx, body);
  }

  if (method === "POST" && name === "foreshadow-gen") {
    const body = await readBody(req);
    return await generateForeshadow(ctx, body);
  }

  if (method === "POST" && name === "outlines-gen") {
    const body = await readBody(req);
    return await generateOutlines(ctx, body);
  }

  if (method === "GET" && name === "browse") {
    // 目录浏览器：列出某目录下的子目录（用于「新建小说」里直接选目录，而不是手打路径）
    const raw = get("dir");
    let dir;
    try {
      dir = raw && raw.trim() ? await assertBrowsableRoot(raw.trim()) : await assertBrowsableRoot(DEFAULT_PROJECTS_DIR);
    } catch (e) {
      throw new HttpError(400, e.message);
    }
    const home = homedir();
    const list = async (d) => {
      const ents = await readdir(d, { withFileTypes: true });
      return ents
        .filter((e) => e.isDirectory() && !e.name.startsWith("."))
        .map((e) => ({ name: e.name, path: path.join(d, e.name) }))
        .sort((a, b) => a.name.localeCompare(b.name, "zh"));
    };
    try {
      let dirs;
      try {
        dirs = await list(dir);
      } catch (e) {
        // 默认目录还没建（第一次用）：从还能打开的主目录起浏览
        if (!raw && e.code === "ENOENT") {
          dir = home;
          dirs = await list(dir);
        } else {
          throw e;
        }
      }
      const parent = path.dirname(dir);
      return {
        ok: true,
        dir,
        parent: parent === dir ? null : parent,
        home,
        isProject: existsSync(path.join(dir, "project.json")),
        entries: dirs,
      };
    } catch (e) {
      throw new HttpError(400, `打不开目录：${dir}（${e.code || e.message}）`);
    }
  }

  if (name === "shelf") {
    if (method !== "GET") throw new HttpError(405, "shelf 只支持 GET");
    return await shelfPayload();
  }

  if (method === "GET" && name === "summary") {
    const dir = await assertDir(get("dir"));
    await remember(dir, (await loadProject(dir))?.title);
    return await summaryPayload(dir);
  }

  if (method === "GET" && name === "studio") {
    return await studioPayload(await assertDir(get("dir")));
  }

  if (method === "GET" && name === "chapter") {
    const root = await assertDir(get("dir"));
    await requireProject(root);
    const n = Number(get("number"));
    if (!Number.isFinite(n)) throw new HttpError(400, "缺少 number 参数");
    const c = await readChapter(root, n);
    return { ok: true, number: c.entry.number, title: c.entry.title, entry: c.entry, text: c.text };
  }

  if (method === "GET" && name === "context") {
    const root = await assertDir(get("dir"));
    await requireProject(root);
    const chapter = Number(get("chapter") || 1);
    const budget = Number(get("budget") || 6000);
    const pack = await buildContext(root, { chapter, budgetChars: budget });
    return { ok: true, chapter, chars: pack.text.length, tokens: pack.tokens, budget: pack.budget, text: pack.text };
  }

  if (method === "GET" && name === "continuity") {
    const root = await assertDir(get("dir"));
    await requireProject(root);
    const r = await continuityCheck(root);
    return { ok: true, ...r };
  }

  if (method === "POST" && name === "repair") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await repairProject(root);
    return { ...(await studioPayload(root)), repair: r };
  }

  if (method === "GET" && name === "outline") {
    const root = await assertDir(get("dir"));
    await requireProject(root);
    const chapter = Number(get("chapter") || 1);
    return { ok: true, chapter, outline: (await getOutline(root, chapter)) || null };
  }

  if (method === "GET" && name === "outlines") {
    const root = await assertDir(get("dir"));
    await requireProject(root);
    return { ok: true, outlines: await listOutlines(root) };
  }

  if (method === "GET" && name === "discarded") {
    const root = await assertDir(get("dir"));
    await requireProject(root);
    return { ok: true, discarded: await listDiscarded(root) };
  }

  if (method === "GET" && name === "discarded-read") {
    const url = new URL(req.url, "http://x");
    const root = await assertDir(url.searchParams.get("dir"));
    await requireProject(root);
    return await readDiscarded(root, { draftFile: url.searchParams.get("draftFile") });
  }

  if (method === "POST" && name === "discarded-restore") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await restoreDiscarded(root, { draftFile: body.draftFile, number: body.number, title: body.title });
    return { ...(await studioPayload(root)), restored: r.restored };
  }

  if (method === "POST" && name === "discarded-purge") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await purgeDiscarded(root, { draftFile: body.draftFile });
    return { ...(await studioPayload(root)), removed: r.removed };
  }

  if (method === "POST" && name === "init") {
    const body = await readBody(req);
    let root = await assertDir(body.dir, { mustExist: false });
    // 新建只允许落在默认目录（桌面/mine/xiaoshuo）或显式放开的根目录内
    try {
      root = await assertWritableRoot(root, { creating: true });
    } catch (e) {
      throw new HttpError(400, e.message);
    }
    if (!body.title) throw new HttpError(400, "缺少 title");
  // 规模在建项目定死（章数 × 每章字数 = 总字数），之后设定页只读，避免大纲按一个数、进度按另一个数。
  const wordsPerChapter = Number(body.wordsPerChapter)
    || Math.round((platformRules(body.platform).wordsMin + platformRules(body.platform).wordsMax) / 2);
  const wantWords = Number(body.totalWords) > 0 ? Number(body.totalWords) : 0;
  const targetChapters = Number(body.targetChapters) > 0
    ? Number(body.targetChapters)
    : (wantWords ? Math.max(1, Math.round(wantWords / wordsPerChapter)) : 120);
  const totalWords = wantWords || targetChapters * wordsPerChapter;
    const project = await initProject(root, {
      title: body.title, genre: body.genre, platform: body.platform, logline: body.logline,
      synopsis: body.synopsis, outlineText: body.outlineText,
      referenceBook: typeof body.referenceBook === "string" ? body.referenceBook.slice(0, 120) : "",
      targetChapters, wordsPerChapter,
      totalWords, direction: body.direction,
      conceptSelected: Array.isArray(body.concepts) && body.concepts.length ? (body.selectedConceptId || "pending") : undefined,
    });
    // 带候选进来：把选题候选与「已选中的那个」一起落盘（向导流程：建项目即锁定选题）
    if (Array.isArray(body.concepts) && body.concepts.length) {
      const p2 = await loadProject(root);
      p2.concepts = body.concepts;
      const picked = body.selectedConceptId
        ? (body.concepts.find((c) => c.id === body.selectedConceptId) || body.concepts[0])
        : body.concepts[0];
      // conceptSelected 统一存「选中项 id 字符串」，与 selectConcept(domain.js:310 = hit.id) 一致；
      // 之前这里存的是整个对象，形状不一致，任何按 id 比较都会失配。
      p2.conceptSelected = picked.id;
      p2.logline = picked.oneLine || p2.logline || "";
      p2.synopsis = picked.synopsis || p2.synopsis || "";
      if (!body.title && picked.title) p2.title = picked.title;
      // 向导里勾了「反差虐点」：基调在建项目时就定下，之后生成大纲不必再点一次
      if (body.tone === "contrast") p2.tone = "contrast";
      p2.gate = { phase: "outline_accept", chapter: 0, reason: "选题已定，下一步生成大纲", at: new Date().toISOString() };
      p2.gates = { ...(p2.gates || {}), brief: true };
      await saveProject(root, p2);
    }
    await remember(root, project.title);
    // 返回与 summary/studio 一致的视图，前端拿到就能直接渲染 gate / wordRange
    return await studioPayload(root);
  }

  if (method === "POST" && name === "setup") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    const project = await requireProject(root);
    // 规模（章数/每章字数/总字数）建项目时定死，设定页与 /setup 都不再改它。
    if (["targetChapters", "wordsPerChapter", "totalWords"].some((k) => body[k] !== undefined)) {
      throw new HttpError(400, "规模在新建小说时已定，之后不能改（改规模等于换一本书：大纲、伏笔回收章、进度都得重算）");
    }
    // 对标书只在新建时填，之后锁定（选题已经按它生成过，再改会前后对不上）
    if (typeof body.referenceBook === "string" && String(project.referenceBook || "").trim()
      && body.referenceBook.trim() !== String(project.referenceBook).trim()) {
      throw new HttpError(400, "对标书在新建小说时已定，之后不能改");
    }
    // 写设定算 bible_write：concept 阶段还没选题时不允许写（PRD 门控）
    const guard = await guardGate(root, "bible_write");
    if (!guard.ok) throw new HttpError(400, guard.error);
    // 只写面板能决定的那几项：故事核/梗概/大纲全文/规模/方向/题材/平台。
    // 人物、世界观、硬规则、势力、地点、物品、文风走 bible（同一个账本，两个入口共用 domain.bibleUpsert）。
    const patch = {};
    // tone：只有 contrast（反差虐点）一种，空字符串表示不启用；存进 project，之后「换一版」不用重新点
    if (body.tone !== undefined) project.tone = body.tone === "contrast" ? "contrast" : "";
    for (const k of ["logline", "synopsis", "outlineText", "worldText", "direction", "genre", "platform", "referenceBook"]) {
      if (typeof body[k] === "string") patch[k] = body[k];
    }
    for (const k of ["targetChapters", "wordsPerChapter", "totalWords"]) {
      if (body[k] !== undefined && Number.isFinite(Number(body[k]))) patch[k] = Number(body[k]);
    }
    // 保存前先让模型把「老韩 / 韩四」这类同一个人的不同写法并成一条（没模型就跳过，不影响保存）
    let mergedNames = [];
    let mergeNote = "";
    if (body.mergeDuplicates !== false) {
      const r = await mergeSamePersonByModel(ctx, body, [["characters", "character"]], root);
      mergedNames = r.merged;
      mergeNote = r.note || "";
    }
    Object.assign(project, patch);
    if (patch.logline) project.gates = { ...(project.gates || {}), brief: true };
    await saveProject(root, project);
    for (const [field, entity] of [
      ["characters", "character"], ["world", "world"], ["rules", "rule"],
      ["factions", "faction"], ["locations", "location"], ["items", "item"],
    ]) {
      if (Array.isArray(body[field])) {
        for (const item of body[field]) {
          if (item && (item.name || "").trim()) await bibleUpsert(root, entity, item);
        }
      }
    }
    // 人物页删除/改名要真的从账本移除；只删明确列出的名字，避免旧页面覆盖会话里新增的人。
    if (Array.isArray(body.deletedCharacters)) {
      const gone = new Set(body.deletedCharacters.map((n) => String(n || "").trim()).filter(Boolean));
      const keep = new Set((Array.isArray(body.characters) ? body.characters : []).map((c) => String(c?.name || "").trim()).filter(Boolean));
      const b = await loadBible(root);
      b.characters = (b.characters || []).filter((c) => !gone.has(c.name) || keep.has(c.name));
      await saveBible(root, b);
    }
    if (body.deletedEntities && typeof body.deletedEntities === "object") {
      const b = await loadBible(root);
      for (const key of ["factions", "locations", "items", "rules"]) {
        const gone = new Set((Array.isArray(body.deletedEntities[key]) ? body.deletedEntities[key] : []).map((n) => String(n || "").trim()).filter(Boolean));
        if (!gone.size) continue;
        const keep = new Set((Array.isArray(body[key]) ? body[key] : []).map((x) => String(x?.name || "").trim()).filter(Boolean));
        b[key] = (b[key] || []).filter((x) => !gone.has(x.name) || keep.has(x.name));
      }
      await saveBible(root, b);
    }
    // 关系矩阵 / 信息差是两张独立表，不按实体去重，整表覆盖保存。
    if (Array.isArray(body.relations) || Array.isArray(body.infoGaps)) {
      const b = await loadBible(root);
      const str = (v) => String(v || "").trim();
      if (Array.isArray(body.relations)) {
        b.relations = body.relations
          .map((r) => ({ a: str(r?.a), b: str(r?.b), state: str(r?.state), note: str(r?.note) }))
          .filter((r) => r.a || r.b);
      }
      if (Array.isArray(body.infoGaps)) {
        b.infoGaps = body.infoGaps
          .map((g) => ({ secret: str(g?.secret), knows: str(g?.knows), doesntKnow: str(g?.doesntKnow), thinksKnows: str(g?.thinksKnows) }))
          .filter((g) => g.secret || g.knows || g.doesntKnow || g.thinksKnows);
      }
      await saveBible(root, b);
    }
    const stylePatch = {};
    if (typeof body.bannedText === "string") stylePatch.banned = body.bannedText.split(/[、,，\s]+/u).map((s) => s.trim()).filter(Boolean);
    if (typeof body.pov === "string") stylePatch.pov = body.pov.trim();
    if (typeof body.tense === "string") stylePatch.tense = body.tense.trim();
    if (typeof body.samplesText === "string") stylePatch.samples = body.samplesText.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
    if (typeof body.stylePreset === "string") stylePatch.preset = body.stylePreset;
    if (Object.keys(stylePatch).length) {
      const curStyle = (await loadBible(root)).style || {};
      // 空数组和「没填」算同一个状态，否则设定页每次保存都会被误判成改文风
      const norm = (v) => (Array.isArray(v) ? (v.length ? JSON.stringify(v) : "") : (v === undefined || v === null ? "" : String(v)));
      const changed = Object.entries(stylePatch).some(([k, v]) => norm(curStyle[k]) !== norm(v));
      if (changed && (Number(project.currentChapter) || 0) >= 1) {
        throw new HttpError(400, "第 1 章已写完，文风已锁定；要改请先作废第 1 章。想调写作要求可以用「当前方向」，它只影响后续章");
      }
      if (changed) {
        await bibleUpsert(root, "style", stylePatch);
        await writeStyleFile(root).catch(() => false);
      }
    }
    return { ...(await studioPayload(root)), mergedNames, mergeNote };
  }

  if (method === "POST" && name === "commit") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    const proj = await requireProject(root);
    const number = Number(body.number);
    if (!Number.isFinite(number) || number < 1) throw new HttpError(400, "number 必须是正整数章号");
    if (typeof body.text !== "string" || !body.text.trim()) throw new HttpError(400, "缺少正文 text");
    // 与 domain 同一口径：长篇每章硬下限 1800 字，≤50 章的短篇项目不设下限
    const floor = chapterMinChars(proj);
    const charsNow = countChars(body.text);
    if (charsNow < 200) throw new HttpError(400, `正文太短（${charsNow} 字 < 200），不像一章`);
    if (floor && charsNow < floor) throw new HttpError(400, `正文 ${charsNow} 字，低于每章硬下限 ${floor} 字（补戏再提交；全书 ≤50 章的项目不设下限）`);
    if (!String(body.summary || "").trim()) throw new HttpError(400, "提交必须带 summary（本章剧情摘要，一两句话）");
    if (!Array.isArray(body.characters) || !body.characters.map((c) => String(c || "").trim()).filter(Boolean).length) throw new HttpError(400, "提交必须带 characters（本章出场人物名列表，至少一个）");
    const r = await commitChapter(root, {
      number, title: body.title, text: body.text,
      summary: body.summary, characters: body.characters, inWorldDay: body.inWorldDay,
      force: Boolean(body.force),
      // 批量写作：面板/脚本走 HTTP 时也要把 batch 传下去，否则每章都被当成逐章提交、进 awaiting_review
      batch: Boolean(body.batch),
    });
    await remember(root, (await loadProject(root))?.title);
    if (r.rejected) {
      return {
        ok: false, rejected: true, chapterVerdict: r.chapterVerdict,
        reason: r.reason, hint: r.hint, draftFile: r.draftFile,
        metrics: r.metrics, judge: r.judge, platform: r.platform,
        tells: r.tells.map((t) => ({ code: t.code, label: t.label, severity: t.severity, count: t.count, per1000: t.per1000, sample: t.samples?.[0]?.text || "" })),
        bannedHits: r.bannedHits,
      };
    }
    return {
      ok: true,
      chapter: r.chapter,
      metrics: r.metrics,
      judge: r.judge,
      chapterVerdict: r.chapterVerdict,
      platform: r.platform,
      tells: r.tells.map((t) => ({ code: t.code, label: t.label, severity: t.severity, count: t.count, per1000: t.per1000, sample: t.samples?.[0]?.text || "" })),
      bannedHits: r.bannedHits,
      file: r.file,
      chapterCheck: r.chapterCheck ? { pass: r.chapterCheck.pass, counts: r.chapterCheck.counts, findings: r.chapterCheck.findings } : null,
    };
  }

  if (method === "POST" && name === "outline") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    const project = await requireProject(root);
    // 会话交回（novel_studio_session return）：面板开着时由这里落盘，和作者手点保存走同一条路
    if (body.op === "session-return") {
      const pj = await loadProject(root);
      // 交回是「覆盖写」：会话跑偏（比如把伏笔清单当大纲交回）会把整份正文换掉。
      // 这里挡两种：字数腰斩、以及根本不是大纲的文档。
      const badOutline = body.force ? "" : sessionOverwriteProblem("大纲", pj.outlineText, body.outlineText);
      const badWorld = body.force ? "" : sessionOverwriteProblem("世界观", pj.worldText, body.worldText);
      if (badOutline) throw new HttpError(400, `拒绝覆盖：${badOutline}。只交回你真正改过的正文；伏笔清单应该留在伏笔账本里。确需整篇替换请加 force:true。`);
      if (badWorld) throw new HttpError(400, `拒绝覆盖：${badWorld}。确需整篇替换请加 force:true。`);
      if (typeof body.outlineText === "string" && body.outlineText.trim()) {
        pj.outlineText = body.outlineText.trim();
        if (!pj.outlineAccepted) { pj.outlineAccepted = true; pj.outlineAcceptedAt = new Date().toISOString(); }
      }
      if (typeof body.worldText === "string" && body.worldText.trim()) pj.worldText = body.worldText.trim();
      pj.sessionReturns = [...(pj.sessionReturns || []), { at: new Date().toISOString(), source: String(body.source || "").slice(0, 40) }].slice(-20);
      await saveProject(root, pj);
      if (body.volumes !== false) { try { await refreshVolumes(root, () => listOutlines(root)); } catch { /* 卷索引不重要 */ } }
      return { ok: true, sessionReturned: true, view: await studioPayload(root) };
    }
    // 作者确认大纲
    if (body.op === "accept") {
      // 先把贴进来的大纲文本存档（有了它，即使 AI 还没写细纲也能确认大纲）
      if (typeof body.outlineText === "string" && body.outlineText.trim()) {
        const pj = await loadProject(root);
        pj.outlineText = body.outlineText.trim();
        await saveProject(root, pj);
      }
      await acceptOutline(root);
      return await studioPayload(root);
    }
    // 「保存大纲正文 / 世界观」路径：给了 outlineText 但没给 beats → 只存文本，不动细纲账本
    const hasText = typeof body.outlineText === "string" && body.outlineText.trim().length > 0;
    const hasBeats = Array.isArray(body.beats) && body.beats.length > 0;
    if (hasText && !hasBeats) {
      const pj = await loadProject(root);
      pj.outlineText = body.outlineText.trim();
      if (typeof body.worldText === "string") pj.worldText = body.worldText.trim();
      await saveProject(root, pj);
      await outlineVolume(root);
      const view = await studioPayload(root);
      return { ...view, ok: true, saved: "outlineText" };
    }
    // 删除某章细纲（重新生成前清掉旧的）
    if (body.op === "delete") {
      const r = await deleteOutline(root, { chapter: body.chapter });
      const view = await studioPayload(root);
      return { ...view, ok: true, deleted: r.chapter };
    }
    const chapter = Number(body.chapter);
    if (!Number.isFinite(chapter)) throw new HttpError(400, "缺少 chapter（保存细纲需要章号）");
    const beats = hasBeats ? body.beats : [];
    if (!beats.length) throw new HttpError(400, "beats 至少要有一条（保存大纲正文请只传 outlineText、不传 beats）");
    const r = await setOutline(root, { chapter, beats, mustInclude: body.mustInclude, mustAvoid: body.mustAvoid, detail: hasText ? body.outlineText : "", volume: body.volume });
    // setOutline 内部已 load+save 过 project，不能再 save 旧对象
    const view = await studioPayload(root);
    return { ...view, ok: true, chapter: r.chapter, beats: r.beats };
  }

  // —— 批量写设定（AI 补全书设定）——
  if (method === "POST" && name === "bible") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    // 合并重复人物：同一个人的多条并成一条（已有重复时手动点一次）
    if (body.op === "merge-duplicates") {
      // 名字规则先挑出疑似配对，再让模型带正文引文复核；没复核通过的不并
      const r = await mergeWithModelCheck(ctx, body, root);
      return { ...(await studioPayload(root)), ok: true, ...r };
    }
    if (body.op === "split") {
      const r = await splitMergedEntity(root, { name: body.name, mergedName: body.mergedName });
      return { ...(await studioPayload(root)), ...r };
    }
    // 复数分类名 → bibleUpsert 的单数实体名（ENTITY_KEY 用 character/rule/faction…）
    const ENT = { characters: "character", world: "world", rules: "rule", factions: "faction", locations: "location", items: "item" };
    let written = 0;
    for (const [plural, sing] of Object.entries(ENT)) {
      const list = Array.isArray(body[plural]) ? body[plural] : [];
      for (const item of list) {
        if (!item) continue;
        const data = typeof item === "string" ? { name: item, text: item } : item;
        await bibleUpsert(root, sing, data);
        written += 1;
      }
    }
    if (body.style && typeof body.style === "object") {
      await bibleUpsert(root, "style", body.style);
      written += 1;
    }
    const view = await studioPayload(root);
    return { ...view, ok: true, written };
  }

  if (method === "POST" && name === "foreshadow") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    if (body.op === "plant") {
      const r = await plantForeshadow(root, {
        name: body.name, plantedChapter: body.plantedChapter, dueChapter: body.dueChapter, note: body.note,
        kind: body.kind, source: body.source, plantBeat: body.plantBeat,
        revealWho: body.revealWho, revealChange: body.revealChange, hint: body.hint, abandon: body.abandon,
      });
      return await studioPayload(root);
    }
    if (body.op === "payoff") {
      const r = await payoffForeshadow(root, { name: body.name, chapter: body.chapter, note: body.note });
      return { ok: true, op: "payoff", foreshadow: r };
    }
    if (body.op === "reschedule") {
      const r = await rescheduleForeshadow(root, { name: body.name, dueChapter: body.dueChapter, note: body.note });
      return { ok: true, op: "reschedule", foreshadow: r };
    }
    if (body.op === "delete") {
      const r = await deleteForeshadow(root, { name: body.name, id: body.id });
      return { ok: true, op: "delete", foreshadow: r };
    }
    throw new HttpError(400, "op 只支持 plant / payoff / reschedule / delete");
  }

  // —— 选题（PRD v1）——
  if (method === "POST" && name === "concept") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    if (body.op === "propose") {
      const r = await proposeConcepts(root, { concepts: body.concepts });
      const view = await studioPayload(root);
      return { ...view, op: "propose", proposedCount: r.count };
    }
    if (body.op === "select") {
      await selectConcept(root, { conceptId: body.conceptId || body.concept_id, title: body.title });
      const view = await studioPayload(root);
      return { ...view, op: "select" };
    }
    throw new HttpError(400, "op 只支持 propose / select");
  }

  // —— 作者三决定门（PRD v1）——
  if (method === "POST" && name === "approve") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const ap = await approveChapter(root, { number: body.number, force: Boolean(body.force) });
    // batchApproved / approvedChapters 要带回去：面板据此做「整批一次补设定」和整批文案
    return {
      ...(await studioPayload(root)),
      debutFilled: ap.debutFilled || [],
      batchApproved: ap.batchApproved,
      approvedChapters: ap.approvedChapters,
    };
  }

  if (method === "POST" && name === "rewrite") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    await requestRewrite(root, { number: body.number, note: body.note });
    return await studioPayload(root);
  }

  // —— 按批体检（批尾 review 用）：一次看整批，告诉哪几章要重写、哪些是整批问题 ——
  if (method === "POST" && name === "batch-check") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await checkBatch(root, { from: body.from, to: body.to });
    // ok:false 在这里表示「这批有问题」，是正常结果不是请求失败；调用方靠 chapters/blocking 判断。
    // 客户端把 data.ok===false 当异常，所以这里统一回 ok:true，问题信息放在 changes 里。
    return { ...r, ok: true, hasProblems: !r.ok };
  }

  // —— 删掉某段还没开写的段落纲（细纲页「删除」按钮）——
  if (method === "POST" && name === "segment-delete") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await deleteSegment(root, { from: body.from, to: body.to });
    const view = await studioPayload(root);
    return { ...view, ok: true, deleted: r };
  }

  // —— 单章体检（进度页每章「体检」按钮）——
  if (method === "POST" && name === "chapter-check") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await checkChapter(root, body.number);
    // 可选：体检没过就自动作废这一章（前端「体检」按钮默认只报，用户确认后调 discard 才作废）
    if (r.missing) return { ok: true, check: r, message: `第${body.number}章不在正文里（被退回重写或还没写），没有可体检的稿子` };
    if (body.discardIfFail && !r.pass) {
      const d = await discardChapter(root, { number: body.number, reason: "体检未通过" });
      const view = await studioPayload(root);
      return { ...view, check: r, discarded: d.discarded, draftFile: d.draftFile, impacts: d.impacts };
    }
    return { ok: true, check: r };
  }

  // —— 单章体检 + AI 复核（语义类候选才调模型）——
  if (method === "POST" && name === "chapter-review") {
    const body = await readBody(req);
    return await reviewChapter(ctx, body);
  }

  // —— 作者把某条体检/断层标记为「合理」，之后不再报 ——
  if (method === "POST" && name === "dismiss") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    return await dismissFinding(root, body);
  }

  // —— 作废某章（体检没过 / 去味后旧稿作废）——
  if (method === "POST" && name === "discard") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await discardChapter(root, { number: body.number, reason: body.reason });
    const view = await studioPayload(root);
    return { ...view, ok: true, discarded: r.discarded, draftFile: r.draftFile, impacts: r.impacts };
  }

  // —— 作废后清掉该章挂着的伏笔/人物登场章（作者确认后才调）——
  if (method === "POST" && name === "cleanup") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await cleanupAfterDiscard(root, { number: body.number, foreshadow: body.foreshadow !== false, settings: body.settings !== false });
    return { ...(await studioPayload(root)), ...r };
  }

  if (method === "POST" && name === "direction") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    await changeDirection(root, { direction: body.direction, style: body.style });
    return await studioPayload(root);
  }

  // —— 导出（PRD v1）——
  if (method === "POST" && name === "export") {
    const body = await readBody(req);
    const root = await assertDir(body.dir);
    await requireProject(root);
    const r = await exportChapters(root, {
      from: Number(body.from) || 1, to: body.to !== undefined ? Number(body.to) : undefined,
      scope: body.scope || "single", includeBible: Boolean(body.includeBible),
    });
    return { ok: true, files: r.files, count: r.count };
  }

  if (method === "POST" && name === "delete") {
    const body = await readBody(req);
    return await deleteProject(await assertDir(body.dir));
  }

  throw new HttpError(404, `未知接口：${method} ${API_BASE}${name}`);
}

/* ------------------------------ 模型（LLM）------------------------------ */

// 面板本身不内置模型。这里用 DSH 自带的 llm 服务：默认拿用户当前默认模型，
// 也可以让用户在面板里选 provider/model。headless / 无 llm 服务时安全降级。

function resolveLlm(ctx) {
  try {
    if (ctx && typeof ctx.get === "function") {
      const llm = ctx.get("llm");
      if (llm) return llm;
    }
  } catch { /* ignore */ }
  try { if (ctx && ctx.llm) return ctx.llm; } catch { /* ignore */ }
  return null;
}

function defaultSelection(ctx) {
  try {
    const dm = (ctx && typeof ctx.get === "function") ? ctx.get("agentDefaultModel") : ctx?.agentDefaultModel;
    if (dm && typeof dm.currentSelection === "function") {
      const sel = dm.currentSelection();
      if (sel && sel.provider && sel.model) return { provider: sel.provider, model: sel.model, reasoningEffort: sel.reasoningEffort };
    }
  } catch { /* ignore */ }
  return null;
}

async function listModelsPayload(ctx) {
  const llm = resolveLlm(ctx);
  const current = defaultSelection(ctx);
  if (!llm) {
    // 没有 llm 服务时，至少把当前默认模型当作一个可选项返回，别让下拉框空着。
    const providers = current ? [{ id: current.provider, name: current.provider, models: [{ id: current.model, name: current.model }] }] : [];
    return { ok: true, available: Boolean(current), current, providers, reason: "当前环境没有可用的模型服务" };
  }
  let providers = [];
  try {
    const list = llm.listProviders ? llm.listProviders() : [];
    for (const p of list) {
      const pid = p.id ?? p.name ?? p.provider;
      let models = [];
      try { models = await llm.listModels(pid); } catch { models = []; }
      providers.push({
        id: pid,
        name: p.name ?? p.label ?? pid,
        models: (models || []).map((m) => ({ id: m.id, name: m.name || m.id })),
      });
    }
  } catch { /* ignore */ }
  // 目录接口没返回任何模型（未登录/未配置 listing）时，至少补上当前默认模型，保证能选。
  const anyModels = providers.some((p) => p.models.length > 0);
  if (!anyModels && current && current.provider && current.model) {
    const hit = providers.find((p) => p.id === current.provider);
    if (hit) hit.models.push({ id: current.model, name: current.model });
    else providers.push({ id: current.provider, name: current.provider, models: [{ id: current.model, name: current.model }] });
  }
  return { ok: true, available: providers.some((p) => p.models.length > 0), current, providers };
}

// 从模型输出里抠出 JSON 数组（容忍 ```json 包裹、前后废话）。
function extractJsonArray(text) {
  if (!text) return null;
  let t = String(text).trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  const start = t.indexOf("[");
  const end = t.lastIndexOf("]");
  if (start === -1 || end === -1 || end <= start) return null;
  try { return JSON.parse(t.slice(start, end + 1)); } catch { return null; }
}

// 输出被截断时，把前面已经写完整的 {...} 逐个捞回来（字符串里的花括号不算）
function salvageJsonObjects(text) {
  const out = [];
  const s = String(text || "");
  for (let i = 0; i < s.length; i++) {
    if (s[i] !== "{") continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < s.length; j++) {
      const c = s[j];
      if (inStr) {
        if (esc) esc = false;
        else if (c === "\\") esc = true;
        else if (c === '"') inStr = false;
        continue;
      }
      if (c === '"') inStr = true;
      else if (c === "{") depth++;
      else if (c === "}") {
        depth--;
        if (!depth) {
          try { out.push(JSON.parse(s.slice(i, j + 1))); } catch { /* 半截跳过 */ }
          i = j;
          break;
        }
      }
    }
  }
  return out;
}

const IDLE_TIMEOUT_MS = 90_000;
const CALL_TIMEOUT_MS = 240_000;

async function streamText(llm, options) {
  let out = "";
  let finish = null;
  let timer = null;
  let timeout = null;
  const watchdog = new Promise((_, reject) => { timeout = reject; });
  const bump = () => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => timeout(new Error(`模型 ${Math.round(IDLE_TIMEOUT_MS / 1000)} 秒没有任何输出（这次尝试已中止）`)), IDLE_TIMEOUT_MS);
  };
  bump();
  const collect = (async () => {
    for await (const chunk of llm.stream(options)) {
      if (!chunk) continue;
      bump();
      if (chunk.type === "finish") { finish = chunk.reason; break; }
      if (chunk.type === "text-delta" && typeof chunk.text === "string") out += chunk.text;
    }
    return { text: out, finish };
  })();
  // 超时后 collect 仍在后台跑，挂个 catch 防止未处理的 rejection
  collect.catch(() => {});
  try {
    return await Promise.race([collect, watchdog]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function generateConcepts(ctx, body) {
  const llm = resolveLlm(ctx);
  if (!llm) throw new HttpError(503, "当前环境没有可用的模型服务，无法直接生成选题");
  const direction = (body.direction || body.elements || body.kw || "").toString().trim();
  const elements = (body.elements || body.kw || "").toString().trim();
  const platform = (body.platform || "起点").toString().trim();
  const wantChapters = Number(body.targetChapters) || 0;
  const totalWords = Number(body.totalWords) || 300000;
  const count = Math.min(5, Math.max(3, Number(body.count) || 3));
  // 换一批时把上一批带回来，模型才知道要避开什么；否则同样的提示词每次都会收敛到同一批套路
  const avoid = (Array.isArray(body.avoid) ? body.avoid : []).map((x) => String(x || "").trim()).filter(Boolean).slice(-16);
  // 跨批次记忆：最近开过的书用什么题材，本次尽量别再撞
  const recentGenres = [];
  try {
    for (const rp of (await readRecent()).slice(0, 8)) {
      try {
        const pr = await loadProject(rp.dir);
        if (pr?.genre) recentGenres.push(String(pr.genre).trim());
      } catch { /* 书架里删掉的项目跳过 */ }
    }
  } catch { /* 记不住不影响生成 */ }
  // 题材收敛的根源：模型每次都会挑同一撮赛道。这里按批次随机分配互不相同的大类，
  // 让「换一批」真的换赛道，而不是同一题材换个细分名。
  const GENRE_LANES = [
    "都市异能 / 都市现实", "玄幻仙侠 / 修真", "科幻 / 末世 / 星际", "历史 / 权谋 / 争霸",
    "武侠 / 江湖", "军事 / 谍战", "赛博朋克 / 近未来",
    "职场 / 商战", "体育 / 竞技", "校园 / 青春",
    "医疗 / 法医 / 刑侦", "克苏鲁 / 无限流 / 规则怪谈",
    "悬疑推理 / 民俗怪谈 / 灵异",
  ];
  const MYSTERY_LANE = /悬疑|推理|刑侦|民俗|怪谈|克苏鲁|灵异|无限流|规则|鬼|恐怖/;
  // 用户没点名悬疑时，悬疑类整条池子都不进候选——模型默认最容易滑向凶案/诡事，必须硬隔离
  const wantsMystery = MYSTERY_LANE.test(`${direction} ${elements}`);
  // 用户填了要求或对标书，就照他们给的来：不强行分配题材池，也不套发散/避重规则
  const followUser = Boolean(direction || elements);
  const hasRef = Boolean(String(body.referenceBook || "").trim());
  const useLanes = !followUser && !hasRef;
  const laneTokens = (s) => (String(s || "").match(/[\u4e00-\u9fa5]{2}/g) || []);
  const usedGenres = [...recentGenres, ...avoid.map((x) => String(x).split("｜")[1] || "")].filter(Boolean);
  const laneBlocked = (lane) => {
    const toks = new Set(laneTokens(lane));
    return usedGenres.some((g) => laneTokens(g).some((t) => toks.has(t)));
  };
  const allowedLanes = GENRE_LANES.filter((l) => wantsMystery || !MYSTERY_LANE.test(l));
  let lanePool = allowedLanes.filter((l) => !laneBlocked(l));
  if (lanePool.length < count) lanePool = allowedLanes.slice();
  const lanes = useLanes
    ? lanePool.map((v) => [Math.random(), v]).sort((a, b) => a[0] - b[0]).slice(0, count).map((x) => x[1])
    : [];
  // 对标书只填书名：先联网查它的大致内容，再让模型按这本书的路子出选题；不抄情节与人物
  const ref = String(body.referenceBook || "").trim().slice(0, 120);
  // 对标书可以填多本，逗号/顿号分隔；每本单独查一次，查不到就明说，别混成一条假资料
  const refTitles = ref.split(/[，,、]/).map((s) => s.trim()).filter(Boolean).slice(0, 3);
  const refResults = refTitles.length
    ? await Promise.all(refTitles.map((t) => lookupReference(ctx, t, platform)))
    : [];
  const refBrief = refTitles.length
    ? refResults.map((brief, i) => brief ? `【《${refTitles[i]}》】\n${brief}` : `【《${refTitles[i]}》】这次没查到资料`).join("\n\n")
    : "";
  // 章数只按平台实际篇幅区间估算（不再一律 /3000，番茄 2000-3500 会被算少）
  const perChapter = Number(body.wordsPerChapter) > 0
    ? Math.round(Number(body.wordsPerChapter))
    : Math.max(1, Math.round((platformRules(platform).wordsMin + platformRules(platform).wordsMax) / 2));
  const estChapters = wantChapters || Math.max(1, Math.round(totalWords / perChapter));

  // 模型：优先用户显式选的 provider/model，否则用默认
  const def = defaultSelection(ctx);
  const provider = (body.provider || def?.provider || "").toString().trim();
  const model = (body.model || def?.model || "").toString().trim();
  if (!provider || !model) throw new HttpError(409, "没有可用的默认模型，请先在面板里选一个模型");

  const length = (body.length || "").toString();
  const short = length === "short" || (length !== "long" && SHORT_PLATFORMS.some((k) => String(platform).includes(k)));
  // 差异化铁律：把「要不一样」从形容词变成可核对的 7 列硬结构。
  // 每一列三题都不许重复——这是压制同质化的主约束。
  // 注意：示例别再用「殡葬师/守夜人/点灯人」这类边缘小手艺，示例即模板，会把它往「诗意小人物」上带。
  const DIVERSITY_COLUMNS = [
    "赛道（genre 大类）——三题大类必须互不相同。",
    "时代/世界——三题分属不同年代或不同世界类型（如现代都市 / 古代朝堂 / 近未来科幻，三者不许都是现代或都是末世废土）。",
    "主角格局与身份——三题主角的社会位置要分层拉开（如一方统帅 / 掌权者嫡系 / 行业顶端操盘手 / 幕后反派 / 市井小人物都行，但三题别都挤在同一个社会层级）。小人物或某个营生当主角完全可以，关键是别三题都用同一种「诗意边缘人」气质。",
    "核心冲突层级——三题分别落在个人恩怨 / 组织博弈 / 阶层或体制对抗 / 世界法则之争 中的不同层级，不许三题都困在一个人的小遭遇里。",
    "金手指类型——三题分属不同来源（系统面板 / 血脉传承 / 知识降维 / 规则漏洞 / 身份马甲 / 时代红利 等），不许三题都用系统或都用「某种感知」。",
    "爽点来源——三题分属不同爽法（打脸复仇 / 经营收米 / 解谜破局 / 攻城略地 / 权力逆袭 / 收集养成 / 科技碾压 等）。爽文可以，但三题的爽必须爽得不一样：不许三题都靠打脸、都靠「贩卖/交易某物」、都靠同一个爽点开关。",
    "叙事切口——三题分属不同切入点（重生回档 / 藏身份 / 夺权开局 / 被卷入大事件 / 反派出场 等），不许三题都重生或都从「一个不起眼的小人物某天」开始。",
  ];
  const systemPrompt = [
    short
      ? "你是一位资深短篇网文策划编辑，擅长给短篇平台（知乎盐言/黑岩/点众）构思开篇就抓人的故事。你唯一的价值是产出「彼此一眼就不同」的选题，题与题只要感觉像同一个模子换皮，就是失败。只输出 JSON，不要多余的话。"
      : [
          "你是一位番茄小说资深选题策划。你的唯一价值是产出「三题之间一眼就不同、都能直接开写」的选题。你不出「听起来都挺燃」的点子，三题只要感觉像同一个模子换皮，就是失败。只输出 JSON，不要多余的话。",
          "",
          `【差异化铁律：每道选题必须在下面 ${DIVERSITY_COLUMNS.length} 个格子上各不相同】`,
          ...DIVERSITY_COLUMNS.map((c, i) => `${i + 1}. ${c}`),
          `先内部填一张 3×${DIVERSITY_COLUMNS.length} 的表，每格填完再写正文。任意一列出现两个相同项，换掉重填。`,
          "",
          "【反套路配方：别一直用，控频】",
          "「诗意边缘职业 + 略带诡秘氛围 + 一个寄生在某营生/物件上」这套模子（点灯人、守夜人、灯塔看守、收尸人、卖梦/卖记忆/贩卖情绪的小贩、拾荒者、摆渡人、代笔人、司机、外卖员、阴间公务员……以及「小人物+一个古怪副业」的开局）本身可以用，写得好的话也是好选题。但它是最省力、最容易三题都滑进去的安全区：三题里最多让它出现一次，其余两题必须走完全不同的气质。不许三题都用这个模子换个皮。",
          "同理，「交易/贩卖某物（记忆/寿命/情绪/运气）」当金手指也可以用，但三题里最多一题用，别三题都靠它。",
          "",
          "【单题最低要求】",
          "- 故事梗概是这一题的核心交付物（180-260 字）：谁、想要什么、被什么挡、爽在哪、往哪走，讲清楚到读者能立刻脑补出这本书，不剧透结局、不堆形容词。",
          "- 一句话卖点（≤20 字）要能把人勾住。",
          "- 给一个爆款率判断（high / mid / low）和一句理由：这个选题凭什么在这个平台爆、它的天花板在哪。",
          "- 有一个「评论区会有人复述、能截图」的具体梗，写进 differentiation。",
          "",
          "【合规（一票否决，放最后执行）】",
          "可操作的违法犯罪细节不写；未成年人性化内容不写；不复制他人作品原句（可借鉴结构，不可抄句子）。此外保留正常创作自由，社会批判、黑暗题材、复杂人性均不受限。",
          "",
          ...(direction
            ? [
                "【用户指定的题材/方向＝硬约束，不许跑题】",
                `用户明确要的是：「${direction}」。三题的 genre 大类必须落在这个题材里（可以细分不同，但大类不许换），故事内核、主角格局、核心冲突都要贴这个题材该有的味道。不许跑偏到用户没要的题材上去凑数。题材内部再用上面的差异化铁律把三题拉开。`,
              ]
            : []),
          "",
          nameStyle(),
          titleStyle(),
        ].join("\n"),
    "",
    skillBlock("concept", { platform, length: short ? "short" : "long", ref: Boolean(ref) }),
    refBrief
      ? "\n【对标书】用户给的对标书是《" + ref + "》。下面是联网查到的资料（可能不全或有误）：\n" + refBrief + "\n先把它拆一遍（题材定位、核心爽点、开局怎么抓人、节奏密度），再照它的路子出差异化选题。资料和你的印象冲突时以资料为准；查不到的部分不要编造。不许照搬它的人物、地名、情节和原句；题材可以同，故事必须是新的。"
      : ref
        ? "\n【对标书】用户给了书名《" + ref + "》，但这次没联网查到资料。按你对这本书的既有了解拆题（题材定位、核心爽点、开局打法）；不确定的地方按同类书套路写，不要编造它的具体情节。不许照搬它的人物、地名、情节和原句。"
        : "",
  ].join("\n");
  const laneLines = lanes.map((l, i) => `${i + 1}）${l} → 「${l.split("/")[0].trim()}·」`).join("\n");
  const directionBlock = useLanes
    ? [
        "【方向与 genre】三个候选预设了不同赛道（题材列已满足差异化铁律第 1 条，不必再凑）：",
        laneLines,
        "genre 必须写成「大类·细分」（例：悬疑·民俗、都市·异能）。",
      ].join("\n")
    : hasRef
      ? "【方向与 genre】题材以对标书为准，genre 按对标书的题材定位写。若三题落在同一大类下，仍须满足差异化铁律其余五列（时代/身份/金手指类型/爽点来源/叙事切口）各不相同。"
      : "【方向与 genre】题材按用户给的要求写，genre 写用户要的题材。若三题落在同一大类下，仍须满足差异化铁律其余五列各不相同；不许为了凑差异换到用户没要的题材。";
  const userPrompt = [
    short
      ? `出 ${count} 个短篇选题候选（一稿完结，不是连载开篇）。候选越少、每个越完整，比给一堆雷同的强。`
      : `出 ${count} 个长篇选题候选。候选越少、每个越完整，比给一堆雷同的强。`,
    "（差异化铁律、单题要求、合规、命名规则、技能纪律，一律按 system prompt 执行，此处不重复。）",
    directionBlock,
    `方向：${direction || "不限"}；想看的元素：${elements || "无"}；目标平台：${platform}；目标规模：约 ${estChapters} 章 × 每章约 ${perChapter} 字（合计约 ${totalWords} 字）。`,
    estChapters >= 200
      ? `这是长篇连载：核心矛盾要能长期驱动，撑得住 ${estChapters} 章的体量，而不是二三十章就能写完的小故事。`
      : "",
    avoid.length
      ? `上一批已经出过下面这些，这次一个都不许重复（换说法、换地名、换职业但骨架一样，也算重复）：\n${avoid.map((x) => "- " + x).join("\n")}`
      : "",
    recentGenres.length && useLanes
      ? `最近开过的书题材有：${[...new Set(recentGenres)].join("、")}。这些题材本批不许再用，全部换到别的赛道。`
      : "",
    ref ? `\n<对标书>《${ref}》</对标书>\n先判断它靠什么留住读者（钩子类型、节奏、视角、爽点密度），再把这种路子用到你要出的选题上。` : "",
    refBrief
      ? `\n<对标书资料>\n${refBrief.slice(0, 5000)}\n</对标书资料>\n上面是联网查到的对标书内容。先拆它的题材定位、核心爽点、开局打法和节奏，再出差异化选题；资料和你的印象冲突时以资料为准，查不到的部分不要编造，也不许照搬它的人物、地名、情节和原句。`
      : "",
    "【输出】严格只输出一个 JSON 数组，不要任何解释。数组每个元素形如：",
    `{"title":"书名(2-10字)","titleOptions":["",""],"genre":"大类·细分","oneLine":"一句话卖点(≤20字)","synopsis":"故事梗概(180-260字)","hitRate":"high|mid|low","hitReason":"爆款率理由(≤40字)","platform":"${platform}","differentiation":"同类通常怎么做→我改成什么(≤60字)","risk":"最易写崩在哪一章、为什么(≤40字)"}`,
    "每条的主件是 synopsis（故事梗概）——大纲就是从它长出来的，梗概写砸这一题就废了，务必 180-260 字讲满要讲的事。title/genre/oneLine/hitRate 是给作者快速挑的工具位。",
    `【输出前自检】3×${DIVERSITY_COLUMNS.length} 表每列无重复项／三题 genre 大类不同／三题爽点各不相同／梗概都在 180-260 字／书名 2-10 字／每题的 hitRate 都给了且理由不重复／JSON 可解析。任一不过，改完再输出。`,
  ].filter(Boolean).join("\n");

  let text = "";
  let finish = null;
  try {
    const res = await streamText(llm, {
      provider, model,
      messages: [
        { role: "system", content: [{ type: "text", text: systemPrompt }] },
        { role: "user", content: [{ type: "text", text: userPrompt }] },
      ],
      maxTokens: 6000,
      purpose: "novel-concept",
    });
    text = res.text;
    finish = res.finish;
  } catch (e) {
    throw new HttpError(502, `模型调用失败：${e?.message || String(e)}`);
  }
  // 模型侧报错（没配 Key、额度、拒答等）：把真实原因透出去，别伪装成"没返回 JSON"。
  if (finish && finish.kind === "error") {
    const msg = finish.failure?.message || "模型返回了错误";
    throw new HttpError(502, `模型调用失败：${msg}`);
  }

  let arr = extractJsonArray(text);
  if (!Array.isArray(arr) || arr.length === 0) {
    // 输出被 maxTokens 截断时，前面完整的候选仍然可用
    arr = salvageJsonObjects(text).filter((c) => c && (c.title || c.name) && (c.synopsis || c.oneLine));
  }
  if (!Array.isArray(arr) || arr.length === 0) {
    throw new HttpError(502, `模型没有返回可解析的选题 JSON。原文片段：${String(text).slice(0, 200)}`);
  }
  arr = arr.slice(0, count).map((c, i) => ({
    id: c.id || `gen-${Date.now().toString(36)}-${i}`,
    title: String(c.title || c.name || "未命名").trim(),
    oneLine: String(c.oneLine || c.logline || "").trim(),
    genre: String(c.genre || direction || "玄幻").trim(),
    platform: String(c.platform || platform).trim(),
    synopsis: String(c.synopsis || "").trim(),
    titleOptions: Array.isArray(c.titleOptions) ? c.titleOptions.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 3) : [],
    // 爆款率：选题阶段给作者一个快速判断依据
    hitRate: String(c.hitRate || "").trim().toLowerCase(),
    hitReason: String(c.hitReason || "").trim(),
    // 差异化 6 列：字段带回前端，既能自我约束也能让作者一眼看出是不是换皮
    era: String(c.era || "").trim(),
    protagonist: String(c.protagonist || "").trim(),
    goldenFingerType: String(c.goldenFingerType || "").trim(),
    pleasureSource: String(c.pleasureSource || "").trim(),
    openingCut: String(c.openingCut || "").trim(),
    goldenFinger: String(c.goldenFinger || "").trim(),
    opening: String(c.opening || "").trim(),
    differentiation: String(c.differentiation || "").trim(),
    business: String(c.business || "").trim(),
    risk: String(c.risk || "").trim(),
    outlineHint: String(c.outlineHint || "").trim(),
  }));
  return {
    ok: true, provider, model, concepts: arr, raw: String(text).slice(0, 500),
    reference: refTitles.map((t, i) => ({ title: t, found: Boolean(refResults[i]) })),
  };
}

// ---- 通用：单次调用模型拿纯文本（可选要求 JSON 对象）----
/**
 * 对标书联网查资料：先用 DSH 自带搜索（ctx.web.search），没有就试本地 Agent-Reach。
 * 都不可用时返回空串，选题照常按书名做，不阻断。
 */
async function lookupReference(ctx, title, platform) {
  const query = `《${title}》小说 剧情简介 题材 ${platform || ""}`.trim();
  const web = (() => { try { return ctx?.get ? ctx.get("web") : ctx?.web; } catch { return null; } })();
  if (web && typeof web.search === "function") {
    try {
      const r = await web.search({ query, maxResults: 5 });
      const lines = (r?.sources || [])
        .map((s) => `- ${s.title || ""}（${s.url || ""}）：${s.snippet || ""}`.trim())
        .filter((l) => l.length > 12);
      if (lines.length) return lines.join("\n").slice(0, 3000);
    } catch { /* 没配搜索服务 → 试 Agent-Reach */ }
  }
  // Agent-Reach（本地安装后提供 agent-reach 命令，输出 JSON）
  try {
    const { execFile } = await import("node:child_process");
    const { homedir } = await import("node:os");
    const { join, dirname } = await import("node:path");
    const bin = process.env.DSH_NOVEL_REACH_BIN || join(homedir(), ".local", "bin", "agent-reach");
    const out = await new Promise((resolve) => {
      execFile(bin, ["web", "search", query], { timeout: 30000, maxBuffer: 4 << 20, env: { ...process.env, PATH: `${dirname(bin)}:${process.env.PATH || ""}` } }, (err, stdout) => resolve(err ? "" : String(stdout || "")));
    });
    if (!out) return "";
    const data = JSON.parse(out.trim());
    const lines = (data?.items || []).slice(0, 5)
      .map((it) => `- ${it.title || ""}（${it.url || ""}）：${it.snippet || it.text || it.description || ""}`.trim())
      .filter((l) => l.length > 12);
    return lines.join("\n").slice(0, 3000);
  } catch { return ""; }
}

async function generateText(ctx, body, { system, user, maxTokens, purpose, allowPartial = false }) {
  const llm = resolveLlm(ctx);
  if (!llm) throw new HttpError(503, "当前环境没有可用的模型服务");
  const def = defaultSelection(ctx);
  const pref = await readModelPref();
  const wantProvider = (body.provider || pref?.provider || def?.provider || "").toString().trim();
  const wantModel = (body.model || pref?.model || def?.model || "").toString().trim();

  const messages = [
    { role: "system", content: [{ type: "text", text: system }] },
    { role: "user", content: [{ type: "text", text: user }] },
  ];
  let lastErrMsg = "";
  const tried = new Set();
  const startedAt = Date.now();
  let attempts = 0;
  const keyOf = (c) => c.provider + "::" + c.model;
  const attempt = async (cand) => {
    if (attempts >= 4 || Date.now() - startedAt > CALL_TIMEOUT_MS) {
      lastErrMsg = lastErrMsg || "生成超时（4 分钟内没有可用结果）";
      return null;
    }
    attempts += 1;
    tried.add(keyOf(cand));
    try {
      const res = await streamText(llm, {
        provider: cand.provider, model: cand.model,
        messages, maxTokens: maxTokens || 4000, purpose: purpose || "novel-gen",
      });
      if (res.finish && res.finish.kind === "error") {
        lastErrMsg = res.finish.failure?.message || "模型返回了错误";
        return null; // 缺 key / 凭证类错误 → 换下一个 provider 再试
      }
      // 输出被截断（maxTokens 用完）：半截 JSON 解析必然失败，明确报出来而不是当成格式问题。
      // 细纲这类「先写机器块再写正文」的调用允许拿半截结果：至少把节拍落账，不整章白跑。
      if (res.finish && res.finish.kind === "max-tokens") {
        if (allowPartial && String(res.text || "").trim()) {
          return { text: res.text, provider: cand.provider, model: cand.model, partial: true };
        }
        lastErrMsg = "输出太长被截断（maxTokens 用完）";
        return null;
      }
      return { text: res.text, provider: cand.provider, model: cand.model };
    } catch (e) {
      lastErrMsg = e?.message || String(e);
      return null;
    }
  };

  // 先用用户选的 / 默认模型。只有它失败了才去枚举其它 provider —— 每次调用都 listModels
  // 会先等一串网络请求，工具看起来就“一直不返回”。
  const primary = [];
  if (wantProvider && wantModel) primary.push({ provider: wantProvider, model: wantModel });
  if (def && def.provider && def.model) primary.push({ provider: def.provider, model: def.model });
  for (const cand of primary) {
    if (!cand.provider || !cand.model || tried.has(keyOf(cand))) continue;
    if (attempts >= 4 || Date.now() - startedAt > CALL_TIMEOUT_MS) break;
    const ok = await attempt(cand);
    if (ok) return ok;
  }

  try {
    const list = llm.listProviders ? llm.listProviders() : [];
    for (const p of list) {
      const pid = p.id ?? p.name ?? p.provider;
      let models = [];
      try { models = await llm.listModels(pid); } catch { models = []; }
      for (const m of models || []) {
        if (!m || !m.id) continue;
        if (attempts >= 4 || Date.now() - startedAt > CALL_TIMEOUT_MS) break;
        const cand = { provider: pid, model: m.id };
        if (tried.has(keyOf(cand))) continue;
        const ok = await attempt(cand);
        if (ok) return ok;
      }
      if (attempts >= 4 || Date.now() - startedAt > CALL_TIMEOUT_MS) break;
    }
  } catch { /* ignore */ }

  if (!tried.size) throw new HttpError(409, "没有可用的模型，请先在设置里选一个模型（DSH 需配好 API Key）");
  // 把常见故障换成能指导用户的话，同时保留原始信息（方便排查）
  const low = String(lastErrMsg || "").toLowerCase();
  let hint = "";
  if (low.includes("insufficient balance") || low.includes("余额") || low.includes("quota") || low.includes("credit")) {
    hint = "：模型账号余额/额度不足，请到 DSH 的模型页充值，或在设置里换一个有额度的模型";
  } else if (low.includes("api key") || low.includes("missing_credential") || low.includes("no api key")) {
    hint = "：模型没有配 API Key，请到 DSH 的模型页配置密钥，或在设置里换一个已配好的模型";
  } else if (low.includes("rate limit") || low.includes("429")) {
    hint = "：触发限流，稍等一会儿再试，或在设置里换一个模型";
  }
  throw new HttpError(502, `生成失败${hint}。原始信息：${lastErrMsg || "无可用模型返回结果"}`);
}

// 从文本里抠出 JSON 对象
function extractJsonObject(text) {
  if (!text) return null;
  let t = String(text).trim();
  const fence = t.match(/```(?:json)?\s*([\s\S]*?)```/i);
  if (fence) t = fence[1].trim();
  const start = t.indexOf("{");
  const end = t.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) return null;
  try { return JSON.parse(t.slice(start, end + 1)); } catch { return null; }
}

// ---- 设定补全（插件内直接调模型）：依大纲+世界观+已有设定，补齐人物/势力/地点/物品/规则/文风
//      关键：已有的（同名）只保留不覆盖；只把缺的补进去。返回写了什么、跳过了什么 ----
/**
 * 同名判定：名字完全一致，或对方名字/别名里出现「老韩」这类简称都算同一个人。
 * 设定里常写成「同期新人·老韩」（别名 老韩），模型又补一条「老韩」，精确比名字就会重复。
 */
function sameName(a, b) {
  const norm = (x) => String(x || "").toLowerCase().replace(/[\s·・\/\-—_,，、()（）]/g, "");
  const x = norm(a), y = norm(b);
  if (!x || !y) return false;
  if (x === y) return true;
  const short = x.length <= y.length ? x : y, long = x.length <= y.length ? y : x;
  return x.length >= 2 && y.length >= 2 && long.includes(short);
}
function namesTaken(list, name, aliases) {
  const cands = [name, ...(Array.isArray(aliases) ? aliases : [])];
  return (list || []).some((x) => [x.name, ...(Array.isArray(x.aliases) ? x.aliases : [])]
    .some((have) => have && cands.some((c) => sameName(have, c))));
}
const SETUP_ENTITIES = [
  { key: "characters", entity: "character", label: "人物" },
  { key: "factions", entity: "faction", label: "势力" },
  { key: "locations", entity: "location", label: "地点" },
  { key: "items", entity: "item", label: "物品" },
  { key: "rules", entity: "rule", label: "硬规则" },
];
// 势力/地点/物品/规则的「静态 + 动态」字段；只补空字段，不覆盖作者已填内容。
const ENTITY_EXTRA_FIELDS = {
  factions: ["aliases", "slang", "nature", "economy", "openRules", "hiddenRules", "relations", "emblem", "representatives", "power", "leader", "attitude", "misjudge", "changeLog", "text", "note"],
  locations: ["aliases", "geo", "structure", "spots", "senses", "owner", "accessRules", "occupied", "state", "events", "familiar", "text", "note"],
  items: ["aliases", "appearance", "origin", "function", "limit", "cost", "type", "holder", "state", "whoKnows", "transferLog", "text", "note"],
  rules: ["judge", "cost", "boundary", "level", "source", "belief", "tested", "exploited", "violationLog", "keywords", "text", "note"],
};
/**
 * 存档后「补全本章设定」：读这一章正文，把正文里出现、但设定里还没有的人物/地点/物品/势力/新规则
 * 抽出来，以「只补不覆盖」的方式写进骨架账本。跟 generateSetup（按大纲补）不同，这是按「已写正文」补。
 */
/**
 * 存档后「精炼章节记忆」：把本章压成一条可复用的叙事记忆（关键事件数组 + 结束时状态 + 人物状态变化），
 * 追加写入 ledger/memory.jsonl。这样 narrativeMemory() 才能在写后续章节时，把「这章到底发生了什么」喂回去。
 * 与 setting-sync（补设定）分工：setting-sync 补的是「世界设定」，这里补的是「剧情记忆」。
 */
/**
 * 叙事断层检查（语义级，report-only，不判废）：
 * 把一章按场景切段后，让模型逐对相邻场景判断「读者能不能接上」——有没有跳步/瞬移/因果断裂
 * （典型：警察上门 → 下一段直接从警局问询室出来，中间的"怎么到的警局/怎么进的问询室"没写）。
 * 这是纯规则查不到的深层逻辑，只能靠模型判。返回 {pass, issues:[{between,issue,why,severity}]}。
 * 默认不判废（severity 封顶 mid），进 continuity 时也只作 info/mid 提示。
 */
/** 给每条断层补「上一段结尾 / 下一段开头」的原文锚点：光有段号作者找不到位置。 */
export function attachSceneAnchors(issues, scenes) {
  for (const x of issues || []) {
    const m = /第\s*(\d+)\s*段\s*[→\-~至到]+\s*第?\s*(\d+)\s*段/.exec(String(x.between || ""));
    const a = m ? (scenes || []).find((s) => Number(s.i) === Number(m[1])) : null;
    const b = m ? (scenes || []).find((s) => Number(s.i) === Number(m[2])) : null;
    const tail = (t) => String(t || "").replace(/\s+/g, " ").trim().slice(-60);
    const head = (t) => String(t || "").replace(/\s+/g, " ").trim().slice(0, 60);
    x.before = a ? tail(a.text) : "";
    x.after = b ? head(b.text) : "";
  }
  return issues || [];
}

/**
 * 断层结果归一：模型说「真断层」却引用了下一段里解释跳跃的原句（如「不知站了多久」），
 * 说明作者已经交代过，只是没写常规过渡——降级成有意留白，不算断层。
 * 引文必须在正文里真实存在，防止模型编一句来给自己开脱。
 */
export function normalizeLogicIssues(list, scenes) {
  const full = (scenes || []).map((s) => String(s?.text || "")).join("\n").replace(/\s+/g, "");
  return (Array.isArray(list) ? list : []).map((x) => {
    const quoted = String(x?.covered || "").trim();
    // 引文必须出自「下一段」本身，不能从本章别处抄一句来打掉断层
    const m = /第\s*(\d+)\s*段\s*[→\-~至到]+\s*第?\s*(\d+)\s*段/.exec(String(x?.between || ""));
    const target = m ? (scenes || []).find((s) => Number(s?.i) === Number(m[2])) : null;
    const scope = target ? String(target.text || "").replace(/\s+/g, "") : full;
    const covered = quoted && (!scope || scope.includes(quoted.replace(/\s+/g, ""))) ? quoted : "";
    return {
      between: String(x?.between || "").trim(),
      issue: String(x?.issue || "").trim(),
      why: String(x?.why || "").trim(),
      evidence: covered,
      intentional: String(x?.kind || "").toLowerCase() === "intentional" || Boolean(covered),
      // report-only：封顶 mid，绝不 high（避免语义误判直接废章）
      severity: ["mid", "low"].includes(String(x?.severity)) ? String(x.severity) : "mid",
    };
  }).filter((x) => x.issue);
}

async function logicCheck(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const n = Number(body.number) || 0;
  if (!n) throw new HttpError(400, "需要 chapter number");
  let text = "";
  try { text = (await readChapter(root, n)).text; } catch { throw new HttpError(404, `第${n}章正文读不到`); }
  const scenes = splitScenes(text);
  if (scenes.length < 2) {
    return { ok: true, chapter: n, scenes: scenes.length, pass: true, issues: [], note: "整章只有一个场景，无需跨场景比对" };
  }
  const es = await endSceneState(root, { chapter: n - 1 });
  const sceneDump = scenes.map((s) => `【第${s.i}段】\n${s.text.slice(0, 1200)}`).join("\n\n");
  // 先用确定性体检打底：规则查得出的问题不交给模型猜，模型只补「段落之间」这类规则查不到的。
  const det = await continuityCheck(root).catch(() => null);
  const ruleFindings = (det?.findings || []).filter((f) => f.severity !== "info"
    && (String(f.message || "").includes(`第${n}章`) || f.code === "chapter-gap"));

  const system = "你是资深小说编辑，专门抓「场景之间的叙事断层」：读者读到下一段时会问『等等，他怎么到这里的？』的那种跳步、瞬移、因果断裂、时间/地点不衔接。只报真问题，不吹毛求疵，不评价文笔。只输出 JSON。";
  const user = [
    es && (es.chars.length || es.place)
      ? `【上一章结尾】在场：${es.chars.join("、") || "未记"}；地点：${es.place || "未记"}。\n（若本章第一段与上一章结尾地点/在场者不同，要检查本章有没有交代"怎么到这里"的过渡。）\n`
      : "",
    ruleFindings.length
      ? `【规则已经查出的问题（不用重复报，只判断还有没有别的段落断层）】\n${ruleFindings.map((f) => `- ${f.message}`).join("\n")}\n`
      : "",
    `下面是第 ${n} 章的正文，已按场景切分为 ${scenes.length} 段。请逐对检查【第i段 → 第i+1段】之间：`,
    "1. 地点是否瞬移（上一段在某处，下一段突然在完全不同的地方，却没写「怎么去的」）。",
    "2. 时间是否跳跃（中间有明显时间跨度，但没交代过渡，读者会困惑）。",
    "3. 动作/因果是否断裂（某人上一段还在做A，下一段在做毫不相干的B，中间那步没写）。",
    "4. 人物位置矛盾（同一时刻这人被写在两个地方）。",
    "只报「读者会觉得接不上」的真断层。写了过渡的时间跳跃、刻意的闪回/留白/蒙太奇，都不算断层。",
    "报之前必须先在【第i+1段】开头找一句过渡（谁到的、怎么到的、隔了多久、或者作者明说「不知何时来的」）。",
    "找到就把它原样填进 covered，kind 必须是 intentional，不要进 issues。",
    "特别注意：人物第一次出现就站在主角身后，但下一段写了「不知站了多久」「像从雾里长出来」「没听见脚步」这类句子——这是作者有意留白（悬疑/压迫感），covered 填那句原话，算 intentional，不算断层。",
    "只有下一段完全没交代、读者会以为漏写了一段，才填 kind=real，covered 留空。",
    "每条先判断：kind=real（真断层）还是 kind=intentional（作者有意为之：闪回、留白、蒙太奇、先果后因）。",
    "输出 JSON：",
    '{"issues":[{"between":"第X段→第Y段","kind":"real|intentional","covered":"第i+1段里解释跳跃的那句原话，没有就空","issue":"一句话说清","why":"读者会问什么","severity":"high|mid|low"}]}',
    "没有断层就返回 {\"issues\":[]}。不要为了交差硬凑问题。",
    "",
    sceneDump,
  ].join("\n");

  const gen = await generateText(ctx, body, { system, user, maxTokens: 2000, purpose: "novel-logic-check" });
  let obj = null;
  try { obj = extractJsonObject(String(gen.text || "")); } catch { obj = null; }
  if (!obj) { const m = String(gen.text || "").match(/\{[\s\S]*\}/); if (m) { try { obj = JSON.parse(m[0]); } catch { obj = null; } } }
  if (!obj) throw new HttpError(502, `模型没返回可解析的 JSON。片段：${String(gen.text || "").slice(0, 140)}`);
  const dismissed = await loadDismissedSet(root);
  const all = normalizeLogicIssues(obj.issues, scenes).filter((x) => !dismissed.has(logicKey(n, x)));
  const issues = all.filter((x) => !x.intentional);
  const notes = all.filter((x) => x.intentional);
  attachSceneAnchors([...issues, ...notes], scenes);
  const pass = issues.length === 0 && ruleFindings.length === 0;
  return {
    ok: true, chapter: n, scenes: scenes.length, pass,
    issues, notes,
    ruleFindings: ruleFindings.map((f) => ({ severity: f.severity, message: f.message, hint: f.hint })),
    summary: pass
      ? (notes.length ? `没查出真断层；模型判断 ${notes.length} 处跳跃是有意为之` : "没查出断层")
      : `${issues.length} 处段落断层${ruleFindings.length ? `，另有 ${ruleFindings.length} 处规则问题` : ""}`,
    provider: gen.provider, model: gen.model,
  };
}

// 值得让模型复核的语义类体检项；缺文件/断章/字数/禁用词这类硬事实永远不进复核。
const REVIEWABLE = new Set([
  "dead-returns", "rule-conflict", "must-include-missed",
  "early-appear", "late-appear", "never-appears", "unknown-speaker", "no-end-hook",
]);

function findingExcerpt(text, message) {
  const m = /「([^」]{1,24})」/.exec(String(message || "")) || /疑似未登记人物：([^×，,、；;\s]+)/.exec(String(message || ""));
  const term = m ? m[1] : "";
  const at = term ? text.indexOf(term) : -1;
  if (at < 0) return text.slice(0, 420);
  const from = Math.max(0, at - 160);
  const to = Math.min(text.length, at + term.length + 240);
  return (from > 0 ? "…" : "") + text.slice(from, to) + (to < text.length ? "…" : "");
}

/**
 * 体检 AI 复核：规则先报候选，模型只判断「语义类」候选在正文语境里是否成立。
 * 模型必须引用正文原句；引文在片段里查不到就维持原判，防止它编理由把问题说成误报。
 */
export async function reviewChapter(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const n = Number(body.number) || 0;
  if (!n) throw new HttpError(400, "需要 chapter number");
  const ck = await checkChapter(root, n);
  if (ck.missing) throw new HttpError(400, `第${n}章不在正文里（被退回重写或还没写），没有可体检的稿子`);
  // 体检通过 = 连续性没硬伤；顺手重算提交时的 AI 痕迹/禁用词/硬规则，清掉就摘掉「待修」
  if ((ck.counts?.high || 0) === 0) {
    try { await refreshChapterVerdict(root, n); } catch { /* 重算失败不影响体检结果 */ }
  }
  const findings = ck.findings || [];
  // 章尾钩子本身是 info（只提示不拦），但正是最容易被规则误判的一类，也送 AI 复核
  const targets = findings.filter((f) => (f.severity !== "info" || f.code === "no-end-hook") && REVIEWABLE.has(f.code));
  const done = (extra = {}) => ({
    ok: true, chapter: n, findings, pass: (ck.counts?.high || 0) === 0 && (ck.debutMisses || []).length === 0,
    counts: ck.counts, reviewed: targets.length, debutMisses: ck.debutMisses || [], ...extra,
  });
  if (!targets.length) return done();

  let text = "";
  try { text = (await readChapter(root, n)).text; } catch { return done(); }

  const items = targets.map((f, i) => ({
    id: i + 1, code: f.code, severity: f.severity,
    message: f.message, hint: f.hint || "",
    // 钩子问题要看章尾，不能截正文开头
    excerpt: f.code === "no-end-hook" ? text.slice(-600) : findingExcerpt(text, f.message),
  }));
  const system = "你是网文编辑部的复核员。规则引擎按字面报出了一批「可能有问题」的条目，你要结合正文片段判断它在语境里是否真的成立。只做语义判断，不评价文笔。只输出 JSON。";
  const user = [
    `第 ${n} 章有 ${items.length} 条候选问题。逐条判断：`,
    "- real：正文确实矛盾/缺失，读者会觉得写错了；",
    "- intentional：作者有意留白、回忆、视角限制或伏笔，片段里有句子支撑；",
    "- invalid：规则误判（尸体/遗物出场、同义改写、称谓被当人名、钩子其实有）。",
    "每条必须给出 quote：从 excerpt 里逐字复制能证明你判断的原句。quote 必须真的出现在 excerpt 里，否则你的判断无效。",
    "拿不准就判 real（宁可保留），不要为了清空问题硬判误报。",
    '输出 {"items":[{"id":1,"verdict":"real|intentional|invalid","reason":"一句话","quote":"原文原句"}]}',
    "",
    ...items.map((x) => `【${x.id}】${x.message}\n${x.hint ? "提示：" + x.hint + "\n" : ""}片段：${x.excerpt}`),
  ].join("\n");

  let gen;
  try {
    gen = await generateText(ctx, body, { system, user, maxTokens: 2200, purpose: "novel-check-review" });
  } catch (e) {
    return done({ reviewError: e?.message || String(e) });
  }
  let obj = null;
  try { obj = extractJsonObject(String(gen.text || "")); } catch { obj = null; }
  if (!obj) { const m = String(gen.text || "").match(/\{[\s\S]*\}/); if (m) { try { obj = JSON.parse(m[0]); } catch { obj = null; } } }
  const rows = Array.isArray(obj?.items) ? obj.items : [];
  for (const j of verifyReviewItems(items, rows)) {
    const f = targets[j.id - 1];
    if (!f) continue;
    f.ai = { verdict: j.verdict, reason: j.reason, quote: j.quote, verified: j.verified, note: j.note };
    if (j.verdict !== "real") f.severity = "info";
  }

  const counts = {
    high: findings.filter((f) => f.severity === "high").length,
    mid: findings.filter((f) => f.severity === "mid").length,
    info: findings.filter((f) => f.severity === "info").length,
  };
  return { ok: true, chapter: n, findings, pass: counts.high === 0 && (ck.debutMisses || []).length === 0, counts, reviewed: items.length, provider: gen.provider, model: gen.model, debutMisses: ck.debutMisses || [] };
}

/** 复核结果落地前先验引文：模型说「误报/有意为之」但引不出正文原句的，一律维持原判。 */
export function verifyReviewItems(items, rows) {
  const norm = (s) => String(s || "").replace(/\s+/g, "");
  return (items || []).map((it) => {
    const row = (rows || []).find((x) => Number(x?.id) === it.id) || null;
    const claimed = ["real", "intentional", "invalid"].includes(String(row?.verdict)) ? String(row.verdict) : "real";
    const quote = String(row?.quote || "").trim();
    const verified = Boolean(quote) && norm(it.excerpt).includes(norm(quote));
    const verdict = claimed !== "real" && !verified ? "real" : claimed;
    return {
      id: it.id, verdict, reason: String(row?.reason || "").trim(), quote, verified,
      note: claimed !== "real" && !verified ? "复核没给出可核对的原文引句，维持原判" : "",
    };
  });
}

export async function distillMemory(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const idx = await loadIndex(root);
  const nums = (Array.isArray(body.numbers) ? body.numbers : [body.number])
    .map((x) => Number(x)).filter((x) => Number.isInteger(x) && x > 0);
  if (!nums.length) throw new HttpError(400, "需要 chapter number 或 numbers");

  const system = "你是长篇小说的连续性记录员。给你一章正文，你把它压成一条『后续写作要用到的记忆』。只记录确定发生的，不评价好坏，不编造。只输出 JSON。";
  const user = [
    `这是第 ${n} 章《${entry.title || ""}》的正文。请提炼：`,
    "1. events：本章实际发生的关键事件，按时间顺序，3-8 条，每条一句话（谁做了什么、结果如何）。",
    "2. state：本章结束时主角/主要人物所处的状态（在哪儿、和谁、知道什么、悬而未决的是什么），2-3 句。",
    "3. characters：本章实际出场的人物（名字）。",
    "4. summary：本章一句话梗概，40-80 字，只写发生了什么（这条会放进后面每一章的上下文，写长了会挤掉别人的位置）。",
    "5. knows：本章里人物新知道了什么（只写会改变后续选择的；谁都不知情就给空数组）。",
    "6. relations：本章里谁和谁的关系变了（从什么变成什么；没变就给空数组）。",
    "严格只输出一个 JSON 对象（不要 Markdown、不要代码块）：",
    '{"summary":"...","events":["..."],"state":"...","characters":["..."],"knows":[{"who":"人物","learned":"知道了什么"}],"relations":[{"a":"人物","b":"人物","change":"从什么变成什么"}]}',
    "",
    "=== 本章正文 ===",
    text.slice(0, 7000),
  ].join("\n");
  const gen = await generateText(ctx, body, { system, user, maxTokens: 1400, purpose: "novel-memory-distill" });
  let obj = null;
  try { obj = extractJsonObject(String(gen.text || "")); } catch { obj = null; }
  if (!obj) { const m = String(gen.text || "").match(/\{[\s\S]*\}/); if (m) { try { obj = JSON.parse(m[0]); } catch { obj = null; } } }
  if (!obj) throw new HttpError(502, `模型没返回可解析的 JSON。片段：${String(gen.text || "").slice(0, 140)}`);

  const row = {
    chapter: n,
    title: entry.title || "",
    summary: clampSummary(String(obj.summary || entry.summary || ""), SUMMARY_TARGET * 2),
    events: Array.isArray(obj.events) ? obj.events.map((x) => String(x || "").trim()).filter(Boolean).slice(0, 8) : [],
    state: String(obj.state || "").trim(),
    characters: Array.isArray(obj.characters) && obj.characters.length ? obj.characters.map((x) => String(x || "").trim()).filter(Boolean) : (entry.characters || []),
    // L0：人物当时知道什么 / 关系怎么变的。合成时取「截止本章」的最新一条，重写后以新行覆盖旧判断
    knows: (Array.isArray(obj.knows) ? obj.knows : []).map((x) => ({ who: String(x?.who || "").trim(), learned: String(x?.learned || "").trim() })).filter((x) => x.who && x.learned).slice(0, 10),
    relations: (Array.isArray(obj.relations) ? obj.relations : []).map((x) => ({ a: String(x?.a || "").trim(), b: String(x?.b || "").trim(), change: String(x?.change || "").trim() })).filter((x) => x.a && x.b && x.change).slice(0, 10),
    at: new Date().toISOString(),
  };
  await appendMemory(root, row);
  await updateRelations(root, n, n).catch(() => null);
  return { ok: true, chapter: n, memory: row, view: await studioPayload(root) };
}

/**
 * 卷盘点（L1）：把这一卷已写的章记忆压成一段「这卷发生了什么」。
 * 每卷只需要做一次；做完之后后面所有章的上下文包里，这卷就是一整段，不再是几百条章记忆。
 * 素材全部来自本地账本（不读正文），所以既快又不会把原文再烧一遍。
 */
async function compileVolumeMemory(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const n = Number(body.number) || Number((await loadProject(root))?.currentChapter) || 0;
  if (!n) throw new HttpError(400, "还没有正文可盘点：先写几章再来");
  const digest = await buildVolumeDigest(root, { chapter: n });
  if (!digest.count) return { ok: false, error: `${digest.volume.title} 里还没有已写的正文`, view: await studioPayload(root) };

  const dims = Object.entries(digest.dims).map(([k, v]) => `- ${k}：${v}`).join("\n");
  const system = "你是长篇小说主编的卷末复盘记录员。给你一卷里每一章的梗概，你写出一段『读完这一卷必须记住的事』，供作者写后面几百章时引用。只写书中确定发生的事实，不评价文笔，不预测后续，不编造。";
  const user = [
    `这是《${digest.volume.title}》第${digest.from}-${digest.to}章（共 ${digest.count} 章）的逐章梗概。请按下面几条各写 1-3 句，合并成一段连贯的记录（总长 500-900 字）：`,
    dims,
    "",
    "要求：每条都写清人物名与结果；计划了但还没发生的不要写；不确定的写「（存疑）」并给章号。",
    "",
    "=== 逐章梗概 ===",
    digest.text.slice(0, 24000),
  ].join("\n");
  const gen = await generateText(ctx, body, { system, user, maxTokens: 1800, purpose: "novel-volume-memory" });
  const summary = String(gen.text || "").trim();
  if (!summary) throw new HttpError(502, "模型没有返回卷记忆");
  await appendMemory(root, { kind: "volume", volume: digest.volume.title, from: digest.from, to: digest.to, chapters: digest.count, summary: summary.slice(0, 2400) });
  // 顺手把这一卷的人物关系压进账本（L1 关系），写后面章节时按出场人物调出来
  await updateRelations(root, digest.from, digest.to).catch(() => null);
  return { ok: true, volume: digest.volume, from: digest.from, to: digest.to, chapters: digest.count, summary, view: await studioPayload(root) };
}

/** 手动合并前复核：名字规则只负责挑候选，模型带正文引文判定，判否/不确定的不合并。 */
async function mergeWithModelCheck(ctx, body, root) {
  const pairs = await listMergePairs(root);
  if (!pairs.length) return { merged: [], count: 0, note: "" };
  const index = await loadIndex(root).catch(() => []);
  const texts = [];
  for (const c of index.slice(-40)) {
    try { texts.push({ n: c.number, t: await readText(p(root, c.file)) }); } catch { /* 缺文件跳过 */ }
  }
  const quoteOf = (it) => {
    for (const name of [it.name, ...(it.aliases || [])].filter(Boolean)) {
      for (const c of texts) {
        const at = String(c.t).indexOf(name);
        if (at >= 0) return `第${c.number}章「…${String(c.t).slice(Math.max(0, at - 30), at + name.length + 30).replace(/\s+/g, " ")}…」`;
      }
    }
    return "（正文里没找到）";
  };
  const lines = pairs.map((x, i) => [
    `${i + 1}. A：${x.a.name}${(x.a.aliases || []).length ? "（又叫" + x.a.aliases.join("、") + "）" : ""}｜${x.a.role || x.a.text || ""}｜${quoteOf(x.a)}`,
    `   B：${x.b.name}${(x.b.aliases || []).length ? "（又叫" + x.b.aliases.join("、") + "）" : ""}｜${x.b.role || x.b.text || ""}｜${quoteOf(x.b)}`,
  ].join("\n")).join("\n\n");
  const system = "你在核对小说设定里的两条是不是同一个实体。只输出 JSON 数组，不要解释。";
  const user = [
    "判断下面每一对是否真的是同一个角色/事物。规则：",
    "- 身份描述（赵家长工、会院守井老汉）不是名字，也不等于另一个人；",
    "- 同姓、同职业、主仆/亲属关系、同乡都不算同一人；",
    "- 只有正文里明确指向同一角色（别名、绰号、称谓）才算；证据不足就判否。",
    "只输出被判为同一对的序号数组，例如 [1,4]；都没有就输出 []。",
    "",
    lines,
  ].join("\n");
  let allow = [];
  try {
    const gen = await generateText(ctx, body, { system, user, maxTokens: 400, purpose: "novel-merge-review" });
    const m = String(gen.text || "").match(/\[[\d,\s]*\]/);
    const picks = m ? JSON.parse(m[0]) : [];
    allow = picks.map((n) => pairs[Number(n) - 1]).filter(Boolean).map((x) => [x.a.name, x.b.name]);
  } catch (e) {
    return { merged: [], count: 0, note: "AI 复核没跑成（" + ((e && e.message) || e) + "），这次没有合并。" };
  }
  if (!allow.length) return { merged: [], count: 0, note: "AI 复核后没有确认的重复条目，未合并。" };
  const r = await mergeDuplicateEntities(root, { allow });
  return { ...r, note: "" };
}

/**
 * 保存设定前让模型核对「这几条是不是同一个人」：插件只认名字和别名的包含关系，
 * 「老韩 / 韩四 / 韩掌柜」这类换说法认不出来。模型只给「哪几条是一组」，
 * 保留哪条、并进哪条由插件按已有条目自己决定，模型说错也不会造出新人。
 */
async function mergeSamePersonByModel(ctx, body, groups, root) {
  const flat = [];
  for (const [field, ent] of groups) {
    for (const it of Array.isArray(body[field]) ? body[field] : []) {
      if (it && String(it.name || "").trim()) flat.push({ field, ent, it });
    }
  }
  if (flat.length < 2) return { merged: [] };
  const lines = flat.map((x, i) => `${i + 1}. [${x.field}] ${x.it.name}${(x.it.aliases || []).length ? `（又叫：${x.it.aliases.join("、")}）` : ""}｜${(x.it.role || "")}｜${(x.it.text || "").slice(0, 60)}`);
  const text = lines.join("\n");
  const system = "你在核对小说设定里有没有「同一个人被写了两遍」。只输出 JSON，不要解释。";
  const user = [
    "下面是一部小说的设定条目。请找出其实是同一个人的分组（外号、职务称呼、姓氏加排行、谐音、明显是同一角色的不同写法都算）。",
    "分不清、只是同姓或同职业的，不要合并。",
    '严格只输出一个 JSON 数组，每个元素是一组序号（至少两个），例如 [[3,7]]；没有就输出 []。',
    "",
    text,
  ].join("\n");
  let arr = [];
  let note = "";
  try {
    const gen = await generateText(ctx, body, { system, user, maxTokens: 800, purpose: "novel-merge-check" });
    const m = String(gen.text || "").match(/\[[\s\S]*\]/);
    arr = m ? JSON.parse(m[0]) : [];
  } catch (e) {
    // 模型没跑成也照常保存，但要说明原因，否则作者以为核对过其实是跳过了
    note = "没做 AI 同名核对（" + ((e && e.message) || e) + "），只按名字和别名合并";
  }
  const merged = [];
  for (const g of Array.isArray(arr) ? arr : []) {
    const rows = (Array.isArray(g) ? g : []).map((n) => flat[Number(n) - 1]).filter(Boolean);
    const keep = rows.find((x) => x.field === "characters");
    for (const from of rows) {
      if (!keep || from === keep || from.field !== keep.field || from.it.name === keep.it.name) continue;
      const nameA = String(keep.it.name), nameB = String(from.it.name);
      const known = [...(keep.it.aliases || []), ...(from.it.aliases || [])].includes(nameB);
      // 去掉共同前缀再比，并排除「新人/同期/掮客/老/小」这类身份词：
      // 「同期新人·老韩 / 同期新人·小满」不该算同一人，「老韩 / 韩四」该算
      let prefix = 0;
      while (prefix < Math.min(nameA.length, nameB.length) && nameA[prefix] === nameB[prefix]) prefix += 1;
      const restA = nameA.slice(prefix), restB = nameB.slice(prefix);
      const filler = new Set(["者", "人", "的", "一", "二", "三", "大", "小", "老", "子", "儿", "头", "生", "士", "中", "上", "下", "之", "其", "某", "氏", "新", "同", "期", "掮", "客", "·", "（", "）"]);
      const shared = [...new Set([...restB])].filter((ch) => /[\u4e00-\u9fa5]/u.test(ch) && restA.includes(ch) && !filler.has(ch));
      if (!shared.length && !known) continue;
      const aliasCap = [...new Set([...(keep.it.aliases || []), nameB, ...(from.it.aliases || [])])].length;
      if (aliasCap > (keep.it.aliases || []).length + 3) continue;
      const fields = { character: "characters", faction: "factions", location: "locations", item: "items", rule: "rules" };
      const twin = findSame((await loadBible(root))[fields[keep.ent]] || [], keep.it.name, keep.it.aliases);
      await bibleUpsert(root, keep.ent, twin ? { id: twin.id, aliases: [nameB, ...(from.it.aliases || [])] } : { name: nameA, aliases: [nameB, ...(from.it.aliases || [])] });
      merged.push(`${from.it.name}→${keep.it.name}`);
    }
  }
  // 别名记上后，用项目自己的合并函数把重复那条真正并掉（不是只加别名留两条）
  if (merged.length) await mergeDuplicateEntities(root);
  return { merged, note };
}

export async function syncSettingFromChapterViaAI(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const project = await loadProject(root);
  const bible = await loadBible(root);
  const idx = await loadIndex(root);
  const nums = (Array.isArray(body.numbers) ? body.numbers : [body.number])
    .map((x) => Number(x)).filter((x) => Number.isInteger(x) && x > 0);
  if (!nums.length) throw new HttpError(400, "需要 chapter number 或 numbers");
  const perLimit = nums.length === 1 ? 12000 : Math.max(2000, Math.floor(36000 / nums.length));
  const parts = [];
  for (const n0 of nums) {
    if (!idx.find((c) => Number(c.number) === n0)) throw new HttpError(404, `第${n0}章不在正文里`);
    let t0 = "";
    try { t0 = (await readChapter(root, n0)).text; } catch { throw new HttpError(404, `第${n0}章正文文件读不到`); }
    parts.push(`=== 第 ${n0} 章正文 ===\n${t0.slice(0, perLimit)}`);
  }
  const label = nums.length === 1 ? `第 ${nums[0]} 章` : `第 ${nums[0]}-${nums[nums.length - 1]} 章（共 ${nums.length} 章，按顺序读）`;
  const text = parts.join("\n\n");
  const n = nums[nums.length - 1];
  // 每章单独从正文头部切（不按整段截，避免后几章只剩尾巴）：单章 12000 字，批量按章数摊

  const fmt = (arr, f) => (arr || []).map(f).filter(Boolean).join("\n") || "（无）";
  const existing = [
    "【已有人物（定位｜名字｜重要性｜别名｜称呼规则｜身份｜年龄｜性别｜种族｜体貌记忆点｜性格｜欲望｜恐惧｜底线｜缺陷｜秘密｜语言指纹｜能力/限制/代价｜位置｜当前目标｜知道/不知道/误以为｜登场/退场｜状态｜变更日志）】",
    fmt(bible.characters, (c) => `- ${c.rolePosition || "空"}｜${c.name}｜${c.importance || "主要"}｜${(c.aliases || []).join("、") || "空"}｜${c.callRules || "空"}｜${c.role || "空"}｜${c.age || "空"}｜${c.gender || "空"}｜${c.race || "空"}｜${c.appearance || "空"}｜${c.personality || "空"}｜${c.want || "空"}｜${c.fear || "空"}｜${c.bottomLine || "空"}｜${c.flaw || "空"}｜${c.secret || "空"}｜${c.voice || "空"}｜${[c.ability, c.abilityLimit, c.abilityCost].filter(Boolean).join("/") || "空"}｜${c.location || "空"}｜${c.currentGoal || "空"}｜${[c.knowledge, c.ignorance, c.misconception].filter(Boolean).join("/") || "空"}｜${c.firstChapter ?? "空"}/${c.exitChapter ?? "空"}｜${c.status || "空"}｜${c.changeLog || "空"}`),
    "【已有地点】", fmt(bible.locations, (l) => `- ${l.name}：${l.text || "空"}`),
    "【已有物品】", fmt(bible.items, (i) => `- ${i.name}：${i.text || "空"}`),
    "【已有势力】", fmt(bible.factions, (f) => `- ${f.name}：${f.text || "空"}`),
    "【已有硬规则】", fmt(bible.rules, (r) => `- ${r.name}：${r.text || "空"}｜${(r.keywords || []).join("、") || "无关键词"}`),
  ].join("\n");

  const system = "你是长篇小说的设定校订员。给你一章已写完的正文和现有设定，你负责两件事：① 正文里出现、设定里还没有的条目，新增进账本；② 已有条目缺的字段（显示「空」的那些），用本章正文补上。已有的值绝不改。不改编剧情，不删已有设定。" + nameStyle() + "只输出 JSON。";
  const user = [
    `下面是${label}的正文。里面可能出现了设定中尚未登记的人物、地点、物品、势力、硬规则；也可能给已有条目补上了身份、欲望、秘密、说话习惯、首次登场章等信息。`,
    nums.length > 1 ? `这几章是连续写的一段：人物在这几章里的位置、目标、知道/不知道、变更日志按「最后一章时」的状态写；登场章填第一次出现的那一章。只登记这几章里确实出现的，不要推演后文。` : "",
    "请只挑「重要且会被后文复用」的：跑过场的路人、用完即弃的一次性道具、只在本章起作用的临时物件，都不要记。已有设定里已经有的不要重复新增；人物空着的性格/欲望/秘密/口吻可以用本章正文补。",
    "硬规则只登记「世界级、跨章一直有效、破了就让人物或世界不成立」的规则。只影响这一章、某个一次性事件或临时约定的约束，不要写进 rules——那种属于细纲的 mustInclude/mustAvoid。",
    "已有条目缺的字段直接写进对应数组（同名会被插件合并，只填空着的，不会覆盖已填内容）；本章第一次出场的角色，把 firstChapter 填成本章章号。",
    "年龄、性别、种族只在正文或世界观有明确依据时填（例如「三十上下」「她是女的」「半妖」「外乡人」），拿不准就留空，不要按名字猜；新出现的别名一并记进 aliases。",
    "关系矩阵/信息差：在 characters 之外，如果这几章正文里明确了谁和谁的关系（师徒/主仆/欠人情/提防/撕破脸）或某个关键秘密的知情范围，另加 \"relations\":[{\"a\":\"\",\"b\":\"\",\"state\":\"\",\"note\":\"\"}] 与 \"infoGaps\":[{\"secret\":\"\",\"knows\":\"\",\"doesntKnow\":\"\",\"thinksKnows\":\"\"}]（已有的那一对/那个秘密只补空着的列，别重复造）。",
    "人物必须写 rolePosition（在本书的定位，如主角/女主/反派/常驻配角/单卷配角/工具人）和 importance（核心/主要/次要/龙套）：核心=主角与核心 3–5 人，主要=常驻配角，次要=单卷功能角色，龙套=只登记名字；本章新登场的路人默认龙套，有名字且会再出现的用次要。动态字段（位置/当前目标/知道/不知道/误以为/变更日志）只写本章正文能确认的，不要编。",
    "势力只补潜规则、对主角态度、他们以为主角是什么人；地点只补地图位置、进出规矩、当前占用/状态；物品只补当前持有人、状态、谁知道；规则只补判定者、可观察的代价、边界/漏洞、主角以为的版本。",
    "规则必须能被正文里的具体句子验证，并且代价要真的落地；只写本章明确发生或明确交代的，不要替作者推演新规则。",
    "严格只输出一个 JSON 对象（不要 Markdown、不要代码块）：",
    '{"characters":[{"name":"","rolePosition":"主角|女主|反派|常驻配角|单卷配角|工具人","importance":"核心|主要|次要|龙套","aliases":[],"callRules":"","role":"","age":"","gender":"","race":"","appearance":"","personality":"","want":"","fear":"","bottomLine":"","flaw":"","secret":"","voice":"","ability":"","abilityLimit":"","abilityCost":"","location":"","currentGoal":"","knowledge":"","ignorance":"","misconception":"","changeLog":"","status":"active|dead|missing|exited","firstChapter":null,"exitChapter":null}],"locations":[{"name":"","aliases":[],"spots":[],"geo":"","structure":"","senses":"","owner":"","accessRules":"","occupied":"","state":"","events":"","familiar":"","text":""}],"items":[{"name":"","aliases":[],"appearance":"","origin":"","function":"","limit":"","cost":"","type":"","holder":"","state":"","whoKnows":"","transferLog":"","text":""}],"factions":[{"name":"","aliases":[],"slang":"","nature":"","economy":"","openRules":"","hiddenRules":"","relations":"","emblem":"","representatives":"","power":"","leader":"","attitude":"","misjudge":"","changeLog":"","text":""}],"rules":[{"name":"","text":"","judge":"","cost":"","boundary":"","level":"铁律|惯例|谣言","source":"","belief":"","tested":"","exploited":"","violationLog":"","keywords":["触发关键词"],"note":""}]}',
    "没有任何新增或可补的字段就输出空数组。只输出这个 JSON 对象本身。",
    "",
    "=== 现有设定 ===",
    existing,
    "",
    "=== 正文 ===",
    text.slice(0, 40000),
  ].join("\n");

  const gen = await generateText(ctx, body, { system, user, maxTokens: 6000, purpose: "novel-setting-sync" });
  let obj = null;
  try { obj = extractJsonObject(String(gen.text || "")); } catch { obj = null; }
  if (!obj || typeof obj !== "object") {
    const m = String(gen.text || "").match(/\{[\s\S]*\}/);
    if (m) { try { obj = JSON.parse(m[0]); } catch { obj = null; } }
  }
  if (!obj) throw new HttpError(502, `模型没返回可解析的 JSON。原文片段：${String(gen.text || "").slice(0, 160)}`);

  const res = await syncSettingFromChapter(root, { entities: obj });
  res.filled = res.filled || [];
  const debut = await backfillFirstAppearances(root, idx).catch(() => []);
  for (const d of debut) res.filled.push(d);
  return { ok: true, provider: gen.provider, model: gen.model, added: res.added, filled: res.filled, relations: res.relations, view: await studioPayload(root) };
}

/**
 * 人设漂移抽样（只报不拦）：取第 N 章对话，对照本章出场人物的 voice，
 * 让 AI 逐句标出「不像」的句子。
 * report-only —— 不写回正文、不改账本、不进 continuity 判废，只返回标记清单给作者看。
 */
async function voiceDrift(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const pack = await sampleVoiceDrift(root, { chapter: body.chapter });
  const lines = pack.sample.dialogue;
  if (!lines.length) return { ok: true, chapter: pack.sample.chapter, marks: [], note: "这一章没有可抽取的对话" };
  const voiceText = pack.voices.map((v) => `- ${v.name}（${v.role}）：${v.voice}`).join("\n") || "（设定里没有 voice）";
  const dialogueText = lines.map((l, i) => `${i + 1}. ${l.who}：「${l.line}」`).join("\n");
  const system = "你是小说编辑，专门核对人物台词是否走味。给你本章出场人物的声音设定和本章逐句对话，你只标出「不符合该角色 voice」的句子。只输出 JSON，不要解释。";
  const user = [
    "【人物声音设定】", voiceText,
    "",
    "【逐句对话】", dialogueText,
    "",
    "严格只输出一个 JSON 数组，每元素：{\"index\":序号(1-based),\"who\":\"说话人\",\"issue\":\"为什么走味(简短)\",\"suggest\":\"建议改成什么口吻(简短)\"}。",
    "只列真正走味的；拿不准的不要报。都对味就输出 []。只输出数组本身。",
  ].join("\n");
  let marks = [];
  let raw = "";
  try {
    const gen = await generateText(ctx, body, { system, user, maxTokens: 1600, purpose: "novel-voice-drift" });
    raw = String(gen.text || "");
    const m = raw.match(/\[[\s\S]*\]/);
    const arr = m ? JSON.parse(m[0]) : [];
    marks = Array.isArray(arr) ? arr.map((x) => ({
      index: Number(x.index) || 0,
      who: String(x.who || ""),
      line: (lines[(Number(x.index) || 0) - 1] || {}).line || "",
      issue: String(x.issue || ""),
      suggest: String(x.suggest || ""),
    })).filter((x) => x.index > 0) : [];
  } catch (e) {
    // 模型不可用（无 key/无余额）时如实上报，不算失败
    return { ok: true, chapter: pack.sample.chapter, marks: [], note: "模型调用未成功，无法自动标记：" + (e.message || e) };
  }
  return { ok: true, chapter: pack.sample.chapter, count: lines.length, marks, note: marks.length ? `发现 ${marks.length} 处可能走味` : "逐句对照 voice，未发现明显走味" };
}

export async function generateSetup(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const project = await loadProject(root);
  const bible = await loadBible(root);
  const outlineText = (body.outlineText ?? project.outlineText ?? "").toString().trim();
  const worldText = (body.worldText ?? project.worldText ?? "").toString().trim();
  if (!outlineText && !worldText) {
    throw new HttpError(400, "还没有大纲和世界观，先去「大纲」页生成，再来补设定");
  }
  // 两个入口各管各的：人物页只补人物，设定页只补势力/地点/物品/硬规则/文风。
  const scope = body.scope === "characters" ? "characters" : "setup";
  const ACTIVE = scope === "characters"
    ? SETUP_ENTITIES.filter((e) => e.key === "characters")
    : SETUP_ENTITIES.filter((e) => e.key !== "characters");

  const fmt = (arr, f) => (arr || []).map((x) => f(x)).filter(Boolean).join("\n") || "（无）";
  // 已有条目整条给模型看（名字 + 全部已填字段），只给名字它换个说法就认不出来，会重复生成
  // 长条目只带前半段（够模型认出是谁就行），别把大纲挤出去
  const cut = (v) => { const t = Array.isArray(v) ? v.join("、") : String(v); return t.length > 160 ? t.slice(0, 160) + "…" : t; };
  const brief = (x, keys) => `- ${x.name}` + keys.filter((k) => x[k] !== undefined && x[k] !== null && x[k] !== "" && !(Array.isArray(x[k]) && !x[k].length))
    .map((k) => `｜${k}:${cut(x[k])}`).join("");
  const existingNames = {};
  for (const e of SETUP_ENTITIES) existingNames[e.key] = bible[e.key] || [];
  existingNames.style = null;

  const isChars = scope === "characters";
  const material = [
    `书名：${project.title || "未命名"}；题材：${project.genre || "未定"}；目标平台：${project.platform || "未定"}`,
    "",
    "【故事梗概】",
    String(project.synopsis || "").trim() || "（空）",
    "",
    "【大纲】",
    outlineText || "（空）",
    "",
    "【世界观】",
    worldText || "（空）",
    "",
    isChars
      ? "【已有的人物（定位｜名字｜重要性｜又叫｜称呼规则｜身份｜年龄｜性别｜种族｜体貌｜性格｜欲望｜恐惧｜底线｜缺陷｜秘密｜语言指纹｜能力｜位置/目标｜知道/不知道/误以为｜登场/退场｜状态｜变更）】"
      : "【已有的人物（只列名字与别名；这一轮不改人物）】",
    isChars
      ? fmt(bible.characters, (c) => brief(c, ["rolePosition", "importance", "aliases", "callRules", "role", "age", "gender", "race", "appearance", "personality", "want", "fear", "bottomLine", "flaw", "secret", "voice", "ability", "abilityLimit", "abilityCost", "location", "currentGoal", "knowledge", "ignorance", "misconception", "firstChapter", "exitChapter", "status", "changeLog", "text"]))
      : fmt(bible.characters, (c) => brief(c, ["aliases", "role"])),
    ...(isChars ? [] : [
      "【已有的势力】", fmt(bible.factions, (f) => brief(f, ["text", "role", "want", "secret"])),
      "【已有的地点】", fmt(bible.locations, (l) => brief(l, ["text", "role"])),
      "【已有的物品】", fmt(bible.items, (i) => brief(i, ["text"])),
      "【已有的硬规则】", fmt(bible.rules, (r) => brief(r, ["text", "note", "keywords"])),
      "【已有文风】", (bible.style && (bible.style.pov || (bible.style.samples || []).length || (bible.style.banned || []).length)) ? JSON.stringify(bible.style) : "（无）",
    ]),
    // 关系矩阵/信息差是人物补全的主要漏项：已有的一并给模型看，它才会补缺而不是重复或跳过
    ...(isChars ? [
      "【已有的关系矩阵（a对b：状态；备注）】",
      (bible.relations || []).map((r) => `- ${r.a}→${r.b}：${r.state || ""}${r.note ? `；${r.note}` : ""}`).join("\n") || "（无）",
      "【已有的信息差（秘密｜知道｜不知道｜误以为知道）】",
      (bible.infoGaps || []).map((g) => `- ${g.secret || "未命名"}｜知道：${g.knows || ""}｜不知道：${g.doesntKnow || ""}｜误以为：${g.thinksKnows || ""}`).join("\n") || "（无）",
    ] : []),
  ].join("\n");

  const system = [
    isChars
      ? "你是中文网文的人物档案员。大纲和世界观已经定了，你的工作是把里面的人物拆成能查、能对照的档案。你不改大纲，不写正文，也不碰势力/地点/物品/规则/文风。"
      : "你是中文网文的设定补全员。大纲和世界观已经定了，你的工作是把它们拆成一条条能查、能对照的设定。你不改大纲，不写正文，也不碰人物。",
    `本次只补「${isChars ? "人物" : "势力 / 地点 / 物品 / 硬规则 / 文风"}」；其余类别一律不输出。`,
    isChars
      ? "素材里出现的人名、称呼都要收进人物表；只有称呼没有名字的，用大纲里最常用的写法当 name。"
      : "分工：大纲只负责结构，世界观只负责叙事；可执行的势力、地点、物品、硬规则由你从这两份素材里拆出来并落账。素材里没有现成规则清单是正常的，不要因此不写规则。",
    nameStyle(),
    "你只能【新增】缺失的条目，绝不能推翻或重复已有的条目（同名条目会被插件直接忽略）。",
    isChars
      ? "「同名」包括别名和简称：已有条目「又叫」里的名字就是这个人的简称，再出现必须认成同一个人，写进 fill 而不是新增，例如已有「同期新人·老韩（又叫：老韩）」就别再加一条「老韩」。"
      : "「同名」包括别名和简称：同一个势力/地点/物品/规则换了说法也算已有，先对上再决定新增还是 fill。",
    "下面是插件现存的全部设定。凡是已有条目能覆盖的（同一个人、同一个势力/地点/物品/规则，换了说法也算），一律不得新增，只能把缺的字段写进 fill；只有现存设定里确实没有的才写进新增字段。",
    isChars
      ? "同一个人还包括外号、职务称呼、姓氏加排行、谐音或近似的写法（如「老韩」「韩四」「韩掌柜」都可能指同一人）：新增之前先拿这些叫法到上面的人物列表里对一遍，对上了就写进 fill，并把叫法记进该人物的 aliases。"
      : "同一个势力/地点/物品/规则换了说法、简称、别名也算已有，先对上再决定新增还是 fill。",
    isChars
      ? "每个人物都要写 rolePosition（在本书的定位：主角/女主/反派/常驻配角/单卷配角/工具人）和 importance（核心/主要/次要/龙套）。核心=主角与核心 3–5 人（全字段），主要=常驻配角（关键字段），次要=单卷功能角色（名字+功能+一个记忆点），龙套=只登记名字。别把所有角色都写成核心；缺的字段能推就推，推不出留空。"
      : "只写大纲/世界观能支撑的条目：势力盯潜规则与对主角的误判，地点盯地图与进出规矩，物品盯持有人与状态，规则盯代价与主角的认知偏差。",
    ...(isChars ? ["取名按圈层配比：市井 : 宗门 : 官场 : 异族 ≈ 4:3:2:1；每 20 个角色至少留 1 个无姓单名或纯绰号（老黄、跛脚六这类）；避免同字辈、同音和近名。"] : []),
    "",
    skillBlock("setup", { scope }),
    "",
    "只输出一个 JSON 对象，不要任何解释文字、不要 Markdown 代码围栏。",
    "",
    "输出 JSON 结构（只输出本次范围的类别）：",
    "{",
    ...(isChars ? [
      '  "characters":[{"name":"","rolePosition":"主角|女主|反派|常驻配角|单卷配角|工具人","importance":"核心|主要|次要|龙套","aliases":[],"callRules":"","role":"","age":"","gender":"","race":"","appearance":"","personality":"","want":"","fear":"","bottomLine":"","flaw":"","secret":"","voice":"","ability":"","abilityLimit":"","abilityCost":"","location":"","currentGoal":"","knowledge":"","ignorance":"","misconception":"","changeLog":"","status":"active|dead|missing|exited","firstChapter":null,"exitChapter":null}],',
      '  "fill":[{"entity":"character","name":"已有条目的名字","rolePosition":"","importance":"","aliases":[],"callRules":"","role":"","age":"","gender":"","race":"","appearance":"","personality":"","want":"","fear":"","bottomLine":"","flaw":"","secret":"","voice":"","ability":"","abilityLimit":"","abilityCost":"","location":"","currentGoal":"","knowledge":"","ignorance":"","misconception":"","changeLog":"","firstChapter":null,"status":"","exitChapter":null}],',
      '  "relations":[{"a":"","b":"","state":"","note":""}],',
      '  "infoGaps":[{"secret":"","knows":"","doesntKnow":"","thinksKnows":""}]',
    ] : [
      '  "factions":[{"name":"","aliases":[],"slang":"内部黑话","nature":"性质与层级（谁管谁）","economy":"经济来源","openRules":"明规则","hiddenRules":"潜规则","relations":"与其他势力的关系","emblem":"标志物/徽记/制服/口头禅","representatives":"代表人物：一把手/执行者/钉子","power":"当前实力：增了还是减了","leader":"掌权者有没有换人","attitude":"对主角的此刻态度","misjudge":"他们以为主角是什么人","changeLog":"第几章：发生了什么变化","text":"一句话概述"}],',
      '  "locations":[{"name":"","aliases":[],"spots":["堂门口","木牌底下"],"geo":"地理位置与相对关系（地图）","structure":"空间结构：几层/几间/进出口/死角","senses":"感官标记：气味/声音/光线/温度","owner":"归属与进出规矩","accessRules":"进出规矩","occupied":"现在被谁占着/什么时间开","state":"有没有被封/被改/被毁","events":"在这里发生过哪些戏","familiar":"谁熟悉这里/谁在这儿吃过亏","text":"一句话概述"}],',
      '  "items":[{"name":"","aliases":[],"appearance":"外观触感（重量/温度/声音）","origin":"来历：怎么到主角手上的","function":"功能","limit":"限制","cost":"使用代价","type":"伏笔型|功能型|氛围型","holder":"当前持有人","state":"完好|损坏|已交出|已销毁","whoKnows":"现在让谁知道什么","transferLog":"第几章：从谁到谁，为什么","text":"一句话概述"}],',
      '  "rules":[{"name":"","text":"用世界里的话写规则条文","judge":"判定者：谁执行/怎么知道违规","cost":"代价：违反会怎样（可观察）","boundary":"边界：什么时候不适用/漏洞在哪","level":"铁律|惯例|谣言","source":"来源（延迟揭示）","belief":"主角以为规则是什么（可能错）","tested":"已实测的规则和结果","exploited":"已利用的漏洞","violationLog":"违规记录与代价是否真的落地","keywords":["触发关键词"],"note":""}],',
      '  "style":{"pov":"","tense":"","samples":["",""],"banned":[""]},',
      '  "fill":[{"entity":"faction|location|item|rule","name":"已有条目的名字","aliases":[],"slang":"","nature":"","economy":"","openRules":"","hiddenRules":"","relations":"","emblem":"","representatives":"","power":"","leader":"","attitude":"","misjudge":"","geo":"","structure":"","senses":"","owner":"","accessRules":"","occupied":"","state":"","events":"","familiar":"","appearance":"","origin":"","function":"","limit":"","cost":"","type":"","holder":"","whoKnows":"","transferLog":"","text":"","judge":"","boundary":"","level":"","source":"","belief":"","tested":"","exploited":"","violationLog":"","keywords":[],"note":""}]',
    ]),
    "}",
    "",
    "硬性要求：",
    "1. 只写大纲/世界观能支撑的内容；推不出的字段留空字符串，不要编造。",
    ...(isChars ? [
      "2. 人物性格只写一句行为倾向（例如「遇事先算账，嘴上不饶人」），不要堆形容词；它要能指导人物在具体场景里怎么选。",
      "2b. 年龄、性别、种族只写大纲/世界观能支撑的（例如「三十上下」「女」「半妖」「外乡人」），推不出就留空，不要按名字猜；外号、简称、职务称呼记进 aliases。",
      `2c. 人物动态字段只写「当前进度（已写到第 ${Number(project.currentChapter) || 0} 章）」的状态，不许写全书走向：location 必须是这一章所在的一个具体地点（如「打铁铺门槛」），不许写全书活动范围（如「南街—城楼一线」）；currentGoal 只写这一章正在追的目标，不写几十章后才发生的事；changeLog 只写已经写完的章节里发生的事，还没有正文时留空，绝不能把大纲后面的剧情写进来；knowledge/ignorance/misconception 写截至当前章的信息差；没有依据就留空。dead 只能从大纲里已死的人写，别把活人写死。`,
      "2d. relations/infoGaps 是必交项，不是可选项：素材里写明的每一对关键人物关系都要出一条（a→b 方向按「谁对谁」，state 写关系的当前状态，如「师徒但彼此提防」「欠一条命」）；素材里写明的每个关键秘密都要出一条 infoGaps（secret 一句话说明是什么秘密，knows/doesntKnow/thinksKnows 按人物名分列）。【已有的】里已经有的那一对/那个秘密，写这条时只看要不要补 note 或补缺失的知道/不知道列，不要重复造同一对人。推不出的具体内容留空，但空关系表不合格。",
    ] : [
      "2. 每条硬规则必须能被正文里的具体句子验证，不许写「主角很强」这类。",
      "2b. 硬规则只收「世界级、跨章一直有效、破了就让人物或世界不成立」的规则；只影响某一章或一次性事件的约束不要写进 rules（它属于细纲的 mustInclude/mustAvoid）。",
      "2c. 物品只收「后面还会被提到、使用、追查」的；一次性道具、临时工具、本章用完就丢的东西不要写进 items。",
    ]),
    "3. 新条目写进正常字段；已有条目缺的字段写进 fill（按名字或别名对上、只写缺的那几项，留空的字段不写）。已有的值一律不改。",
    ...(isChars ? ["4. fill 里的登场章 firstChapter 要按大纲/世界观能推出的章号填（数字），推不出就省略。"] : []),
    `5. 全部控制在 3000 字以内，并省略所有空字段：值为空的键直接不要输出（不要写 ""、[]、null 占位）；新增条目控制在势力≤6、地点≤6、物品≤6、规则≤8、人物≤10，fill≤12 条。结构示例里的空字符串只是字段示意，不要照抄成空字段。宁可少写描述，也要先把${isChars ? "人物的身份/想要/秘密" : "势力的目标/手段/底线、规则的代价"}补齐。`,
  ].join("\n");
  const user = [
    `以下是这本书的素材与已有设定，请按系统提示补齐缺失的${isChars ? "人物" : "设定"}，只输出 JSON：`,
    "",
    "<素材>",
    material,
    "</素材>",
  ].join("\n");

  // 一次全类别输出会顶满 maxTokens：拆成两批，每批只让它写少数类别，输出自然短。
  const groups = isChars ? [["characters"]] : [["factions", "locations"], ["items", "rules", "style"]];
  const obj = { characters: [], factions: [], locations: [], items: [], rules: [], fill: [], relations: [], infoGaps: [], style: {} };
  let provider = "", model = "";
  for (const keys of groups) {
    const only = keys.filter((k) => k !== "style");
    const onlyLabel = isChars ? "characters / relations / infoGaps" : only.join(" / ");
    const g = await generateText(ctx, body, {
      system, user: user + `\n\n本次只输出 ${onlyLabel}，其它类别一律不要输出。`,
      maxTokens: 4500, purpose: "novel-setup",
    });
    provider = g.provider; model = g.model;
    const part = extractJsonObject(g.text);
    if (!part || typeof part !== "object" || Array.isArray(part)) {
      throw new HttpError(502, `模型没有返回可解析的设定 JSON。原文片段：${String(g.text || "").slice(0, 200)}`);
    }
    for (const k of only) if (Array.isArray(part[k])) obj[k].push(...part[k]);
    if (Array.isArray(part.fill)) obj.fill.push(...part.fill);
    if (Array.isArray(part.relations)) obj.relations.push(...part.relations);
    if (Array.isArray(part.infoGaps)) obj.infoGaps.push(...part.infoGaps);
    if (keys.includes("style") && part.style && typeof part.style === "object") obj.style = { ...obj.style, ...part.style };
  }

  const added = { characters: 0, factions: 0, locations: 0, items: 0, rules: 0 };
  let relationsAdded = null;
  const skipped = { characters: 0, factions: 0, locations: 0, items: 0, rules: 0 };
  const addedNames = [];
  for (const e of ACTIVE) {
    const arr = Array.isArray(obj[e.key]) ? obj[e.key] : [];
    for (const it of arr) {
      const nm = String(it && it.name || "").trim();
      if (!nm) continue;
      if (namesTaken(existingNames[e.key], nm, it.aliases)) { skipped[e.key] += 1; continue; }
      const payload = { name: nm };
      if (e.key === "characters") {
        Object.assign(payload, {
          rolePosition: it.rolePosition || "", importance: it.importance || "主要", age: it.age || "",
          role: it.role || "", gender: it.gender || "", race: it.race || "",
          callRules: it.callRules || "", appearance: it.appearance || "",
          personality: it.personality || "", want: it.want || "", fear: it.fear || "",
          bottomLine: it.bottomLine || "", flaw: it.flaw || "", secret: it.secret || "",
          voice: it.voice || "", ability: it.ability || "", abilityLimit: it.abilityLimit || "",
          abilityCost: it.abilityCost || "", location: it.location || "", currentGoal: it.currentGoal || "",
          knowledge: it.knowledge || "", ignorance: it.ignorance || "", misconception: it.misconception || "",
          changeLog: it.changeLog || "", status: it.status || "active",
          exitChapter: it.exitChapter ?? undefined, firstChapter: it.firstChapter ?? undefined,
          aliases: Array.isArray(it.aliases) ? it.aliases : undefined,
        });
      } else {
        payload.text = it.text || "";
        for (const f of ENTITY_EXTRA_FIELDS[e.key] || []) {
          if (it[f] !== undefined && it[f] !== "" && it[f] !== null) payload[f] = it[f];
        }
      }
      try {
        await bibleUpsert(root, e.entity, payload);
        existingNames[e.key] = [...existingNames[e.key], payload]; added[e.key] += 1; addedNames.push(nm);
      } catch { /* 单条失败忽略 */ }
    }
  }
  // 文风：只在缺失时写
  // 已有条目补字段：只填空着的（模型给的值不覆盖作者已填的）
  const FILL_FIELDS = [...new Set([
    "rolePosition", "importance", "role", "age", "gender", "race", "callRules", "appearance", "personality",
    "want", "fear", "bottomLine", "flaw", "secret", "voice",
    "ability", "abilityLimit", "abilityCost", "location", "currentGoal",
    "knowledge", "ignorance", "misconception", "changeLog",
    "firstChapter", "status", "exitChapter", "aliases", "text", "note",
    ...Object.values(ENTITY_EXTRA_FIELDS).flat(),
  ])];
  let filled = 0;
  for (const it of Array.isArray(obj.fill) ? obj.fill : []) {
    const key = SETUP_ENTITIES.find((e) => e.entity === String(it?.entity || "").trim())?.key;
    const nm = String(it?.name || "").trim();
    if (!key || !nm) continue;
    const cur = (bible[key] || []).find((x) => namesTaken([x], nm, it.aliases));
    if (!cur) continue;
    const patch = { name: cur.name };
    for (const f of FILL_FIELDS) {
      const v = it[f];
      const empty = cur[f] === undefined || cur[f] === null || cur[f] === "" || (Array.isArray(cur[f]) && !cur[f].length);
      const has = v !== undefined && v !== null && v !== "" && !(Array.isArray(v) && !v.length);
      if (empty && has) patch[f] = v;
    }
    if (Object.keys(patch).length > 1) {
      try { await bibleUpsert(root, SETUP_ENTITIES.find((e) => e.key === key).entity, patch); filled += 1; } catch { /* 单条失败忽略 */ }
    }
  }
  if (scope === "characters") {
    // 重新读盘：上面新增/补字段已经落盘，用开头那份旧 bible 保存会把刚补的字段冲掉
    const book = await loadBible(root);
    const str = (v) => String(v ?? "").trim();
    const relAdded = [];
    const gapAdded = [];
    const relCount = (book.relations || []).length;
    const gapCount = (book.infoGaps || []).length;
    if (Array.isArray(obj.relations)) {
      const old = new Map((book.relations || []).map((r) => [`${str(r.a)}→${str(r.b)}`, r]));
      for (const it of obj.relations) {
        const row = { a: str(it?.a), b: str(it?.b), state: str(it?.state), note: str(it?.note) };
        if (!row.a || !row.b || row.a === row.b || (!row.state && !row.note)) continue;
        const k = `${row.a}→${row.b}`;
        const cur = old.get(k);
        // 已有这一对：只补空着的列（作者手填的不改）
        if (cur) {
          if (!str(cur.state) && row.state) cur.state = row.state;
          if (!str(cur.note) && row.note) cur.note = row.note;
          continue;
        }
        old.set(k, row); relAdded.push(k);
      }
      book.relations = [...old.values()].filter((r) => r.a || r.b);
    }
    if (Array.isArray(obj.infoGaps)) {
      const old = new Map((book.infoGaps || []).map((g) => [str(g.secret), g]));
      for (const it of obj.infoGaps) {
        const row = { secret: str(it?.secret), knows: str(it?.knows), doesntKnow: str(it?.doesntKnow), thinksKnows: str(it?.thinksKnows) };
        if (!row.secret) continue;
        const cur = old.get(row.secret);
        if (cur) {
          for (const f of ["knows", "doesntKnow", "thinksKnows"]) if (!str(cur[f]) && row[f]) cur[f] = row[f];
          continue;
        }
        old.set(row.secret, row); gapAdded.push(row.secret);
      }
      book.infoGaps = [...old.values()].filter((g) => g.secret || g.knows || g.doesntKnow || g.thinksKnows);
    }
    relationsAdded = { relations: relAdded.length, infoGaps: gapAdded.length, totalRelations: (book.relations || []).length, totalInfoGaps: (book.infoGaps || []).length };
    if (!relAdded.length && !gapAdded.length) relationsAdded.note = `关系矩阵/信息差没有新增（原有 ${relCount} 对关系、${gapCount} 条信息差；模型这次没给出新的）。`;
    await saveBible(root, book);
  }
  let styleWritten = false;
  // 第 1 章写完后文风锁死，AI 补全也不能回头改
  if (scope === "setup" && obj.style && typeof obj.style === "object" && (Number(project.currentChapter) || 0) < 1) {
    const cur = bible.style || {};
    const patch = {};
    if (!cur.pov && obj.style.pov) patch.pov = obj.style.pov;
    if (!cur.tense && obj.style.tense) patch.tense = obj.style.tense;
    if ((!(cur.samples || []).length) && Array.isArray(obj.style.samples) && obj.style.samples.length) patch.samples = obj.style.samples;
    if ((!(cur.banned || []).length) && Array.isArray(obj.style.banned) && obj.style.banned.length) patch.banned = obj.style.banned;
    if (Object.keys(patch).length) {
      try { await bibleUpsert(root, "style", patch); styleWritten = true; await writeStyleFile(root).catch(() => false); } catch { /* ignore */ }
    }
  }

  const totalAdded = Object.values(added).reduce((a, b) => a + b, 0);
  const totalSkipped = Object.values(skipped).reduce((a, b) => a + b, 0);
  return {
    ok: true, provider, model, added, skipped, styleWritten, addedNames, filled, relations: relationsAdded,
    summary: `新增 ${totalAdded} 条设定（人物${added.characters}/势力${added.factions}/地点${added.locations}/物品${added.items}/规则${added.rules}）` +
      (totalSkipped ? `；已有同名跳过 ${totalSkipped} 条` : "") + (filled ? `；给 ${filled} 个已有条目补了空着的字段` : "") + (styleWritten ? "；补了文风" : "") +
      (relationsAdded ? `；关系矩阵 +${relationsAdded.relations} 对（共 ${relationsAdded.totalRelations}）、信息差 +${relationsAdded.infoGaps} 条（共 ${relationsAdded.totalInfoGaps}）` : ""),
    view: await studioPayload(root),
  };
}

// ---- 大纲生成：依故事梗概 + 章节规模，直接产出「大纲正文 + 世界观」，写进项目 ----
async function generateOutline(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const project = await loadProject(root);
  const chars = Number(body.targetChapters || project.targetChapters || 100);
  const wpc = Number(project.wordsPerChapter) || 0;
  const synopsis = (body.synopsis ?? project.synopsis ?? "").toString().trim();
  if (!synopsis) throw new HttpError(400, "还没有故事梗概，先回「概览」页写一段梗概再来生成大纲");

  // 素材：大纲只依「故事梗概 + 规模」生成——不读已有的人物/世界观/硬规则（那些是后面阶段的产物）
  const material = [
    `书名：${project.title || "未命名"}`,
    `题材：${project.genre || "未定"}`,
    `目标平台：${project.platform || "未定"}`,
    `规模：约 ${chars} 章${wpc ? `，每章约 ${wpc} 字，全书约 ${Math.round((chars * wpc) / 10000)} 万字` : ""}`,
    `故事梗概：${synopsis}`,
  ].filter(Boolean).join("\n");

  const planVols = Math.max(2, Math.round(chars / 50));
  const perVol = Math.round(chars / planVols);
  // 卷长按剧情走，不按平均劈：只给量级参考，单卷允许 10 章到整本的 1/3
  const volMin = Math.max(10, Math.round(perVol * 0.4));
  const volMax = Math.max(volMin + 10, Math.round(chars / 3));
  const system = [
    "你是一名擅长中文网文结构设计的策划，负责把素材整理成可执行的写作大纲。你不写正文。",
    "",
    skillBlock("outline"),
    nameStyle(),
    "",
    "# 任务",
    "从素材里提炼出一本小说的两层大纲：全书层 + 卷层。素材没写的要补全，但推断出来的内容集中写在「素材研判」里说明，不要在正文到处标「补 / 原」。",
    "",
    "# 硬性要求",
    "1. 每个节拍必须是可观察的事件：写清谁对谁做了什么、谁失去或得到了什么。禁止「他意识到局势不妙」「气氛紧张起来」这类心理活动或总结。",
    "2. 前 3 章固定三拍，且是同一条冲突线加深：第1章触发（主角被卷入）→ 第2章加码（代价具体成可量化损失：钱、亲人、资格）→ 第3章反制有结果但引出更大反噬。三章钩子分别用信息钩 / 危机钩 / 反差钩，不许都用「就在这时，一道声音传来」。",
    "3. 钩子四类（信息 / 危机 / 悬念 / 反差）每 10 章轮换一轮，同类不连续超过 2 章。",
    "4. 素材没提的设定可以补，但不得与素材冲突；冲突时保留素材，把调整写进「素材研判」。",
    "5. 不写正文、不写对话样例、不写景物描写。",
    "6. 不确定的地方用「待定：」标出，并给一个推荐的默认答案。",
    "7. 只分「全书层」和「卷层」两层，不要再加「部 / 篇」这一层。",
    "8. 篇幅纪律：全书层每项不超过 2 行，表格一行一条，卷层每卷不超过 5 行；不展开场景。",
    "9. 章号区间（第a-b章）只允许出现在「卷层」的卷头行，以及全书层的支线表、对手阶梯表里；其他任何地方都不要写区间，否则进度页分卷会识别错位。",
    "10. 大纲只写结构：不要输出硬规则清单、人物卡、势力表或世界观条目；这些由「设定」页统一生成，写进大纲会和设定页打架。",
    "",
    ...(body.tone === "contrast" || project.tone === "contrast" ? [
      "# 反差虐点（作者要的是「意难平」，这次必须落进结构）",
      "- 全书层的「主角的欲望、恐惧、致命缺陷」之后，加一张表：| 角色 | 他最想要/最骄傲的（一句话） | 被什么逼到反面 | 结算章 |。至少 4 行，主角必须在表里。",
      "- 每个核心角色一条「反命题」：结局是他的核心特质被拧到相反面（最强的败于无能为力、最会算的败于算漏、最骄傲的跪求、最自私的为别人牺牲、最被呵护的先凋零、最求团圆的长年孤身）。一人一条，不许重复同一种刀。",
      "- 卷层每卷的「卷内节拍」里，至少一拍要写清「这一卷具体拿走了谁的什么」——写损失，不写「气氛沉重」「他意识到」。",
      "- 全书至少三处用具体画面结算（台词 / 一个物件 / 一个动作），不靠旁白说「他很难过」。例如「我比你们都大了」这种一句台词承载全书分量的写法。",
      "- 结局留一口气：最后一个核心角色半死不活或求而不得，读者憋着，才叫意难平。不许全员圆满收尾。",
      "- 自检里加一条：反命题表每行都写了自己失去的东西和真的失去它的章号。",
      "",
    ] : []),
    "# 全书规模（硬约束）",
    `- 这本书的书目规模是 ${chars} 章，这是建项目时就定死的，不能缩成短篇。大纲必须完整覆盖第 1 章到第 ${chars} 章，结局落在第 ${chars} 章附近。`,
    `- 卷数按内容定：每卷 = 一个完整的矛盾阶段（目标 → 升级 → 卷末不可逆变化），阶段走完就换卷，不要为了凑 ${planVols} 卷把一段硬劈成两卷、也不要塞进不相关的支线撑长度；${chars} 章大约 ${planVols} 卷只是个量级参考，实际可以是 ${Math.max(2, planVols - 2)}–${planVols + 3} 卷。`,
    `- 卷长也按内容定：短卷可以只有十几章（单一目标、单线推进），长卷可以是主线大阶段带几条支线；单卷一般落在 ${volMin}–${volMax} 章，超过这个范围要能说出这一卷为什么必须这么长（例如要铺一条贯穿全卷的支线，或要跨地图换场）。卷长起伏要有理由，不许机械地每卷都一样长。`,
    `- 卷层每卷的章数区间必须首尾相接、不重叠不断档，合起来正好覆盖 1-${chars} 章。`,
    `- 这么大的体量不能只靠一条主线撑：主线之外至少 2 条支线，每条支线必须写死「发起卷 / 交汇章 / 收束章 / 给主线提供了什么（信息·资源·敌人·代价，至少一项）」。给不出这四样的支线直接删掉。`,
    "- 对手要按阶梯升级：每 1-2 章小摩擦、每 3-5 章中等冲突、每 8-12 章大高潮；同时对手层级必须随卷上升，不能第 200 章还在打第 20 章同量级的对手。",
    "- 每次大跨度换地图，必须带一个旧地图的角色随行，或留一笔旧地图的未了债务；不许裸换地图。",
    "",
    "# 输出格式（严格按此结构，纯 Markdown，不要输出 JSON、不要加代码围栏）",
    "## 0. 素材研判",
    "- 能确定的核心：5 条以内（世界观 / 金手指或核心规则 / 主角起点 / 核心矛盾 / 终局方向）",
    "- 素材里的矛盾或空白：列出，并说明你打算怎么处理",
    "",
    "## 1. 全书层",
    "- 一句话故事核：谁 + 想要什么 + 被什么挡住 + 代价",
    "- 主角的欲望、恐惧、致命缺陷",
    "- 主线六节点：起点 → 第一次转折 → 中点大转折 → 虚假胜利 → 最低谷 → 结局。其中「虚假胜利」= 主角用错误的方式拿到了想要的东西，代价到全书约 75% 处才结算。",
    "- 结局必须回答的问题（读者合上书要得到的答案）",
    "- 主题：一句话，且必须能在高潮处被「事件」而不是「议论」证明",
    "- 支线表：| 支线 | 发起卷 | 交汇章 | 收束章 | 给主线提供 |",
    "- 对手阶梯表：| 章段 | 对手层级 | 与主角的差距 | 主角若输要付的代价 |",
    "- 爽点模式白名单：列 6-8 种本书允许的打脸/逆袭手法（如借势压人、信息差反杀、规则漏洞、扮猪吃虎、资源碾压、以彼之道），并注明轮换使用、不连续重复。",
    "",
    "## 2. 卷层",
    `- 每卷必须以这一行开头，格式一字不差：### 第N卷 卷名（第a-b章）。用阿拉伯数字，a-b 用半角连字符，卷名不超过 8 个字。`,
    `- 每卷下面固定 4 行，共 5 行以内：`,
    "  1. 任务与矛盾：这一卷要完成什么，主要阻力是谁/什么",
    "  2. 卷内节拍：3-5 拍，每拍写「谁做了什么 → 谁失去/得到什么」，不写心理活动和场景",
    "  3. 卷末钩子：类型（信息/危机/悬念/反差）+ 钩住的是什么问题",
    "  4. 卷末快照：主角实力刻度｜资源或势力净增｜当前最高层级敌人｜已埋未收的伏笔（写名字，不写编号）",
    "- 全部卷合起来覆盖 1-" + chars + " 章；最后一卷必须写到结局。",
    "",
    "# 自检（输出前逐条核对）",
    "- [ ] 六节点齐全，且「虚假胜利」写清了代价在什么时候结算",
    "- [ ] 每条支线四个字段齐全，交汇章落在某一卷的区间内",
    "- [ ] 对手阶梯表覆盖全书，层级逐段上升",
    "- [ ] 每卷都有卷末快照四项，能看出主角在这一卷净变化了什么",
    "- [ ] 每个节拍都有可观察的得失，没有「他意识到 / 气氛紧张」",
    `- [ ] 卷头严格是「### 第N卷 卷名（第a-b章）」，区间连续覆盖 1-${chars} 章，无部/篇、无重叠、无断档`,
    "- [ ] 章号区间只出现在卷头和全书层的两张表里，其他小节没有区间",
  ].join("\n");

  const user = [
    "以下是全部素材，可能很零碎、互相矛盾，也可能只有一两句话：",
    "",
    "<素材>",
    material,
    "</素材>",
    "",
    `请按系统提示里的输出格式与硬性要求，输出这本小说的两层大纲（全书层 + 卷层，不要「部」）。特别提醒：全书共 ${chars} 章${wpc ? `、每章约 ${wpc} 字` : ""}，卷数和卷长都按剧情阶段定（${planVols} 卷只是量级参考，长短卷可以差很多）；每卷卷头必须是「### 第N卷 卷名（第a-b章）」这种格式，卷层章数区间必须一路铺到第 ${chars} 章结束。`,
  ].join("\n");

  const { text, provider, model } = await generateText(ctx, body, { system, user, maxTokens: 8000, purpose: "novel-outline" });
  let outlineText = String(text || "").trim();
  // 去掉模型可能加的 ``` 围栏
  const fence = outlineText.match(/^```[a-zA-Z]*\s*([\s\S]*?)```\s*$/);
  if (fence) outlineText = fence[1].trim();
  if (!outlineText) throw new HttpError(502, "模型没有返回大纲内容。");
  // 至少要有「全书层」的痕迹，否则视为失败（避免把一句道歉存成大纲）
  if (!/全书层|一句话故事核|素材研判/.test(outlineText)) {
    throw new HttpError(502, `模型返回的内容不像大纲，未保存。原文片段：${outlineText.slice(0, 200)}`);
  }
  // 规模核对：大纲里出现过的最大章号明显没铺到全书规模，说明模型按短篇写完了。
  // 不拦（拦了作者就没大纲可用），但把问题直接告诉作者，让他点「换一版」。
  const nums = [...outlineText.matchAll(/第\s*(\d{1,5})\s*章/g)].map((m) => Number(m[1]));
  const maxSeen = nums.length ? Math.max(...nums) : 0;
  const scaleWarning = chars >= 20 && maxSeen && maxSeen < chars * 0.6
    ? `大纲只铺到第 ${maxSeen} 章，离你定的 ${chars} 章差得远（后半本没有大纲）。点「换一版」重新生成，或在下面手动补卷。`
    : "";

  project.outlineText = outlineText;
  if (body.tone === "contrast") project.tone = "contrast";
  // 「换一版」不带 tone 时沿用上次的选择，否则反差要求会悄悄丢
  await saveProject(root, project);
  return { ok: true, provider, model, outlineText, targetChapters: chars, maxChapterSeen: maxSeen, warning: scaleWarning, view: await studioPayload(root) };
}

// ---- 世界观生成：素材 = 已生成的大纲，输出叙事性 Markdown（不列规则/人物卡），存 project.worldText ----
async function generateWorld(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const project = await loadProject(root);
  const bible = await loadBible(root);
  const outlineText = (body.outlineText ?? project.outlineText ?? "").toString().trim();
  if (!outlineText) throw new HttpError(400, "还没有大纲，先在大纲页生成/写好大纲，再来生成世界观");

  const charsList = (bible.characters || []).map((c) => {
    const bits = [c.role || ""].filter(Boolean);
    if (c.want) bits.push(`想要：${String(c.want).trim().slice(0, 40)}`);
    if (c.ability) bits.push(`能力：${String(c.ability).trim().slice(0, 40)}`);
    if (c.secret) bits.push(`秘密：${String(c.secret).trim().slice(0, 40)}`);
    return `${c.name || ""}（${bits.join("｜") || "关键人物"}）`;
  }).join("、");
  const target = Number(project.targetChapters) || 0;
  const synopsis = String(body.synopsis ?? project.synopsis ?? "").trim();
  // 「重新生成」是覆盖重写，但必须让模型看到上一版世界观，才能沿用专名地名、只补不改
  const oldWorldText = String(body.oldWorldText ?? project.worldText ?? "").trim();
  const material = [
    `书名：${project.title || "未命名"}；题材：${project.genre || "未定"}；目标平台：${project.platform || "未定"}`,
    target ? `规模：约 ${target} 章` : "",
    charsList ? `已有的人物（可沿用或调整）：${charsList}` : "",
    synopsis ? `【故事梗概】\n${synopsis}` : "",
    "",
    oldWorldText ? `【已有世界观（尽量沿用其中的专名、地名、势力名与已成立的设定，只补深、只精修，不要整份推翻重写）】\n${oldWorldText}` : "",
    "",
    "【大纲】",
    outlineText,
  ].filter(Boolean).join("\n");

  // 按题材给「这一节该加厚什么」的侧重提示（不是换结构，只是轻重不同）
  const gw = `${project.genre || ""} ${synopsis}`;
  const genreHint = /末世|废土|丧尸|求生/.test(gw)
    ? "末世/废土：第 4 节重点写「资源从哪来、据点怎么守、感染或灾变的规则」，把货币/物资/通行写具体。"
    : /悬疑|推理|刑侦|法医|探案|破案/.test(gw)
    ? "悬疑/刑侦：第 4 节重点写「信息差怎么形成、证据链靠什么运转、谁有权限查什么」，世界观要给推理留出可操作的线索土壤。"
    : /仙侠|修真|玄幻|灵气|宗门|丹药/.test(gw)
    ? "仙侠/玄幻：第 4 节重点写「修炼/资源体系怎么升、瓶颈在哪、越级要付什么代价」，宗门/秘境/天材地宝的分配逻辑要自洽。"
    : /宫斗|权谋|历史|朝堂|争霸/.test(gw)
    ? "历史/权谋：第 4 节重点写「权力怎么继承与制衡、情报与财政从哪来、礼法能管到哪一步」，恩怨落到具体的联姻/血债/盟约。"
    : /科幻|星际|赛博|未来|机械/.test(gw)
    ? "科幻/星际：第 4 节重点写「技术红线、能源与算力从谁手里出、不同文明/阶层的信息落差」，硬设定要能前后自洽。"
    : /都市|异能|职场|商战|校园|现实/.test(gw)
    ? "都市/现实：第 4 节重点写「钱权怎么流动、规则漏洞在哪、普通人靠什么往上爬」，把行业/圈层的潜规则写实。"
    : "通用：按题材把第 4 节的「体系如何运作」写具体，别停在概念。";

  const system = [
    "你是中文网文的世界观叙事作者。你只写「世界是什么样、为什么是这样、人怎么在里面活」，不列设定条目。",
    "",
    skillBlock("world"),
    "",
    "# 任务",
    "以大纲为骨架，写一份叙事性的世界观：世界基底、历史、地理、体系如何运作、势力恩怨、日常氛围、自洽检查。",
    "若素材里带了【已有世界观】，就以它为蓝本：沿用其中已成立的专名、地名、势力名，只补深、只精修，不要整份推翻重写。",
    "",
    "# 按题材取重点",
    genreHint,
    "",
    "# 边界（重要）",
    "- 不输出硬规则清单、人物卡、势力字段表、物品清单、文风参数。这些由「设定」页的 AI 补全统一从大纲 + 世界观里拆出来落账。",
    "- 但叙事里必须把将来能拆成规则的东西讲清楚：什么能做、什么不能做、代价是什么、谁知道什么。",
    "- 不写情节、不写对话、不写章节；不替角色做决定。",
    "- 素材里已有的信息不得推翻；冲突时选最有利于后续剧情的一种写法。",
    "- 不用「补 / 原」标记，推断出来的内容在行文里自然交代。",
    "- 说人话、写具体：每个说法尽量落到可被验证的东西上（一个数字、一个专名、一句当地人会说的话），不写「繁华 / 诡异 / 复杂」这类空词。",
    "- 全文控制在 2200 字以内，信息密度优先于形容词。",
    "",
    "# 输出格式（严格按此结构，纯 Markdown，不要加代码围栏）",
    "## 1. 世界基底",
    "- 世界是什么形态：时代或地貌、秩序由谁维持、普通人靠什么活着",
    "- 三条不可动摇的底层逻辑（物理、社会或超自然层面的）",
    "- 这套逻辑的代价：使用它要付出什么，或者谁来收这个代价",
    "- 世界当前的裂缝：一个正在恶化的矛盾，主角会被卷进去",
    "",
    "## 2. 历史与时间线",
    "- 三个改变格局的旧事，每条写「当时发生了什么 → 留下什么」，至少一条带具体年份或纪年",
    "- 一件所有人都记错或不愿提的旧事",
    "",
    "## 3. 地理与空间",
    "- 主角活动区域的相对位置：从 A 到 B 怎么走、要多久（给具体天数或路程）",
    "- 一处核心地带和一处边缘地带，各自谁在管、谁能进",
    "",
    "## 4. 体系如何运作（没有超自然体系，就写资源/权力怎么分配）",
    "- 普通人怎么获得、怎么失去、越界时会发生什么（用叙事句子写，不列规则表）",
    "- 这套体系的上限、代价和已知漏洞，用「有人试过……」的方式讲出来",
    "- 至少给一个具体的量（价格 / 等级 / 时长 / 配额），让读者能感知尺度",
    "",
    "## 5. 势力与恩怨",
    "3–6 个势力：每个写清互相欠着什么、怕什么、现在在争什么；至少两对之间有具体旧账——写成「谁欠谁一条命 / 一笔钱 / 一个承诺」，不许只写「关系复杂」。",
    "",
    "## 6. 日常与氛围",
    "- 普通人一天怎么过：钱、时间、称呼、禁忌（写出货币叫什么、一顿饭多少钱、怎么称呼长辈这类可被验证的细节）",
    "- 三个只有这个世界才有的生活细节（声音、气味、习惯），每个都要能落到具体场景",
    "",
    "## 7. 自洽检查",
    "逐条回答：",
    "- 主角为什么现在才行动，之前为什么不动？",
    "- 反派为什么不在第 1 章就杀掉主角？",
    "- 这套体系为什么没有让普通人全部被淘汰？",
    "- 如果读者问「为什么不用 X 一下子解决」，X 是什么，为什么不行？",
    "- 设定了但暂时没用的东西有哪些？",
    "",
    "# 机器块（正文之后附加，供插件落账，不要写进上面正文）",
    "在纯 Markdown 正文写完后，另起一段，用如下结构输出一个 JSON（供把「自洽检查里的未解钩子」和「可拆成规则的三联」存进设定账本）：",
    "<<<WORLD_JSON",
    "{",
    "  \"openThreads\": [\"设定了但暂时没用的钩子/悬念（每条一句）\"],",
    "  \"worldRules\": [{ \"can\": \"能做什么\", \"cannot\": \"不能做什么\", \"cost\": \"代价是什么\" }]",
    "}",
    "WORLD_JSON>>>",
    "只有这两类；不要塞人物卡、势力字段、正文。",
    "",
    "# 自检",
    "- [ ] 没有出现「第 X 条规则」「人物卡」这类账本式清单（除末尾机器块外）",
    "- [ ] 每段体系描述都能在后文被拆成可检查的规则（能做/不能做/代价）",
    "- [ ] 势力之间有具体旧账（欠命/欠钱/欠承诺），不只是「关系复杂」",
    "- [ ] 自洽五问都有具体答案，不是「因为剧情需要」",
    "- [ ] 末尾附了合法的 <<<WORLD_JSON ... WORLD_JSON>>> 机器块",
  ].join("\n");

  const user = [
    "以下是全部素材（包含这本书已生成的大纲，可能还有上一版世界观），可能很零碎、互相矛盾：",
    "",
    "<素材>",
    material,
    "</素材>",
    "",
    "请按系统提示里的输出格式写这本书的叙事性世界观（世界基底/历史/地理/体系/势力恩怨/日常/自洽检查），并在正文后附上 <<<WORLD_JSON>>> 机器块。",
    "不要列硬规则清单、人物卡或势力字段表——这些稍后会由「设定」页的 AI 补全从这份世界观和大纲里拆出来落账。",
  ].join("\n");

  const { text, provider, model } = await generateText(ctx, body, { system, user, maxTokens: 6000, purpose: "novel-world" });
  let worldText = String(text || "").trim();
  const fence = worldText.match(/^```[a-zA-Z]*\s*([\s\S]*?)```\s*$/);
  if (fence) worldText = fence[1].trim();
  if (!worldText) throw new HttpError(502, "模型没有返回设定内容。");
  if (!/世界基底|地理|势力|自洽/.test(worldText)) {
    throw new HttpError(502, `模型返回的内容不像设定，未保存。原文片段：${worldText.slice(0, 200)}`);
  }
  // 若带机器块，拆出结构化设定写进 bible（硬规则/人物卡/势力/地点/世界）
  let worldObj = null;
  const wm = worldText.match(/<<<WORLD_JSON([\s\S]*?)WORLD_JSON>>>/);
  if (wm) {
    worldText = (worldText.slice(0, wm.index).trim() + "\n" + worldText.slice(wm.index + wm[0].length).trim()).trim();
    try { worldObj = extractJsonObject(wm[1]); } catch { worldObj = null; }
  }
  project.worldText = worldText;
  // 把机器块里的「自洽检查未解钩子」落成项目字段，供后续章节/伏笔引用（不塞进正文）
  if (worldObj && Array.isArray(worldObj.openThreads)) {
    project.openThreads = worldObj.openThreads.map((s) => String(s || "").trim()).filter(Boolean).slice(0, 20);
  }
  await saveProject(root, project);

  // 把结构化设定写入 bible（去重同名，已有则不覆盖正文，只补空）
  let bibleWritten = { world: 0, factions: 0, locations: 0, rules: 0, characters: 0 };
  if (worldObj && typeof worldObj === "object") {
    // 新机器块的 worldRules [{can,cannot,cost}] → 转成硬规则条目（能做/不能做/代价 合成一句）
    if (Array.isArray(worldObj.worldRules)) {
      const curRules = (await loadBible(root)).rules || [];
      for (const it of worldObj.worldRules.slice(0, 12)) {
        const can = String(it && it.can || "").trim();
        const cannot = String(it && it.cannot || "").trim();
        const cost = String(it && it.cost || "").trim();
        if (!can && !cannot) continue;
        const name = (can || cannot).slice(0, 24);
        const text = [can ? `能：${can}` : "", cannot ? `不能：${cannot}` : "", cost ? `代价：${cost}` : ""].filter(Boolean).join("；");
        if (!name || namesTaken(curRules, name)) continue;
        try { await bibleUpsert(root, "rule", { name, text }); curRules.push({ name }); bibleWritten.rules += 1; } catch { /* ignore */ }
      }
    }
    const entMap = { world: "world", factions: "faction", locations: "location", rules: "rule", characters: "character" };
    const cur = await loadBible(root);
    const existing = {};
    for (const [k] of Object.entries(entMap)) existing[k] = cur[k] || [];
    for (const [k, ent] of Object.entries(entMap)) {
      const arr = Array.isArray(worldObj[k]) ? worldObj[k] : [];
      for (const it of arr) {
        const nm = String(it && it.name || "").trim();
        if (!nm || namesTaken(existing[k], nm, it.aliases)) continue;
        try {
          const payload = { name: nm, text: it.text || "" };
          if (k === "characters") {
            Object.assign(payload, {
              rolePosition: it.rolePosition || "", importance: it.importance || "主要", age: it.age || "",
              role: it.role || "", gender: it.gender || "", race: it.race || "",
              callRules: it.callRules || "", appearance: it.appearance || "",
              personality: it.personality || "", want: it.want || "", fear: it.fear || "",
              bottomLine: it.bottomLine || "", flaw: it.flaw || "", secret: it.secret || "",
              voice: it.voice || "", ability: it.ability || "", abilityLimit: it.abilityLimit || "",
              abilityCost: it.abilityCost || "",
              aliases: Array.isArray(it.aliases) ? it.aliases : undefined,
            });
          } else if (it.role || it.want || it.secret) {
            Object.assign(payload, { role: it.role || "", want: it.want || "", secret: it.secret || "" });
          }
          await bibleUpsert(root, ent, payload);
          existing[k] = [...existing[k], { name: nm }];
          bibleWritten[k] += 1;
        } catch { /* 门控拒绝等，忽略单条 */ }
      }
    }
  }
  return { ok: true, provider, model, worldText, openThreads: project.openThreads || [], bibleWritten, view: await studioPayload(root) };
}

// ---- 伏笔设计：依大纲 + 世界观，直接产出伏笔并记进账本 ----
/** 把模型输出里能救回来的伏笔对象都捞出来（数组、foreshadows 包装、被截断的逐条对象）。 */
function parseForeshadowEntries(text) {
  const out = [];
  const push = (v) => { if (v && typeof v === "object" && !Array.isArray(v) && (v.name || v.title)) out.push(v); };
  try { const a = extractJsonArray(text); if (Array.isArray(a)) a.forEach(push); } catch { /* ignore */ }
  if (!out.length) {
    try {
      const o = extractJsonObject(text);
      const a = Array.isArray(o) ? o : (Array.isArray(o?.foreshadows) ? o.foreshadows : (Array.isArray(o?.items) ? o.items : []));
      a.forEach(push);
    } catch { /* ignore */ }
  }
  if (!out.length) {
    // 逐字符找配平的 {...}：截断时前面的完整条目仍能捞回来，字符串里的花括号不算
    for (let i = 0; i < text.length; i++) {
      if (text[i] !== "{") continue;
      let depth = 0, inStr = false, esc = false;
      for (let j = i; j < text.length; j++) {
        const c = text[j];
        if (inStr) {
          if (esc) esc = false;
          else if (c === "\\") esc = true;
          else if (c === '"') inStr = false;
          continue;
        }
        if (c === '"') inStr = true;
        else if (c === "{") depth++;
        else if (c === "}") {
          depth--;
          if (!depth) {
            try { push(JSON.parse(text.slice(i, j + 1))); } catch { /* 半截对象跳过 */ }
            i = j;
            break;
          }
        }
      }
    }
  }
  return out;
}

/** 紧凑行格式：名称|层次|来源|埋设章|埋在哪拍|回收章|谁来揭|改变了什么|中途提示|怎么放弃 */
function parseForeshadowLines(text) {
  const KIND = { 主线: "main", 卷内: "volume", 卷线: "volume", 细节: "detail", main: "main", volume: "volume", detail: "detail" };
  const out = [];
  for (const raw of String(text || "").split(/\r?\n/)) {
    const line = raw.trim().replace(/^[-*\d.、)\s]+/u, "");
    if (!line || line.includes("|") === false) continue;
    const parts = line.split("|").map((s) => s.trim());
    if (parts.length < 6) continue;
    if (/^名称$|^伏笔$/u.test(parts[0])) continue;
    const name = parts[0].replace(/^["「『]|["」』]$/gu, "");
    if (!name) continue;
    out.push({
      name,
      kind: KIND[parts[1]] || "detail",
      source: parts[2] || "",
      plantChapter: parts[3] || "",
      plantBeat: parts[4] || "",
      dueChapter: parts[5] || "",
      revealWho: parts[6] || "",
      revealChange: parts[7] || "",
      hint: parts[8] || "",
      abandon: parts[9] || "",
    });
  }
  return out;
}

/**
 * 伏笔生成按轮调用：一次点击把全书该有的条数补全。
 * 每轮单独解析、去重，没写够就带着已写名单继续要，最多 8 轮。
 */
async function collectForeshadows(ctx, body, system, user, want) {
  const llm = resolveLlm(ctx);
  if (!llm) throw new HttpError(503, "当前环境没有可用的模型服务");
  const def = defaultSelection(ctx);
  const provider = (body.provider || def?.provider || "").toString().trim();
  const model = (body.model || def?.model || "").toString().trim();
  if (!provider || !model) throw new HttpError(409, "没有可用的默认模型，请先在面板里选一个模型");
  const entries = [];
  const seen = new Set();
  let text = "";
  let lastFinish = null;
  for (let round = 0; round < 8; round++) {
    if (entries.length >= want) break;
    const got = entries.map((e) => String(e.name || e.title || "")).filter(Boolean);
    const ask = round
      ? `${user}\n\n（已经写出的 ${got.length} 条：${got.join("、") || "无"}。还差 ${want - got.length} 条；这次别重复它们，接着往下写，不要重头再来。）`
      : user;
    let out = "";
    try {
      for await (const chunk of llm.stream({
        provider, model,
        messages: [
          { role: "system", content: [{ type: "text", text: system }] },
          { role: "user", content: [{ type: "text", text: ask }] },
        ],
        maxTokens: 8000, purpose: "novel-foreshadow",
      })) {
        if (!chunk) continue;
        if (chunk.type === "finish") { lastFinish = chunk.reason; break; }
        if (chunk.type === "text-delta" && typeof chunk.text === "string") out += chunk.text;
      }
    } catch (e) {
      throw new HttpError(502, `模型调用失败：${e?.message || String(e)}`);
    }
    if (lastFinish && lastFinish.kind === "error") throw new HttpError(502, `模型调用失败：${lastFinish.failure?.message || "模型返回了错误"}`);
    const add = out.trim();
    if (!add) break;
    text += `${text ? "\n" : ""}${add}`;
    const added = entries.length;
    let gotNew = [];
    try { gotNew = [...parseForeshadowEntries(add), ...parseForeshadowLines(add)]; } catch { /* 下一轮再补 */ }
    for (const e of gotNew) {
      const nm = String(e?.name || e?.title || "").trim();
      if (!nm || seen.has(nm)) continue;
      seen.add(nm);
      entries.push(e);
    }
    // 这一轮一条新的都没捞到就停：再问也是重复
    if (entries.length === added && round > 0) break;
  }
  if (!text.trim()) throw new HttpError(502, "模型没有返回任何伏笔内容（可能是额度/限流，换一个模型再试）");
  return { entries, text, provider, model };
}

async function generateForeshadow(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const project = await loadProject(root);
  const bible = await loadBible(root);
  const outlineText = (project.outlineText || "").trim();
  const worldText = (project.worldText || "").trim();
  const current = Number(project.currentChapter) || 0;
  const total = Number(project.targetChapters) || 0;
  if (!outlineText) throw new HttpError(400, "还没有大纲，先在大纲页生成/写好大纲，再来设计伏笔");
  if (!worldText) throw new HttpError(400, "还没有世界观，先在大纲页生成世界观，再来设计伏笔（伏笔必须源自世界观规则）");

  // 用「类型·名字」作来源标签（不用 R2/C1 这种临时下标，账本里存不住、日后对不上）
  const labeled = (tag, arr, fmt) => (arr || []).map((w) => (fmt ? fmt(w) : `【${tag}·${w.name || ""}】${w.text || ""}`)).join("\n");
  const worldList = labeled("世界", bible.world);
  const factionList = labeled("势力", bible.factions);
  const locList = labeled("地点", bible.locations);
  const ruleList = labeled("硬规则", bible.rules);
  const charList = (bible.characters || []).map((c) => `【人物·${c.name || ""}】身份:${c.role || ""}；想要:${c.want || ""}；秘密:${c.secret || ""}`).join("\n");
  const itemList = (bible.items || []).map((w) => `【物品·${w.name || ""}】${[w.text, w.holder, w.state].filter(Boolean).join("；")}`).join("\n");
  const synopsis = String(project.synopsis || "").trim();
  // 世界观自洽检查遗留的未解钩子：最该优先长成伏笔（闭环）
  const openThreads = Array.isArray(project.openThreads) ? project.openThreads.filter(Boolean) : [];
  const threadBlock = openThreads.length ? `=== 世界观遗留钩子（优先发展成伏笔）===\n${openThreads.join("\n")}` : "";
  // 已有伏笔：带上详情（名字｜层次｜埋设→回收｜来源），避免同名换说法重复埋，也让新伏笔能衔接
  const existingFs = await listForeshadow(root, current);
  const fsAll = [...(existingFs.open || []), ...(existingFs.paid || [])];
  const existingBlock = fsAll.length
    ? "=== 已有伏笔（不要重复；新伏笔要和它们衔接或留出空间）===\n" + fsAll.slice(0, 80).map((f) =>
        `${f.name}｜${f.kind || "detail"}｜第${f.plantedChapter || "?"}→${f.dueChapter || "?"}章｜${f.source || ""}`).join("\n")
    : "";

  // 大纲截断到「卷边界」，避免从某一卷中间切断导致后段章号错位；设定优先保留
  const outlineBudget = Math.max(1200, 6500 - (synopsis.length + worldText.length + worldList.length + factionList.length + locList.length + ruleList.length + itemList.length + charList.length + threadBlock.length + existingBlock.length));
  let outlineBrief = outlineText;
  if (outlineText.length > outlineBudget) {
    // 找最后一个完整的「### 第N卷」之前的内容作为安全截断点
    const cutAt = outlineText.lastIndexOf("\n### ", outlineBudget);
    outlineBrief = outlineText.slice(0, cutAt > 800 ? cutAt : outlineBudget) + "\n…（大纲后段从略，按上面卷结构推断即可）";
  }
  const material = [
    synopsis ? `=== 故事梗概 ===\n${synopsis}` : "",
    threadBlock,
    existingBlock,
    worldText ? `=== 世界观 ===\n${worldText}` : "",
    worldList, factionList, locList, ruleList, itemList, charList,
    `=== 大纲 ===\n${outlineBrief}`,
  ].filter(Boolean).join("\n") || "（暂无设定与大纲）";

  const system = "你是长篇网文的结构编辑。任务：在故事梗概、世界观、人物与设定、大纲已经定下的范围里，设计整套伏笔的埋设与揭晓计划。你只输出结构化数据，不写正文。";
  // 按作者定的配额：核心 3 条 + 每卷 2 条 + 情节伏笔（按卷给上限、按需自取，不再机械「每 6 章一条」）
  const vols = await loadVolumes(root).catch(() => []);
  const volumeCount = Math.max(1, vols.length || Number(project.volumeCount) || Math.ceil((total || 120) / 40));
  const coreCount = 3;
  const volumeCountFs = volumeCount * 2;
  // 情节伏笔：每卷 2-4 条，按剧情需要取，允许不足（不再强制堆满）
  const plotMax = volumeCount * 4;
  const planned = coreCount + volumeCountFs + plotMax;
  // 一次点击就铺满全书：内部自动分批续写，不算“点很多次”
  const asked = Number(body.count) > 0
    ? Math.max(3, Math.min(200, Number(body.count)))
    : Math.min(planned, 300);
  const user = [
    skillBlock("foreshadow"),
    "",
    `当前进度：第 ${current} 章。${total ? `全书计划约 ${total} 章。` : ""}`,
    `这是全书的伏笔总表：埋设章要从第 ${current + 1} 章起按大纲的卷往后铺${total ? `，一直铺到第 ${total} 章以前` : ""}，同一卷内大致均匀，不要全挤在最近几章。`,
    "",
    "<素材>",
    material,
    "</素材>",
    "",
    total ? `全书约 ${total} 章、约 ${volumeCount} 卷。配额：核心伏笔 ${coreCount} 条，卷级伏笔每卷 2 条共 ${volumeCountFs} 条，情节伏笔每卷 2-4 条（按需要取，不必凑满）。` : "",
    `请按配额设计约 ${asked} 条伏笔：核心约 ${coreCount} 条（贯穿全书、最后揭）、卷级约 ${volumeCountFs} 条（每卷 2 条，在本卷区间内回收）、情节约 ${Math.max(2, asked - coreCount - volumeCountFs)} 条（一句话物件/习惯/称呼，顺手埋顺手收）。层次列分别写 主线/卷内/细节。`,
    // 回收章不能太近，否则伏笔退化成一次性道具
    `回收章要求：必须大于埋设章；核心伏笔回收章要比埋设章晚至少一整卷的跨度、尽量留到全书后段；卷级伏笔回收章 ≥ 埋设章 +5 且落在同一卷区间内；情节伏笔可以埋收相邻。${total ? `所有回收章不超过第 ${total} 章。` : ""}`,
    "每条伏笔必须来自世界观里已给出的一条规则/人物/地点/势力/物品，或有【世界观遗留钩子】里的一条——source 里写清「类型·名字」，如「硬规则·噬灵代价」「人物·沈砚」「钩子·失踪的第七口井」，不要只写编号。优先把遗留钩子发展成伏笔。没有来源的不许写。",
    "",
    "草蛇灰线要求（这些是长篇能不能留住重读者的关键）：",
    "- 一条重要伏笔不许只埋一次：埋设章埋下后，中途至少在 1-2 个间隔章里不经意地再露一次（人物提一句、物件换个地方、旁人一句闲话），那条章节的「中途提示」里写清在哪露、以什么形式露；揭晓章才收。只埋一次就揭的，读者不会觉得「原来早写了」。",
    "- 细节伏笔优先用「读者第一遍看不出是伏笔」的东西：一个称呼、一个习惯动作、一件旧物、一句说反的话、一个没回答的问题、一处钱数/日期对不上。不许写成作者举着牌子埋伏笔。",
    "- 伏笔要跟人物或主线有牵连：揭晓后改变了谁对谁的看法、谁的身份、哪条利益，或反过来解释了前面某个反常。只解释世界设定的伏笔最多占三成。",
    "- 埋点要能被后续确定性体检查到：plantBeat 里写清具体的物件/台词/动作/地名（正文里会原样出现或近义出现），不要写「氛围」「暗示」这种查不到的词。",
    "",
    "为了能一次写完，用紧凑的竖线格式，一行一条，不要 JSON、不要表头、不要解释、不要代码块：",
    "名称|层次|来源|埋设章|埋在哪一拍|回收章|谁来揭|揭开后改变了什么|中途提示|收不回时怎么放弃",
    "示例：断齿梳|卷内|物品·断齿梳|12|拍2 客户袖口露出|18|顾青棠|证明客户早就有预谋|反复摸袖子|改由收费单编号替代",
    "层次只写 主线/卷内/细节；文字列各控制在 20 字以内；埋设章和回收章必须是数字；名称各不相同。",
    `共约 ${asked} 条。如果一次写不完，就尽量多写，不要重复已写过的名称。`,
  ].join("\n");

  const gen = await collectForeshadows(ctx, body, system, user, asked);
  const text = gen.text;
  const entries = gen.entries;

  const num = (v) => { const n = parseInt(String(v ?? "").replace(/[^0-9]/g, ""), 10); return Number.isFinite(n) && n > 0 ? n : null; };
  const str = (v) => String(v ?? "").trim();

  const existing = await listForeshadow(root, current);
  // 已有伏笔用列表保存（支持 sameName 模糊去重，避免"同名换说法"重复埋）
  const existingList = [...(existing.open || []), ...(existing.paid || [])].map((f) => ({ name: f.name }));
  const isDup = (nm) => existingList.some((f) => sameName(f.name, nm));
  // 回收章"过热"守卫：核心/卷级不能埋完一两章就收，否则伏笔退化成一次性道具
  const minGap = (kind) => (kind === "main" ? Math.max(10, Math.ceil(volumeCount * 1)) : kind === "volume" ? 5 : 0);
  const plantedNames = [], skippedNames = [], guardedNames = [], rows = [];
  const seen = new Set();
  for (const f of (entries || []).slice(0, 220)) {
    if (!f || typeof f !== "object") continue;
    const name = str(f.name || f.title);
    if (!name || seen.has(name) || isDup(name)) { if (name) skippedNames.push(name); continue; }
    seen.add(name);
    const plantChapter = num(f.plantChapter ?? f.plantedChapter) || (current + 1);
    let dueChapter = num(f.dueChapter ?? f.due);
    const kind = str(f.kind) || "detail";
    // 回收章守卫：太近则推后到 plant+gap；仍不合法（≤plant）则置空，交给后续手动补
    const gap = minGap(kind);
    if (dueChapter && dueChapter <= plantChapter) dueChapter = null;
    else if (dueChapter && gap && dueChapter - plantChapter < gap) {
      const pushed = plantChapter + gap;
      if (!total || pushed <= total) { dueChapter = pushed; guardedNames.push(name); }
      else dueChapter = null;
    }
    const row = {
      name, kind, source: str(f.source),
      plantChapter, plantBeat: str(f.plantBeat), dueChapter,
      revealWho: str(f.revealWho), revealChange: str(f.revealChange),
      hint: str(f.hint), abandon: str(f.abandon),
    };
    rows.push(row);
    try {
      await plantForeshadow(root, {
        name, plantedChapter: plantChapter,
        dueChapter: dueChapter && dueChapter > plantChapter ? dueChapter : null,
        kind: row.kind, source: row.source, plantBeat: row.plantBeat,
        revealWho: row.revealWho, revealChange: row.revealChange, hint: row.hint, abandon: row.abandon,
        note: [row.source ? `来源${row.source}` : "", row.plantBeat, row.revealChange].filter(Boolean).join("；"),
      });
      existingList.push({ name });
      plantedNames.push(name);
    } catch { /* 单条失败忽略 */ }
  }

  if (!rows.length) {
    throw new HttpError(502, `模型没返回可解析的伏笔（输出被截断或格式不对；已自动重试仍不行，换一个模型再试）。原文片段：${text.slice(0, 160)}`);
  }
  return {
    ok: true, provider: gen.provider, model: gen.model,
    asked, planned,
    written: plantedNames.length, parsedCount: rows.length, plantedNames, skippedNames, guardedNames,
    rows, view: await studioPayload(root),
  };
}

/** 「必须回避」里写了本章该登场的人，等于把人物卡作废：丢掉该条，别让它进上下文包。 */
export function dropDebutFromAvoid(mustAvoid, debut) {
  const list = Array.isArray(mustAvoid) ? mustAvoid : [];
  if (!debut || !debut.length) return list;
  return list.filter((x) => !debut.some((name) => String(x).includes(String(name))));
}

/** 「反差虐点」开关落进 project，面板与工具共用同一处。 */
export async function setTone(root, tone) {
  const project = await requireProject(root);
  project.tone = tone === "contrast" ? "contrast" : "";
  await saveProject(root, project);
  return { ok: true, tone: project.tone };
}

export async function generateOutlines(ctx, body) {
  const root = await assertDir(body.dir);
  await requireProject(root);
  const project = await loadProject(root);
  const bible = await loadBible(root);
  const after = Number(body.after) || Number(project.currentChapter) || 0; // 生成 after+1 .. after+N
  // 默认只生成「下一章」1 章；只有显式传 count 才多章。避免一次生成 10 章导致慢/中途断/跳章。
  const count = Math.min(20, Math.max(1, Number(body.count) || 1));
  const outlineText = (project.outlineText || "").trim();
  if (!outlineText) throw new HttpError(400, "还没有大纲，先在大纲页生成/写好大纲，再来生成细纲");
  const worldText = (project.worldText || "").trim();
  const worldList = (bible.world || []).map((w) => `【世界·${w.name || ""}】${w.text || ""}`).join("\n");
  const factionList = (bible.factions || []).map((w) => `【势力·${w.name || ""}】${w.text || ""}`).join("\n");
  const locList = (bible.locations || []).map((w) => `【地点·${w.name || ""}】${w.text || ""}`).join("\n");
  const ruleList = (bible.rules || []).map((w) => `【硬规则·${w.name || ""}】${w.text || ""}`).join("\n");
  const charsList = (bible.characters || []).map((c) => `【人物·${c.name || ""}】身份:${c.role || ""}；想要:${c.want || ""}；秘密:${c.secret || ""}${c.firstChapter ? "；首次登场:第" + c.firstChapter + "章起" : ""}`).join("\n");
  const existing = await listOutlines(root);
  // 已排细纲只给最近的 6 章（几百章时全给会让 prompt 爆掉，反而丢掉真正要衔接的东西）
  const recentOutlines = existing.filter((o) => o.chapter <= after && o.chapter > after - 6);
  const existingBrief = recentOutlines.map((o) => `第${o.chapter}章：${(o.beats || []).join(" / ")}`).join("\n") || "（暂无）";

  // 未收伏笔账本：数据源取一次；「本章该收/其余在账」按每章各自的 ch 现算（见循环内 fsForChapter）。
  let fsOpen = [];
  const fmt = (f) => `${f.name}｜第${f.plantedChapter}章埋·计划第${f.dueChapter || "?"}章收${f.overdue ? "·超期" : ""}${f.kind ? "·" + f.kind : ""}${f.revealChange ? "·揭开后：" + f.revealChange : ""}`;
  try {
    const fsState = await listForeshadow(root, project.currentChapter || 1);
    fsOpen = fsState.open || [];
  } catch { fsOpen = []; }
  // 给定章节号，算「本章应收 / 已超期 / 其余在账」三拨（批量生成时每章各算一次，避免全用第一章的清单）
  const fsForChapter = (ch) => {
    const dueHere = fsOpen.filter((f) => Number(f.dueChapter) === Number(ch));
    const overdue = fsOpen.filter((f) => f.overdue && Number(f.dueChapter) !== Number(ch));
    const rest = fsOpen.filter((f) => !dueHere.includes(f) && !overdue.includes(f));
    return {
      fsThis: [...dueHere.map((f) => "【本章应收】" + fmt(f)), ...overdue.map((f) => "【已超期·应尽快收】" + fmt(f))].join("\n"),
      fsOthers: rest.map(fmt).join("\n"),
      dueNames: dueHere.map((f) => f.name),
    };
  };
  // 世界观遗留钩子（世界观自洽检查产出）：细纲里可择机带一笔，别断线
  const openThreads = Array.isArray(project.openThreads) ? project.openThreads.filter(Boolean) : [];

  // 上一章结尾原文（供衔接）
  let prevTail = "";
  let prevEnd = { place: "", chars: [] };
  try {
    const idx = await loadIndex(root);
    const lastC = idx.filter((c) => Number(c.number) <= after).sort((a, b) => b.number - a.number)[0];
    if (lastC && lastC.file) {
      const bodytxt = await readFile(path.join(root, lastC.file), "utf8");
      prevTail = bodytxt.replace(/\s+/g, " ").trim().slice(-500);
    }
    if (after >= 1) prevEnd = await endSceneState(root, { chapter: after });
  } catch { /* ignore */ }

  // 记忆层：本卷大纲切片 + 前情记忆（近章/前卷），替代「全文大纲 + 全文世界观每次重发」
  const volumes = await loadVolumes(root);
  const volOfNext = volumeOf(volumes, after + 1);
  const eventMemory = await buildEchoMemory(root, { chapter: after + 1 });
  const prevVolMem = await volumeMemory(root, { chapter: after + 1, volumes });

  const system = "你是长篇网文的章节设计编辑。你要把「这一章该发生什么」拆成可以直接照着写的节拍。你不写正文，不写对话样例，不写景物。" + nameStyle();
  const skillNote = skillBlock("outlines");
  const results = [];
  let written = 0;
  let lastProvider = null, lastModel = null;
  let accExistingBrief = existingBrief;

  for (let ch = after + 1; ch <= after + count; ch += 1) {
    const inVol = volumeOf(volumes, ch);
    const volHere = inVol || volOfNext;
    // 每段各自限长、重要的排前面：否则总截断会先吃掉排在后面的「本章伏笔」。
    const cap = (s, max) => {
      const t = String(s || "");
      return t.length > max ? t.slice(0, max) + "…" : t;
    };
    const volSlice = volHere
      ? `=== 本卷大纲（只给这一卷；全书其他卷和本章无关） ===\n${cap(localOutlineSlice(outlineText, volHere), 2400)}`
      : `=== 大纲（没识别出卷区间，只给前段；建议在大纲里写成「第 a-b 章」） ===\n${cap(outlineText, 2400)}`;
    // 人物卡的登场章是硬约定：本章首次登场的角色必须真的出场，不能被写成「回避」
    const debut = (bible.characters || []).filter((c) => c.name && Number(c.firstChapter) === ch).map((c) => c.name);
    // 批量生成时只有第一章的「上一章结尾」是真的；后面几章的上一章还没写，不要拿同一段原文冒充。
    const tail = ch === after + 1 ? prevTail : "";
    // 每章按自己的章号现算「本章应收/超期/其余」伏笔，不能全用第一章的清单（批量生成会错位）
    const fsC = fsForChapter(ch);
    const threadBlock = openThreads.length ? `=== 世界观遗留钩子（可择机在节拍里带一笔，别断线） ===\n${cap(openThreads.join("\n"), 400)}` : "";
    const materialParts = [
      `【本章】第 ${ch} 章 / 全书共 ${project.targetChapters || "?"} 章${inVol ? `，位于「${inVol.title}」（第${inVol.from}-${inVol.to}章）` : ""}。【上一章】第 ${ch - 1} 章${tail ? "（结尾原文见下，已提供）" : ch === 1 ? "（开篇，没有上一章）" : "（还没写，按下面已排细纲接上）"}`,
      volSlice,
      `=== 本章伏笔（已为你算好，直接用，不要再说"缺伏笔清单"） ===\n${cap(fsC.fsThis || "（本章没有到期该收的伏笔；可从下面的「其他在账未收」里选择在本章埋一提或续一笔，也可不埋）", 900)}`,
      `=== 其他在账未收伏笔（供参考，不必强行用；但核心/卷级别提前收） ===\n${cap(fsC.fsOthers || "（无）", 900)}`,
      threadBlock,
      eventMemory.text ? `=== 前情记忆（已写 ${eventMemory.covered} 章；本章必须接上，不能重复交代） ===\n${cap(eventMemory.text, 1500)}` : "",
      prevVolMem.text ? `=== 前卷记忆（前面各卷已经发生的事） ===\n${cap(prevVolMem.text, 700)}` : "",
      tail ? `=== 上一章（第${ch - 1}章）结尾原文（已提供，直接用） ===\n…${tail}` : (ch === 1 ? "=== 上一章 ===\n（本章为开篇，无上一章）" : "=== 上一章 ===\n（没有原文；按「已排细纲」的最后一章接上）"),
      ch === after + 1 && (prevEnd.place || prevEnd.chars.length)
        ? `=== 上一章收尾状态（本章开场必须接上） ===\n地点：${prevEnd.place || "以结尾原文为准"}；在场：${prevEnd.chars.join("、") || "以结尾原文为准"}`
        : "",
      `=== 硬规则（不可违反） ===\n${cap(ruleList || "（无）", 800)}`,
      `=== 人物卡（可能出场；含首次登场章） ===\n${cap(charsList || "（无）", 1300)}`,
      debut.length ? `=== 本章必须登场（人物卡里首次登场章就是本章，别漏） ===\n${debut.join("、")}` : "",
      `=== 世界观 ===\n${cap(worldList || "（无）", 800)}`,
      factionList ? `=== 势力 ===\n${cap(factionList, 400)}` : "",
      locList ? `=== 地点 ===\n${cap(locList, 400)}` : "",
      `=== 已排细纲（避免重复，要衔接） ===\n${cap(accExistingBrief, 800)}`,
    ].filter(Boolean);
    // 按预算从尾部（优先级最低的）逐段丢弃，而不是把整串硬切——硬切会从末尾吃掉"必须登场/衔接"这类关键段
    const MATERIAL_BUDGET = 12000;
    let material = materialParts.join("\n");
    for (let pi = materialParts.length - 1; pi >= 0 && material.length > MATERIAL_BUDGET; pi -= 1) {
      materialParts[pi] = "";
      material = materialParts.filter(Boolean).join("\n");
    }
    if (material.length > MATERIAL_BUDGET) material = material.slice(0, MATERIAL_BUDGET);

    const user = [
      skillNote,
      "",
      "说明：下面素材里已经提供了——①本章章号与全书规模 ②本章所在卷的大纲切片 ③世界观与硬规则 ④人物卡（含首次登场章） ⑤上一章结尾原文 ⑥本章该埋/该收的伏笔清单。这些不要再说「缺」。",
      debut.length
        ? `人物卡的「首次登场章」是硬约定：${debut.join("、")} 的首次登场章就是本章，必须真的在「出场人物」和节拍里出现；「必须回避」里不许写这些人的名字（回避项只能写信息、桥段、能力，不能写人）。`
        : "人物卡的「首次登场章」是硬约定：首次登场章晚于本章的角色不要提前当面出场，也不要写进「必须回避」。",
      "重要认识：**大纲和世界观只是骨架，不是剧本**。大纲本来就是只给大方向、不会把每件事写清楚——「把一件事具体化到能照着写」正是你现在要做的工作，这**不算素材缺口**。有些剧情故意留白、有些细节本该由你设计，都不是缺口。",
      "只有当**素材之间真的互相矛盾**（例如人物卡说某人第 3 章才登场、但这章剧情非要他当面出现；或硬规则禁止的行为和本章要求直接冲突）时，才在「素材缺口」里指出，并说明你按哪边取、为什么。素材不矛盾、只是没写细的，一律自己设计，不要写进缺口。没有矛盾就写「无」。",
      "",
      "<素材>",
      material,
      "</素材>",
      "",
      "输出顺序（硬要求）：**先输出机器可读块**（整段最先输出、必须完整），再另起一行输出 Markdown 细纲正文。机器块是落账依据，后面的正文即使被截断也不能让它缺半截：",
      "<<<OUTLINE_JSON",
      '{"chapter":' + ch + ',"title":"≤12字标题","beats":["拍1：谁→想要→受阻→结果","拍2：…","拍3：…"],"mustInclude":["必须写到点"],"mustAvoid":["要避免的"],"openingState":"本章开场必须接上的上章状态","endingState":"本章结束时人物在哪、谁欠谁、留下什么悬念","pressure":{"deadline":"还剩多久","stake":"不做会立刻失去什么","opponent":"谁在逼"},"volume":{"title":"本卷名","to":本卷第几章结束}}',
      "OUTLINE_JSON>>>",
      "",
      "然后按下面 Markdown 格式严格输出（不写正文、不写对话和描写，但每拍要是一句能读通的因果链）：",
      "## 0. 素材缺口（只写素材里真的没有、且必须假设才能写的；素材已给的不要写。没有就写「无」）",
      "## 1. 本章定位（章号 + 建议标题≤12字 / 本章目标一句话 / 本章高潮点哪一拍 / 结束状态：人物在哪、谁欠谁、悬念）",
      "## 2. 出场人物（只列真正出场的：名字 | 本章想要什么 | 结束时处境变化）",
      "## 3. 节拍（3-6 拍，每拍严格写成：拍N：谁·在哪儿 → 想要什么 → 被什么挡住 → 结果变成什么 / 落点：读者情绪或信息变化。必须含主角的一个决定及其代价；这个决定要写清「为什么此刻做」——他此刻得到什么，或不做会立刻失去什么（钱、期限、病房、工作这类具体的东西），不能只用「有缘」「旧账」「诡异」当理由；拍与拍因果递进；至少一拍障碍来自世界观规则；不要「思考/回忆/感慨」的独立一拍）",
      "## 4. 必须出现（关键道具/信息/台词要点；本章要埋的伏笔：名称+埋在哪一拍+怎么顺带一提；本章要收的伏笔：名称+收在哪一拍+揭开后改变了什么。**回收纪律**：只能收上面的【本章应收】伏笔；核心/卷级伏笔不得提前于其计划回收章收，「其他在账未收」里的核心/卷级这章不许收，只能续一笔或从遗留钩子发展新伏笔）",
      "## 5. 必须回避（不得使用的表达或桥段；不得出现的角色或信息；不得新增的设定或能力）",
      "## 6. 章末钩子（三种写法各一：一信息型 / 二危险型 / 三选择型）",
      "## 7. 动机三件套（期限：他还有几天/几小时；代价：不做会立刻失去什么，要具体到钱、病房、工作、命；谁在逼：谁的动作让这件事不能再拖）",
      "",
      "位置连续性（硬要求）：拍1的地点必须等于上一章收尾状态或 openingState 写明的地点；每拍换地点都要在拍里写出「离开 A 去了 B」。一拍结束时人已经离开 A，后面不许不写移动就「摸回 A」——同一章里回到刚离开的地点必须有明确理由和往返动作。openingState / endingState 都要写清具体地点（如「打铁铺门槛」「南街陈婶杂货铺」），不能写「南街一线」这类范围。",
      "硬性要求：每拍都要能回答「为什么是现在」，答案必须来自第 7 节的期限/代价/谁在逼，不能靠「诡异」「有缘」「旧账」；每条节拍能对应到大纲某一处；超世界观规则的动作不写（需要就在素材缺口提出）；不写正文、不写对话和描写，但每拍要是一句能读通的因果链；本章收在本章，不安排下一章。",
    ].join("\n");

    let gen;
    try {
      gen = await generateText(ctx, body, {
        system, user, maxTokens: OUTLINE_MAX_TOKENS, purpose: "novel-outlines", allowPartial: true,
      });
    } catch (err) {
      // 一章都没写成时就按原错误抛出（保持 503/502/400 语义），前端能明确知道是"根本没开始"。
      if (written === 0) throw err;
      // 中途失败（多为余额不足）：不再往前写，把已生成的章数如实返回，并给出原因
      return {
        ok: true,
        partial: true,
        error: `生成到第 ${ch} 章时中断：${err.message || err}。已生成前 ${written} 章细纲（第 ${after + 1}-${after + written} 章）。`,
        written,
        outlines: results,
        view: await studioPayload(root),
      };
    }
    const { text, provider, model } = gen;
    lastProvider = provider; lastModel = model;
    const truncated = Boolean(gen.partial);
    let detail = String(text || "").trim();
    let obj = null;
    const m = detail.match(/<<<OUTLINE_JSON([\s\S]*?)OUTLINE_JSON>>>/);
    if (m) {
      detail = (detail.slice(0, m.index).trim() + "\n" + detail.slice(m.index + m[0].length).trim()).trim();
      try { obj = extractJsonObject(m[1]); } catch { obj = null; }
    }
    // 兜底：若没有机器块，尝试整段里找 JSON 对象
    if (!obj) { try { obj = extractJsonObject(detail); } catch { obj = null; } }
    const beats = obj && Array.isArray(obj.beats) ? obj.beats.map((b) => String(b).trim()).filter(Boolean) : [];
    // 截断而且连节拍都没拿到：明确告诉作者怎么调，不要只报「maxTokens 用完」。
    if (!beats.length && truncated) {
      const msg = `第 ${ch} 章细纲输出被截断（maxTokens ${OUTLINE_MAX_TOKENS}），机器块也没输出完。`
        + `把环境变量 DSH_NOVEL_OUTLINE_TOKENS 调到 ${OUTLINE_MAX_TOKENS * 2}（或换一个输出上限更大的模型）后重试。`;
      if (written === 0) throw new HttpError(502, msg);
      return { ok: true, partial: true, error: msg, written, outlines: results, view: await studioPayload(root) };
    }
    if (beats.length) {
      const avoid = dropDebutFromAvoid(obj.mustAvoid, debut);
      // 首章细纲与续写细纲共用同一套字段：开场状态、结束状态、卷尾章一起落账
      await setOutline(root, {
        chapter: ch, beats, mustInclude: obj.mustInclude, mustAvoid: avoid, detail,
        title: obj.title, openingState: obj.openingState, endingState: obj.endingState,
        pressure: obj.pressure,
        volume: obj.volume && Number(obj.volume.to) ? obj.volume : null,
      });
      written += 1;
      accExistingBrief += `\n第${ch}章：${beats.join(" / ")}`;
    }
    const missingMotivation = ["deadline", "stake", "opponent"].filter((k) => !String(obj?.pressure?.[k] || "").trim());
    results.push({
      chapter: ch, title: (obj && obj.title) || "", beats, detail, debut,
      ok: beats.length > 0,
      truncated,
      motivationWarning: missingMotivation.length ? `第${ch}章细纲的动机缺：${missingMotivation.join("、")}——写正文前要么补全，要么这一章的推动会变成凭气氛走` : "",
    });
  }

  return { ok: true, provider: lastProvider, model: lastModel, written, outlines: results, view: await studioPayload(root) };
}

/* ------------------------------ HTTP 管道 ------------------------------ */

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(new HttpError(413, "请求体过大（> 4MB），正文请走 novel_chapter 工具"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      if (!chunks.length) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new HttpError(400, "请求体不是合法 JSON"));
      }
    });
    req.on("error", reject);
  });
}

function send(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

/** 一个前缀路由处理所有 /novel/api/* 请求。 */
export function createHandler(ctx) {
  return async function handler(req, res) {
    try {
      const url = new URL(req.url ?? "/", "http://localhost");
      if (url.pathname !== API_PREFIX && !url.pathname.startsWith(API_BASE)) return send(res, 404, { ok: false, error: "not found" });
      const name = url.pathname.slice(API_BASE.length).replace(/\/+$/u, "");
      const method = (req.method || "GET").toUpperCase();
      checkWriteOrigin(req);
      const payload = await dispatch(method, name, url, req, ctx);
      send(res, 200, payload);
    } catch (error) {
      const msg = error?.message || String(error);
      // 门控拒绝（domain.guardGate 抛的普通 Error）是「状态不满足」，统一 409，不是 500。
      const isGate = /还没|待确认|不是当前待写章|先至少|先 novel_|不能先写|不存在，没有可重写|已锁定|已确认过|不要重复确认|第\d+章还没|还没有细纲|还没有大纲/i.test(msg);
      const status = error instanceof HttpError ? error.status : (isGate ? 409 : 500);
      send(res, status, { ok: false, error: msg });
    }
  };
}

/** 在 webServer 上挂载前缀路由；返回 disposer。
 *  rootCtx（可选）用来读 llm / agentDefaultModel；缺了就是 web ctx 自身。 */
export function mount(ctx, rootCtx) {
  const apiCtx = rootCtx || ctx;
  return ctx.webServer.register({ kind: "prefix", path: API_PREFIX, handler: createHandler(apiCtx) });
}
