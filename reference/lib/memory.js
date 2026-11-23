// 写作记忆层：决定「写第 N 章时到底把哪些前情装进上下文包」。
// 百万字的关键不是上下文窗口有多大，而是每次只装「这一章用得上的」：
//
//   L0 状态账（结构化、事实）  人物现状 / 关系 / 已知真相 / 开放线（伏笔+目标+悬念）/ 世界状态
//   L1 卷级记忆（模型精炼）    按大纲卷分组的「这部/卷发生了什么」，不是全文
//   L2 章级记忆（模型精炼）    关键事件 + 结束时状态，近章给全文，远章给一条主语
//   L3 原文（只在需要时）      上一章结尾 / 本章点名的伏笔出处
//
// 旧记忆还有一条「点名才查」的检索（recall）：不占每章预算，作者/Agent 问
// 「第几卷那条线索」时用 novel_memory op=recall 按关键词把原文切片调出来，带章号出处。
//
// 另一件必做的事是「按段分配预算」：必守段（细纲/规则/角色/出场）先占位，
// 可选段（大纲/世界观/前情）平分剩下的，永远不从末尾一刀切。
import { LAYOUT, appendJsonl, p, readJson, readJsonl, readText, writeJson } from "./io.js";

export const MEMORY_FILE = "ledger/memory.jsonl";
export const VOLUMES_FILE = "ledger/volumes.json";

export const STRONG_RECENT = 8;     // 最近 8 章给完整摘要 + 事件
export const FAR_LINES = 40;        // 再往前 40 章，一章一句
export const DEFAULT_BUDGET = 12000;

/* ------------------------------ 卷索引 ------------------------------ */

// chapters/index.json 是 JSON 数组（不是 jsonl）；读错会让章记忆/卷盘点一直“没有正文”
const readIndex = async (root) => {
  const v = await readJson(p(root, LAYOUT.chapterIndex), []).catch(() => []);
  return Array.isArray(v) ? v : [];
};

const CN = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
export function cnNum(s) {
  if (!s) return null;
  if (/^\d+$/.test(s)) return Number(s);
  let n = 0, cur = 0;
  for (const ch of s) {
    if (CN[ch]) cur = CN[ch];
    else if (ch === "百") { n += (cur || 1) * 100; cur = 0; }
    else if (ch === "千") { n += (cur || 1) * 1000; cur = 0; }
  }
  return n + cur || null;
}

const RANGES = /第\s*([0-9一二三四五六七八九十百千]+)\s*章?\s*[~～\-—–至到]\s*第?\s*([0-9一二三四五六七八九十百千]+)\s*章/g;
// 卷头行：「第一部：旧卷疑云（第 1-120 章）」「第2卷 轮回之证」「## 第一卷 风起」
const VOL_HEAD = /^#{0,6}\s*(第\s*([0-9一二三四五六七八九十百千]+)\s*[部卷篇]|[部卷篇]\s*[一二三四五六七八九十0-9]+)\s*[：:、.·\s]*(.*)$/;

/**
 * 从大纲 Markdown 里抠卷索引：[{title, from, to}]。
 * 整卷识别：卷头行（第X部/卷/篇）自带的区间就是这一卷；没带区间时，把下面各小节的区间合并成整卷范围
 * （否则「第 1-30 章 发现线索」这种每 30 章一节会被当成一卷）。没有卷头才退回按章节区间拆。
 * 「全书层」「主线」这类总览小节里的区间（起点/转折/结局）不是卷，跳过。
 */
export function parseVolumes(outlineText) {
  const lines = String(outlineText || "").replace(/\r\n/g, "\n").split("\n");
  const vols = [];
  let cur = null;
  let inOverview = false;
  const span = (text) => {
    const res = [];
    for (const m of text.matchAll(RANGES)) {
      const from = cnNum(m[1]);
      const to = cnNum(m[2]);
      if (!from || !to || to < from) continue;
      res.push({ from, to });
    }
    return res;
  };
  for (const raw of lines) {
    // 卷头常写成列表项 / 加粗：`- **第一卷 第 1-36 章｜第一单**`，先去掉这些装饰再认
    const line = raw.trim().replace(/^[*>\-+\s]+/, "").replace(/\*\*/g, "").trim();
    const head = /^#{2,6}\s*(.+)$/.exec(line);
    const volHead = VOL_HEAD.exec(line);
    if (head || volHead) {
      const t = head ? head[1].trim() : volHead[3].trim();
      if (/^(全书|主线|总览|素材|开篇|结局层)/.test(t)) inOverview = true;
      if (volHead) {
        inOverview = false;
        const rawName = String(t || "")
          .replace(/[（(].*$/, "")
          .replace(/^(第\s*[0-9一二三四五六七八九十百千]+\s*[部卷篇]|[部卷篇]\s*[一二三四五六七八九十0-9]+)/, "")
          .replace(/^第\s*[0-9一二三四五六七八九十百千]+\s*[-–—~～至到]\s*[0-9一二三四五六七八九十百千]+\s*章/, "")
          .replace(/^[：:、.·｜|\s]+/, "").trim();
        // 只认短的卷名；「卷一 第 1-30 章：任务——……」后面是描述，不能当卷名
        const label = rawName.split(/[：:｜|（(]/)[0].trim();
        const name = label && label.length <= 12 && !/^(任务|矛盾|新增|情绪|大致|回收|新埋|节奏)/.test(label) ? label : "";
        cur = {
          title: `${volHead[1].replace(/\s+/g, "")}${name ? " " + name : ""}`.trim().slice(0, 60),
          from: 0, to: 0, src: [],
          // 「部」只是分组：下面还有「卷」时以卷为准，否则进度页会同时出现第一部与卷四两张重叠的卡
          part: /[部]/.test(volHead[1]),
        };
        vols.push(cur);
      }
      const marks = span(line.replace(/^#{2,6}/, ""));
      if (cur && !inOverview) cur.src.push(...marks);
      continue;
    }
    if (cur && !inOverview) cur.src.push(...span(line));
    RANGES.lastIndex = 0;
  }
  const out = [];
  for (const v of vols) {
    if (!v.src.length) continue;
    const from = Math.min(...v.src.map((x) => x.from));
    const to = Math.max(...v.src.map((x) => x.to));
    out.push({ title: v.title, from, to, part: Boolean(v.part) });
  }
  // 卷把「部」的区间铺满时丢掉部这层（部与卷重叠，卷才是章节归属）；铺不满就保留部兜底
  const covered = (part) => {
    const kids = out.filter((c) => !c.part && part.from <= c.from && c.to <= part.to).sort((a, b) => a.from - b.from);
    let at = part.from;
    for (const k of kids) {
      if (k.from > at) return false;
      at = Math.max(at, k.to + 1);
      if (at > part.to) return true;
    }
    return at > part.to;
  };
  const kept = out.filter((v) => !v.part || !covered(v));
  // 大纲完全没写卷头：退回按章节区间拆（兼容「## 第 1-120 章」这种写法）
  if (!out.length) {
    let section = "";
    let overview = false;
    for (const raw of lines) {
      const line = raw.trim();
      const head = /^#{2,6}\s*(.+)$/.exec(line);
      if (head) { section = head[1].trim(); overview = /^(全书|主线|总览|素材|开篇|结局层)/.test(section); continue; }
      if (overview) continue;
      for (const m of span(line)) out.push({ title: (section || `第${m.from}-${m.to}章`).slice(0, 60), from: m.from, to: m.to });
    }
  }
  const seen = new Set();
  const uniq = kept.filter((v) => {
    const k = `${v.from}-${v.to}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  }).sort((a, b) => a.from - b.from || a.to - b.to).map((v) => ({ title: v.title, from: v.from, to: v.to }));
  return uniq;
}

export async function loadVolumes(root) {
  const rows = await readJsonl(p(root, VOLUMES_FILE)).catch(() => []);
  if (!rows.length) return [];
  const last = rows.filter((r) => r && !r.__corrupt).pop();
  return Array.isArray(last?.volumes) ? last.volumes : [];
}

export async function saveVolumes(root, outlines, outlineText) {
  const fromOutline = parseVolumes(outlineText);
  // 细纲只记了「本卷到第几章」时，用它补出大纲里没写全的卷（从上一卷末尾+1 开始）
  const marks = (outlines || [])
    .map((o) => ({ to: Number(o?.volume?.to), title: String(o?.volume?.title || o?.volume?.name || "") }))
    .filter((x) => Number.isFinite(x.to) && x.to > 0)
    .sort((a, b) => a.to - b.to);
  const manual = [];
  let prevTo = 0;
  for (const m of marks) {
    if (m.to <= prevTo) continue;
    if (fromOutline.some((v) => v.from <= m.to && m.to <= v.to)) { prevTo = m.to; continue; }
    manual.push({ title: m.title || `第${prevTo + 1}-${m.to}章`, from: prevTo + 1, to: m.to });
    prevTo = m.to;
  }
  const merged = [...fromOutline];
  for (const m of manual) {
    // 与已有区间重叠的丢掉（大纲里的更权威）
    if (merged.some((v) => !(m.to < v.from || m.from > v.to))) continue;
    merged.push(m);
  }
  if (!merged.length) return [];
  merged.sort((a, b) => a.from - b.from);
  // 卷索引没变就不重复追加：面板每次刷新都会重算，重复写会把 volumes.json 撑大
  const prev = await readJsonl(p(root, VOLUMES_FILE)).catch(() => []);
  const last = prev[prev.length - 1];
  if (last && JSON.stringify(last.volumes) === JSON.stringify(merged)) return merged;
  await appendJsonl(p(root, VOLUMES_FILE), { volumes: merged, source: manual.length ? "outline+chapters" : "outline", at: new Date().toISOString() });
  return merged;
}

/**
 * 大纲文本变了就刷新卷索引（保存大纲 / 生成大纲 / 写细纲三处都调）。
 * 这是「百万字也记得住」的底座：章节 -> 卷 的映射只算一次，写每章按卷取切片。
 */
export async function refreshVolumes(root, loadOutlines) {
  const proj = await readJson(p(root, LAYOUT.project));
  if (!proj) return [];
  let outlines = [];
  try { outlines = loadOutlines ? await loadOutlines() : []; } catch { outlines = []; }
  const vols = await saveVolumes(root, outlines, proj.outlineText || "");
  if (!proj.volumeCount && vols.length) {
    proj.volumeCount = vols.length;
    proj.updatedAt = new Date().toISOString();
    await writeJson(p(root, LAYOUT.project), proj);
  }
  return vols;
}

/** 第 n 章属于哪一卷；卷索引没铺到就返回 null（= 没有卷记忆可用）。 */
export function volumeOf(volumes, n) {
  return (volumes || []).find((v) => Number(n) >= v.from && Number(n) <= v.to) || null;
}

/** 章节按卷分组（给「盘点卷记忆」用）：返回 [{volume, numbers}]。 */
export function groupByVolume(volumes, numbers) {
  if (!volumes.length) return [];
  const map = new Map(volumes.map((v) => [v, []]));
  const rest = [];
  for (const n of numbers) {
    const v = volumeOf(volumes, n);
    if (v) map.get(v).push(n);
    else rest.push(n);
  }
  const out = [...map.entries()].filter(([, nums]) => nums.length).map(([volume, nums]) => ({ volume, numbers: nums.sort((a, b) => a - b) }));
  return out;
}

/* ------------------------------ 设定别名 ------------------------------ */

/** 人物的所有称呼：name + aliases（数组或「小默、默哥」这种字符串都认）。 */
export function aliasesOf(c) {
  const raw = c?.aliases;
  const list = Array.isArray(raw) ? raw : (typeof raw === "string" ? raw.split(/[、,，/\s]+/) : []);
  return [...new Set([c?.name, ...list].map((s) => String(s || "").trim()).filter(Boolean))];
}

/** 名字 → 角色；正文里用别名也算同一个人。设定里没写的返回 null。 */
export function resolveCharacter(bible, name) {
  const want = String(name || "").trim();
  if (!want) return null;
  const chars = bible?.characters || [];
  return chars.find((c) => c.name === want)
    || chars.find((c) => aliasesOf(c).includes(want))
    || chars.find((c) => aliasesOf(c).some((a) => a.length >= 2 && (want.includes(a) || a.includes(want))))
    || null;
}

/** 正文里出现的人物（含别名），返回设定里的规范名（按出场顺序、去重）。 */
export function charactersMentioned(bible, text) {
  const t = String(text || "");
  const hits = [];
  for (const c of bible?.characters || []) {
    if (!c?.name) continue;
    if (aliasesOf(c).some((a) => t.includes(a))) hits.push(c.name);
  }
  return hits;
}

/* ------------------------------ 摘要与记忆 ------------------------------ */

/** 一块中文字数（粗略，够用来判超长）。 */
const charLen = (s) => String(s || "").replace(/\s+/g, "").length;
export const SUMMARY_MAX = 400;
export const SUMMARY_TARGET = 160;

/**
 * 摘要成形：把多行压成一句一段，超长就丢掉最后一句、补省略号。
 * 这里是「摘要不设上限 → 前情记忆被一章吃光」的修法：摘要必须小、必须稳。
 */
export function clampSummary(text, max = SUMMARY_MAX) {
  const s = String(text || "").replace(/\s*\n+\s*/g, " ").trim();
  if (charLen(s) <= max) return s;
  const head = s.slice(0, Math.max(1, Math.floor(max * 0.95)));
  const cut = Math.max(head.lastIndexOf("。"), head.lastIndexOf("；"), head.lastIndexOf("！"), head.lastIndexOf("？"));
  return (cut > max * 0.4 ? head.slice(0, cut + 1) : head) + "…";
}

export async function loadMemoryRows(root) {
  const rows = await readJsonl(p(root, MEMORY_FILE)).catch(() => []);
  const byChapter = new Map();
  const volumes = [];
  for (const r of rows) {
    if (!r || r.__corrupt) continue;
    if (r.kind === "volume") { volumes.push(r); continue; }
    if (r.kind === "character-state") continue;
    if (r.chapter != null) byChapter.set(Number(r.chapter), r); // 同章重写后取最新
  }
  return { byChapter, volumes: volumes.sort((a, b) => (a.to || 0) - (b.to || 0)), rows };
}

export async function appendMemory(root, row) {
  await appendJsonl(p(root, MEMORY_FILE), { ...row, at: new Date().toISOString() });
}

/* ------------------------------ 章级记忆（L2） ------------------------------ */

export async function buildEchoMemory(root, { chapter, budgetChars = DEFAULT_BUDGET, focus = [] } = {}) {
  const n = Number(chapter) || 0;
  if (!n) return { text: "", chars: 0, covered: 0 };
  const index = (await readIndex(root)).filter((c) => Number.isFinite(Number(c.number)));
  const before = index.filter((c) => Number(c.number) < n).sort((a, b) => a.number - b.number);
  if (!before.length) return { text: "", chars: 0, covered: 0 };
  const { byChapter } = await loadMemoryRows(root);
  const strongFrom = Math.max(1, n - STRONG_RECENT);
  const farStart = Math.max(1, strongFrom - FAR_LINES);
  const focusSet = new Set(focus.map(String));
  const hitFocus = (c) => focusSet.size && (c.characters || []).some((x) => [...focusSet].some((f) => String(x).includes(f) || f.includes(String(x))));

  const near = before.filter((c) => c.number >= strongFrom || hitFocus(c));
  const far = before.filter((c) => c.number < strongFrom && !hitFocus(c));
  const clipped = before.filter((c) => far.includes(c) && c.number < farStart);
  const lines = [];
  if (clipped.length) {
    lines.push(`更早的第 ${before[0].number}-${clipped[clipped.length - 1].number} 章（共 ${clipped.length} 章）已从近章记忆滑出；` +
      `上一句只给了一句摘要，需要原话/细节时：novel_memory op=recall query=关键词（确定性检索，带章号出处）。`);
  }
  const farIn = far.filter((c) => c.number >= farStart);
  if (farIn.length) {
    lines.push(`### 前情一句一章（第 ${farIn[0].number}-${farIn[farIn.length - 1].number} 章）`);
    for (const c of farIn) {
      const one = clampSummary((c.summary || byChapter.get(c.number)?.summary || "").split(/[。！？\n]/)[0] || "", 80);
      lines.push(`- 第${c.number}章《${c.title || ""}》：${one || "（无摘要）"}`);
    }
  }
  // 放不下时先丢远章那句摘要、再丢 near 最旧章的整块，保住近章（近章才是写这一章真正要接上的）。
  // 关键：trim 必须每次都能实际删掉内容并返回 true；删无可删返回 false，避免 while 空转死循环。
  const trim = () => {
    // 1) 先删「前情一句一章」里最靠后（最旧仍在 far 的一行）的一条
    const at = lines.findIndex((l) => l.startsWith("### 前情一句一章"));
    if (at >= 0) {
      const end = lines.findIndex((l, i) => i > at && l.startsWith("### "));
      const stop = end > 0 ? end : lines.length;
      // 该段除标题行外还有正文行才删
      if (stop - at > 1) { lines.splice(stop - 1, 1); return true; }
      // 只剩标题行，整段去掉
      lines.splice(at, stop - at); return true;
    }
    // 2) 没有 far 段可删时，删 near 里最旧的一章整块（从「### 最近几章」标题之后第一条章节行开始，删到下一个「- 第」或 「### 」为止），但至少保留最近一章
    const nearHead = lines.findIndex((l) => l.startsWith("### 最近几章"));
    if (nearHead >= 0) {
      // 收集 near 段内每个「- 第N章」块的起始下标
      const starts = [];
      for (let i = nearHead + 1; i < lines.length; i++) {
        if (lines[i].startsWith("### ")) break;
        if (/^- 第\s*\d+\s*章/.test(lines[i])) starts.push(i);
      }
      // 至少保留最近 1 章；块数为 1 时删无可删
      if (starts.length > 1) {
        const from = starts[0];
        const to = starts[1];
        lines.splice(from, to - from);
        return true;
      }
    }
    return false;
  };
  if (near.length) {
    lines.push("### 最近几章（写新章必须接上）");
    for (const c of near) {
      const m = byChapter.get(c.number) || {};
      const chars = (c.characters || m.characters || []).join("、");
      lines.push(`- 第${c.number}章《${c.title || ""}》${chars ? `｜出场：${chars}` : ""}${hitFocus(c) ? " · 与本章相关，单独调出" : ""}`);
      const summary = clampSummary(m.summary || c.summary || "", 240);
      if (summary) lines.push(`  摘要：${summary}`);
      if (m.events?.length) lines.push(`  关键事件：${m.events.slice(0, 8).join("；")}`);
      if (m.state) lines.push(`  结束时：${clampSummary(m.state, 200)}`);
      // 硬上限兜底：最多修剪 lines.length 次，防止极端数据下空转
      let guard = lines.length + 4;
      while (lines.join("\n").length > budgetChars && guard-- > 0) {
        if (!trim()) break; // 删无可删就停，宁超预算也不死循环
      }
    }
  }
  const text = lines.join("\n");
  return { text, chars: text.length, covered: before.length };
}

/* ------------------------------ 卷级记忆（L1） ------------------------------ */

export async function volumeMemory(root, { chapter, volumes, budgetChars = 1200 } = {}) {
  const n = Number(chapter) || 0;
  const vs = volumes?.length ? volumes : await loadVolumes(root);
  const cur = volumeOf(vs, n);
  if (!cur) return { text: "", chars: 0, volume: null };
  const { volumes: mem } = await loadMemoryRows(root);
  const lines = [];
  // 不假设 vs 已按 to 升序且不重叠：显式排序 + filter，避免中途 break 漏掉更早的卷
  const prior = vs
    .filter((v) => Number(v.to) < Number(cur.from))
    .sort((a, b) => Number(a.to) - Number(b.to));
  for (const v of prior) {
    const m = mem.find((x) => Number(x.to) === v.to);
    lines.push(`- ${v.title}（第${v.from}-${v.to}章）${m?.summary ? "：" + clampSummary(m.summary, 220) : "（还没做卷记忆）"}`);
  }
  if (!lines.length) return { text: "", chars: 0, volume: cur };
  let text = `前面各卷发生了什么（不要在新章里重新交代）：\n${lines.join("\n")}`;
  if (text.length > budgetChars) text = text.slice(0, budgetChars) + "…";
  return { text, chars: text.length, volume: cur };
}

/* ------------------------------ 卷底稿（卷记忆的素材） ------------------------------ */

export async function buildVolumeDigest(root, { chapter } = {}) {
  const n = Number(chapter) || 0;
  if (!n) throw new Error("需要 chapter（盘点哪一章所在的卷）");
  const vs = await loadVolumes(root);
  const v = volumeOf(vs, n);
  if (!v) throw new Error(`第${n}章落在任何已识别的大纲卷之外。先把大纲里的卷写成「第 a-b 章」的区间，或在细纲写入 volume.chapters`);
  const to = Math.min(v.to, n);
  const index = (await readIndex(root)).filter((c) => c.number >= v.from && c.number <= to);
  const { byChapter } = await loadMemoryRows(root);
  const rows = index.sort((a, b) => a.number - b.number).map((c) => {
    const m = byChapter.get(c.number) || {};
    return `第${c.number}章《${c.title || ""}》：${clampSummary(m.summary || c.summary || c.title || "", 160)}`;
  });
  return {
    volume: v, from: v.from, to, count: rows.length,
    text: rows.length ? rows.join("\n") : "（这一卷还没有正文）",
    dims: {
      mainline: "主线推进到哪一步（对比大纲本卷任务）",
      threads: "哪些支线/人物线被推进或丢下",
      relations: "关系变化（谁和谁从什么变成什么）",
      knowledge: "读者目前知道的真相 / 主角不知道的部分",
      carryover: "必须带进下一卷的未收线索",
      drift: "与大纲本卷任务不一致的地方",
    },
  };
}

/* ------------------------------ 人物状态（L0） ------------------------------ */

/** 「截至第 n 章，这个人知道什么、和谁是什么关系」。来源是章记忆的 knows/relations，没变化的章不占位置。 */
export async function characterState(root, { chapter, names = [] } = {}) {
  const n = Number(chapter) || 0;
  const want = names.filter(Boolean).map(String);
  if (!n || !want.length) return { text: "", touches: {} };
  const { byChapter } = await loadMemoryRows(root);
  const rows = [...byChapter.values()].filter((r) => Number(r.chapter) < n).sort((a, b) => a.chapter - b.chapter);
  const knows = new Map();
  const rel = new Map();
  const touches = Object.fromEntries(want.map((w) => [w, 0]));
  for (const r of rows) {
    for (const k of r.knows || []) {
      if (!k?.who || !k.learned) continue;
      const hit = want.find((w) => k.who.includes(w) || w.includes(k.who));
      if (!hit) continue;
      if (!knows.has(hit)) knows.set(hit, []);
      knows.get(hit).push({ chapter: Number(r.chapter), learned: k.learned });
      touches[hit] += 1;
    }
    for (const x of r.relations || []) {
      if (!x?.a || !x?.b || !x.change) continue;
      for (const who of [x.a, x.b]) {
        if (!want.includes(who)) continue;
        const other = who === x.a ? x.b : x.a;
        if (!rel.has(who)) rel.set(who, new Map());
        rel.get(who).set(other, { change: x.change, chapter: Number(r.chapter) });
        touches[who] += 1;
      }
    }
  }
  const lines = [];
  for (const who of want) {
    const ks = (knows.get(who) || []).slice(-4).map((k) => `第${k.chapter}章知道：${clampSummary(k.learned, 90)}`);
    const rs = [...(rel.get(who) || new Map()).entries()].slice(-4).map(([o, v]) => `与${o}：${clampSummary(v.change, 90)}（第${v.chapter}章）`);
    if (!ks.length && !rs.length) continue;
    lines.push(`- ${who}\n${[...ks, ...rs].map((x) => `  · ${x}`).join("\n")}`);
  }
  return { text: lines.join("\n"), touches };
}

/* ------------------------------ 人物关系表（简版关系图） ------------------------------ */

export const RELATIONS_FILE = "ledger/relations.json";

export async function loadRelations(root) {
  const v = await readJson(p(root, RELATIONS_FILE), { edges: [] }).catch(() => ({ edges: [] }));
  return Array.isArray(v?.edges) ? v.edges : [];
}

/** 从章记忆的 relations 汇总成一张边表；同一对人以最新章为准，重写章节后重跑即可修正。 */
export async function updateRelations(root, from = 1, to = Infinity) {
  const { byChapter } = await loadMemoryRows(root);
  const rows = [...byChapter.values()].filter((r) => Number(r.chapter) >= from && Number(r.chapter) <= to).sort((a, b) => a.chapter - b.chapter);
  if (!rows.length) return [];
  const key = (a, b) => [a, b].sort().join("|");
  const map = new Map((await loadRelations(root)).map((e) => [key(e.a, e.b), e]));
  for (const r of rows) {
    for (const x of r.relations || []) {
      if (!x?.a || !x?.b || !x.change) continue;
      const k = key(x.a, x.b);
      if (Number(map.get(k)?.chapter || 0) > Number(r.chapter)) continue;
      map.set(k, { a: x.a, b: x.b, state: x.change, chapter: Number(r.chapter) });
    }
  }
  const out = [...map.values()].sort((a, b) => a.chapter - b.chapter);
  await writeJson(p(root, RELATIONS_FILE), { edges: out });
  return out;
}

/** 上下文包用：和本章出场人物有关的现有关系（最多 20 条）。 */
export async function relationLines(root, names = []) {
  if (!names.length) return "";
  const hit = (await loadRelations(root)).filter((e) => names.includes(e.a) || names.includes(e.b)).slice(-20);
  return hit.map((e) => `- ${e.a} ↔ ${e.b}：${clampSummary(e.state, 80)}（第${e.chapter}章）`).join("\n");
}

/* ------------------------------ 回查（L3，点名才用） ------------------------------ */

/** 关键词拆成词：中文按 2 字滑窗，英文/数字按词。 */
function recallTerms(query) {
  const q = String(query || "").trim().toLowerCase();
  const out = new Set();
  for (const w of q.match(/[a-z0-9_]{2,}/g) || []) out.add(w);
  const han = q.replace(/[^\u4e00-\u9fa5]/g, "");
  for (let i = 0; i < han.length - 1; i++) out.add(han.slice(i, i + 2));
  return [...out];
}

/**
 * 旧记忆按关键词回查：正文切片原文 + 记忆事件/摘要 + 伏笔/细纲命中，每段都带章号出处。
 * 纯字符串匹配，不调模型、不联网，所以结果可核对、快、零成本。
 */
export async function recallMemory(root, { query, from, to, limit = 6, context = 160 } = {}) {
  const terms = recallTerms(query);
  if (!terms.length) return { ok: false, text: "给一个关键词（至少两个字），比如人物名、地点、物件、伏笔名。", hits: [] };
  const f = Number(from) || 1, t = Number(to) || Infinity;
  const idx = (await readIndex(root)).filter((c) => Number(c.number) >= f && Number(c.number) <= t);
  const { byChapter } = await loadMemoryRows(root);
  const fsRows = await readJsonl(p(root, "ledger/foreshadow.jsonl")).catch(() => []);
  const outRows = await readJsonl(p(root, "ledger/outline.jsonl")).catch(() => []);
  const score = (s) => terms.reduce((a, k) => a + (String(s || "").toLowerCase().split(k).length - 1), 0);

  const hits = [];
  for (const c of idx.sort((a, b) => a.number - b.number)) {
    const m = byChapter.get(Number(c.number)) || {};
    const s = score([c.title, c.summary, (c.characters || []).join(" "), m.summary, m.state, (m.events || []).join(" ")].join("\n"));
    // 正文只在记忆里没写（或摘要不足以回答）时才翻；每个命中章只留一处切片
    let quote = "", where = "记忆";
    let text = "";
    // 没摘要的老项目才翻原文；已有记忆的章不读全文（几百章全读会很慢）
    if (!m.summary && !c.summary) { try { text = await readText(p(root, c.file)); } catch { /* 文件丢了就只给记忆 */ } }
    if (text) {
      const re = new RegExp(terms.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "i");
      const at = text.search(re);
      if (at >= 0) { quote = text.slice(Math.max(0, at - context), at + context).replace(/\s+/g, " "); where = "原文"; }
    }
    const total = s + (quote ? 2 : 0);
    if (total > 0) hits.push({ chapter: Number(c.number), title: c.title || "", score: total, where, quote, summary: clampSummary(m.summary || c.summary || "", 160) });
  }
  // 伏笔 / 细纲里的线索也一并给（作者常问「那个钥匙到底哪章埋的」）
  for (const r of fsRows) {
    if (!r || r.__corrupt) continue;
    const s = score([r.name, r.note, r.source, r.hint, r.plantBeat].join(" "));
    if (s > 0) hits.push({ chapter: Number(r.plantedChapter) || 0, title: `伏笔「${r.name}」`, score: s, where: "伏笔账", quote: [r.plantBeat, r.hint, r.source].filter(Boolean).join("｜"), summary: r.note || "" });
  }
  for (const r of outRows) {
    if (!r || r.__corrupt || r.deleted) continue;
    const s = score([(r.beats || []).join(" "), r.openingState, r.endingState].join(" "));
    if (s > 0) hits.push({ chapter: Number(r.chapter) || 0, title: "细纲命中", score: s, where: "细纲", quote: (r.beats || []).find((b) => terms.some((k) => String(b).toLowerCase().includes(k))) || r.endingState || "", summary: "" });
  }
  hits.sort((a, b) => b.score - a.score || a.chapter - b.chapter);
  const top = hits.slice(0, Math.max(1, Math.min(20, Number(limit) || 6)));
  // 分档读：先用「一行摘要 + 命中处的小标题」，需要原文再 novel_chapter op=read
  const outlineOf = async (h) => {
    if (h.where !== "原文" && h.where !== "记忆") return "";
    if (outlineCache.has(h.chapter)) return outlineCache.get(h.chapter);
    let heads = [];
    try {
      const idxRow = idx.find((c) => Number(c.number) === h.chapter);
      const body = idxRow ? await readText(p(root, idxRow.file)) : "";
      heads = body.split("\n").filter((l) => /^\s*(\d+[.、]|#|第[一二三四五六七八九十百\d]+[节章])/.test(l)).map((l) => l.trim().slice(0, 24));
    } catch { heads = []; }
    const v = heads.slice(0, 5).join(" / ");
    outlineCache.set(h.chapter, v);
    return v;
  };
  const outlineCache = new Map();
  const lines = await Promise.all(top.map(async (h) => {
    const heads = await outlineOf(h);
    return `第${h.chapter}章《${h.title}》[${h.where}]${heads ? `\n小标题：${heads}` : ""}\n${clampSummary(h.quote || h.summary || "（命中标题/摘要）", 220)}`;
  }));
  return {
    ok: true, scope: { terms, from: f, to: Number.isFinite(t) ? t : "末章" }, hits: top, total: hits.length,
    text: top.length ? `回查「${query}」命中 ${hits.length} 处，按相关度给前 ${top.length} 处（带章号，可直接 novel_chapter op=read 看原文）：\n\n${lines.join("\n\n")}` : `没找到「${query}」相关的记忆或正文。换个说法（人名/地点/物件/伏笔名）再查。`,
  };
}

/* ------------------------------ 技能路由 ------------------------------ */

export const SHORT_PLATFORMS = ["知乎", "盐言", "盐选", "黑岩", "点众", "短篇"];

function isShort(opts = {}) {
  if (opts.length === "short") return true;
  if (opts.length === "long") return false;
  return SHORT_PLATFORMS.some((k) => String(opts.platform || "").includes(k));
}

/**
 * 「这一步该用哪个技能」的唯一定义处：面板/工具写进提示词，面板自己调模型时也拼同一份。
 * 每个动作只给必用 + 最多两个可选——给多了等于没给，模型会一个都不调。
 */
export const SKILL_ROUTES = {
  concept: {
    use: (o) => (isShort(o) ? ["story-short-scan"] : ["story-long-scan"]),
    opt: (o) => (isShort(o) ? ["story-short-write"] : ["story-long-write"]).concat(o.ref ? ["agent-reach"] : []),
    why: (o) => (isShort(o)
      ? "先加载 `story-short-scan`（看知乎盐言/黑岩/点众什么短篇在爆），需要手感再叠 `story-short-write`。榜单只当参考，不要完全照着排行和新书趋势写，优先做有辨识度的选题。"
      : "先加载 `story-long-scan`（看起点/番茄/七猫的排行与新书趋势），需要开篇手感再叠 `story-long-write`。榜单只当参考，不要完全照着排行和新书趋势写，优先做有辨识度的选题。")
      + (o.ref ? "填了对标书时，自带网页搜索查不到的话用 `agent-reach` 再搜一次它的简介。" : ""),
  },
  outline: { use: () => ["story-long-write"], opt: () => ["novel-creator"], why: () => "先加载 `story-long-write`（卷纲拆分与节奏），人物动机可选 `novel-creator`。" },
  world: { use: () => ["novel-creator"], opt: () => ["story-long-write"], why: () => "先加载 `novel-creator`（世界架构 + 角色心理），要埋长线可选 `story-long-write`。" },
  setup: {
    use: () => ["novel-creator"], opt: () => [],
    why: (o) => (o && o.scope === "characters"
      ? "先加载 `novel-creator`，用角色心理拆人物卡（定位/欲望/恐惧/底线/缺陷/语言指纹）。"
      : "先加载 `novel-creator`，用世界架构的方法拆势力/地点/物品/硬规则；这一轮不写人物卡。"),
  },
  foreshadow: { use: () => ["story-long-write"], opt: () => ["story-review"], why: () => "先加载 `story-long-write`（长篇伏笔节奏），想先审已有承诺再叠 `story-review`。" },
  outlines: { use: () => ["story-long-write"], opt: () => ["novel-creator"], why: () => "先加载 `story-long-write`（每拍的目标-阻碍-变化），人物一致性可选 `novel-creator`。" },
  write: { use: () => ["story-long-write", "novel-creator"], opt: () => [], why: () => "同时加载 `story-long-write`（按章节奏）与 `novel-creator`（人物欲望/缺陷一致）。" },
  deslop: { use: () => ["story-deslop"], opt: () => ["humanizer"], why: () => "先加载 `story-deslop`（中文网文逐段改写）；英文/散文惯性再叠 `humanizer`。" },
  review: { use: () => ["story-review"], opt: () => ["first-reader", "maoni-perspective", "fenghuo-perspective", "yuhua-perspective"], why: () => "先加载 `story-review`（多视角挑刺）；要真人感叠 `first-reader`，要作家视角只选其一。" },
  memory: { use: () => [], opt: () => [], why: () => "" },
  analyze: { use: () => ["story-long-analyze"], opt: () => ["story-short-analyze"], why: () => "长篇对标用 `story-long-analyze`，短篇对标用 `story-short-analyze`。" },
  import: { use: () => ["story-import"], opt: () => [], why: () => "加载 `story-import`，按它的规则把已有稿子解析成项目目录。" },
  cover: { use: () => ["story-cover"], opt: () => [], why: () => "加载 `story-cover`，按书名与题材出封面。" },
  envcheck: { use: () => ["story-setup"], opt: () => [], why: () => "加载 `story-setup`，核对技能与目录是否齐全。" },
};

/** 生成提示词末尾的「要加载的技能」几行；只列这一步真要用的。 */
export function skillBlock(action, opts = {}) {
  const r = SKILL_ROUTES[action];
  if (!r) return "";
  const use = r.use(opts).filter(Boolean);
  if (!use.length) return "";
  const opt = r.opt(opts).filter(Boolean);
  const tag = (s) => "`" + s + "`";
  return [
    "【这一步要加载的技能】",
    `- 必用：${use.map(tag).join("、")}`,
    opt.length ? `- 可选（最多再叠一个）：${opt.map(tag).join("、")}` : "",
    `- 为什么：${r.why(opts)}`,
    "- 技能只给方法，事实一律以账本/工具返回为准；不要加载这里没列出的技能。",
  ].filter(Boolean).join("\n");
}

export function packBudget(chars) {
  const n = Number(chars) || 0;
  return Math.min(24000, Math.max(16000, Math.round(n * 3.2)));
}

/**
 * 按段分配预算。必守段整段保留（并且记一笔被砍了多少字，而不是假装没事），
 * 可选段按权重平分剩余额度，各自截断并标注。
 * @param {{key,title,text,critical?:boolean,weight?:number,max?:number}[]} sections
 */
export function fitSections(sections, budget) {
  const critical = sections.filter((s) => s.critical);
  const optional = sections.filter((s) => !s.critical);
  const cap = (s, limit) => (s.text.length <= limit ? s.text : s.text.slice(0, Math.max(0, limit - 1)).trimEnd() + "…");

  // 必守段：先按各自 max 截一遍（比如上一章原文只留 900 字），再全部收下
  let criticalText = 0;
  const critOut = critical.map((s) => ({ key: s.key, title: s.title, text: cap(s, s.max || Infinity), shortened: Boolean(s.max && s.text.length > s.max) }));
  criticalText = critOut.reduce((a, x) => a + x.text.length, 0);

  // 可选段：权重平分；带 min 的段先保底，再按剩余权重重分（前情记忆不该被设定挤到只剩几百字）
  const remaining = Math.max(0, budget - criticalText);
  const mins = optional.map((s) => Math.min(Number(s.min) || 0, s.text.length, s.max || Infinity));
  const minTotal = mins.reduce((a, b) => a + b, 0);
  const pool = Math.max(0, remaining - minTotal);
  const totalW = optional.reduce((a, s) => a + (s.weight ?? 1), 0) || 1;
  const optOut = optional.map((s, i) => {
    let limit = mins[i] + Math.floor((pool * (s.weight ?? 1)) / totalW);
    if (s.max) limit = Math.min(limit, s.max);
    if (limit < 24) return { key: s.key, title: s.title, text: "", skipped: true };
    const text = s.text.length <= limit ? s.text : s.text.slice(0, Math.max(0, limit - 1)).trimEnd() + "…";
    return { key: s.key, title: s.title, text, truncated: text.length < s.text.length };
  });

  const dropped = critOut.filter((x) => x.shortened).map((x) => x.title);
  const shortened = optOut.filter((x) => x.truncated).map((x) => x.title);
  const skipped = optOut.filter((x) => x.skipped).map((x) => x.title);
  return { sections: [...critOut, ...optOut].filter((x) => x.text), dropped, shortened, skipped, budget, used: [...critOut, ...optOut].reduce((a, x) => a + (x.text || "").length, 0) };
}

