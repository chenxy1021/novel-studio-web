// novel-partner 桥：把工作室项目临时渲染成 novel-partner 的书目录，跑它的确定性检查。
//
// 为什么是桥而不是移植：novel-partner 的检查（8 字复读、POV、套话、疑似别名、复读行）
// 已经有一份被 254 项回归锁住的 Python 实现，在 JS 里再写一遍必然漂移。
// 这里只做三件事：造临时书目录 → 调 np.py check --json → 把 finding 映射成工作室的
// {severity, code, message, hint} 契约。
//
// 边界（有意为之）：
// - 只取文本级检查。时间线/伏笔/角色退场这类账本检查由 domain.js 自己做，更准。
// - 任何失败（没装 python3、没装 novel-partner、超时、解析失败）都只产出 info，绝不抛。
// - 临时目录用完即删，不往用户项目里写任何东西。
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const KEEP = new Set([
  "empty-chapter", "repeat-ngram", "duplicate-line", "cliche", "pov-shift", "canon-alias",
]);
const SEVERITY = { error: "high", warn: "mid", info: "info" };
const HINT = {
  "empty-chapter": "正文太短，先确认稿子贴全了",
  "repeat-ngram": "对照证据片段人工复核；≥5 次是硬伤，3–4 次先看是不是人名或成语",
  "duplicate-line": "相邻两行完全相同，多为粘贴重复",
  cliche: "一级套话，按 novel-continuity 的改法换成具体动作",
  "pov-shift": "场景之间人称主导翻转，确认是否有意换视角",
  "canon-alias": "疑似未登记称呼；确认后把别名登进人物卡",
};
const MAX_FINDINGS = 40;
const CONCURRENCY = 4;
const CHAPTER_TIMEOUT_MS = 8000;
const TOTAL_BUDGET_MS = 30000;

export function novelPartnerScript() {
  return process.env.DSH_NOVEL_NP
    || path.join(os.homedir(), ".dsh", "skills", "novel-partner", "scripts", "np.py");
}

function runFile(cmd, args, timeout) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout, maxBuffer: 8 * 1024 * 1024, env: process.env }, (err, stdout, stderr) => {
      resolve({ err, stdout: String(stdout || ""), stderr: String(stderr || "") });
    });
  });
}

let pyPromise;
function pythonBin() {
  if (!pyPromise) {
    pyPromise = (async () => {
      const cands = [process.env.DSH_NOVEL_PYTHON, "python3", "/opt/homebrew/bin/python3", "/usr/bin/python3"]
        .filter(Boolean);
      for (const bin of cands) {
        const r = await runFile(bin, ["-c", "import sys;print(sys.version_info[0])"], 4000);
        if (!r.err && r.stdout.trim() === "3") return bin;
      }
      return null;
    })();
  }
  return pyPromise;
}

const yamlSafe = (v) => String(v).replace(/[\r\n]+/g, " ").replace(/:/g, "：").trim();

async function writeShadow(dir, chapters, bible) {
  const bookDir = path.join(dir, "book");
  const charDir = path.join(dir, "canon", "characters");
  await mkdir(bookDir, { recursive: true });
  await mkdir(charDir, { recursive: true });

  for (const c of bible?.characters || []) {
    const name = String(c?.name || "").trim();
    if (!name) continue;
    const aliases = (Array.isArray(c.aliases) ? c.aliases : []).map(yamlSafe).filter(Boolean);
    const safe = name.replace(/[\\/:*?"<>|]/g, "_");
    const lines = ["---", `name: ${yamlSafe(name)}`];
    if (aliases.length) lines.push("aliases:", ...aliases.map((a) => `  - ${a}`));
    else lines.push("aliases: []");
    lines.push("---", "");
    await writeFile(path.join(charDir, `${safe}.md`), lines.join("\n"), "utf8");
  }

  // 空台账：不带表头会让 novel-partner 报 threads-format，那是假问题
  await writeFile(
    path.join(dir, "canon", "threads.md"),
    "| ID | 描述 | 埋设章 | 预期回收章 | 状态 |\n|---|---|---|---|---|\n",
    "utf8",
  );

  const files = [];
  for (const c of chapters) {
    const no = String(c.number).padStart(3, "0");
    const file = path.join(bookDir, `ch-${no}.md`);
    const title = yamlSafe(c.title || `第${c.number}章`);
    const body = String(c.text || "").trim();
    await writeFile(file, `---\nchapter: ${Number(c.number)}\ntitle: ${title}\n---\n${body}\n`, "utf8");
    files.push({ number: Number(c.number), file });
  }
  return files;
}

function mapOne(number, finding) {
  const sev = SEVERITY[finding?.level] || "info";
  const raw = String(finding?.message || "").trim();
  if (!raw) return null;
  const tagged = /第\s*\d+\s*章/.test(raw) ? raw : `第${number}章 ${raw}`;
  return {
    severity: sev,
    code: `np-${finding.check}`,
    message: tagged,
    hint: HINT[finding.check] || "来自 novel-partner 的确定性检查",
  };
}

/**
 * 跑 novel-partner 的文本级检查。返回工作室契约的 findings；永不抛异常。
 * @param {object} bible 工作室的 bible.json
 * @param {Array<{number:number,title?:string,text?:string}>} chapters 已读入正文的章节
 */
export async function novelPartnerFindings(bible, chapters) {
  const np = novelPartnerScript();
  if (!existsSync(np)) {
    return [{
      severity: "info", code: "np-unavailable",
      message: "novel-partner 未安装，文本体检跳过（字数/复读/套话/POV/别名）",
      hint: `找不到 ${np}；装到 ~/.dsh/skills/novel-partner，或用 DSH_NOVEL_NP 指定 np.py`,
    }];
  }
  const py = await pythonBin();
  if (!py) {
    return [{
      severity: "info", code: "np-unavailable",
      message: "本机找不到 python3，novel-partner 文本体检跳过",
      hint: "装 Python 3 或用 DSH_NOVEL_PYTHON 指定解释器",
    }];
  }
  if (!Array.isArray(chapters) || !chapters.length) return [];

  const started = Date.now();
  let tmp = null;
  const out = [];
  try {
    tmp = await mkdtemp(path.join(os.tmpdir(), "np-bridge-"));
    const files = await writeShadow(tmp, chapters, bible);
    let next = 0;
    let failed = 0;
    let skipped = 0;

    const worker = async () => {
      for (;;) {
        const i = next++;                       // 先领号再判预算，否则超时后原地打转
        if (i >= files.length) return;
        if (Date.now() - started > TOTAL_BUDGET_MS) { skipped += 1; continue; }
        const { number, file } = files[i];
        const r = await runFile(py, [np, "check", file, "--json"], CHAPTER_TIMEOUT_MS);
        if (r.err || !r.stdout.trim()) { failed += 1; continue; }
        let payload;
        try { payload = JSON.parse(r.stdout); } catch { failed += 1; continue; }
        const all = [
          ...(payload?.errors || []),
          ...(payload?.warnings || []),
          ...(payload?.info || []),
        ];
        for (const f of all) {
          if (out.length >= MAX_FINDINGS) return;
          if (!KEEP.has(f?.check)) continue;
          const mapped = mapOne(number, f);
          if (mapped) out.push(mapped);
        }
      }
    };
    await Promise.all(Array.from({ length: Math.min(CONCURRENCY, files.length) }, worker));

    if (failed) {
      out.push({
        severity: "info", code: "np-check-failed",
        message: `novel-partner 有 ${failed} 章没跑成（解释器报错或超时）`,
        hint: "单独跑一次 np.py check <章节文件> 看具体原因",
      });
    }
    if (skipped) {
      out.push({
        severity: "info", code: "np-incomplete",
        message: `超过 ${Math.round(TOTAL_BUDGET_MS / 1000)} 秒预算，约 ${skipped} 章未做文本体检`,
        hint: "章节多时属正常；需要全量可单独跑 novel-partner",
      });
    }
    if (out.length >= MAX_FINDINGS) {
      out.push({
        severity: "info", code: "np-truncated",
        message: `novel-partner 的发现超过 ${MAX_FINDINGS} 条，其余未列出`,
        hint: "这类问题通常是成片的复读或套话，先修前面的",
      });
    }
  } catch (err) {
    return [{
      severity: "info", code: "np-unavailable",
      message: `novel-partner 检查未运行：${err?.message || err}`,
      hint: "体检其余部分不受影响；修好后再跑一次",
    }];
  } finally {
    if (tmp) await rm(tmp, { recursive: true, force: true }).catch(() => {});
  }
  return out;
}
