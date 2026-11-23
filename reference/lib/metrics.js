// 文本度量 + AI 痕迹检测。全部确定性、可复现，不依赖模型判断。
// 目的：把"这篇写得像 AI"从主观评价变成可对比的数字。

const CJK = /[\u3400-\u4dbf\u4e00-\u9fff]/gu;
const LATIN_WORD = /[A-Za-z][A-Za-z'-]*/g;
const SENTENCE = /[^。！？!?…\n]+[。！？!?…]*/g;
const PARAGRAPH_SPLIT = /\n\s*\n/;
const DIALOGUE = /[“"]([^”"]*)[”"]/g;

/** 中文"字数"口径：汉字数 + 西文词数 */
export function countChars(text) {
  const cjk = (text.match(CJK) || []).length;
  const latin = (text.match(LATIN_WORD) || []).length;
  return cjk + latin;
}

/**
 * token 估算（只用于记账与预算对比，不追求分词器级精确）。
 * 中文按 ~1 token/字，ASCII 按 ~4 字符/token，标点折半。
 * 真实用量以模型返回的 usage 为准，没有时用这个数兜底。
 */
export function estimateTokens(text) {
  const s = String(text || "");
  if (!s) return 0;
  let cjk = 0;
  let ascii = 0;
  let punct = 0;
  for (const ch of s) {
    if (/[㐀-䶿一-鿿豈-﫿]/u.test(ch)) cjk += 1;
    else if (/[　-〿＀-￯]/u.test(ch)) punct += 1;
    else if (ch.codePointAt(0) < 128) ascii += 1;
    else cjk += 1;
  }
  return Math.ceil(cjk + punct * 0.5 + ascii / 4);
}

function std(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  const variance = values.reduce((a, b) => a + (b - mean) ** 2, 0) / values.length;
  return Math.sqrt(variance);
}

export function textMetrics(text) {
  const clean = text.replace(/\r\n/g, "\n").trim();
  const paragraphs = clean.split(PARAGRAPH_SPLIT).map((s) => s.trim()).filter(Boolean);
  const paraLens = paragraphs.map((s) => countChars(s));
  const sentences = (clean.match(SENTENCE) || []).map((s) => s.trim()).filter(Boolean);
  const sentLens = sentences.map((s) => countChars(s)).filter((n) => n > 0);
  const dialogueChars = [...clean.matchAll(DIALOGUE)].reduce((a, m) => a + countChars(m[1]), 0);
  const total = countChars(clean) || 1;
  const mean = paraLens.length ? paraLens.reduce((a, b) => a + b, 0) / paraLens.length : 0;
  const sentMean = sentLens.length ? sentLens.reduce((a, b) => a + b, 0) / sentLens.length : 0;
  return {
    chars: total,
    paragraphs: paragraphs.length,
    sentences: sentLens.length,
    dialogueRatio: +(dialogueChars / total).toFixed(3),
    paragraphMean: +mean.toFixed(1),
    paragraphMax: paraLens.length ? Math.max(...paraLens) : 0,
    paragraphBurstiness: +(mean ? std(paraLens) / mean : 0).toFixed(3),
    sentenceMean: +sentMean.toFixed(1),
    sentenceBurstiness: +(sentMean ? std(sentLens) / sentMean : 0).toFixed(3),
    dashPer1000: +(((clean.match(/——/g) || []).length / total) * 1000).toFixed(2),
    ellipsisPer1000: +(((clean.match(/……/g) || []).length / total) * 1000).toFixed(2),
  };
}

/** AI / 网文套路痕迹规则库。severity: high 必须改，mid 建议改，low 观察项 */
export const AI_TELL_RULES = [
  { id: "not-x-but-y", label: "不是A，而是B 对举句", severity: "high", re: /不是[^。！？\n]{1,20}[，,]?\s*(而是|是)[^。！？\n]{1,25}/g },
  { id: "rather-say", label: "与其说…不如说", severity: "high", re: /与其说[^。！？\n]{1,20}[，,]\s*不如说/g },
  { id: "as-if-density", label: "仿佛/宛如/犹如 比喻密度", severity: "mid", re: /(仿佛|宛如|犹如|好似){1}/g },
  { id: "air-froze", label: "空气凝固 / 时间静止 类陈词", severity: "high", re: /(空气(仿佛|似乎|好像)?(都)?(凝固|安静|静止)|时间(仿佛|似乎)?(静止|凝固)|落针可闻)/g },
  { id: "pupil-micro", label: "瞳孔微缩 / 眼神一暗 类表情包", severity: "mid", re: /(瞳孔(微|猛)?缩|眼神(一)?(暗|沉|冷)|嘴角(微微)?(勾|扬)起)/g },
  { id: "eyebrow-frown", label: "皱眉 类表情包", severity: "mid", re: /(皱着眉头|皱了皱眉|皱眉)/g },
  { id: "heart-thrill", label: "心中一凛 / 心神一震 类内心套话", severity: "mid", re: /(心中(一)?(凛|震|惊|沉)|心神(一)?(震|荡)|不由得|忍不住|下意识(地)?)/g },
  { id: "summary-close", label: "章末总结句（这一刻他终于明白…）", severity: "high", re: /(这一刻|那一瞬间|从今往后|他知道|她明白)[^。！？\n]{0,40}[。！？]\s*$/gm },
  { id: "triad", label: "三连排比 / 三词并列", severity: "low", re: /[^，。！？\n]{2,6}、[^，。！？\n]{2,6}、[^，。！？\n]{2,6}/g },
  { id: "empty-adj", label: "空洞形容词堆叠（无尽的/深深的/淡淡的）", severity: "mid", re: /(无尽|深深|淡淡|缓缓|静静|默默|微微)(的|地)/g },
  { id: "eye-cliche", label: "眼眸 / 目光深邃 类眼神陈词", severity: "mid", re: /(眼眸|目光(深邃|幽深|复杂))/g },
  { id: "inner-cliche", label: "心中一动 / 内心复杂 / 心情久久不能平静", severity: "mid", re: /(心中一动|内心复杂|心情久久不能平静)/g },
  { id: "explain-emotion", label: "直接解释情绪（他感到愤怒）", severity: "mid", re: /(感到|感觉到|心里(很|有些|无比))(愤怒|悲伤|害怕|紧张|难过|开心|痛苦|兴奋)/g },
];

export function detectAiTells(text, limit = 40) {
  const hits = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  for (const rule of AI_TELL_RULES) {
    const re = new RegExp(rule.re.source, rule.re.flags.includes("g") ? rule.re.flags : rule.re.flags + "g");
    let total = 0;
    const samples = [];
    for (const [i, line] of lines.entries()) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(line))) {
        total++;
        if (samples.length < 3) samples.push({ line: i + 1, text: m[0].slice(0, 40) });
        if (m[0].length === 0) re.lastIndex++;
      }
    }
    if (total) hits.push({ id: rule.id, label: rule.label, severity: rule.severity, count: total, samples, per1000: 0 });
  }
  const chars = countChars(text) || 1;
  for (const h of hits) h.per1000 = +((h.count / chars) * 1000).toFixed(2);
  return hits.sort((a, b) => b.per1000 - a.per1000).slice(0, limit);
}

/** 一句话体检结论，供工具输出首行使用 */
export function verdict(metrics, tells) {
  const high = tells.filter((t) => t.severity === "high").reduce((a, t) => a + t.count, 0);
  const mid = tells.filter((t) => t.severity === "mid").reduce((a, t) => a + t.count, 0);
  const density = +(((high + mid) / (metrics.chars || 1)) * 1000).toFixed(2);
  const flat = metrics.paragraphBurstiness < 0.45 || metrics.sentenceBurstiness < 0.5;
  // 阈值唯一定义在这里（域A口径）：needs_fix 只看「差」= high≥2 或密度 >2.5/千字。
  // 其余调用方（commit / 体检 / repair）直接读 level，不再各自叠一层判定。
  const level = density > 2.5 || high >= 2 ? "差" : density > 2 || high >= 1 ? "中" : "良";
  return { level, density, flatRhythm: flat, high, mid };
}

/**
 * 章尾钩子可执行判法：取最后两段（最多 200 字），满足任一即算「有钩子」。
 * 网文的钩子不止问句，还有发现/反转、意外动作、被打断、倒计时、
 * 对话收尾、短句留白。这里只做确定性提示，不拦提交。
 * 返回 { ok, reason }。
 */
export function checkChapterEndHook(text) {
  const clean = String(text || "").replace(/\r\n/g, "\n").trim();
  if (!clean) return { ok: false, reason: "正文为空，无章尾" };
  const paras = clean.split(/\n+/).map((s) => s.trim()).filter(Boolean);
  const tail = paras.slice(-2).join("").replace(/\s+/g, "").slice(-200);
  const lastPara = (paras[paras.length - 1] || "").replace(/\s+/g, "");
  const checks = [
    { k: "问句收尾", re: /(？|\?|吗[。！]?$|呢[。！]?$|难道|岂不|怎么|为何|为什么)/ },
    { k: "发现/反转", re: /(发现|看见|看到|意识到|原来|才明白|才知道|竟然是|竟不是|不料|没想到|不对|少了一个|多出来|不见了|变了|上面写着)/ },
    { k: "意外动作", re: /(突然|猛地|骤然|忽然|猛然|冷不丁)/ },
    { k: "被打断/有人到场", re: /(没说完|话没说完|戛然而止|停在半空|顿住|僵住|门开了|传来|脚步声|身后|有人)/ },
    { k: "倒计时/威胁", re: /(来不及|只剩|再晚|期限|到期|最后一天|今晚|明早|否则)/ },
    { k: "对话收尾", re: /[”"]$/ },
  ];
  for (const c of checks) if (c.re.test(tail)) return { ok: true, reason: `钩子：${c.k}` };
  // 短句独立成段收尾：网文常用的留白 / 砸钉子写法
  if (paras.length > 1 && lastPara && lastPara.length <= 10) return { ok: true, reason: "钩子：短句留白" };
  return { ok: false, reason: "章尾两段没有问句/发现反转/意外动作/打断/倒计时/留白，读者可能不追更" };
}
