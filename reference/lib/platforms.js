// 平台规则集：每个平台的篇幅区间、开头钩子、章末钩子、单段字数上限、对话比下限、标题格式。
// PRD v1 §3.3。作为确定性校验的依据，面板与 chapter_commit 共用。
export const PLATFORMS = {
  fanqie: {
    id: "fanqie", name: "番茄小说",
    wordsMin: 2000, wordsMax: 3500,
    openingHook: "前 3 章每章至少一次冲突升级，章末留钩子",
    chapterEndHook: true, maxParagraphChars: 120, dialogueMin: 0.15,
    titlePattern: "第N章 标题",
  },
  qidian: {
    id: "qidian", name: "起点中文网",
    wordsMin: 2500, wordsMax: 4000,
    openingHook: "黄金三章，开局给钩子", chapterEndHook: true,
    maxParagraphChars: 150, dialogueMin: 0.1,
    titlePattern: "第N章 标题",
  },
  jinjiang: {
    id: "jinjiang", name: "晋江文学城",
    wordsMin: 3000, wordsMax: 5000,
    openingHook: "开篇立人物关系", chapterEndHook: true,
    maxParagraphChars: 150, dialogueMin: 0.3,
    titlePattern: "不用「第N章」式标题，直接写标题名",
  },
  zongheng: {
    id: "zongheng", name: "纵横中文网",
    wordsMin: 2500, wordsMax: 4000,
    openingHook: "开局冲突明确", chapterEndHook: true,
    maxParagraphChars: 150, dialogueMin: 0.1,
    titlePattern: "第N章 标题",
  },
  generic: {
    id: "generic", name: "通用",
    wordsMin: 1500, wordsMax: 5000,
    openingHook: "开篇抓住读者", chapterEndHook: false,
    maxParagraphChars: 200, dialogueMin: 0.0,
    titlePattern: "第N章 标题",
  },
  // 短篇平台：走 story-short-* 那一套方法（选题扫短篇榜、拆解按短篇拆）
  zhihu: {
    id: "zhihu", name: "知乎盐言", short: true,
    wordsMin: 8000, wordsMax: 30000,
    openingHook: "第一段就要抛出矛盾或反转", chapterEndHook: true,
    maxParagraphChars: 120, dialogueMin: 0.2,
    titlePattern: "直接写标题，不用「第N章」",
  },
  heiyan: {
    id: "heiyan", name: "黑岩", short: true,
    wordsMin: 5000, wordsMax: 20000,
    openingHook: "开头直接进冲突", chapterEndHook: true,
    maxParagraphChars: 120, dialogueMin: 0.15,
    titlePattern: "直接写标题",
  },
  duanzhang: {
    id: "duanzhang", name: "点众短篇", short: true,
    wordsMin: 6000, wordsMax: 20000,
    openingHook: "开头三行内给冲突", chapterEndHook: true,
    maxParagraphChars: 120, dialogueMin: 0.15,
    titlePattern: "直接写标题",
  },
};

const ALIAS = {
  "番茄": "fanqie", "番茄小说": "fanqie",
  "起点": "qidian", "起点中文网": "qidian",
  "晋江": "jinjiang", "晋江文学城": "jinjiang",
  "纵横": "zongheng", "纵横中文网": "zongheng",
  "通用": "generic", "未定": "generic",
  "知乎": "zhihu", "知乎盐言": "zhihu", "盐言故事": "zhihu", "盐选": "zhihu",
  "黑岩": "heiyan", "黑岩小说": "heiyan",
  "点众": "duanzhang", "点众短篇": "duanzhang",
};

/** 把平台名/ID 归一成规则对象。认不出就回通用规则，绝不让校验因平台名崩掉。 */
export function platformRules(platform) {
  if (!platform) return PLATFORMS.generic;
  const key = String(platform).trim();
  if (PLATFORMS[key]) return PLATFORMS[key];
  if (ALIAS[key]) return PLATFORMS[ALIAS[key]];
  const hit = Object.values(PLATFORMS).find((p) => p.name === key);
  return hit || PLATFORMS.generic;
}

/** 按平台规则校验一章正文，返回 {pass, issues:[{code,severity,message}]}。 */
export function checkPlatformFormat(text, title, metrics, rules = PLATFORMS.generic, opts = {}) {
  const issues = [];
  const chars = metrics?.chars ?? 0;
  const hardMin = Number(opts.minChars) || 0;
  if (hardMin && chars < hardMin) {
    // 硬下限：长篇每章 1800 字起（项目侧统一传入；超短篇项目传 0）
    issues.push({ code: "words-below", severity: "hard", message: `${chars} 字，低于每章硬下限 ${hardMin} 字` });
  } else if (chars < rules.wordsMin) {
    issues.push({ code: "words-below", severity: "info", message: `${chars} 字，低于${rules.name}要求 ${rules.wordsMin} 字` });
  } else if (chars > rules.wordsMax) {
    issues.push({ code: "words-above", severity: "info", message: `${chars} 字，超过${rules.name}上限 ${rules.wordsMax} 字` });
  }
  const dr = metrics?.dialogueRatio ?? 0;
  if (dr < rules.dialogueMin) {
    issues.push({ code: "dialogue-low", severity: "info", message: `对话比 ${(dr * 100).toFixed(0)}%，低于${rules.name}建议 ${(rules.dialogueMin * 100).toFixed(0)}%` });
  }
  const maxPara = metrics?.paragraphMax ?? 0;
  if (maxPara > rules.maxParagraphChars) {
    issues.push({ code: "paragraph-too-long", severity: "info", message: `最长段落 ${maxPara} 字，超过单段上限 ${rules.maxParagraphChars} 字` });
  }
  if (rules.id === "jinjiang" && /^第\s*[0-9一二三四五六七八九十百零]+\s*章/u.test(String(title || ""))) {
    issues.push({ code: "title-pattern", severity: "info", message: `晋江不建议「第N章」式标题：${title}` });
  }
  return { pass: !issues.some((i) => i.severity === "mid" || i.severity === "hard"), issues };
}
