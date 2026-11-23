// 小说项目磁盘层：固定目录结构 + 原子写 + JSONL 账本 + 项目写锁。
// 所有工具共用这一层，保证"模型不许直接改账本、只能通过工具追加"。
import { appendFile, mkdir, open, readFile, readdir, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";

export const LAYOUT = {
  project: "project.json",
  bible: "bible.json",
  chapters: "chapters",
  chapterIndex: "chapters/index.json",
  ledger: "ledger",
  foreshadow: "ledger/foreshadow.jsonl",
  timeline: "ledger/timeline.jsonl",
  review: "review",
  drafts: "drafts",
  exports: "exports",
  usage: "metrics/usage.jsonl",
};

/* ------------------------------ 目录约定与写权限 ------------------------------ */

/** 新书默认落点：桌面/mine/xiaoshuo（可用 DSH_NOVEL_HOME 覆盖）。 */
export const DEFAULT_PROJECTS_DIR = process.env.DSH_NOVEL_HOME
  || path.join(os.homedir(), "Desktop", "mine", "xiaoshuo");

/** 允许新建项目的根目录：默认目录 + 临时目录 + 环境变量显式放开的目录。 */
export function allowedProjectRoots(extra = []) {
  const list = [
    DEFAULT_PROJECTS_DIR,
    os.tmpdir(),
    // macOS 临时目录 /var 是 /private/var 的软链，realpath 后是 /private/...，两种形态都要认
    "/private" + os.tmpdir(),
    "/tmp",
    ...String(process.env.DSH_NOVEL_ALLOWED_ROOTS || "").split(path.delimiter),
    ...(Array.isArray(extra) ? extra : [extra]),
  ].filter(Boolean).map((x) => path.resolve(String(x)));
  return [...new Set(list)];
}

function isInside(child, parent) {
  const c = path.resolve(child);
  const p = path.resolve(parent);
  return c === p || c.startsWith(p + path.sep);
}

const SYSTEM_ROOTS = ["/", "/System", "/Library", "/Applications", "/etc", "/usr", "/bin", "/sbin", "/private", "/var"];
const SYSTEM_PREFIXES = ["/System/", "/Library/", "/Applications/", "/etc/", "/usr/", "/bin/", "/sbin/", "/private/", "/var/"];

/** 临时目录按真实路径判：/tmp 与 /var 在 macOS 上都 realpath 成 /private/... */
async function insideTmp(abs) {
  const roots = [os.tmpdir(), "/tmp"];
  for (const root of roots) {
    if (isInside(abs, root)) return true;
    if (isInside(abs, await realpathLoose(root))) return true;
  }
  return false;
}

/**
 * 写权限闸：新建项目必须落在允许的根目录内；已有项目（含 project.json）允许原地读写。
 * 系统目录与家目录本身一律拒绝，避免一份带指令的导入稿把模型引到别处写文件。
 */
export async function assertWritableRoot(root, { creating = false, extraRoots = [] } = {}) {
  if (!path.isAbsolute(String(root || ""))) throw new Error(`项目路径必须是绝对路径：${root}`);
  // 软链会把「看起来在允许目录里」的路径指到别处：先解析真实路径再判白名单
  const abs = await realpathLoose(root);
  // 临时目录（测试、试写）本身在 /var 下，先放行，别被系统目录规则误伤
  if (await insideTmp(abs)) return abs;
  if (SYSTEM_ROOTS.includes(abs) || SYSTEM_PREFIXES.some((x) => abs === x.slice(0, -1) || abs.startsWith(x))) {
    throw new Error(`拒绝写入系统目录：${abs}`);
  }
  if (abs === path.resolve(os.homedir())) throw new Error("拒绝把家目录本身当成小说项目，请建一个子目录");
  if (!creating) return abs;
  const allowed = allowedProjectRoots(extraRoots);
  if (!allowed.some((base) => isInside(abs, base))) {
    throw new Error(`新项目只能建在 ${allowed.join(" 或 ")} 之内（要换位置请设 DSH_NOVEL_HOME 或 DSH_NOVEL_ALLOWED_ROOTS）：${abs}`);
  }
  return abs;
}

/** 目录浏览只读，但也不该把系统目录摊给模型看。 */
export async function assertBrowsableRoot(dir) {
  const abs = await realpathLoose(dir);
  if (await insideTmp(abs)) return abs;
  if (SYSTEM_ROOTS.includes(abs) || SYSTEM_PREFIXES.some((x) => abs === x.slice(0, -1) || abs.startsWith(x))) {
    throw new Error(`不浏览系统目录：${abs}`);
  }
  return abs;
}

/* ------------------------------ 项目写锁 ------------------------------ */
// 同一本书可能被会话、面板、两个并行会话同时写。JSONL 追加会交错，project.json 会后写覆盖。
// 做法：进程内按根目录重入计数（嵌套调用不重复加锁）+ 跨进程 .lock 文件（带过期抢占）。

const heldLocks = new Map();

export async function withProjectLock(root, fn, { timeoutMs = 20000, staleMs = 120000 } = {}) {
  const key = path.resolve(root);
  const cur = heldLocks.get(key);
  if (cur) {
    cur.depth += 1;
    try {
      return await fn();
    } finally {
      cur.depth -= 1;
      if (!cur.depth) heldLocks.delete(key);
    }
  }
  await ensureDir(key);
  const lockFile = path.join(key, ".novel-studio.lock");
  const started = Date.now();
  for (;;) {
    try {
      const fh = await open(lockFile, "wx");
      try {
        await fh.writeFile(JSON.stringify({ pid: process.pid, host: os.hostname(), at: new Date().toISOString() }));
      } finally {
        await fh.close();
      }
      break;
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
      // 崩溃残留：超过 staleMs 没释放的锁视为失效，抢占一次
      try {
        const st = await stat(lockFile);
        if (Date.now() - st.mtimeMs > staleMs) {
          await rm(lockFile, { force: true });
          continue;
        }
      } catch { /* 锁刚被释放，直接重试 */ }
      if (Date.now() - started > timeoutMs) {
        throw new Error(`这本书正被另一个会话写入（锁文件 ${lockFile}），等它写完再试；确认没人在写可删掉该锁文件`);
      }
      await new Promise((r) => setTimeout(r, 50 + Math.random() * 100));
    }
  }
  heldLocks.set(key, { depth: 1 });
  try {
    return await fn();
  } finally {
    heldLocks.delete(key);
    await rm(lockFile, { force: true }).catch(() => {});
  }
}

export const p = (root, ...rest) => path.join(root, ...rest);

/** 解析真实路径：存在就 realpath，不存在就解析父目录再拼末段，避免软链绕过白名单。 */
export async function realpathLoose(target) {
  const abs = path.resolve(String(target || ""));
  try {
    return await realpath(abs);
  } catch (error) {
    if (error.code !== "ENOENT" && error.code !== "ENOTDIR") return abs;
    const parent = await realpathLoose(path.dirname(abs));
    return path.join(parent, path.basename(abs));
  }
}

export async function ensureDir(dir) {
  await mkdir(dir, { recursive: true });
}

export async function readJson(file, fallback) {
  try {
    return JSON.parse(await readFile(file, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT" && fallback !== undefined) return structuredClone(fallback);
    throw new Error(`读取失败 ${file}: ${error.message}`);
  }
}

export async function writeJson(file, value) {
  await ensureDir(path.dirname(file));
  const tmp = `${file}.tmp-${process.pid}`;
  await writeFile(tmp, JSON.stringify(value, null, 2) + "\n", "utf8");
  await rename(tmp, file);
}

export async function readText(file) {
  return readFile(file, "utf8");
}

export async function writeText(file, text) {
  await ensureDir(path.dirname(file));
  const tmp = `${file}.tmp-${process.pid}`;
  await writeFile(tmp, text, "utf8");
  await rename(tmp, file);
}

export async function appendJsonl(file, record) {
  await ensureDir(path.dirname(file));
  await appendFile(file, JSON.stringify(record) + "\n", "utf8");
}

export async function readJsonl(file) {
  if (!existsSync(file)) return [];
  const raw = await readFile(file, "utf8");
  const out = [];
  for (const [i, line] of raw.split("\n").entries()) {
    const t = line.trim();
    if (!t) continue;
    try {
      out.push(JSON.parse(t));
    } catch {
      out.push({ __corrupt: true, line: i + 1, raw: t });
    }
  }
  return out;
}

export async function listFiles(dir) {
  if (!existsSync(dir)) return [];
  return (await readdir(dir)).filter((n) => !n.startsWith("."));
}

export async function projectRoots(dir) {
  const project = await readJson(p(dir, LAYOUT.project), null);
  if (!project) throw new Error(`不是一个小说项目目录（缺少 ${LAYOUT.project}）：${dir}`);
  return { project, biblePath: p(dir, LAYOUT.bible) };
}

export const pad3 = (n) => String(n).padStart(3, "0");

/** 章节文件名：001-章名.md —— 章名只保留中英文数字 */
export function chapterFilePath(root, number, title) {
  const safe = String(title || "未命名")
    .replace(/[^\p{Script=Han}A-Za-z0-9]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 30) || "未命名";
  return p(root, LAYOUT.chapters, `${pad3(number)}-${safe}.md`);
}
