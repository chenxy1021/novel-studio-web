// 批次段落纲：批量写作时，10 章共用一份「段落纲」，不再每章一份细纲。
// 只做确定性拼装，不调模型；数据全部来自 bible / 伏笔账 / 大纲 / 章节索引。
import {
  LAYOUT, appendJsonl, p, readJson, readJsonl, withProjectLock,
} from "./io.js";

const SEGMENTS_FILE = "ledger/segments.jsonl";
const MAX_RANGE = 30;

const now = () => new Date().toISOString();
const num = (x) => Number(x) || 0;

/** 段落纲事件折叠：同一 from-to 以最后一条为准；op=delete 的事件把它整段移除。 */
function foldSegments(rows) {
  const map = new Map();
  for (const r of rows || []) {
    if (!r || r.__corrupt) continue;
    const from = num(r.from);
    const to = num(r.to);
    if (!from || to < from) continue;
    if (r.op === "delete") { map.delete(`${from}-${to}`); continue; }
    if (!r.plan) continue;
    map.set(`${from}-${to}`, { ...r, from, to });
  }
  return [...map.values()].sort((a, b) => a.from - b.from || a.to - b.to);
}

function covers(seg, chapter) {
  return chapter >= num(seg.from) && chapter <= num(seg.to);
}

/** 同一章只能落在一个批次里：新批次与已有批次重叠直接报错。 */
function overlapOf(segments, from, to, exceptKey = "") {
  return segments.find((s) => `${s.from}-${s.to}` !== exceptKey && s.from <= to && from <= s.to) || null;
}

/** 读伏笔账：折叠到当前状态，只留 open（未收/未放弃）的条目。 */
function openForeshadows(rows) {
  const map = new Map();
  for (const r of rows || []) {
    if (!r || r.__corrupt) continue;
    const cur = map.get(r.id) || { id: r.id, status: "open" };
    map.set(r.id, {
      ...cur,
      name: r.name ?? cur.name,
      plantedChapter: r.plantedChapter ?? cur.plantedChapter,
      dueChapter: r.dueChapter ?? cur.dueChapter,
      status: r.op === "payoff" ? "paid" : r.op === "abandon" ? "abandoned" : (r.status || cur.status),
    });
  }
  return [...map.values()].filter((f) => f.status === "open");
}

/** 读逐章细纲（兼容老模式）；批次模式下一般没有，返回空。 */
async function outlineByChapter(root) {
  const rows = await readJsonl(p(root, "ledger/outline.jsonl")).catch(() => []);
  const map = new Map();
  for (const r of rows) {
    if (!r || r.__corrupt) continue;
    const n = num(r.chapter);
    if (!n) continue;
    map.set(n, r.deleted ? null : r);
  }
  return map;
}

function splitRange(from, to, stageCount) {
  const total = to - from + 1;
  const base = Math.floor(total / stageCount);
  let extra = total % stageCount;
  const out = [];
  let cur = from;
  for (let i = 0; i < stageCount; i += 1) {
    const size = base + (extra > 0 ? 1 : 0);
    if (extra > 0) extra -= 1;
    out.push({ from: cur, to: cur + size - 1, chapters: Array.from({ length: size }, (_, k) => cur + k) });
    cur += size;
  }
  return out;
}

const GOALS = [
  (who) => `${who}先拿到本段的第一条实证，但因此暴露一个弱点`,
  (who) => `把「${who}想要的东西」推到不可退的位置，逼对手第一次正面出手`,
  (who) => `让本段的主要目标见分晓，同时留下下一段的引子`,
  (who) => `处理上一台阶留下的代价，让${who}失去一个原本依赖的东西`,
  (who) => `收束本段因果，把下一段的压力提前压到${who}身上`,
];

function pickNames(text, names) {
  const t = String(text || "");
  return names.filter((n) => n && t.includes(n));
}

/**
 * 规划一批段落纲（不写盘）。
 * 输出：{from,to,stages:[{chapters,goal,turn,foreshadow:{plant,payoff},pace,places}],spine}
 */
export async function planSegment(root, { from, to } = {}) {
  const start = Number(from);
  if (!Number.isInteger(start) || start <= 0) throw new Error("planSegment 需要 from（起始章号，≥1 的整数）");
  const end = to === undefined || to === null || to === "" ? start + 9 : Number(to);
  if (!Number.isInteger(end) || end < start) throw new Error(`planSegment 的 to（${to}）必须是 ≥ from（${start}）的整数`);
  if (end - start + 1 > MAX_RANGE) throw new Error(`一段最多 ${MAX_RANGE} 章，现在 ${start}-${end} 有 ${end - start + 1} 章`);

  const project = await readJson(p(root, LAYOUT.project), null);
  if (!project) throw new Error(`不是小说项目（缺 project.json）：${root}`);
  const bible = await readJson(p(root, LAYOUT.bible), {});
  const fsRows = await readJsonl(p(root, LAYOUT.foreshadow)).catch(() => []);
  const outlines = await outlineByChapter(root);
  const allFs = openForeshadows(fsRows);

  const chars = Array.isArray(bible.characters) ? bible.characters : [];
  const main = chars.find((c) => ["核心", "主要", "S", "A"].includes(String(c.importance || c.tier || "").trim()))
    || chars[0] || {};
  const who = String(main.name || "主角");
  const want = String(main.want || project.concept?.oneLine || project.logline || "推进主线目标");
  const flaw = String(main.flaw || main.fear || "自己的执念");
  const ability = String(main.ability || "现有手段");
  const rules = Array.isArray(bible.rules) ? bible.rules.filter((r) => r && (r.name || r.text)) : [];
  const ruleName = String(rules[0]?.name || rules[0]?.text || "这个世界的硬规则").slice(0, 40);
  const placesAll = (Array.isArray(bible.locations) ? bible.locations : []).map((x) => String(x.name || "").trim()).filter(Boolean);
  const namesAll = chars.map((c) => String(c.name || "").trim()).filter(Boolean);

  const total = end - start + 1;
  // 3-5 个台阶：10 章默认 3 个，12 章 4 个，15 章以上 5 个；至少 3 个，避免一段只有起和收。
  // 章节数不足 3 时台阶数不能超过章数，否则会拆出空台阶。
  const stageCount = Math.max(1, Math.min(5, total, Math.max(3, Math.round(total / 3))));
  const ranges = splitRange(start, end, stageCount);

  const stages = ranges.map((r, i) => {
    const beatsText = r.chapters.map((n) => {
      const o = outlines.get(n);
      return o ? [o.title, ...(o.beats || []), ...(o.mustInclude || [])].filter(Boolean).join(" ") : "";
    }).join(" ");
    const plant = allFs.filter((f) => num(f.plantedChapter) >= r.from && num(f.plantedChapter) <= r.to)
      .map((f) => String(f.name || "").trim()).filter(Boolean);
    const payoff = allFs.filter((f) => num(f.dueChapter) >= r.from && num(f.dueChapter) <= r.to)
      .map((f) => String(f.name || "").trim()).filter(Boolean);
    // 预计地点：细纲里点到的地点优先；没有就按地点表轮转，保证每段有可对照的现场。
    let places = pickNames(beatsText, placesAll);
    if (!places.length && placesAll.length) places = [placesAll[i % placesAll.length]];
    const cast = pickNames(beatsText, namesAll);
    return {
      chapters: r.chapters,
      goal: GOALS[Math.min(i, GOALS.length - 1)](who),
      turn: `${who}想靠${ability}硬推，结果触碰「${ruleName}」，${flaw}被对手抓住`,
      foreshadow: { plant, payoff },
      pace: i % 2 === 0 ? "紧" : "缓",
      places,
      cast: cast.length ? cast : [who],
    };
  });

  const spine = String(project.logline || project.concept?.oneLine || project.synopsis || "").trim()
    || `${who}为了${want}，在第 ${start}-${end} 章里先拿到实证、付出代价，再逼出对手的正面反应。`;
  return { from: start, to: end, stages, spine };
}

/** 把段落纲落盘到 ledger/segments.jsonl（追加事件）。 */
export async function writeSegmentOutline(root, plan) {
  if (!plan || !Array.isArray(plan.stages) || !plan.stages.length) throw new Error("writeSegmentOutline 需要 plan.stages（至少一个台阶）");
  const from = Number(plan.from);
  const to = Number(plan.to);
  if (!Number.isFinite(from) || from <= 0 || !Number.isFinite(to) || to < from) throw new Error("段落纲的 from/to 不合法");
  return withProjectLock(root, async () => {
    const rows = await readJsonl(p(root, SEGMENTS_FILE)).catch(() => []);
    const segments = foldSegments(rows);
    const hit = overlapOf(segments, from, to);
    if (hit) throw new Error(`第${from}-${to}章与已有批次第${hit.from}-${hit.to}章重叠；一批只能覆盖一段连续章号，写第 ${hit.to + 1} 章起请重新 plan`);
    // 章号覆盖必须连续且与 stages 一致
    const covered = plan.stages.flatMap((s) => (Array.isArray(s.chapters) ? s.chapters.map(Number) : []));
    const want = Array.from({ length: to - from + 1 }, (_, i) => from + i);
    if (covered.length !== want.length || covered.some((n, i) => n !== want[i])) {
      throw new Error(`段落纲的 stages 必须按顺序完整覆盖第${from}-${to}章（现在是 ${covered.join(",") || "空"}）`);
    }
    await appendJsonl(p(root, SEGMENTS_FILE), { kind: "segment", from, to, plan, at: now() });
    return { ok: true, from, to, stages: plan.stages.length };
  });
}

/** 读某段（from/to 精确匹配）或覆盖某章的最新段落纲。 */
export async function getSegment(root, { from, to } = {}) {
  const rows = await readJsonl(p(root, SEGMENTS_FILE)).catch(() => []);
  const segments = foldSegments(rows);
  if (from !== undefined && to !== undefined) {
    return segments.find((s) => s.from === Number(from) && s.to === Number(to)) || null;
  }
  const ch = Number(from);
  if (!ch) return segments[segments.length - 1] || null;
  return [...segments].reverse().find((s) => covers(s, ch)) || null;
}

/**
 * 本章属于哪一批：返回段落纲 + 本章位置 + 批内已写章节摘要。
 * 老逐章模式（没有 segment）返回 null，调用方继续走 outline。
 */
export async function chapterFromSegment(root, chapter) {
  const n = Number(chapter);
  if (!Number.isFinite(n) || n <= 0) return null;
  const seg = await getSegment(root, { from: n });
  if (!seg) return null;
  const idx = Array.isArray(seg.plan?.stages) ? seg.plan.stages : [];
  const stageIndex = idx.findIndex((s) => (s.chapters || []).map(Number).includes(n));
  if (stageIndex < 0) return null;
  const index = await readJson(p(root, LAYOUT.chapterIndex), []).catch(() => []);
  const previous = (Array.isArray(index) ? index : [])
    .filter((c) => num(c.number) >= seg.from && num(c.number) < n)
    .sort((a, b) => a.number - b.number)
    .map((c) => ({ chapter: num(c.number), title: c.title || "", summary: String(c.summary || "").slice(0, 120) }));
  const info = {
    segment: seg.plan, from: seg.from, to: seg.to,
    stage: idx[stageIndex], stageIndex, stageCount: idx.length, previous,
  };
  info.text = segmentText(info);
  return info;
}

/** 段落纲的可读文本（上下文包 / 工具返回共用）。 */
export function segmentText(info, maxChars = 2500) {
  if (!info || !info.segment) return "";
  const { segment, stage, stageIndex, stageCount, previous } = info;
  const lines = [
    `本批：第${info.from}-${info.to}章（共 ${stageCount} 个台阶）｜本章在第 ${stageIndex + 1} 个台阶`,
    `整段因果：${segment.spine || "—"}`,
  ];
  (segment.stages || []).forEach((s, i) => {
    const fs = s.foreshadow || {};
    lines.push(`\n台阶${i + 1}（第${(s.chapters || []).join("、")}章）｜节奏：${s.pace || "—"}${i === stageIndex ? " ← 本章" : ""}`);
    lines.push(`- 目标：${s.goal || "—"}`);
    lines.push(`- 转折：${s.turn || "—"}`);
    if ((fs.plant || []).length) lines.push(`- 本台阶埋：${fs.plant.join("、")}`);
    if ((fs.payoff || []).length) lines.push(`- 本台阶收：${fs.payoff.join("、")}`);
    if ((s.places || []).length) lines.push(`- 预计现场：${s.places.join("、")}`);
  });
  if (previous && previous.length) {
    lines.push("\n批内已写：");
    for (const p0 of previous) lines.push(`- 第${p0.chapter}章 ${p0.title}｜${p0.summary || "（无摘要）"}`);
  } else {
    lines.push("\n批内已写：本章是这一批的第一章。");
  }
  lines.push(`\n本章位置：第 ${stageIndex + 1}/${stageCount} 个台阶；只推进本台阶的「目标→转折」，不要把整批写完。`);
  const text = lines.join("\n");
  return text.length <= maxChars ? text : text.slice(0, maxChars) + "…";
}

/** 供面板/工具列批次用（不带章节上下文）；带上每个台阶的内容，面板才能直接显示段落纲正文。 */
export async function listSegments(root) {
  const rows = await readJsonl(p(root, SEGMENTS_FILE)).catch(() => []);
  return foldSegments(rows).map((s) => ({
    from: s.from, to: s.to, at: s.at,
    stages: s.plan?.stages?.length || 0,
    spine: s.plan?.spine || "",
    plan: s.plan ? { from: s.plan.from, to: s.plan.to, spine: s.plan.spine || "", stages: s.plan.stages || [] } : null,
  }));
}

/**
 * 删除一段段落纲（以 from-to 精确定位）。
 * 已经写了正文的批次也能删：那些章会退回逐章模式（上下文包改为按上一章收尾续写），
 * 不会丢稿；下次要按段落纲写就重新 plan。
 */
export async function deleteSegment(root, { from, to } = {}) {
  const f = Number(from);
  const t = Number(to);
  if (!Number.isFinite(f) || !Number.isFinite(t) || t < f) throw new Error(`deleteSegment 需要合法的 from/to（现在是 ${from}-${to}）`);
  return withProjectLock(root, async () => {
    const rows = await readJsonl(p(root, SEGMENTS_FILE)).catch(() => []);
    const segments = foldSegments(rows);
    const hit = segments.find((s) => s.from === f && s.to === t);
    if (!hit) throw new Error(`没有第 ${f}-${t} 章的段落纲`);
    const index = await readJson(p(root, LAYOUT.chapterIndex), []).catch(() => []);
    const written = (Array.isArray(index) ? index : []).map((c) => num(c.number)).filter((n) => n >= f && n <= t);
    // 追加一条删除事件，foldSegments 按 from-to 以最后一条为准 → 该段从列表里消失
    await appendJsonl(p(root, SEGMENTS_FILE), { kind: "segment", op: "delete", from: f, to: t, at: now() });
    return { ok: true, from: f, to: t, written: written.length };
  });
}
