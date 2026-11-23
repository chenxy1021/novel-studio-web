// dsh-novel-studio / 浏览器半边 —— PRD v1「AI 代笔工作台」
//
// 界面取向（PRD §4.7 + ui-ux-pro-max 设计系统）：
//   Minimalism & Swiss + 单一 creative pink CTA，导航/表单/数据区无衬线中性灰；
//   只有「正文阅读区」保留中文衬线（小说正文要有书卷气）。
//   作者只做 3 个决定：选题 / 本章过不过 / 方向改不改。其余交给 Agent。
//
//  布局：左书架（master）→ 点书进右工作台（detail）。
//   工作台页签：概览 / 大纲 / 世界观 / 人物 / 设定 / 伏笔 / 细纲(10章一段) / 进度 / 废章 / 设置
//   正文按 10 章一段批量写：先铺段落纲，再一章章写、一章章体检，哪章有问题只退那一章。
//
// 手写 __ModuleLoader__ 包装，不引构建链，只 require react 与 @deepseek-ai/cordis。
window.__ModuleLoader__.load({
  id: "dsh-novel-studio",
  factory: (require) => {
    const React = require("react");
    const h = React.createElement;
    const { useState, useEffect, useCallback, useRef } = React;

    const PANEL_ID = "novel-studio";
    const API = "/novel/api/";
    const LS_DIR = "nvs.dir";
    const LS_MODEL = "nvs.model";        // {provider, model} 面板选定的大模型
    const LS_AUTO_ARCHIVE = "nvs.autoArchive"; // 待确认章体完自动存档（默认开）
    const readAutoArchive = () => {
      try { const v = localStorage.getItem(LS_AUTO_ARCHIVE); return v === null ? true : v === "1"; } catch (_) { return true; }
    };
    const writeAutoArchive = (v) => { try { localStorage.setItem(LS_AUTO_ARCHIVE, v ? "1" : "0"); } catch (_) {} };
    const STYLE_ID = "nvs-style";
    let ROOT_CTX = null;                   // apply(ctx) 时存根 ctx，供页面跳会话用

    // 让「写第N章」跳到这本书的写小说会话，并把任务书预填进输入框
    async function openWritingSession(dir, prompt) {
      try {
        const uiWs = ROOT_CTX && ROOT_CTX.get ? ROOT_CTX.get("uiWorkspace") : null;
        const wsc = ROOT_CTX && ROOT_CTX.get ? ROOT_CTX.get("workspaces") : null;
        if (!uiWs || !wsc) return { ok: false, reason: "当前环境不支持跳转会话" };
        let r = null;
        try {
          r = await wsc.create({ path: dir });
        } catch (e) {
          // 已注册过的目录有的版本会直接报「已存在」，不算失败，下面按路径去列表里找
          if (!/exist|resolv|already/i.test((e && e.message) || "")) throw e;
        }
        // 兼容两种返回：{workspaceId,...} 或 {ok,value:{workspace:{workspaceId}}}
        // workspaces.create 返回的结构随版本变：{workspace:{workspaceId}} / {value:{workspace}} / 直接 id
        const pick = (v) => v && (v.workspaceId || (v.workspace && v.workspace.workspaceId) || (v.value && (v.value.workspaceId || (v.value.workspace || {}).workspaceId))) || null;
        let wid = pick(r);
        if (!wid) {
          // 已经建过这个目录时会报重复：去现有工作区列表里按路径找
          const list = wsc.list && wsc.list.getSnapshot ? wsc.list.getSnapshot() : null;
          const hit = (list && list.items || []).find((it) => it.path === dir);
          wid = hit && (hit.workspaceId || hit.id);
        }
        if (!wid) return { ok: false, reason: "没能打开工作区（返回：" + JSON.stringify(r).slice(0, 80) + "）" };
        // 刚建好的工作区可能还没进客户端列表，此时 startSession 会被宿主判成 unknown workspace
        const listed = () => {
          const snap = wsc.list && wsc.list.getSnapshot ? wsc.list.getSnapshot() : null;
          if (!snap || !Array.isArray(snap.items)) return true;
          return snap.items.some((it) => it.workspaceId === wid || it.id === wid);
        };
        for (let i = 0; i < 30 && !listed(); i += 1) await new Promise((res) => setTimeout(res, 50));
        // append：空白会话里已经有作者草稿时接在后面，不覆盖；宿主默认的 keep 会静默不动
        const next = { prompt, whenDraftExists: "append" };
        const conversation = ROOT_CTX.get ? ROOT_CTX.get("conversation") : null;
        const sessionsSvc = ROOT_CTX.get ? ROOT_CTX.get("sessions") : null;
        const put = conversation && conversation.input && conversation.input.requestDraftInitialization;
        let drafted = false;
        // beforeOpen 是宿主在「会话已保留、界面就绪」后同步调用的钩子，正好用来写草稿
        const beforeOpen = (sessionId) => {
          try {
            const binding = sessionsSvc && sessionsSvc.binding ? sessionsSvc.binding(sessionId) : null;
            if (binding && typeof put === "function") {
              drafted = put.call(conversation.input, binding, next) !== "blocked";
            }
          } catch (_) { drafted = false; }
        };
        if (typeof uiWs.openWorkspace === "function") {
          try {
            await uiWs.openWorkspace(wid, beforeOpen, {});
            if (drafted) return { ok: true };
            copyText(prompt);
            return { opened: true, reason: "草稿没写进去" };
          } catch (e) {
            copyText(prompt);
            return { ok: false, reason: (e && e.message) || String(e) };
          }
        }
        // 老版本没有 openWorkspace 时才退回 startSession（它失败只能靠宿主自己提示）
        await uiWs.startSession(wid, next);
        return { ok: true };
      } catch (e) {
        return { ok: false, reason: (e && e.message) || String(e) };
      }
    }
    function readModelSel() {
      try { const v = JSON.parse(localStorage.getItem(LS_MODEL) || "null"); return v && v.provider ? v : null; } catch (_) { return null; }
    }
    function saveModelSel(sel) {
      try { if (sel && sel.provider) localStorage.setItem(LS_MODEL, JSON.stringify(sel)); else localStorage.removeItem(LS_MODEL); } catch (_) {}
      // 同步到服务端：Agent 工具调用（如 novel_outline generate）读不到 localStorage
      if (sel && sel.provider && sel.model) postJSON("model", sel).catch(() => {});
    }

    /* --------------------------------- 样式 --------------------------------- */
    const CSS = `
    .nvs-root{
      /* Swiss 中性底 + creative pink 单 CTA；正文区另用衬线 */
      --nvs-bg:var(--dsw-alias-bg-base,#FAFAFA);
      --nvs-card:var(--dsw-alias-bg-layer-1,#fff);
      --nvs-card2:var(--dsw-alias-bg-layer-2,#f4f4f5);
      --nvs-line:var(--dsw-alias-border-l2,#E4E4E7);
      --nvs-line2:var(--dsw-alias-border-l3,#d4d4d8);
      --nvs-text:var(--dsw-alias-label-primary,#18181B);
      --nvs-sub:var(--dsw-alias-label-secondary,#475569);
      --nvs-dim:var(--dsw-alias-label-tertiary,#8a8f98);
      --nvs-accent:#EC4899;                 /* creative pink：只给主 CTA */
      --nvs-accent-soft:rgba(236,72,153,.10);
      --nvs-ink:#18181B;
      --nvs-ok:#16A34A; --nvs-warn:#D97706; --nvs-bad:#DC2626;
      --nvs-serif:"Songti SC","Noto Serif SC",宋体,Georgia,serif;
      --nvs-sans:"Inter",-apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
      --nvs-mono:var(--ds-font-family-code,ui-monospace,SFMono-Regular,Menlo,monospace);
      --nvs-r:12px;
      position:relative; width:100%; height:100%;
      display:flex; flex-direction:row; min-height:0;
      background:var(--nvs-bg); color:var(--nvs-text);
      font-family:var(--nvs-sans); font-size:13px; line-height:1.65;
      -webkit-font-smoothing:antialiased;
    }
    .nvs-root *{box-sizing:border-box}
    .nvs-body{flex:1 1 auto; min-height:0; min-width:0; overflow:auto;}
    .nvs-wrap{width:100%; max-width:880px; min-width:0; margin:0 auto; padding:24px 28px 64px;}

    /* hero */
    .nvs-hero{display:flex; align-items:center; gap:16px; padding:18px 20px; border:1px solid var(--nvs-line); border-radius:16px;
      background:var(--nvs-card); margin-bottom:16px}
    .nvs-hero .mark{width:44px;height:44px;flex:none;border-radius:12px;display:grid;place-items:center;background:var(--nvs-ink);color:#fff}
    .nvs-hero h1{margin:0;font-size:18px;font-weight:700;letter-spacing:-.01em}
    .nvs-hero .meta{color:var(--nvs-sub);font-size:12px;margin-top:2px}
    .nvs-hero .side{margin-left:auto;display:flex;align-items:center;gap:8px;flex:none}

    /* gate 状态条 */
    .nvs-gate{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:10px;margin-bottom:14px;
      border:1px solid var(--nvs-line);background:var(--nvs-card2);font-size:12.5px}
    .nvs-gate .phase{font-weight:700;flex:none;padding:2px 9px;border-radius:999px;background:var(--nvs-ink);color:#fff;font-size:11px}
    .nvs-gate .phase.await{background:var(--nvs-accent)}
    .nvs-gate .phase.writing{background:var(--nvs-ok)}
    .nvs-gate .reason{color:var(--nvs-sub);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}

    /* 导航 */
    .nvs-nav{position:sticky; top:0; z-index:5; margin-bottom:16px; border:1px solid var(--nvs-line); border-radius:12px;
      background:color-mix(in srgb,var(--nvs-card) 94%,transparent); backdrop-filter:blur(12px)}
    .nvs-nav-row{display:flex; align-items:center; gap:2px; padding:5px 6px; overflow-x:auto}
    .nvs-tab{appearance:none;border:1px solid transparent;background:transparent;color:var(--nvs-sub);font:inherit;
      padding:6px 12px;border-radius:9px;cursor:pointer;white-space:nowrap;display:inline-flex;align-items:center;gap:7px;transition:all .15s ease}
    .nvs-tab:hover{color:var(--nvs-text);background:var(--nvs-card2)}
    .nvs-tab[aria-selected="true"]{background:var(--nvs-ink);color:#fff;font-weight:600}
    .nvs-tab .dot{width:6px;height:6px;border-radius:50%;background:var(--nvs-warn);flex:none}
    .nvs-tab .dot.ok{background:var(--nvs-ok)}

    /* 卡片与行 */
    .nvs-card{background:var(--nvs-card);border:1px solid var(--nvs-line);border-radius:var(--nvs-r);padding:16px 18px}
    .nvs-card + .nvs-card{margin-top:12px}
    .nvs-card h3{margin:0 0 3px;font-size:13.5px;font-weight:650;display:flex;align-items:center;gap:8px}
    .nvs-card .desc{margin:0 0 14px;color:var(--nvs-sub);font-size:12.5px}
    /* 大纲页：两块编辑区 + 吸底保存栏 */
    .nvs-ol-sec{padding:16px 18px 14px}
    .nvs-ol-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:12px}
    .nvs-ol-head h3{margin:0;font-size:14px;font-weight:650;letter-spacing:-.01em}
    .nvs-ol-head .desc{margin:3px 0 0;color:var(--nvs-sub);font-size:12.5px;line-height:1.6;max-width:62ch}
    /* 大纲页：页头 + 卷目导航 + 正文 */
    .nvs-ol-top{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:14px}
    .nvs-ol-title{margin:0;font-size:21px;font-weight:700;letter-spacing:-.02em;line-height:1.3}
    .nvs-ol-sub{margin:5px 0 0;color:var(--nvs-sub);font-size:13px;line-height:1.6;max-width:62ch}
    .nvs-ol-meta{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
    .nvs-ol-chip{font-size:11.5px;color:var(--nvs-sub);border:1px solid var(--nvs-line);background:var(--nvs-card2);
      border-radius:999px;padding:2px 9px;font-variant-numeric:tabular-nums;white-space:nowrap}
    .nvs-ol-chip b{color:var(--nvs-ink);font-weight:650}
    .nvs-ol-cover{background:var(--nvs-card);border:1px solid var(--nvs-line);border-radius:var(--nvs-r);padding:12px 16px;margin-bottom:14px}
    .nvs-ol-cover .row{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:baseline;margin-bottom:8px}
    .nvs-ol-cover .k{font-size:12.5px;font-weight:600}
    .nvs-ol-cover .v{font-size:12px;color:var(--nvs-sub);font-variant-numeric:tabular-nums}
    .nvs-ol-track{height:6px;border-radius:999px;background:var(--nvs-card2);overflow:hidden}
    .nvs-ol-fill{height:100%;border-radius:999px;background:var(--nvs-accent);transition:width .35s ease}
    .nvs-ol-grid{display:grid;grid-template-columns:216px minmax(0,1fr);gap:14px;align-items:start}
    .nvs-ol-nav{position:sticky;top:12px;background:var(--nvs-card);border:1px solid var(--nvs-line);
      border-radius:var(--nvs-r);padding:12px;max-height:calc(100vh - 170px);overflow:auto}
    .nvs-ol-nav h4{margin:0 0 8px;font-size:11.5px;font-weight:650;color:var(--nvs-sub);letter-spacing:.02em}
    .nvs-ol-nav h4 + .nvs-ol-navlist{margin-bottom:12px}
    .nvs-ol-navlist{display:grid;gap:2px}
    .nvs-ol-navbtn{display:flex;align-items:baseline;gap:6px;width:100%;text-align:left;border:0;background:transparent;
      color:inherit;font:inherit;font-size:12.5px;line-height:1.5;padding:5px 7px;border-radius:7px;cursor:pointer}
    .nvs-ol-navbtn:hover{background:var(--nvs-card2)}
    .nvs-ol-navbtn:focus-visible{outline:2px solid var(--nvs-accent);outline-offset:1px}
    .nvs-ol-navbtn .n{flex:none;color:var(--nvs-dim);font-variant-numeric:tabular-nums;font-size:11.5px}
    .nvs-ol-navbtn .t{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .nvs-ol-navbtn .r{flex:none;margin-left:auto;color:var(--nvs-dim);font-size:10.5px;font-variant-numeric:tabular-nums}
    .nvs-ol-main{display:grid;gap:0;padding:0;overflow:hidden}
    .nvs-ol-main .nvs-ol-md{margin:0;border-left:0;border-right:0;border-radius:0;background:var(--nvs-card)}
    .nvs-ol-main .nvs-ol-md:focus{box-shadow:inset 0 0 0 2px var(--nvs-accent);border-color:transparent}
    .nvs-ol-bar{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;
      padding:11px 16px;border-bottom:1px solid var(--nvs-line);background:var(--nvs-card2)}
    .nvs-ol-bar .l{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:12.5px;font-weight:600}
    .nvs-ol-bar .r{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .nvs-ol-tips{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;
      padding:9px 16px 11px;border-top:1px solid var(--nvs-line);color:var(--nvs-dim);font-size:11.5px}
    .nvs-ol-empty{display:grid;gap:10px;padding:34px 26px;text-align:center;place-items:center}
    .nvs-ol-empty .ico{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;
      background:color-mix(in srgb,var(--nvs-accent) 10%,transparent);color:var(--nvs-accent);font-size:18px}
    .nvs-ol-empty h3{margin:2px 0 0;font-size:16px}
    .nvs-ol-empty p{margin:0;color:var(--nvs-sub);font-size:12.5px;line-height:1.7;max-width:46ch}
    .nvs-ol-empty .steps{display:grid;gap:5px;text-align:left;font-size:12.5px;color:var(--nvs-sub);margin:4px 0 6px}
    .nvs-ol-empty .steps b{color:var(--nvs-ink);font-weight:600}
    .nvs-filterbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 12px}
    .nvs-filterbar .nvs-input{width:auto;flex:1 1 180px;max-width:320px}
    .nvs-empty{padding:26px 20px;text-align:center;color:var(--nvs-sub);font-size:12.5px;line-height:1.7}
    .nvs-empty b{display:block;color:var(--nvs-ink);font-size:14px;margin-bottom:4px}
    @media (max-width:900px){
      .nvs-ol-grid{grid-template-columns:1fr}
      .nvs-ol-nav{position:static;max-height:240px;order:0}
    }
    .nvs-area.nvs-ol-md{height:clamp(460px,66vh,860px);min-height:460px;font-family:var(--nvs-serif);font-size:15px;line-height:2;max-width:100%;padding:16px 18px}
    .nvs-ol-tools{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-top:10px;padding-top:10px;border-top:1px dashed var(--nvs-line)}
    .nvs-ol-tools .st{min-width:0;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .nvs-badge-dirty{font-size:11.5px;font-weight:600;color:#B45309;background:color-mix(in srgb,#B45309 9%,transparent);
      border:1px solid color-mix(in srgb,#B45309 35%,transparent);border-radius:999px;padding:1px 9px}
    .nvs-badge-dirty::before{content:"●";font-size:8px;margin-right:5px;vertical-align:1px}
    .nvs-ol-savebar{position:sticky;bottom:0;z-index:4;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
      margin-top:14px;padding:11px 16px;border:1px solid var(--nvs-line);border-radius:var(--nvs-r);
      background:color-mix(in srgb,var(--nvs-card) 94%,transparent);backdrop-filter:blur(12px)}
    @media (max-width:720px){
      .nvs-area.nvs-ol-md,.nvs-md{height:380px;min-height:380px}
      .nvs-ol-savebar{position:static}
    }
    @media (prefers-reduced-motion:reduce){.nvs-ol-savebar,.nvs-ol-fill{transition:none}}
    .nvs-g2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    @media (max-width:720px){.nvs-g2{grid-template-columns:1fr}}
    .nvs-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin-bottom:12px}
    .nvs-stat{background:var(--nvs-card);border:1px solid var(--nvs-line);border-radius:var(--nvs-r);padding:13px 15px}
    .nvs-stat .n{font-size:23px;font-weight:700;line-height:1.15;letter-spacing:-.02em}
    .nvs-stat .l{color:var(--nvs-sub);font-size:12px;margin-top:1px}

    /* 一行设置 */
    .nvs-row{display:flex;align-items:flex-start;gap:14px;padding:11px 0;border-top:1px solid var(--nvs-line)}
    .nvs-row:first-of-type{border-top:0;padding-top:0}
    .nvs-row .lab{flex:0 0 132px;padding-top:6px}
    .nvs-row .lab b{display:block;font-weight:600;font-size:12.5px}
    .nvs-row .lab small{display:block;color:var(--nvs-dim);font-size:11.5px;line-height:1.5;margin-top:2px}
    .nvs-row .ctl{flex:1 1 auto;min-width:0}
    @media (max-width:600px){.nvs-row{flex-direction:column;gap:6px}.nvs-row .lab{flex:none;padding-top:0}}

    .nvs-input,.nvs-area,.nvs-select{width:100%;border:1px solid var(--nvs-line2);border-radius:8px;background:var(--nvs-card);
      color:var(--nvs-text);padding:7px 10px;font:inherit;outline:none;font-family:var(--nvs-sans)}
    .nvs-input:focus,.nvs-area:focus,.nvs-select:focus{border-color:var(--nvs-accent);box-shadow:0 0 0 3px var(--nvs-accent-soft)}
    .nvs-area{resize:vertical;line-height:1.75;min-height:74px}
    .nvs-input.big{font-size:15px;height:36px;font-weight:600}

    /* chips / seg */
    .nvs-chips{display:flex;flex-wrap:wrap;gap:7px}
    .nvs-chip{appearance:none;border:1px solid var(--nvs-line2);background:var(--nvs-card);color:var(--nvs-sub);font:inherit;
      padding:5px 12px;border-radius:999px;cursor:pointer;transition:all .15s ease;font-family:var(--nvs-sans)}
    .nvs-chip:hover{border-color:var(--nvs-dim);color:var(--nvs-text)}
    .nvs-chip[aria-pressed="true"]{background:var(--nvs-ink);border-color:var(--nvs-ink);color:#fff;font-weight:600}
    .nvs-seg{display:inline-flex;border:1px solid var(--nvs-line2);border-radius:9px;padding:3px;gap:2px;margin-bottom:16px;background:var(--nvs-card2)}
    .nvs-seg button{appearance:none;border:0;background:transparent;color:var(--nvs-sub);font:inherit;font-size:12.5px;
      padding:6px 14px;border-radius:7px;cursor:pointer;transition:all .15s ease;font-family:var(--nvs-sans)}
    .nvs-seg button:hover{color:var(--nvs-text)}
    .nvs-seg button.on{background:var(--nvs-card);color:var(--nvs-text);font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.08)}
    .nvs-steps{margin:14px 0 0;padding-left:20px;color:var(--nvs-sub);font-size:12px;line-height:2}
    .nvs-steps li::marker{color:var(--nvs-accent);font-weight:600}

    /* 按钮 */
    .nvs-btn{appearance:none;border:1px solid var(--nvs-line2);background:var(--nvs-card);color:var(--nvs-text);font:inherit;
      padding:7px 15px;border-radius:8px;cursor:pointer;display:inline-flex;align-items:center;gap:7px;white-space:nowrap;
      font-family:var(--nvs-sans);transition:all .15s ease}
    .nvs-btn:hover:not(:disabled){background:var(--nvs-card2)}
    .nvs-btn:disabled{opacity:.5;cursor:default}
    .nvs-btn.primary{background:var(--nvs-accent);border-color:transparent;color:#fff;font-weight:600}
    .nvs-btn.primary:hover:not(:disabled){filter:brightness(.95)}
    .nvs-btn.primary:disabled{background:var(--nvs-card2);color:var(--nvs-dim)}
    .nvs-btn.ghost{border-color:transparent;color:var(--nvs-sub)}
    .nvs-btn.ghost:hover:not(:disabled){color:var(--nvs-text);background:var(--nvs-card2)}
    .nvs-btn.sm{padding:4px 10px;font-size:12px;border-radius:7px}
    .nvs-btn.danger{border-color:color-mix(in srgb,var(--nvs-bad) 55%,transparent);color:var(--nvs-bad);background:transparent;font-weight:600}
    .nvs-btn.danger:hover:not(:disabled){background:color-mix(in srgb,var(--nvs-bad) 10%,transparent)}

    /* 交办卡 */
    .nvs-task{border:1px solid var(--nvs-line);border-radius:var(--nvs-r);padding:14px 16px;background:var(--nvs-card)}
    .nvs-task + .nvs-task{margin-top:10px}
    .nvs-task .top{display:flex;align-items:center;gap:10px}
    .nvs-task b{font-size:13px}
    .nvs-task .desc{color:var(--nvs-sub);font-size:12px;margin-top:2px}
    .nvs-task .prompt{margin-top:10px;padding:10px 12px;border-radius:8px;background:var(--nvs-card2);border:1px solid var(--nvs-line);
      font-family:var(--nvs-mono);font-size:11.5px;line-height:1.7;white-space:pre-wrap;word-break:break-word;color:var(--nvs-sub);max-height:180px;overflow:auto}
    .nvs-task .acts{display:flex;gap:8px;margin-top:10px}
    .nvs-tbl{width:100%;border-collapse:separate;border-spacing:0;border:1px solid var(--nvs-line);border-radius:10px;overflow:hidden;background:var(--nvs-card)}
    .nvs-tbl th{text-align:left;font-weight:600;font-size:11.5px;color:var(--nvs-sub);padding:7px 10px;background:var(--nvs-card2);border-bottom:1px solid var(--nvs-line);white-space:nowrap}
    .nvs-tbl th:not(:last-child),.nvs-tbl td:not(:last-child){border-right:1px solid var(--nvs-line)}
    .nvs-tbl td{padding:0;border-bottom:1px solid var(--nvs-line);vertical-align:middle}
    .nvs-tbl tr:last-child td{border-bottom:none}
    .nvs-tbl td input{border:none;background:transparent;width:100%;padding:8px 10px;font-size:13px;color:var(--nvs-ink);outline:none;font-family:inherit}
    .nvs-tbl td input:focus{background:var(--nvs-card2)}
    .nvs-tbl td input::placeholder{color:var(--nvs-faint,#a9a9b3)}
    .nvs-tbl td.act{width:1%;white-space:nowrap;padding:0 8px}
    .nvs-tbl td.cell{padding:7px 10px;font-size:13px;white-space:nowrap;line-height:1.4}
    .nvs-tbl td.cell.clip{max-width:240px;overflow:hidden;text-overflow:ellipsis}
    .nvs-tbl td.cell.clip-sm{max-width:110px;overflow:hidden;text-overflow:ellipsis}
    .nvs-tbl td.cell.clip-md{max-width:180px;overflow:hidden;text-overflow:ellipsis}
    .nvs-tbl .nvs-tbl-empty{padding:14px;text-align:center;color:var(--nvs-sub);font-size:12.5px}
    .nvs-tbl-wrap{display:grid;gap:8px;overflow-x:auto}

    /* -------- 人物工作台：左列表 + 右档案 -------- */
    .nvs-char-sub{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
    .nvs-char-sub .nvs-chip[aria-selected="true"]{background:var(--nvs-accent);border-color:var(--nvs-accent);color:#fff}
    .nvs-chars{display:grid;grid-template-columns:250px minmax(0,1fr);gap:14px;align-items:start}
    .nvs-char-side{position:sticky;top:10px;display:grid;gap:8px;min-width:0}
    .nvs-char-list{display:grid;gap:3px;max-height:620px;overflow:auto;padding-right:2px}
    .nvs-char-item{display:flex;align-items:center;gap:8px;width:100%;text-align:left;font:inherit;border:1px solid transparent;
      background:transparent;border-radius:9px;padding:7px 8px;cursor:pointer}
    .nvs-char-item:hover{background:var(--nvs-card)}
    .nvs-char-item:focus-visible{outline:2px solid var(--nvs-accent);outline-offset:1px}
    .nvs-char-item[aria-current="true"]{background:var(--nvs-card);border-color:var(--nvs-line);box-shadow:inset 3px 0 0 var(--nvs-accent)}
    .nvs-char-item-main{display:grid;min-width:0;flex:1 1 auto}
    .nvs-char-item-main b{font-size:12.5px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .nvs-char-item-main small{font-size:10.5px;color:var(--nvs-dim);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .nvs-tier-badge{flex:none;display:inline-grid;place-items:center;width:20px;height:20px;border-radius:6px;
      font:700 10px/1 var(--nvs-mono);background:var(--nvs-card2);color:var(--nvs-sub);border:1px solid var(--nvs-line)}
    .nvs-tier-badge.tS{background:color-mix(in srgb,var(--nvs-accent) 16%,transparent);color:var(--nvs-accent);border-color:color-mix(in srgb,var(--nvs-accent) 38%,transparent)}
    .nvs-tier-badge.tA{background:color-mix(in srgb,var(--nvs-ok) 12%,transparent);color:var(--nvs-ok);border-color:color-mix(in srgb,var(--nvs-ok) 30%,transparent)}
    .nvs-tier-badge.tB{background:var(--nvs-card2);color:var(--nvs-sub)}
    .nvs-tier-badge.tC{background:transparent;color:var(--nvs-dim)}
    .nvs-status-dot{flex:none;width:7px;height:7px;border-radius:999px;background:var(--nvs-ok)}
    .nvs-status-dot.dead{background:var(--nvs-bad)}
    .nvs-status-dot.missing{background:var(--nvs-warn)}
    .nvs-status-dot.exited{background:var(--nvs-dim)}
    .nvs-char-main{min-width:0;display:grid;gap:10px}
    .nvs-char-title{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
    .nvs-char-title > div:first-child{flex:1 1 auto;min-width:0;font-size:15px}
    .nvs-char-sec{border:1px solid var(--nvs-line);border-radius:10px;padding:12px 14px;background:var(--nvs-card)}
    .nvs-char-sec h4{margin:0 0 10px;font-size:12px;font-weight:700;letter-spacing:.02em;color:var(--nvs-sub)}
    .nvs-char-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px 12px}
    .nvs-char-grid .nvs-field{margin-bottom:0}
    @media (max-width:900px){
      .nvs-chars{grid-template-columns:1fr}
      .nvs-char-side{position:static}
      .nvs-char-list{max-height:220px}
    }
    @media (max-width:600px){.nvs-char-grid{grid-template-columns:1fr}}

    /* 章节行 */
    .nvs-ch{display:flex;align-items:center;gap:12px;padding:10px 4px;border-top:1px solid var(--nvs-line);cursor:pointer;transition:background .15s ease}
    .nvs-ch:first-child{border-top:0}
    .nvs-ch:hover{background:var(--nvs-card2)}
    .nvs-ch .num{font-family:var(--nvs-mono);font-size:11.5px;color:var(--nvs-dim);flex:none;width:34px}
    .nvs-ch .name{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .nvs-ch .chars{font-family:var(--nvs-mono);font-size:11px;color:var(--nvs-dim);flex:none}
    .nvs-ch .tag{font-size:11px;padding:1px 8px;border-radius:999px;border:1px solid var(--nvs-line);flex:none;font-weight:600}
    .nvs-ch .tag.ok{color:var(--nvs-ok);border-color:color-mix(in srgb,var(--nvs-ok) 45%,transparent);background:color-mix(in srgb,var(--nvs-ok) 8%,transparent)}
    .nvs-ch .tag.mid{color:var(--nvs-warn);border-color:color-mix(in srgb,var(--nvs-warn) 45%,transparent);background:color-mix(in srgb,var(--nvs-warn) 8%,transparent)}
    .nvs-ch .tag.bad{color:var(--nvs-bad);border-color:color-mix(in srgb,var(--nvs-bad) 45%,transparent);background:color-mix(in srgb,var(--nvs-bad) 8%,transparent)}
    .nvs-ch .tag.wait{color:#B45309;border-color:color-mix(in srgb,#B45309 45%,transparent);background:color-mix(in srgb,#B45309 8%,transparent)}

    .nvs-note{padding:10px 14px;border-radius:10px;border:1px solid var(--nvs-line);background:var(--nvs-card2);
      color:var(--nvs-sub);font-size:12.5px}
    .nvs-note.warn{border-color:color-mix(in srgb,var(--nvs-warn) 40%,transparent);background:color-mix(in srgb,var(--nvs-warn) 8%,transparent);color:var(--nvs-text)}
    .nvs-note.err{border-color:color-mix(in srgb,var(--nvs-bad) 40%,transparent);background:color-mix(in srgb,var(--nvs-bad) 8%,transparent);color:var(--nvs-text)}
    .nvs-note.ok{border-color:color-mix(in srgb,var(--nvs-ok) 40%,transparent);background:color-mix(in srgb,var(--nvs-ok) 8%,transparent);color:var(--nvs-text)}
    .nvs-hint{color:var(--nvs-dim);font-size:11.5px}
    .nvs-mono{font-family:var(--nvs-mono)}
    .nvs-flex{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .nvs-spacer{flex:1 1 auto}

    .nvs-field{display:grid;gap:6px;margin-bottom:14px}
    .nvs-field > label{font-size:11.5px;font-weight:600;color:var(--nvs-sub);letter-spacing:.02em}

    .nvs-toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:50;padding:9px 18px;border-radius:999px;
      background:var(--nvs-ink);color:#fff;font-size:12.5px;box-shadow:0 8px 24px rgba(0,0,0,.18)}
    .nvs-loading{display:grid;place-items:center;height:100%;color:var(--nvs-dim);font-size:12.5px}

    /* -------- 书架 + 详情 master-detail -------- */
    .nvs-shell{display:flex;flex:1 1 auto;min-width:0;min-height:0}
    .nvs-shelf{width:256px;flex:none;display:flex;flex-direction:column;min-height:0;
      border-right:1px solid var(--nvs-line);background:var(--nvs-card2)}
    .nvs-shelf-head{display:flex;align-items:center;gap:8px;padding:14px 12px 10px 16px}
    .nvs-shelf-head b{font-size:15px;font-weight:700;letter-spacing:-.01em}
    .nvs-shelf-list{flex:1 1 auto;min-height:0;overflow:auto;padding:2px 8px 14px}
    .nvs-shelf-empty{padding:18px 14px;color:var(--nvs-dim);font-size:12px;line-height:1.9}
    .nvs-book{position:relative;display:block;width:100%;text-align:left;font:inherit;border:1px solid transparent;
      background:transparent;border-radius:10px;padding:9px 10px 9px 14px;cursor:pointer;transition:background .15s ease,border-color .15s ease}
    .nvs-book:hover{background:var(--nvs-card)}
    .nvs-book:focus-visible{outline:2px solid var(--nvs-accent);outline-offset:1px}
    .nvs-book[aria-current="true"]{background:var(--nvs-card);border-color:var(--nvs-line);box-shadow:inset 3px 0 0 var(--nvs-accent)}
    .nvs-book .t{display:block;font-size:13.5px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .nvs-book .d{display:block;font-family:var(--nvs-mono);font-size:10px;color:var(--nvs-dim);margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .nvs-book .p{display:flex;align-items:center;gap:6px;margin-top:4px;font-size:11px;color:var(--nvs-sub)}
    .nvs-book .del{flex:none;margin-left:auto;display:inline-flex;align-items:center;justify-content:center;
      width:24px;height:24px;border:0;border-radius:6px;background:transparent;color:var(--nvs-dim);cursor:pointer;
      opacity:0;transition:opacity .15s ease,color .15s ease,background .15s ease}
    .nvs-book:hover .del,.nvs-book .del:focus-visible{opacity:1}
    .nvs-book .del:hover{color:var(--nvs-bad);background:color-mix(in srgb,var(--nvs-bad) 10%,transparent)}
    .nvs-detail{flex:1 1 auto;min-width:0;min-height:0;display:flex;flex-direction:column}
    .nvs-pane{flex:1 1 auto;min-width:0;min-height:0;display:flex;flex-direction:column}
    .nvs-pane .nvs-body{display:flex;flex-direction:column}
    .nvs-detail > *, .nvs-pane, .nvs-pane .nvs-wrap{min-width:0}

    /* 空状态 */
    .nvs-empty{flex:1 1 auto;display:grid;place-items:center;padding:40px 24px}
    .nvs-empty-in{text-align:center;max-width:420px}
    .nvs-empty-in .ic{width:56px;height:56px;margin:0 auto 14px;border-radius:16px;display:grid;place-items:center;
      background:var(--nvs-accent-soft);color:var(--nvs-accent)}
    .nvs-empty-in h2{margin:0 0 8px;font-size:20px;font-weight:700;letter-spacing:-.01em}
    .nvs-empty-in p{margin:0 0 18px;color:var(--nvs-sub);font-size:12.5px;line-height:1.9}

    /* 弹窗 */
    .nvs-modal{position:fixed;inset:0;z-index:60;display:grid;place-items:center;padding:20px;
      background:rgba(0,0,0,.32);backdrop-filter:blur(2px)}
    .nvs-modal-card{width:min(620px,100%);max-height:86vh;overflow:auto;background:var(--nvs-card);
      border:1px solid var(--nvs-line);border-radius:16px;padding:20px 24px 18px;box-shadow:0 18px 48px rgba(0,0,0,.22)}
    .nvs-modal-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
    .nvs-modal-head h2{margin:0;font-size:18px;font-weight:700}
    .nvs-x{margin-left:auto;border:0;background:transparent;color:var(--nvs-dim);cursor:pointer;padding:6px;border-radius:8px;display:inline-flex}
    .nvs-x:hover{color:var(--nvs-text);background:var(--nvs-card2)}
    .nvs-dirlist{max-height:280px;overflow:auto;border:1px solid var(--nvs-line);border-radius:10px;background:var(--nvs-card2)}
    .nvs-dirow{padding:9px 12px;font-size:13px;cursor:pointer;border-bottom:1px solid var(--nvs-line);display:flex;gap:6px;align-items:center}
    .nvs-dirow:last-child{border-bottom:0}
    .nvs-dirow:hover{background:color-mix(in srgb,var(--nvs-accent) 10%,transparent)}

    /* 正文字体（阅读区） */
    .nvs-prose{font-family:var(--nvs-serif);font-size:15px;line-height:2.05;white-space:pre-wrap}

    /* 大纲 / 世界观 markdown 预览 */
    .nvs-md{padding:16px 18px;height:clamp(460px,66vh,860px);overflow:auto;
      font-family:var(--nvs-serif);font-size:15px;line-height:2}
    .nvs-md h1,.nvs-md h2,.nvs-md h3,.nvs-md h4,.nvs-md h5,.nvs-md h6{margin:1.1em 0 .5em;line-height:1.5;font-weight:700}
    .nvs-md h1{font-size:21px}.nvs-md h2{font-size:18px}.nvs-md h3{font-size:16px}.nvs-md h4{font-size:14.5px}
    .nvs-md p{margin:.5em 0;white-space:pre-wrap}
    .nvs-md ul,.nvs-md ol{margin:.5em 0;padding-left:1.4em}
    .nvs-md li{margin:.2em 0}
    .nvs-md blockquote{margin:.6em 0;padding:2px 12px;border-left:3px solid var(--nvs-line2);color:var(--nvs-sub)}
    .nvs-md code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.88em;
      background:var(--nvs-card2);padding:1px 4px;border-radius:4px}
    .nvs-md pre{background:var(--nvs-card2);border:1px solid var(--nvs-line);border-radius:8px;
      padding:10px 12px;overflow:auto;white-space:pre-wrap}
    .nvs-md hr{border:0;border-top:1px solid var(--nvs-line);margin:1em 0}
    .nvs-md-tbl{overflow:auto;margin:.8em 0}
    .nvs-md-tbl table{border-collapse:collapse;width:100%;font-family:inherit;font-size:12.5px}
    .nvs-md-tbl th,.nvs-md-tbl td{border:1px solid var(--nvs-line);padding:6px 9px;text-align:left;vertical-align:top}
    .nvs-md-tbl th{background:var(--nvs-card2);font-weight:600;white-space:nowrap}
    .nvs-ol-bar .nvs-seg{margin-bottom:0}

    /* 体检项 */
    .nvs-find{display:flex;gap:10px;padding:10px 12px;border:1px solid var(--nvs-line);border-radius:9px;margin-top:8px;background:var(--nvs-card)}
    .nvs-find .sev{flex:none;font-size:10.5px;font-weight:700;padding:1px 8px;border-radius:999px;height:fit-content}
    .nvs-find .sev.high{background:color-mix(in srgb,var(--nvs-bad) 14%,transparent);color:var(--nvs-bad)}
    .nvs-find .sev.mid{background:color-mix(in srgb,var(--nvs-warn) 14%,transparent);color:var(--nvs-warn)}
    .nvs-find .sev.info{background:var(--nvs-card2);color:var(--nvs-sub)}
    .nvs-find .msg{min-width:0;flex:1 1 auto}
    .nvs-find .hint{color:var(--nvs-dim);font-size:11.5px;margin-top:2px}

    /* 伏笔三列 */
    .nvs-cols{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
    @media (max-width:760px){.nvs-cols{grid-template-columns:1fr}}
    .nvs-col-h{font-size:12px;font-weight:700;margin-bottom:8px;display:flex;align-items:center;gap:6px}
    .nvs-col-h .ct{font-family:var(--nvs-mono);font-size:11px;color:var(--nvs-dim);font-weight:400}
    .nvs-fs{border:1px solid var(--nvs-line);border-radius:9px;padding:9px 11px;background:var(--nvs-card);margin-bottom:8px;font-size:12.5px}
    .nvs-fs.overdue{border-color:color-mix(in srgb,var(--nvs-bad) 40%,transparent);background:color-mix(in srgb,var(--nvs-bad) 6%,transparent)}
    .nvs-fs .nm{font-weight:600}
    .nvs-fs .mt{color:var(--nvs-dim);font-size:11px;margin-top:3px}
    .nvs-pill{display:inline-block;font-size:10.5px;padding:0 7px;border-radius:999px;background:var(--nvs-card2);color:var(--nvs-sub);margin-right:5px}
    .nvs-pill.bad{background:color-mix(in srgb,var(--nvs-bad) 14%,transparent);color:var(--nvs-bad)}

    /* 选题候选卡 */
    .nvs-cand{border:1px solid var(--nvs-line);border-radius:12px;padding:14px 16px;background:var(--nvs-card);cursor:pointer;transition:all .15s ease}
    .nvs-cand:hover{border-color:var(--nvs-accent);box-shadow:0 0 0 3px var(--nvs-accent-soft)}
    .nvs-cand h4{margin:0 0 6px;font-size:15px;font-weight:700}
    .nvs-cand .line{color:var(--nvs-sub);font-size:12.5px;margin-bottom:6px}
    .nvs-cand .tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}

    /* 开书向导（分步） */
    .nvs-modal-card.wide{width:min(720px,100%)}
    .nvs-wiz-steps{display:flex;align-items:center;gap:6px;margin:2px 0 16px;flex-wrap:wrap}
    .nvs-wiz-step{display:flex;align-items:center;gap:6px;font-size:11.5px;color:var(--nvs-dim)}
    .nvs-wiz-step .n{width:18px;height:18px;border-radius:999px;display:grid;place-items:center;font-size:10.5px;font-weight:700;
      background:var(--nvs-card2);color:var(--nvs-sub);border:1px solid var(--nvs-line2)}
    .nvs-wiz-step.on{color:var(--nvs-text);font-weight:700}
    .nvs-wiz-step.on .n{background:var(--nvs-accent);color:#fff;border-color:var(--nvs-accent)}
    .nvs-wiz-step.done .n{background:var(--nvs-ok);color:#fff;border-color:var(--nvs-ok)}
    .nvs-wiz-sep{color:var(--nvs-dim);font-size:11px}
    .nvs-choice{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:6px 0 4px}
    @media (max-width:640px){.nvs-choice{grid-template-columns:1fr}}
    .nvs-choice-card{border:1px solid var(--nvs-line);border-radius:12px;padding:16px;background:var(--nvs-card);cursor:pointer;transition:all .15s ease;text-align:left}
    .nvs-choice-card:hover{border-color:var(--nvs-accent);box-shadow:0 0 0 3px var(--nvs-accent-soft)}
    .nvs-choice-card.on{border-color:var(--nvs-accent);box-shadow:0 0 0 3px var(--nvs-accent-soft)}
    .nvs-choice-card h4{margin:6px 0 5px;font-size:14.5px;font-weight:700}
    .nvs-choice-card p{margin:0;font-size:12px;color:var(--nvs-sub);line-height:1.7}
    .nvs-wiz-foot{display:flex;align-items:center;gap:10px;margin-top:18px;padding-top:14px;border-top:1px solid var(--nvs-line)}
    .nvs-wiz-outline{border:1px solid var(--nvs-line);border-radius:10px;background:var(--nvs-card2);padding:12px 14px;max-height:300px;overflow:auto;
      font-family:var(--nvs-serif);font-size:13.5px;line-height:1.9;white-space:pre-wrap}
    .nvs-busy{display:inline-flex;align-items:center;gap:8px;color:var(--nvs-sub);font-size:12.5px}
    .nvs-spin{width:14px;height:14px;border-radius:999px;border:2px solid var(--nvs-line2);border-top-color:var(--nvs-accent);animation:nvs-spin .8s linear infinite}
    @keyframes nvs-spin{to{transform:rotate(360deg)}}
    .nvs-think{display:flex;align-items:center;gap:10px;margin:0 0 12px;padding:10px 12px;border:1px solid var(--nvs-accent-soft);border-radius:10px;background:var(--nvs-accent-soft);color:var(--nvs-sub);font-size:12.5px}
    .nvs-think b{color:var(--nvs-text)}
    .nvs-think .bar{flex:1;height:4px;border-radius:999px;background:rgba(236,72,153,.18);overflow:hidden}
    .nvs-think .bar i{display:block;height:100%;width:38%;border-radius:999px;background:var(--nvs-accent);animation:nvs-think 1.6s ease-in-out infinite}
    @keyframes nvs-think{0%{transform:translateX(-100%)}100%{transform:translateX(300%)}}
    `;

    function injectStyles() {
      try {
        if (typeof document === "undefined") return;
        if (document.getElementById(STYLE_ID)) return;
        const el = document.createElement("style");
        el.id = STYLE_ID;
        el.textContent = CSS;
        document.head.appendChild(el);
      } catch (_) { /* 无 document 的测试环境 */ }
    }

    /* --------------------------------- 图标 --------------------------------- */
    const svg = (paths, size = 18, extra) =>
      h("svg", Object.assign({ width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true }, extra || {}), ...paths);

    const BookIcon = ({ size = 18 }) => svg([
      h("path", { key: 1, d: "M4 5.5A2 2 0 0 1 6 3.5h5v17H6a2 2 0 0 0-2 2z" }),
      h("path", { key: 2, d: "M20 5.5a2 2 0 0 0-2-2h-5v17h5a2 2 0 0 1 2 2z" }),
    ], size);
    const PlusIcon = ({ size = 14 }) => svg([h("path", { key: 1, d: "M12 5v14M5 12h14" })], size, { strokeWidth: 2 });
    const TrashIcon = ({ size = 14 }) => svg([
      h("path", { key: 1, d: "M4 7h16" }),
      h("path", { key: 2, d: "M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" }),
      h("path", { key: 3, d: "M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12" }),
    ], size);
    const DownloadIcon = ({ size = 14 }) => svg([
      h("path", { key: 1, d: "M12 3v12" }), h("path", { key: 2, d: "M7 11l5 5 5-5" }), h("path", { key: 3, d: "M4 21h16" }),
    ], size);

    /* --------------------------------- IO --------------------------------- */
    const q = (s) => encodeURIComponent(s || "");
    async function call(path, opts) {
      const res = await fetch(API + path, opts);
      const data = await res.json().catch(() => ({ ok: false, error: "返回不是 JSON" }));
      if (!res.ok || data.ok === false) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }
    const getJSON = (path) => call(path);
    const postJSON = async (path, body) => {
      const r = await call(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
      // 会话里用 novel_studio_session return 交回正文后，面板不用等窗口切回来也能刷新
      if (r && r.sessionReturned && typeof window.__nvsRefresh === "function") window.__nvsRefresh();
      return r;
    };

    const readDirs = () => { try { return [localStorage.getItem(LS_DIR)].filter(Boolean); } catch (_) { return []; } };
    const saveDir = (d) => { try { localStorage.setItem(LS_DIR, d); } catch (_) {} };
    const copyText = (text) => {
      try { if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(text); return true; } } catch (_) {}
      try {
        const ta = document.createElement("textarea");
        ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select(); document.execCommand("copy"); document.body.removeChild(ta);
        return true;
      } catch (_) { return false; }
    };

    // 开会话做的事：先让 AI 在本项目里改，改完把正文交回来，由面板落盘（面板开着就自动刷新）
    const sessionRecipe = (prompt, label) => [
      prompt,
      "",
      "【改完怎么交回面板】",
      "- 改动直接写进项目；用哪个工具、要不要回传正文，以上面的任务说明为准（设定条目 novel_bible upsert；大纲正文与世界观正文一律用 novel_studio_session op=return 回写，不要在会话里用 op=set 覆盖大纲）。",
      "- 最后再用 novel_studio_session return 把完整的大纲正文（markdown）和/或世界观正文交回面板，面板会据此立即刷新。",
      "- 只回一句「改好了」不算交回：面板拿不到正文，作者就看不到结果。",
      label ? `- 这次会话：${label}` : "",
    ].filter(Boolean).join("\n");
    // 开会话的公共流程：先给按钮「打开中」反馈，失败时把原因摆明，并兜底复制指令
    const runSession = async ({ dir, prompt, label, okMsg, toast, pending, setPending }) => {
      if (pending) return;
      if (setPending) setPending(label);
      let r;
      try {
        r = await openWritingSession(dir, sessionRecipe(prompt, label));
      } catch (e) { r = { ok: false, reason: (e && e.message) || String(e) }; }
      if (setPending) setPending(null);
      if (r.ok) { toast(okMsg); return; }
      const copied = copyText(sessionRecipe(prompt, label));
      if (r.opened) {
        toast(`会话已打开，但${r.reason || "草稿没写进去"}。${copied ? "指令已复制，粘贴给 AI 就行。" : "请手动把指令贴给 AI。"}`);
        return;
      }
      toast(`没能自动打开会话（${r.reason || "未知原因"}）。${copied ? "指令已复制，去任意会话里粘贴给 AI 就行。" : "请手动复制指令给 AI。"}`);
    };

    // 把 GET models 的返回摊平成下拉选项 [{value:"provider::model", label}]
    const modelOptions = (models, current) => {
      const out = [];
      if (models && Array.isArray(models.providers)) {
        for (const p of models.providers) {
          for (const m of (p.models || [])) {
            out.push({ value: p.id + "::" + m.id, label: (p.name || p.id) + " · " + (m.name || m.id) });
          }
        }
      }
      // 记住的/当前的选择不在列表里也要能显示出来
      const sel = current || (models && models.current) || null;
      if (sel && sel.provider) {
        const v = sel.provider + "::" + sel.model;
        if (!out.some((o) => o.value === v)) out.push({ value: v, label: (sel.provider) + " · " + (sel.model || "") + "（当前）" });
      }
      if (out.length === 0) out.push({ value: "::", label: "（没有可用模型）" });
      return out;
    };

    /* ------------------------------- 小组件 ------------------------------- */
    const Card = ({ title, desc, children, right }) =>
      h("div", { className: "nvs-card" },
        title ? h("h3", null, title, right ? h("span", { className: "nvs-spacer" }) : null, right || null) : null,
        desc ? h("p", { className: "desc" }, desc) : null,
        children);

    const Row = ({ label, hint, children }) =>
      h("div", { className: "nvs-row" },
        h("div", { className: "lab" }, h("b", null, label), hint ? h("small", null, hint) : null),
        h("div", { className: "ctl" }, children));

    // 各页统一页头：标题 / 一句话说明 / 指标 chips / 右侧操作。指标用文字+数字，不靠颜色传达。
    const PageHead = ({ title, desc, meta = [], actions = null }) =>
      h("div", { className: "nvs-ol-top", style: { marginBottom: 14 } },
        h("div", { style: { minWidth: 0 } },
          h("h2", { className: "nvs-ol-title" }, title),
          desc ? h("p", { className: "nvs-ol-sub" }, desc) : null,
          meta.length ? h("div", { className: "nvs-ol-meta" },
            meta.map((m, i) => h("span", { key: i, className: "nvs-ol-chip" }, m))) : null),
        actions ? h("div", { className: "nvs-flex", style: { gap: 8, flex: "none", flexWrap: "wrap" } }, actions) : null);

    const Chips = ({ value, options, onPick }) =>
      h("div", { className: "nvs-chips" }, options.map((o) =>
        h("button", {
          key: o, type: "button", className: "nvs-chip", "aria-pressed": value === o ? "true" : "false",
          onClick: () => onPick(value === o ? "" : o),
        }, o)));

    const Field = ({ label, children }) =>
      h("div", { className: "nvs-field" }, h("label", null, label), children);

    const thinkRow = (label) => h("div", { className: "nvs-think", role: "status" },
      h("span", { className: "nvs-spin", "aria-hidden": "true" }),
      h("span", null, h("b", null, "深度思考中"), ` · ${label}`),
      h("span", { className: "bar", "aria-hidden": "true" }, h("i")));

    const fmtWan = (n) => (n >= 10000 ? (n / 10000).toFixed(1).replace(/\.0$/, "") + " 万字" : (n || 0) + " 字");

    /* ------------------------------- 弹窗 ------------------------------- */
    const Modal = ({ title, onClose, children, wide }) => {
      useEffect(() => {
        const onKey = (e) => { if (e.key === "Escape" && onClose) onClose(); };
        try { window.addEventListener("keydown", onKey); } catch (_) {}
        return () => { try { window.removeEventListener("keydown", onKey); } catch (_) {} };
      }, [onClose]);
      return h("div", { className: "nvs-modal", role: "dialog", "aria-label": title,
          onClick: (e) => { if (e.target === e.currentTarget && onClose) onClose(); } },
        h("div", { className: "nvs-modal-card" + (wide ? " wide" : "") },
          h("div", { className: "nvs-modal-head" },
            h("h2", null, title),
            onClose ? h("button", { className: "nvs-x", "aria-label": "关闭", onClick: onClose }, "✕") : null),
          children));
    };

    /* ------------------------------ 目录选择器 ------------------------------ */
    // 直接浏览系统目录（GET /novel/api/browse），不用手打绝对路径。
    function DirPicker({ home, value, onPick, onClose }) {
      const [cur, setCur] = useState(value || home || "");
      const [data, setData] = useState(null);
      const [err, setErr] = useState("");
      const load = async (d) => {
        setErr("");
        try { const r = await getJSON("browse" + (d ? "?dir=" + q(d) : "")); setData(r); setCur(r.dir); }
        catch (e) { setErr(e.message); }
      };
      useEffect(() => { load(cur || null); }, []);
      const up = data && data.parent ? data.parent : null;
      return h(Modal, { title: "选择目录", onClose },
        h("div", { className: "nvs-flex", style: { marginBottom: 8 } },
          h("button", { className: "nvs-btn sm", disabled: !up, onClick: () => up && load(up) }, "↑ 上一级"),
          h("button", { className: "nvs-btn sm", onClick: () => load(home) }, "⌂ 主目录"),
          h("code", { className: "nvs-mono", style: { flex: "1 1 auto", fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--nvs-sub)" } }, cur || "…")),
        err ? h("div", { className: "nvs-note err", style: { marginBottom: 8 } }, err) : null,
        h("div", { className: "nvs-dirlist" },
          data && data.entries.length ? data.entries.map((e) =>
            h("div", { key: e.path, className: "nvs-dirow", role: "button",
              onClick: () => load(e.path) }, "📁 ", e.name)) : h("div", { className: "nvs-hint", style: { padding: 10 } }, "（这个目录下没有子目录）")),
        h("div", { className: "nvs-flex", style: { marginTop: 12, justifyContent: "flex-end" } },
          h("span", { className: "nvs-hint", style: { flex: "1 1 auto" } }, data && data.isProject ? "✓ 这个目录已经是一个小说项目" : "选好后点「用这个目录」"),
          h("button", { className: "nvs-btn primary", onClick: () => { if (onPick) onPick(cur); onClose(); } }, "用这个目录")));
    }

    /* ------------------------------- 开书向导 ------------------------------- */
    // 新流程（m03837）：①想法(自由输入，可选也可空) ②AI 出选题 ③选目录/初始化 → 直接进工作台
    // 不再有「怎么写」选择页、不再在向导里生成大纲/设定（这些放到工作台的「大纲」「设定」页做）。
    const WIZ_STEPS = ["想法", "选题", "目录"];
    // 每一步该加载哪个技能：提示词里的文字统一从 SKILL_ROUTES 生成，避免各处口径不一
    const SKILL_ROUTES = {
      write: { use: ["story-long-write", "novel-creator"], opt: [], why: "同时加载 `story-long-write`（按章节奏）与 `novel-creator`（人物欲望/缺陷一致）。" },
      deslop: { use: ["story-deslop"], opt: ["humanizer"], why: "先加载 `story-deslop`（中文网文逐段改写）；英文/散文惯性再叠 `humanizer`。" },
      review: { use: ["story-review"], opt: ["first-reader", "maoni-perspective", "fenghuo-perspective", "yuhua-perspective"], why: "先加载 `story-review`（多视角挑刺）；要真人感叠 `first-reader`，要作家视角只选其一。" },
      worldDeep: { use: ["novel-creator"], opt: ["maoni-perspective", "fenghuo-perspective"], why: "先加载 `novel-creator`（世界架构 + 角色心理）；想听作者式点评再叠一个视角。" },
      volume: { use: ["story-long-write"], opt: ["maoni-perspective", "fenghuo-perspective"], why: "先加载 `story-long-write`（卷纲拆分与节奏）；想听“怎么拆才够连载”再叠一个视角。" },
      shadow: { use: ["story-review"], opt: [], why: "加载 `story-review`，用它多视角审查的方法找出“已承诺未兑现 / 埋了没动”的线索。" },
      concept: { use: ["story-long-scan"], opt: ["story-long-write"], why: "先加载 `story-long-scan`（看排行与新书趋势），需要开篇手感再叠 `story-long-write`。" },
      conceptShort: { use: ["story-short-scan"], opt: ["story-short-write"], why: "先加载 `story-short-scan`（看知乎盐言/黑岩/点众什么短篇在爆），需要手感再叠 `story-short-write`。" },
      conceptRef: { use: ["story-long-scan"], opt: ["agent-reach"], why: "先加载 `story-long-scan`（看排行与新书趋势）；填了对标书时，联网查它的简介用 `agent-reach`。" },
      conceptShortRef: { use: ["story-short-scan"], opt: ["agent-reach"], why: "先加载 `story-short-scan`（看短篇在爆什么）；填了对标书时，联网查它的简介用 `agent-reach`。" },
      analyze: { use: ["story-long-analyze"], opt: ["story-short-analyze"], why: "长篇对标用 `story-long-analyze`，短篇对标用 `story-short-analyze`。" },
      import: { use: ["story-import"], opt: [], why: "加载 `story-import`，按它的规则把已有稿子解析成项目目录。" },
      cover: { use: ["story-cover"], opt: [], why: "加载 `story-cover`，按书名与题材出封面。" },
      envcheck: { use: ["story-setup"], opt: [], why: "加载 `story-setup`，核对技能与目录是否齐全。" },
    };
    // 文风库（和 lib/domain.js 的 STYLE_PRESETS 保持一致；以后加作家两边一起加）
    const STYLE_PRESETS = {
      fenghuo: { label: "烽火戏诸侯", skill: "fenghuo-perspective", hint: "文白夹杂、留白、判词式人物" },
      maoni: { label: "猫腻", skill: "maoni-perspective", hint: "古今混搭、猫式幽默、人物复杂" },
      yuhua: { label: "余华", skill: "yuhua-perspective", hint: "冷峻克制、短句、把感受写成动作" },
      aiqianshuidewuzhe: { label: "爱潜水的乌贼", skill: "aiqianshuidewuzhe-perspective", hint: "克苏鲁神秘感、英伦书面腔、冷静叙事、细节惊悚" },
      chendong: { label: "辰东", skill: "chendong-perspective", hint: "东方玄幻、气势磅礴、热血悲壮、苍凉宿命" },
      sanjiuyinyu: { label: "三九音域", skill: "sanjiuyinyu-perspective", hint: "都市异能、神明神话、中二热血、爽点密集、画面感强" },
      enyang: { label: "恩养", skill: "enyang-perspective", hint: "短篇悬疑志怪、民间技艺、冷峻反转、中式诡异" },
      liucixin: { label: "刘慈欣", skill: "liucixin-perspective", hint: "硬科幻、宇宙社会学、冷酷理性、宏大尺度、苍凉美学" },
    };
    function skillLines(key) {
      const r = SKILL_ROUTES[key];
      if (!r) return "";
      const tag = (s) => "`" + s + "`";
      return [
        "【这一步要加载的技能】",
        "- 必用：" + r.use.map(tag).join("、"),
        r.opt.length ? "- 可选（最多再叠一个）：" + r.opt.map(tag).join("、") : "",
        "- 为什么：" + r.why,
        "- 技能只给方法，事实一律以账本/工具返回为准；不要加载这里没列出的技能。",
      ].filter(Boolean).join("\n");
    }
    function NewBookWizard({ home, defaultDir, onClose, onCreated, toast }) {
      const [step, setStep] = useState(0); // 0 想法 / 1 选题 / 2 目录
      const [kw, setKw] = useState("");            // 作者自由输入的想法/方向/要求
      const [chapters, setChapters] = useState(300);   // 预计章节数，建项目时定死
      const [wpc, setWpc] = useState(3000);            // 每章字数，建项目时定死
      const lenKind = Number(chapters) <= 50 ? "short" : "long"; // 只用于选题的短/长套路
      const platform = "通用";                          // 不再让作者填发在哪
      const [refBook, setRefBook] = useState("");      // 对标书（选填）：只填书名
      const [contrast, setContrast] = useState(false);   // 想要强烈反差/意难平：选题往虐点方向出，建项目后大纲也会带上反命题表
      const [refStatus, setRefStatus] = useState(null); // 上次生成时对标书资料查没查到
      const [cands, setCands] = useState([]);
      const [pickId, setPickId] = useState("");
      const [genBusy, setGenBusy] = useState(false);
      const [models, setModels] = useState(null); // {available,current,providers}
      const [modelSel, setModelSel] = useState({ provider: "", model: "" });
      const avoidRef = useRef([]);
      const [dir, setDir] = useState("");
      const [touched, setTouched] = useState(false);
      const [browsing, setBrowsing] = useState(false);
      const [err, setErr] = useState("");
      const [busy, setBusy] = useState(false);
      const [created, setCreated] = useState(null); // {dir,title}

      const picked = cands.find((c) => c.id === pickId) || null;
      const suggestTitle = picked ? picked.title : "";
      const baseDir = defaultDir || (home ? `${home}/Desktop/mine/xiaoshuo` : "");
      const suggest = suggestTitle && baseDir ? `${baseDir}/${suggestTitle}` : "";
      useEffect(() => { if (!touched) setDir(suggest); }, [suggest, touched]);


      useEffect(() => {
        let alive = true;
        getJSON("models").then((r) => {
          if (!alive || !r) return;
          setModels(r);
          if (r.current && r.current.provider) setModelSel({ provider: r.current.provider, model: r.current.model });
        }).catch(() => {});
        return () => { alive = false; };
      }, []);

      // 真·让模型生成选题（换一批 = 用当前输入重新调模型）
      const genConcepts = async () => {
        if (genBusy) return;
        setGenBusy(true); setErr("");
        // 和手动输入的方向合成一段，题材不跑偏，但要求「最想要的东西最后被夺走」这一路
        const dirText = [kw.trim(), contrast ? "要强反差、意难平：主角最想要或最骄傲的东西最后被夺走，落到他最不想成为的样子；结局不要圆满。" : ""].filter(Boolean).join("；");
        try {
          // 换一批：把这一批和之前各批一起带回去，避免连着几轮都出同一套骨架
          const avoid = avoidRef.current
            .concat(cands.map((c) => `${c.title}｜${c.genre || ""}｜${c.oneLine || ""}`))
            .slice(-24);
          const r = await postJSON("concepts", {
            direction: dirText, elements: dirText, totalWords: (Number(chapters) || 300) * (Number(wpc) || 3000),
            targetChapters: Math.max(1, Math.round(Number(chapters) || 300)),
            wordsPerChapter: Math.max(200, Number(wpc) || 3000),
            platform, length: lenKind,
            referenceBook: refBook.trim() || undefined,
            avoid: avoid.length ? avoid : undefined,
            provider: modelSel.provider || undefined, model: modelSel.model || undefined,
          });
          setCands(r.concepts || []);
          avoidRef.current = avoid;
          setRefStatus(Array.isArray(r.reference) ? r.reference : null);
          setPickId("");
          if (!r.concepts || r.concepts.length === 0) setErr("模型没给出候选，换个想法再试试");
        } catch (e) {
          setErr(e.message || "生成失败");
        } finally {
          setGenBusy(false);
        }
      };

      const toPicking = () => {
        setErr("");
        setStep(1);
        genConcepts(); // 进选题步就直接让模型出一批
      };

      const addOwnCandidate = () => {
        // 自己设定：用一个小表单收书名+一句话，作为唯一候选
        setErr("__self_form__");
      };

      const createProject = async () => {
        if (!picked || busy) { if (!picked) setErr("先挑一个选题"); return; }
        setBusy(true); setErr("");
        try {
          const finalDir = (dir.trim() || suggest);
          const tCh = Math.max(1, Math.round(Number(chapters) || 300));
          const r = await postJSON("init", {
            dir: finalDir, title: picked.title, genre: picked.genre, platform: picked.platform,
            targetChapters: tCh, wordsPerChapter: Math.max(200, Number(wpc) || 3000),
            tone: contrast ? "contrast" : undefined,
            referenceBook: refBook.trim() || undefined,
            concepts: cands, selectedConceptId: picked.id,
          });
          saveDir(r.dir);
          if (contrast) { try { await postJSON("setup", { dir: r.dir, tone: "contrast" }); } catch (_) {} }
          setCreated({ dir: r.dir, title: picked.title });
          setBusy(false);
          setStep(2); // 目录已建，可以进工作台
        } catch (e) { setErr(e.message); setBusy(false); }
      };

      const finish = () => {
        if (created) onCreated(created.dir);
      };

      /* --- 各步视图 --- */
      const stepsBar = h("div", { className: "nvs-wiz-steps" },
        WIZ_STEPS.map((label, i) => {
          const curIdx = ({ 0: 0, 1: 1, 2: 2 })[step];
          const cur = i === curIdx;
          const done = i < curIdx;
          return h(React.Fragment, { key: label },
            i > 0 ? h("span", { className: "nvs-wiz-sep" }, "›") : null,
            h("span", { className: "nvs-wiz-step" + (cur ? " on" : "") + (done ? " done" : "") },
              h("span", { className: "n" }, done ? "✓" : String(i + 1)), label));
        }));

      const modelPicker = () => h(Field, { label: "用哪个模型生成选题" },
        models && models.available === false
          ? h("div", { className: "nvs-note warn" }, "当前没有可用模型，无法生成选题；请先在下面选一个模型。")
          : h("div", { className: "nvs-flex", style: { alignItems: "center", gap: 8, flexWrap: "wrap" } },
              h("select", {
                className: "nvs-input", style: { width: "auto", minWidth: 200 },
                value: modelSel.provider + "::" + modelSel.model,
                onChange: (e) => { const [p, m] = e.target.value.split("::"); const next = { provider: p, model: m }; setModelSel(next); saveModelSel(next); },
              },
                modelOptions(models).map((o) => h("option", { key: o.value, value: o.value }, o.label))),
              h("span", { className: "nvs-hint" }, "默认用 DSH 当前模型，可切换")));

      // 步骤 0：想法（自由输入，也可留空让 AI 随便想）
      const step0 = h("div", null,
        h("p", { style: { margin: "0 0 12px", color: "var(--nvs-sub)", fontSize: 13, lineHeight: 1.8 } },
          "说说你想写个什么故事。只有大概方向也行，什么都不填也行——AI 会给你出几个选题，你挑一个。"),
        h(Field, { label: "你的想法 / 大概方向 / 要求（选填）" },
          h("textarea", {
            className: "nvs-input", style: { minHeight: 96, fontFamily: "var(--nvs-serif)", lineHeight: 1.9 },
            placeholder: "例如：少年背着师门血仇下山，遇到一个不肯透露身份的女子；主线是复仇与抉择，想要一点克苏鲁味道，别太玛丽苏。",
            value: kw, onChange: (e) => setKw(e.target.value),
          })),
        h(Field, { label: "基调", hint: "决定了选题往哪个方向出，之后生成大纲也会按这个基调排结构" },
          h("label", { className: "nvs-flex", style: { gap: 8, cursor: "pointer", fontSize: 13 } },
            h("input", { type: "checkbox", checked: contrast, onChange: (e) => setContrast(e.target.checked) }),
            "反差虐点（主角越想要的越被夺走，结局不圆满）")),
        h(Field, { label: "预计章节数", hint: "建项目时定死，之后不能改" },
          h("div", { className: "nvs-flex" },
            h("input", { className: "nvs-input", type: "number", min: 1, style: { width: 140 }, value: chapters, onChange: (e) => setChapters(e.target.value) }),
            h("span", { className: "nvs-hint" }, "章，约 " + Math.max(1, Math.round(((Number(chapters) || 0) * (Number(wpc) || 0)) / 10000)) + " 万字"))),
        h(Field, { label: "每章字数", hint: "建项目时定死，之后不能改" },
          h("div", { className: "nvs-flex" },
            h("input", { className: "nvs-input", type: "number", min: 200, step: 100, style: { width: 140 }, value: wpc, onChange: (e) => setWpc(e.target.value) }),
            h("span", { className: "nvs-hint" }, "字 / 章"))),
        h("p", { className: "nvs-hint", style: { margin: "-6px 0 12px" } },
          "这两个数写进项目后不能再改；选题、大纲、伏笔的数量都会按这个体量来配。"),
        h(Field, { label: "对标书（选填）", hint: "只填书名；多本用逗号分隔。选题会照它的路子来，不抄它的人和情节" },
          h("div", null,
            h("input", {
              className: "nvs-input", placeholder: "例如：我在废土世界扫垃圾，诡秘之主。没有就留空",
              value: refBook, onChange: (e) => { setRefBook(e.target.value); setRefStatus(null); },
            }),
            refStatus && refStatus.length
              ? h("div", { className: "nvs-hint", style: { marginTop: 4 } },
                  refStatus.map((x) => x.found ? `已查到《${x.title}》的资料` : `没查到《${x.title}》的资料，只按书名判断`).join("；"))
              : null)),
        modelPicker(),
        err ? h("div", { className: "nvs-note err", style: { marginTop: 12 } }, err) : null,
        h("div", { className: "nvs-wiz-foot" },
          h("button", { className: "nvs-btn primary", onClick: toPicking }, "下一步：让 AI 出选题 →")));

      // 步骤 1：选题（真·模型生成）
      const step1 = h("div", null,
        h("p", { style: { margin: "0 0 12px", color: "var(--nvs-sub)", fontSize: 13, lineHeight: 1.8 } },
          genBusy
            ? "正在让 AI 出选题…"
            : (cands.length
                ? "下面是 AI 按你的想法出的候选，点一个选中；不满意点「换一批」重出。"
                : "点「生成选题」让 AI 按你的想法出 3 个候选。")),
        genBusy ? thinkRow("正在分析想法和对标书") : null,
        modelPicker(),
        h("div", { style: { display: "grid", gap: 10 } },
          cands.map((c) => h("button", {
            key: c.id, type: "button", className: "nvs-cand", style: pickId === c.id ? { borderColor: "var(--nvs-accent)", boxShadow: "0 0 0 3px var(--nvs-accent-soft)" } : null,
            onClick: () => { setPickId(c.id); setErr(""); },
          },
            h("h4", null, c.title, pickId === c.id ? h("span", { className: "nvs-pill", style: { marginLeft: 8, background: "var(--nvs-accent)", color: "#fff" } }, "已选") : null),
            c.titleOptions && c.titleOptions.length ? h("div", { className: "line", style: { fontSize: 12, color: "var(--nvs-sub)" } }, "备选书名：" + c.titleOptions.join(" ／ ")) : null,
            h("div", { className: "line" }, c.oneLine),
            c.hitRate ? h("div", { className: "line", style: { fontSize: 12 } },
              h("span", { className: "nvs-pill", style: { background: c.hitRate === "high" ? "#e5484d" : c.hitRate === "mid" ? "#f5a623" : "var(--nvs-sub)", color: "#fff" } },
                "爆款率 " + ({ high: "高", mid: "中", low: "低" }[c.hitRate] || c.hitRate)),
              c.hitReason ? h("span", { style: { color: "var(--nvs-sub)", marginLeft: 8 } }, c.hitReason) : null) : null,
            h("div", { className: "line" }, c.synopsis || ""),
            c.business || c.risk ? h("div", { className: "line", style: { fontSize: 12, color: "var(--nvs-sub)" } }, [c.business ? "商业评估：" + c.business : "", c.risk ? "风险：" + c.risk : ""].filter(Boolean).join("；")) : null,
            h("div", { className: "tags" }, c.genre ? h("span", { className: "nvs-pill" }, c.genre) : null)))),
        err ? h("div", { className: "nvs-note err", style: { marginTop: 12 } }, err) : null,
        h("div", { className: "nvs-wiz-foot" },
          h("button", { className: "nvs-btn ghost", disabled: genBusy, onClick: genConcepts }, genBusy ? "生成中…" : (cands.length ? "换一批" : "生成选题")),
          h("span", { className: "nvs-spacer" }),
          h("button", { className: "nvs-btn primary", disabled: !pickId, onClick: () => { setStep(2); setTouched(false); } }, "用这个选题 →")));

      // 步骤 2：目录 + 初始化（建完直接进工作台，不再在向导里生成大纲/设定）
      const step2 = h("div", null,
        h("p", { style: { margin: "0 0 12px", color: "var(--nvs-sub)", fontSize: 13, lineHeight: 1.8 } },
          `选题定了：《${picked ? picked.title : ""}》。选个地方放这本书的文件，初始化后直接进工作台，大纲和设定都在工作台里做。`),
        picked ? h("div", { className: "nvs-cand", style: { cursor: "default", marginBottom: 14 } },
          h("h4", null, picked.title),
          h("div", { className: "line" }, picked.oneLine),
          h("div", { className: "tags" }, picked.genre ? h("span", { className: "nvs-pill" }, picked.genre) : null,
            h("span", { className: "nvs-pill" }, `约 ${Math.max(1, Number(chapters) || 300)} 章 × ${Math.max(200, Number(wpc) || 3000)} 字`))) : null,
        h(Field, { label: "存在哪" },
          h("div", { className: "nvs-flex" },
            h("input", { className: "nvs-input nvs-mono", style: { flex: "1 1 240px", fontSize: 12 }, value: dir, spellCheck: false,
              placeholder: "填了书名会自动给出", onChange: (e) => { setTouched(true); setDir(e.target.value); } }),
            h("button", { className: "nvs-btn", onClick: () => setBrowsing(true) }, "选目录…")),
          h("span", { className: "nvs-hint" }, `默认放在 ${baseDir || "~/Desktop/mine/xiaoshuo"}/书名；也可以点「选目录…」挑一个现成文件夹。`)),
        err ? h("div", { className: "nvs-note err", style: { marginBottom: 12 } }, err) : null,
        h("div", { className: "nvs-wiz-foot" },
          h("button", { className: "nvs-btn ghost", onClick: () => setStep(1) }, "← 换选题"),
          h("span", { className: "nvs-spacer" }),
          created
            ? h("button", { className: "nvs-btn primary", onClick: finish }, "进入工作台 →")
            : h("button", { className: "nvs-btn primary", disabled: busy, onClick: createProject }, busy ? "初始化中…" : "初始化目录 →")));

      const pane = ({ 0: step0, 1: step1, 2: step2 })[step] || step0;

      return h(Modal, { title: "新建小说", onClose, wide: true },
        stepsBar,
        pane,
        browsing ? h(DirPicker, { home, value: dir || suggest || home,
          onPick: (d) => { setTouched(true); setDir(d); }, onClose: () => setBrowsing(false) }) : null);
    }


    /* ------------------------------- 删除确认 ------------------------------- */
    function DeleteDialog({ book, busy, onClose, onConfirm }) {
      return h(Modal, { title: "删除这本书？", onClose },
        h("p", { style: { margin: "0 0 6px", fontSize: 13 } },
          "《", (book.title || "未命名"), "》的正文、设定、伏笔账会一起删掉。"),
        h("p", { className: "nvs-hint", style: { margin: "0 0 16px", lineHeight: 1.8, color: "var(--nvs-danger, #dc2626)" } },
          "真删：整个项目目录会被永久删除，不进回收站，删掉之后找不回来。"),
        h("div", { className: "nvs-flex", style: { justifyContent: "flex-end" } },
          h("button", { className: "nvs-btn", disabled: busy, onClick: onClose }, "先留着"),
          h("button", { className: "nvs-btn danger", disabled: busy, onClick: onConfirm },
            busy ? "删除中…" : "永久删除")));
    }

    /* --------------------------------- 概览 --------------------------------- */
    const PHASE_LABEL = { concept: "选题", outline_accept: "待确认大纲", bible: "建设定", outline: "排段落纲", writing: "写作中", awaiting_review: "待你确认", none: "未开始" };

    // 10 章一段的批量任务书：先铺段落纲，再逐章写、逐章体检；有问题只退那一章
    function batchChapterPrompt(st, n, size, openSeg) {
      const p = st.project || {};
      const to = (openSeg ? Number(openSeg.to) : n + size - 1);
      const lines = [
        `用 novel-studio 技能，给《${p.title || "这本书"}》批量写第 ${n}-${to} 章（一段 ${size} 章左右）。`,
        skillLines("write"),
        `1) 先 novel_status 看进度和 gate。`,
        openSeg
          ? `2) 第 ${n} 章已在本批段落纲（第${openSeg.from}-${openSeg.to}章）里，直接用，不要再 plan。`
          : `2) 还没有覆盖第 ${n} 章的段落纲：先 novel_segment op=plan from=${n} to=${to} 规划这一段（3-5 个台阶），作者确认台阶方向后再 op=write 落账。不要逐章写细纲。`,
        `3) 从第 ${n} 章起一章一章往下写：novel_context → 按段落纲里本章所在的台阶写这一章 → novel_chapter commit（带 batch:true）。这批不逐章 approve。`,
        `4) 每章提交后看返回的「本章体检」：有 high 或判定 needs_fix，就用 novel_gate rewrite 章号 note=... 退回这一章，重写后再 commit（batch:true）；改好再往下写。其余章不动，也不要停下来等作者确认整批。`,
        `4b) 本批写到最后一章后，先跑一次按批体检：novel_continuity scope=batch（默认就是这一段），一次看整批；只把返回里 action=rewrite 的章按章 novel_gate rewrite，别整批重写。`,
        `5) 一章一章按顺序写到第 ${to} 章，不许跳过中间章。写完停下，gate 会停在待确认：把本批各章的体检结果汇总给我，等我一次 review 或指定哪一章重写。`,
        `6) 本批写完后，设定（含关系矩阵/信息差）等我 approve 时一次补整批，不要一章一章补设定。`,
        `注意：正文一律用 novel_chapter op=read 读，不要去 exports/ 目录找 txt 文件。`,
      ];
      const preset = STYLE_PRESETS[st.setup?.style?.preset];
      if (preset) lines.push(`文风必须按 ${preset.label} 那一路（${preset.hint}）：动笔前先加载 \`${preset.skill}\`，按它的语感写；只学语感，不抄原句。`);
      const longBook = !(Number(p.targetChapters) > 0 && Number(p.targetChapters) <= 50);
      const floor = longBook ? "每章不少于 1800 字（硬下限，少了会被拒收）" : "";
      if (p.wordsRange && p.wordsRange.min) lines.push(`每章字数控制在 ${p.wordsRange.min}-${p.wordsRange.max} 字${floor ? `，且${floor}` : ""}。`);
      else if (floor) lines.push(`${floor}。`);
      return lines.join("\n");
    }

    function Overview({ st, dir, go, toast, onChanged }) {
      const p = st.project;
      const s = st.setup || {};
      const [syn, setSyn] = useState(s.synopsis || "");
      const [synBusy, setSynBusy] = useState(false);
      const synDirty = syn !== (s.synopsis || "");
      const [preset, setPreset] = useState(s.style?.preset || "");
      const [metaBusy, setMetaBusy] = useState(false);
      const metaDirty = preset !== (s.style?.preset || "");
      const styleLocked = (Number(p.currentChapter) || 0) >= 1;
      const saveMeta = async () => {
        setMetaBusy(true);
        try {
          await postJSON("setup", { dir, stylePreset: preset });
          if (onChanged) await onChanged();
          toast("文风已保存");
        } catch (e) { toast("保存失败：" + (e.message || e)); }
        setMetaBusy(false);
      };
      const chars = st.chapters || [];
      const last = chars.length ? chars[chars.length - 1] : null;
      const done = p.currentChapter || 0;
      const target = p.targetChapters || 0;
      const pct = target ? Math.min(100, Math.round((done / target) * 100)) : 0;
      const gate = st.gate || {};
      const nextN = st.nextChapter || (done + 1);
      // 上一章还没通过就不让开下一章：后端也会拦，这里先把按钮关掉，省得白开一个会话
      const pendingCh = chars.find((c) => !c.approved) || null;
      const [busy, setBusy] = useState(false);
      // 10 章一段：没铺过段落纲就开第一批，已经开的批次接着写
      const segs = st.segments || [];
      const openSeg = segs.find((g) => nextN >= Number(g.from) && nextN <= Number(g.to)) || null;
      const batchSize = Math.min(10, Math.max(1, (target || nextN + 9) - nextN + 1));

      const startBatch = async () => {
        if (pendingCh) { toast(`第 ${pendingCh.number} 章还没确认，先在「进度」页点「通过并存档」`); return; }
        setBusy(true);
        try {
          const r = await openWritingSession(st.dir, batchChapterPrompt(st, nextN, batchSize, openSeg));
          if (!r.ok) toast("跳转失败：" + r.reason);
        } catch (e) { toast("跳转失败：" + (e.message || e)); }
        setBusy(false);
      };

      return h("div", null,
        h("div", { className: "nvs-hero" },
          h("div", { className: "mark" }, h(BookIcon, { size: 22 })),
          h("div", { style: { minWidth: 0 } },
            h("h1", null, p.title),
            h("div", { className: "meta" }, [p.genre].filter(Boolean).join(" · ") + (target ? ` · 已写 ${done}/${target} 章` : ` · 已写 ${done} 章`))),
          h("div", { className: "side" },
            h("button", {
              className: "nvs-btn primary", disabled: busy || Boolean(pendingCh), onClick: startBatch,
              title: pendingCh ? `第 ${pendingCh.number} 章还没通过确认` : "",
            },
              busy ? "正在打开会话…" : pendingCh ? `先确认第 ${pendingCh.number} 章` : (done === 0 ? `写第 1-${batchSize} 章` : `接着写第 ${nextN}-${nextN + batchSize - 1} 章`)))),

        (() => {
          const steps = [
            { n: 0, t: "写故事梗概", d: "上面那段梗概就是这本书的地基：主角、核心冲突、结局方向。大纲和世界观都从这里长出来。", tab: "overview" },
            { n: 1, t: "生成大纲", d: "把故事梗概交给 AI，产出全书 / 卷两层大纲。", tab: "outline" },
            { n: 2, t: "生成世界观", d: "依大纲的核心冲突和主角，产出骨架、硬规则、人物卡。", tab: "world" },
            { n: 3, t: "补全设定", d: "一键把大纲+世界观拆成人物/势力/地点/物品/规则/文风，缺的补、有的不动。", tab: "setup" },
            { n: 4, t: "生成伏笔", d: "依大纲与世界观设计埋设与揭晓计划，写进伏笔账本。", tab: "foreshadow" },
            { n: 5, t: "批量写作", d: "点「写第 1-10 章」开会话：先出 10 章一段的段落纲，再一章章写、一章章体检；哪章有问题只退回那一章。", tab: "progress" },
          ];
          return h(Card, { title: "怎么用这个插件", desc: "第一次用就照着这五步走，点每一步能直接跳过去。10 章一段，先铺段落纲再写，不用逐章排细纲。" },
            h("div", { style: { display: "grid", gap: 8 } },
              steps.map((s) => h("div", { key: s.n, className: "nvs-flex", style: { alignItems: "flex-start", gap: 10 } },
                h("span", { className: "nvs-pill", style: { flex: "none", minWidth: 22, textAlign: "center", fontWeight: 700 } }, s.n),
                h("div", { style: { flex: "1 1 auto", minWidth: 0 } },
                  h("div", { style: { fontWeight: 600, fontSize: 13 } }, s.t),
                  h("div", { className: "nvs-hint", style: { marginTop: 2 } }, s.d)),
                h("button", { className: "nvs-btn ghost sm", style: { flex: "none" }, onClick: () => go && go(s.tab) }, "去")))));
        })(),

        h("div", { className: "nvs-stats" },
          [[done, "已写章节"], [fmtWan(st.totalChars), "总字数"], [(st.foreshadow?.open || []).length, "开着的伏笔"], [(st.badChapters || []).length, "需返工的章"]]
            .map(([n, l]) => h("div", { key: l, className: "nvs-stat" }, h("div", { className: "n", style: l === "需返工的章" && n ? { color: "var(--nvs-bad)" } : null }, n), h("div", { className: "l" }, l)))),

        (() => {
          const u = st.usage || {};
          if (!u.contextCalls && !u.commitCalls) return null;
          const tk = (n) => (Number(n) >= 10000 ? `${(Number(n) / 10000).toFixed(1)} 万` : String(Number(n) || 0));
          return h("div", { className: "nvs-hint", style: { margin: "-2px 0 12px" } },
            `上下文用量（估算）：最近一章 ≈ ${tk(u.contextTokensLast)} tokens · 章均 ≈ ${tk(u.contextTokensPerChapter)} · 全书上下文累计 ≈ ${tk(u.contextTokensTotal)} tokens · 正文累计 ≈ ${tk(u.outputTokensTotal)} tokens（${u.contextCalls} 次组装 / ${u.commitCalls} 次提交）`);
        })(),

        h(Card, { title: "故事梗概", desc: "这本书的地基。生成大纲、世界观、选题都会以它为准；改了记得保存，之后生成的大纲才会跟着变。",
          right: h("button", {
            className: "nvs-btn sm " + (synDirty ? "primary" : ""),
            disabled: !synDirty || synBusy,
            onClick: async () => {
              setSynBusy(true);
              try {
                await postJSON("setup", { dir, synopsis: syn });
                if (onChanged) await onChanged();
                toast("梗概已保存");
              } catch (e) { toast("保存失败：" + (e.message || e)); }
              setSynBusy(false);
            },
          }, synBusy ? "保存中…" : synDirty ? "保存梗概 •" : "已保存") },
          h("textarea", {
            className: "nvs-area", style: { minHeight: 140, fontFamily: "var(--nvs-serif)", lineHeight: 1.9 },
            placeholder: "一句话到一段话都行：谁、想要什么、被什么挡住、代价是什么。写得越具体，大纲越靠谱。",
            value: syn, onChange: (e) => setSyn(e.target.value),
          })),

        h(Card, { title: "文风", desc: styleLocked
            ? "第 1 章已写完，文风锁定；要换文风请先作废第 1 章。写作方向仍可在「设定」页调整。"
            : "选一位作家当语感参照，写正文时会按这一路走（只学语感，不抄原句）。写完第 1 章后锁定。禁用表达和写作方向在「设定」页。",
          right: h("button", {
            className: "nvs-btn sm " + (metaDirty ? "primary" : ""), disabled: !metaDirty || metaBusy || styleLocked, onClick: saveMeta,
          }, metaBusy ? "保存中…" : metaDirty ? "保存 •" : "已保存") },
          h(Row, { label: "文风", hint: "技能库里的作家" },
            h("select", { className: "nvs-input", style: { width: "auto", minWidth: 220 }, value: preset, disabled: styleLocked, onChange: (e) => setPreset(e.target.value) },
              h("option", { value: "" }, "不指定（默认文风）"),
              Object.entries(STYLE_PRESETS).map(([k, v]) => h("option", { key: k, value: k }, `${v.label} — ${v.hint}`))))),

        (p.referenceBook || "").trim()
          ? h(Card, { title: "对标书", desc: "新建小说时定的，之后不能改。生成选题时按它的路子来；大纲、世界观、设定不参考它。" },
              h(Row, { label: "书名" },
                h("input", { className: "nvs-input", value: p.referenceBook, readOnly: true, style: { opacity: 0.75, cursor: "not-allowed" } })))
          : null,

        h(Card, { title: "写这本书时可以用的小工具", desc: "每个都会开一个会话，由 AI 按对口的技能去做；做完的结果仍通过工具落进账本。" },
          (() => {
            const tools = [
              { k: "analyze", t: "拆一本对标书", d: "把你喜欢的书拆成结构、节奏、情绪线，供这本书参考。" },
              { k: "import", t: "导入已有旧稿", d: "已经写了一部分、或想搬进这套账本，按项目结构解析进来。" },
              { k: "cover", t: "做封面", d: "按书名与题材生成封面图。" },
              { k: "envcheck", t: "检查写作环境", d: "核对技能与目录是否齐全，缺什么一次说清。" },
            ];
            return h("div", { className: "nvs-flex", style: { flexWrap: "wrap", gap: 8 } }, tools.map((x) =>
              h("button", { key: x.k, className: "nvs-btn sm", title: x.d, onClick: async () => {
                const r = await openWritingSession(st.dir, [`用 novel-studio 技能，给《${p.title}》${x.t}。`, skillLines(x.k), `做完把结果报给我，涉及账本的用 novel_* 工具落账。`].join("\n"));
                toast(r.ok ? `已开会话：${x.t}` : "已复制指令：" + r.reason);
              } }, x.t)));
          })()),

        );

    }


    /* --------------------------------- 设定 --------------------------------- */
    // 设定页：题材来自选题自动匹配（只读）；平台本期不做；大纲移到「大纲」页。
    // 其他设定可以让 AI 依大纲生成——大纲没内容就不给按。
    // 人物别名在账本里是数组，表格里用顿号串编辑；性别/种族/别名一起进上下文，避免后文写跑。
    const charsForEdit = (list) => (list || []).map((c) => ({
      ...c, _origName: c._origName ?? c.name ?? "",
      aliases: Array.isArray(c.aliases) ? c.aliases.join("、") : (c.aliases || ""),
    }));
    const aliasesToArray = (v) => (Array.isArray(v) ? v : String(v || "").split(/[、,，/\s]+/u)).map((s) => String(s || "").trim()).filter(Boolean);

    function Setup({ st, dir, onSaved, toast, onDirty, saveRef, go, part = "all" }) {
      const s = st.setup || {};
      const styleLocked = (Number(st.project?.currentChapter) || 0) >= 1;
      const showChars = part !== "setup";
      const showRest = part !== "characters";
      const outlineText = (s.outlineText || "").trim();
      const hasOutline = outlineText.length > 0;
      const [draft, setDraft] = useState(() => ({
        genre: st.project.genre || "",
        synopsis: s.synopsis || "",
        referenceBook: st.project.referenceBook || "",
        direction: s.direction || "",
        targetChapters: s.targetChapters || "",
        wordsPerChapter: s.wordsPerChapter || "",
        totalWords: (Number(s.targetChapters) || 0) * (Number(s.wordsPerChapter) || 0),
        characters: charsForEdit(s.characters),
        world: s.world || [],
        factions: charsForEdit(s.factions),
        locations: charsForEdit(s.locations),
        items: charsForEdit(s.items),
        rules: charsForEdit(s.rules),
        relations: s.relations || [],
        infoGaps: s.infoGaps || [],
        bannedText: (s.style?.banned || []).join("、"),
        pov: s.style?.pov || "",
        tense: s.style?.tense || "",
        samplesText: (s.style?.samples || []).join("\n\n"),
      }));
      const [busy, setBusy] = useState(false);
      const [dirty, setDirty] = useState(false);
      const [charSel, setCharSel] = useState(0);
      const [charView, setCharView] = useState("files");
      const [charTier, setCharTier] = useState("all");
      const [charQuery, setCharQuery] = useState("");
      const [charDeleted, setCharDeleted] = useState([]);
      const [assetTab, setAssetTab] = useState("factions");
      const [assetSel, setAssetSel] = useState({});
      const [assetQuery, setAssetQuery] = useState("");
      const [deletedAssets, setDeletedAssets] = useState({});
      const set = (k, v) => { setDraft((d) => ({ ...d, [k]: v })); setDirty(true); if (onDirty) onDirty(true); };
      useEffect(() => { if (onDirty) onDirty(false); }, []);

      const save = async () => {
        setBusy(true);
        try {
          const renamed = (draft.characters || [])
            .filter((c) => c._origName && c.name && c._origName !== c.name)
            .map((c) => c._origName);
          const deletedCharacters = [...new Set([...charDeleted, ...renamed])];
          const assetKeys = ["factions", "locations", "items", "rules"];
          const cleanAssets = {};
          const deletedEntities = {};
          for (const key of assetKeys) {
            const rows = draft[key] || [];
            const renamedRows = rows
              .filter((x) => x._origName && x.name && x._origName !== x.name)
              .map((x) => x._origName);
            deletedEntities[key] = [...new Set([...(deletedAssets[key] || []), ...renamedRows])];
            cleanAssets[key] = rows.map(({ _origName, keywords, ...x }) => {
              const kw = Array.isArray(keywords) ? keywords : String(keywords || "").split(/[、,，/\s]+/u).filter(Boolean);
              return { ...x, aliases: aliasesToArray(x.aliases), ...(kw.length ? { keywords: kw } : {}) };
            });
          }
          const r = await postJSON("setup", {
            dir,
            synopsis: draft.synopsis, direction: draft.direction,
            referenceBook: draft.referenceBook,
            characters: (draft.characters || []).map(({ _origName, ...c }) => ({ ...c, aliases: aliasesToArray(c.aliases) })),
            deletedCharacters,
            factions: cleanAssets.factions, locations: cleanAssets.locations, items: cleanAssets.items, rules: cleanAssets.rules,
            deletedEntities,
            relations: draft.relations, infoGaps: draft.infoGaps,
            genre: draft.genre,
            bannedText: draft.bannedText,
            pov: draft.pov, tense: draft.tense, samplesText: draft.samplesText,
          });
          onSaved(r);
          setDirty(false);
          setCharDeleted([]);
          setDeletedAssets({});
          const sv = (r.view && r.view.setup) || r.setup || null;
          if (sv) setDraft((d) => ({
            ...d,
            characters: charsForEdit(sv.characters || d.characters),
            factions: charsForEdit(sv.factions || d.factions),
            locations: charsForEdit(sv.locations || d.locations),
            items: charsForEdit(sv.items || d.items),
            rules: charsForEdit(sv.rules || d.rules),
            relations: sv.relations || d.relations,
            infoGaps: sv.infoGaps || d.infoGaps,
          }));
          const merged = (r && r.mergedNames) || [];
          toast("设定已保存" + (merged.length ? `；同一个人合并了 ${merged.length} 条：${merged.join("、")}` : "")
            + (r && r.mergeNote ? `。${r.mergeNote}` : ""));
        } catch (e) { toast("保存失败：" + e.message); }
        setBusy(false);
      };
      if (saveRef) { saveRef.current = save; }

      // 表格编辑器：columns = [{k, ph, w}]，表头 + 每行 input + 行尾删按钮
      const tableEditor = (key, columns, addLabel) => {
        const rows = draft[key] || [];
        const upd = (i, k, v) => { const next = rows.slice(); next[i] = { ...next[i], [k]: v }; set(key, next); };
        const del = (i) => set(key, rows.filter((_, j) => j !== i));
        const totalW = columns.reduce((a, c) => a + (c.w || 1), 0);
        return h("div", { className: "nvs-tbl-wrap" },
          h("table", { className: "nvs-tbl" },
            h("thead", null, h("tr", null,
              columns.map((c) => h("th", { key: c.k, style: { width: ((c.w || 1) / totalW * 100) + "%" } }, c.ph)),
              h("th", { className: "act" }, ""))),
            h("tbody", null,
              rows.length
                ? rows.map((row, i) => h("tr", { key: i },
                    columns.map((c) => h("td", { key: c.k },
                      h("input", { className: "nvs-input", placeholder: c.ph, value: row[c.k] ?? "", onChange: (e) => upd(i, c.k, e.target.value) }))),
                    h("td", { className: "act" }, h("button", { className: "nvs-btn ghost sm", style: { padding: "0 7px", color: "var(--nvs-danger,#DC2626)" }, title: "删掉这条", onClick: () => del(i) }, "删"))))
                : h("tr", null, h("td", { colSpan: columns.length + 1, className: "nvs-tbl-empty" }, "还没有，点下面按钮添加"))),
          h("button", { className: "nvs-btn sm", style: { justifySelf: "start" }, onClick: () => set(key, [...rows, {}]) }, addLabel)));
      };

      // 已有重复人物（同一个人的不同写法）→ 一键并成一条
      const applySetupView = (r) => {
        const sv = (r && ((r.view && r.view.setup) || r.setup)) || null;
        if (sv) {
          setDraft((d) => ({ ...d,
            characters: charsForEdit(sv.characters || d.characters),
            rules: charsForEdit(sv.rules || d.rules),
            factions: charsForEdit(sv.factions || d.factions), locations: charsForEdit(sv.locations || d.locations),
            items: charsForEdit(sv.items || d.items),
            relations: sv.relations || d.relations, infoGaps: sv.infoGaps || d.infoGaps,
            bannedText: ((sv.style && sv.style.banned) || []).join("、"),
            pov: (sv.style && sv.style.pov) || "",
            tense: (sv.style && sv.style.tense) || "",
            samplesText: ((sv.style && sv.style.samples) || []).join("\n\n"),
          }));
          setDirty(false);
        }
        onSaved(r.view || r);
      };
      const mergeDup = async () => {
        if (busy) return;
        setBusy(true);
        try {
          const r = await postJSON("bible", { dir, op: "merge-duplicates" });
          applySetupView(r);
          toast(r.count ? `合并了 ${r.count} 条重复：` + r.merged.join("、") + (r.note ? `。${r.note}` : "") : (r.note || "没有找到重复的条目"));
        } catch (e) { toast("合并失败：" + (e.message || e)); }
        setBusy(false);
      };
      const splitMerged = async (name, mergedName) => {
        if (!window.confirm(`把「${mergedName}」从「${name}」里拆出来？拆开后两条各自独立。`)) return;
        setBusy(true);
        try {
          const r = await postJSON("bible", { dir, op: "split", name, mergedName });
          applySetupView(r);
          toast(`已把「${mergedName}」拆出来`);
        } catch (e) { toast("拆开失败：" + (e.message || e)); }
        setBusy(false);
      };

      // 生成设定的条件：大纲 + 世界观都要有。
      const worldText = (s.worldText || "").trim();
      const hasWorld = worldText.length > 0;
      const ready = hasOutline && hasWorld;
      const merges = (draft.characters || []).filter((c) => (c.mergedFrom || []).length);
      const mergedList = () => merges.length
        ? h("div", { className: "nvs-hint", style: { marginTop: 10, display: "grid", gap: 6 } },
            h("div", null, "合并记录（判错可以拆开）："),
            merges.flatMap((c) => (c.mergedFrom || []).map((m) =>
              h("div", { key: c.name + "|" + m.name, className: "nvs-flex", style: { gap: 8, alignItems: "center" } },
                h("span", null, `「${m.name}」并进了「${c.name}」`),
                h("button", { className: "nvs-btn ghost sm", disabled: busy, onClick: () => splitMerged(c.name, m.name) }, "拆开")))))
        : null;

      const genSettings = async (scope = "setup") => {
        if (busy) return;
        setBusy(true);
        try {
          const ms = readModelSel() || {};
          const r = await postJSON("setup-gen", { dir, scope, provider: ms.provider || undefined, model: ms.model || undefined });
          // 补全后刷新父级视图：否则页头「保存」还亮着，一点保存会把刚补的关系矩阵/信息差用旧快照覆盖回去
          if (onSaved) { try { onSaved(r.view || r); } catch (_) { /* 只是刷新视图 */ } }
          toast(r.summary || "补全完成");
          // 用返回的最新设定刷新本地表格，同时同步父级视图
          const sv = (r.view && r.view.setup) || null;
          if (sv) {
            setDraft((d) => ({ ...d,
              characters: charsForEdit(sv.characters || d.characters),
              rules: charsForEdit(sv.rules || d.rules),
              factions: charsForEdit(sv.factions || d.factions), locations: charsForEdit(sv.locations || d.locations),
              items: charsForEdit(sv.items || d.items),
              relations: sv.relations || d.relations, infoGaps: sv.infoGaps || d.infoGaps,
              bannedText: ((sv.style && sv.style.banned) || []).join("、"),
              pov: (sv.style && sv.style.pov) || "",
              tense: (sv.style && sv.style.tense) || "",
              samplesText: ((sv.style && sv.style.samples) || []).join("\n\n"),
            }));
            setDirty(false);
          }
          onSaved(r.view || r);
        } catch (e) { toast("补全失败：" + (e.message || e)); }
        setBusy(false);
      };
      const genBtn = ready
        ? h("button", { className: "nvs-btn primary", disabled: busy, onClick: () => genSettings("setup") }, busy ? "AI 正在拆设定…" : "AI 从大纲+世界观生成设定")
        : h("button", { className: "nvs-btn", onClick: () => go && go("world") }, "先去世界观页生成世界观 →");
      // 人物页补全时关系矩阵/信息差也一起补，按钮上写明，免得以为只补人物卡
      const charsGenBtn = ready
        ? h("button", { className: "nvs-btn primary", disabled: busy, onClick: () => genSettings("characters") }, busy ? "AI 正在补人物…" : "AI 补全人物 + 关系矩阵 + 信息差")
        : h("button", { className: "nvs-btn", onClick: () => go && go("world") }, "先去世界观页生成世界观 →");

      const IMPORTANCE = ["核心", "主要", "次要", "龙套"];
      const importanceOf = (c) => {
        const legacy = { S: "核心", A: "主要", B: "次要", C: "龙套" };
        const raw = String(c?.importance || c?.tier || "").trim();
        const v = legacy[raw.toUpperCase()] || raw;
        return IMPORTANCE.includes(v) ? v : "主要";
      };
      const depthOf = (c) => ({ 核心: "S", 主要: "A", 次要: "B", 龙套: "C" })[importanceOf(c)];
      const STATUS = { active: "存活", dead: "已死亡", missing: "失踪", exited: "已退场" };
      const statusOf = (c) => STATUS[c?.status] || "存活";
      const charactersPage = () => {
        const all = draft.characters || [];
        const q = charQuery.trim().toLowerCase();
        const filtered = all.map((c, i) => ({ c, i })).filter(({ c }) => {
          if (charTier !== "all" && importanceOf(c) !== charTier) return false;
          if (!q) return true;
          return [c.name, c.rolePosition, c.role, ...aliasesToArray(c.aliases)].join(" ").toLowerCase().includes(q);
        });
        const sel = all[charSel] ? charSel : (all.length ? 0 : -1);
        const cur = sel >= 0 ? all[sel] : {};
        const up = (k, v) => {
          if (sel < 0) return;
          const next = all.slice();
          next[sel] = { ...next[sel], [k]: v };
          set("characters", next);
        };
        const cf = (label, key, ph, opts = {}) => h(Field, { label },
          opts.area
            ? h("textarea", {
                className: "nvs-area", style: { minHeight: opts.rows ? opts.rows * 22 : 64, ...(opts.full ? { gridColumn: "1 / -1" } : {}) },
                placeholder: ph, value: cur[key] ?? "", onChange: (e) => up(key, e.target.value),
              })
            : h("input", { className: "nvs-input", placeholder: ph, value: cur[key] ?? "", onChange: (e) => up(key, e.target.value) }));
        const addChar = () => {
          const next = [...all, { name: "", importance: charTier === "all" ? "次要" : charTier, rolePosition: "", status: "active" }];
          set("characters", next);
          setCharSel(next.length - 1);
          setCharView("files");
        };
        const delChar = (i) => {
          if (!window.confirm(`删掉「${all[i].name || "这个人物"}」？删了不会自动从正文里消失。`)) return;
          const gone = String(all[i].name || "").trim();
          if (gone) setCharDeleted((d) => [...new Set([...d, gone])]);
          set("characters", all.filter((_, j) => j !== i));
          setCharSel(Math.max(0, i - 1));
        };
        const changeStatus = (v) => {
          if (cur.status === "dead" && v !== "dead" && !window.confirm("这个角色已标成死亡。确定解除死亡锁定、改回存活？")) return;
          if (v === "dead" && cur.status !== "dead" && !window.confirm("确认这个角色已死亡？死亡状态会锁死，防止后文误写复活。")) return;
          const next = all.slice();
          next[sel] = { ...next[sel], status: v };
          if (v === "dead") delete next[sel].revive;
          else if (cur.status === "dead") next[sel].revive = true;
          set("characters", next);
        };

        const sub = [["files", "角色档案"], ["relations", "关系矩阵"], ["gaps", "信息差"], ["monitor", "出场监控"]];
        const header = h("div", null,
          h("div", { className: "nvs-flex", style: { gap: 8, flexWrap: "wrap", marginBottom: 10 } },
            h("button", { className: "nvs-btn primary sm", onClick: addChar }, "+ 新建人物"),
            h("button", { className: "nvs-btn sm", disabled: busy, onClick: mergeDup }, "合并重复条目"),
            charsGenBtn,
            h("span", { className: "nvs-spacer" }),
            h("span", { className: "nvs-hint" }, `共 ${all.length} 人 · ` + IMPORTANCE.map((t) => `${t} ${all.filter((c) => importanceOf(c) === t).length}`).join(" / "))),
          h("div", { className: "nvs-char-sub", role: "tablist", "aria-label": "人物视图" }, sub.map(([k, label]) =>
            h("button", { key: k, type: "button", role: "tab", className: "nvs-chip", "aria-selected": charView === k ? "true" : "false", onClick: () => setCharView(k) }, label))));

        if (!all.length) {
          return h("div", null, header,
            h("div", { className: "nvs-note" }, "还没有人物。可以点「+ 新建人物」手动加，或先让 AI 按大纲和世界观补一轮。先填「定位」和「重要性」：主角和核心 3–5 人标核心，其余按主要/次要/龙套记。"));
        }

        const filesView = () => h("div", { className: "nvs-chars" },
          h("div", { className: "nvs-char-side" },
            h("input", {
              className: "nvs-input", style: { marginBottom: 8, fontSize: 12.5 },
              placeholder: "搜名字、身份、别名", value: charQuery, onChange: (e) => setCharQuery(e.target.value),
            }),
            h("div", { className: "nvs-chips", style: { flexWrap: "wrap" } },
              [["all", "全部"], ...IMPORTANCE.map((t) => [t, t])].map(([v, label]) =>
                h("button", { key: v, type: "button", className: "nvs-chip", "aria-pressed": charTier === v ? "true" : "false", onClick: () => setCharTier(v) }, label))),
            h("div", { className: "nvs-char-list" },
              filtered.length
                ? filtered.map(({ c, i }) => h("button", {
                    key: i, type: "button", className: "nvs-char-item", "aria-current": sel === i ? "true" : "false",
                    onClick: () => setCharSel(i),
                  },
                    h("span", { className: "nvs-char-item-main" },
                      h("b", null, c.name || "未命名"),
                      h("small", null, [c.rolePosition || c.role || "—", importanceOf(c), c.status && c.status !== "active" ? statusOf(c) : ""].filter(Boolean).join(" · "))),
                    h("span", { className: "nvs-status-dot " + (c.status || "active"), title: statusOf(c) })))
                : h("div", { className: "nvs-hint", style: { padding: "12px 6px" } }, "没有匹配的人物"))),
          sel < 0
            ? h("div", { className: "nvs-char-main" }, h("div", { className: "nvs-note" }, "左边选一个人物，或点「+ 新建人物」。"))
            : h("div", { className: "nvs-char-main" },
                (() => { const tier = depthOf(cur); const imp = importanceOf(cur); return [
                h("div", { className: "nvs-char-title" },
                  h("div", null, h("b", null, cur.name || "未命名"), h("span", { className: "nvs-hint" }, "  " + ([cur.rolePosition, cur.role].filter(Boolean).join(" · ") || "还没填定位"))),
                  h("button", { className: "nvs-btn ghost sm", style: { color: "var(--nvs-danger,#DC2626)" }, onClick: () => delChar(sel) }, "删掉")),
                cur.status === "dead" ? h("div", { className: "nvs-note warn" }, "死亡锁定：这个角色已死亡。后文不许以任何理由让他复活或继续行动；要改回存活，需要在「当前状态」里重新选择并确认。") : null,
                tier === "B" ? h("div", { className: "nvs-hint" }, "「次要」只记定位、功能和一个记忆点；要写细，先把重要性调成「主要」。") : null,
                tier === "C" ? h("div", { className: "nvs-hint" }, "「龙套」只防重名，不展开性格和信息差；需要他反复出场时再调整重要性。") : null,
                h("div", { className: "nvs-char-sec" },
                  h("h4", null, "标识"),
                  h("div", { className: "nvs-char-grid" },
                    cf("姓名", "name", "名字"),
                    cf("定位", "rolePosition", "主角 / 女主 / 反派 / 常驻配角 / 工具人"),
                    h(Field, { label: "重要性" }, h("select", { className: "nvs-input", value: imp, onChange: (e) => up("importance", e.target.value) },
                      IMPORTANCE.map((t) => h("option", { key: t, value: t }, t)))),
                    cf("身份", "role", "捕快 / 赵家长工 / 反派"),
                    cf("年龄", "age", "数字或「三十上下」"),
                    cf("性别", "gender", "男 / 女 / 不明"),
                    cf("种族", "race", "人 / 半妖 / 外乡人"),
                    cf("别名与称呼", "aliases", "岩哥、陈哥（顿号分隔）"),
                    cf("称呼规则", "callRules", "谁叫他什么；他自称什么；正式场合叫什么", { area: true, rows: 2 }),
                    cf("首次登场", "firstChapter", "第几章（可不填）"),
                    cf("退场章", "exitChapter", "第几章退场（可不填）"))),
                tier !== "C" ? h("div", { className: "nvs-char-sec" },
                  h("h4", null, "体貌与语言"),
                  h("div", { className: "nvs-char-grid" },
                    cf("体貌记忆点", "appearance", "只记一个能反复用的：疤、口音、走路姿势、手上的活", { area: true, rows: 2 }),
                    tier === "B" ? null : cf("语言指纹", "voice", "口头禅、句子长短、用词层级、说话时的习惯动作", { area: true, rows: 2 }))) : null,
                tier === "S" || tier === "A" ? h("div", { className: "nvs-char-sec" },
                  h("h4", null, "性格内核"),
                  h("div", { className: "nvs-char-grid" },
                    cf("性格一句话", "personality", "遇事先算账，嘴上不饶人"),
                    cf("欲望（要什么）", "want", "他这阶段最想得到的东西"),
                    cf("恐惧（怕什么）", "fear", "失去什么会让他失控"),
                    cf("底线（死也不做）", "bottomLine", "越过这条线人设就崩"),
                    cf("缺陷（会栽在哪）", "flaw", "让他犯错、被利用、付代价的地方"),
                    cf("秘密 / 隐情", "secret", "不能让人知道的事"))) : null,
                tier === "S" || tier === "A" ? h("div", { className: "nvs-char-sec" },
                  h("h4", null, "能力与限制"),
                  h("div", { className: "nvs-char-grid" },
                    cf("能力", "ability", "当前层级、手段"),
                    cf("限制", "abilityLimit", "什么情况下失灵"),
                    cf("代价", "abilityCost", "每次使用要付什么"))) : null,
                h("div", { className: "nvs-char-sec" },
                  h("h4", null, "当前状态"),
                  h("div", { className: "nvs-char-grid" },
                    h(Field, { label: "生存状态" }, h("select", { className: "nvs-input", value: cur.status || "active", onChange: (e) => changeStatus(e.target.value) },
                      Object.entries(STATUS).map(([k, v]) => h("option", { key: k, value: k }, v)))),
                    tier === "C" ? null : cf("当前位置", "location", "他现在在哪（收稿时会自动记进位置轨迹）"),
                    tier === "C" ? null : cf("当前目标", "currentGoal", "这一章/这一卷想要什么"),
                    tier === "S" || tier === "A" ? cf("知道什么", "knowledge", "他掌握的信息", { area: true, rows: 2 }) : null,
                    tier === "S" || tier === "A" ? cf("不知道什么", "ignorance", "他还被蒙在鼓里的事", { area: true, rows: 2 }) : null,
                    tier === "S" || tier === "A" ? cf("误以为什么", "misconception", "他信错的判断（打脸/悬疑的发动机）", { area: true, rows: 2 }) : null)),
                tier !== "C"
                  ? h("div", { className: "nvs-char-sec" },
                      h("h4", null, "位置轨迹"),
                      h("div", { style: { fontSize: 12.5, color: "var(--nvs-sub)", lineHeight: 1.8 } },
                        Array.isArray(cur.locationTrail) && cur.locationTrail.length
                          ? cur.locationTrail.slice(-10).map((x) => `第${x.chapter}章 ${Array.isArray(x.places) && x.places.length ? x.places.join("→") : x.place}`).join(" ｜ ")
                          : "还没有记录。只认「设定 · 地点」里登记过的名字，收稿后按章内出现顺序记录；正文写了但没登记的地点不会记。"))
                  : null,
                tier === "S" ? h("div", { className: "nvs-char-sec" },
                  h("h4", null, "变更日志"),
                  h("div", { className: "nvs-char-grid" },
                    cf("不可逆变化", "changeLog", "第几章：因为什么，发生了什么不可逆的变化（升级、受伤、立场转变、得知真相），一行一条", { area: true, rows: 4, full: true }))) : null,
                (() => {
                  const my = (draft.relations || []).filter((r) => r.a === cur.name || r.b === cur.name);
                  if (!my.length) return null;
                  return h("div", { className: "nvs-char-sec" },
                    h("h4", null, "此人的当前关系"),
                    h("div", { style: { display: "grid", gap: 5 } }, my.map((r, i) =>
                      h("div", { key: i, style: { fontSize: 12.5 } },
                        h("b", null, r.a === cur.name ? `→ ${r.b || "?"}` : `← ${r.a || "?"}`),
                        "：", r.state || "有记录", r.note ? h("span", { className: "nvs-hint" }, "（" + r.note + "）") : null))));
                })(),
                mergedList()]; })()));

        const relationsView = () => {
          const rels = draft.relations || [];
          const names = [...new Set(rels.flatMap((r) => [r.a, r.b]).filter(Boolean))];
          const cell = (a, b) => {
            const hit = rels.find((r) => r.a === a && r.b === b);
            return hit ? (hit.state || "有记录") : "";
          };
          return h("div", { style: { display: "grid", gap: 12 } },
            h(Card, { title: "关系矩阵", desc: "谁恨谁、谁欠谁、谁在提防谁。空白=还没记。矩阵只读，改下面的关系表。" },
              names.length
                ? (() => {
                    const head = h("thead", null, h("tr", null,
                      h("th", null, "从 ＼ 到"),
                      names.map((n) => h("th", { key: n }, n))));
                    const body = h("tbody", null, names.map((a) => h("tr", { key: a },
                      h("th", { style: { padding: "7px 10px", background: "var(--nvs-card2)", fontSize: 12 } }, a),
                      names.map((b) => h("td", { key: b, className: "cell clip-sm" }, a === b ? "—" : (cell(a, b) || ""))))));
                    return h("div", { className: "nvs-tbl-wrap" }, h("table", { className: "nvs-tbl" }, head, body));
                  })()
                : h("div", { className: "nvs-hint" }, "还没有关系记录。先在下面加一条，比如「陈岩 → 老徐：欠一条命，仍在提防」。")),
            h(Card, { title: "关系表", desc: "只记此刻的关系，不记初始设定。谁欠谁人情、谁撕破脸、谁掌握谁秘密。" },
              tableEditor("relations", [
                { k: "a", ph: "从（谁）", w: 1 }, { k: "b", ph: "到（对谁）", w: 1 },
                { k: "state", ph: "当前关系（欠人情/提防/撕破脸）", w: 2 }, { k: "note", ph: "备注：因为什么", w: 1.6 },
              ], "+ 加一条关系")));
        };

        const gapsView = () => h("div", { style: { display: "grid", gap: 12 } },
          h(Card, { title: "信息差表", desc: "每个关键秘密，列清楚谁知道、谁不知道、谁以为自己知道。打脸打不打得准，全看这张表。" },
            tableEditor("infoGaps", [
              { k: "secret", ph: "关键秘密", w: 1.6 },
              { k: "knows", ph: "谁知道", w: 1.2 },
              { k: "doesntKnow", ph: "谁不知道", w: 1.2 },
              { k: "thinksKnows", ph: "谁以为自己知道（其实错了）", w: 1.6 },
            ], "+ 加一条信息差")));

        const monitorView = () => {
          const chapters = Array.isArray(st.chapters) ? st.chapters : [];
          const current = Number(st.project?.currentChapter) || Number(chapters[chapters.length - 1]?.number) || 0;
          const rows = all.map((c) => {
            const names = [c.name, ...aliasesToArray(c.aliases)].filter(Boolean);
            const nums = chapters
              .filter((ch) => (ch.characters || []).some((n) => names.includes(String(n))))
              .map((ch) => Number(ch.number)).filter(Number.isFinite).sort((a, b) => a - b);
            const last = nums.length ? nums[nums.length - 1] : null;
            const gap = last && current ? current - last : null;
            const gone = c.status === "dead" || c.status === "exited";
            const important = depthOf(c) === "S" || depthOf(c) === "A";
            const warn = gone || !important ? "" : (gap !== null && gap > 8 ? `${gap} 章没出场，读者会忘` : "");
            return { c, first: nums[0] || c.firstChapter || null, last, count: nums.length, gap, warn };
          });
          const near = [];
          for (let i = 0; i < all.length; i += 1) {
            for (let j = i + 1; j < all.length; j += 1) {
              const a = String(all[i].name || ""), b = String(all[j].name || "");
              if (!a || !b || a === b) continue;
              const linked = aliasesToArray(all[i].aliases).includes(b) || aliasesToArray(all[j].aliases).includes(a);
              if (linked) continue;
              const contains = a.includes(b) || b.includes(a);
              const sameFirst = a[0] === b[0] && Math.abs(a.length - b.length) <= 1;
              if (contains || sameFirst) near.push(`${a} / ${b}`);
            }
          }
          return h("div", { style: { display: "grid", gap: 12 } },
            near.length ? h("div", { className: "nvs-note warn" }, "近名提醒：" + near.slice(0, 8).join("；") + "。不是错误，但建名/称呼时确认一下，别让读者混成一个人。") : null,
            h(Card, { title: "出场监控", desc: "首次出场、最近出场、累计戏份。核心/主要人物超过 8 章没露面，就该安排他回来或明确退场。" },
              h("div", { className: "nvs-tbl-wrap" },
                h("table", { className: "nvs-tbl" },
                  h("thead", null, h("tr", null,
                    ["定位", "人物", "重要性", "状态", "首次出场", "最近出场", "累计戏份", "提醒"].map((x) => h("th", { key: x }, x)))),
                  h("tbody", null, rows.map((r) => h("tr", { key: r.c.name || r.count },
                    h("td", { className: "cell" }, r.c.rolePosition || r.c.role || "—"),
                    h("td", { className: "cell" }, r.c.name || "未命名"),
                    h("td", { className: "cell" }, importanceOf(r.c)),
                    h("td", { className: "cell" }, statusOf(r.c)),
                    h("td", { className: "cell" }, r.first ? "第" + r.first + "章" : "—"),
                    h("td", { className: "cell" }, r.last ? "第" + r.last + "章" : "—"),
                    h("td", { className: "cell" }, r.count ? r.count + " 章" : "—"),
                    h("td", { className: "cell clip-md", style: { color: r.warn ? "var(--nvs-warn)" : "var(--nvs-dim)" } }, r.warn || "—"))))))));
        };

        return h("div", null, header,
          charView === "files" ? filesView()
            : charView === "relations" ? relationsView()
              : charView === "gaps" ? gapsView()
                : monitorView());
      };

      const ASSET_META = {
        factions: {
          label: "势力", add: "+ 新建势力",
          sub: (x) => x.nature || x.text || "还没填性质",
          fields: [
            { sec: "静态：写一次", k: "name", label: "名称", ph: "门派 / 组织 / 机构" },
            { sec: "静态：写一次", k: "aliases", label: "对外称呼", ph: "别名、俗称（顿号分隔）" },
            { sec: "静态：写一次", k: "slang", label: "内部黑话", ph: "自己人怎么称呼事情/人", area: true, rows: 2 },
            { sec: "静态：写一次", k: "nature", label: "性质与层级", ph: "谁管谁、上下级、明面身份", area: true, rows: 2 },
            { sec: "静态：写一次", k: "economy", label: "经济来源", ph: "靠什么活着", area: true, rows: 2 },
            { sec: "静态：写一次", k: "openRules", label: "明规则", ph: "对外宣称的规矩", area: true, rows: 2 },
            { sec: "静态：写一次", k: "hiddenRules", label: "潜规则", ph: "真正运行的规矩（最该盯死）", area: true, rows: 2 },
            { sec: "静态：写一次", k: "relations", label: "与其他势力", ph: "结盟/敌对/欠人情", area: true, rows: 2 },
            { sec: "静态：写一次", k: "emblem", label: "标志物", ph: "徽记、制服、口头禅" },
            { sec: "静态：写一次", k: "representatives", label: "代表人物", ph: "一把手 / 执行者 / 钉子" },
            { sec: "静态：写一次", k: "text", label: "一句话概述", ph: "给上下文用的一句话", area: true, rows: 2 },
            { sec: "动态：每次登场更新", k: "power", label: "当前实力", ph: "增了还是减了" },
            { sec: "动态：每次登场更新", k: "leader", label: "掌权者", ph: "有没有换人" },
            { sec: "动态：每次登场更新", k: "attitude", label: "对主角的态度", ph: "此刻是拉拢/利用/提防/翻脸", area: true, rows: 2 },
            { sec: "动态：每次登场更新", k: "misjudge", label: "他们以为主角是什么人", ph: "误判（最该盯死）", area: true, rows: 2 },
            { sec: "动态：每次登场更新", k: "changeLog", label: "变更日志", ph: "第几章：发生了什么，一行一条", area: true, rows: 3, full: true },
          ],
        },
        locations: {
          label: "地点", add: "+ 新建地点",
          sub: (x) => x.geo || x.text || "还没填位置",
          fields: [
            { sec: "静态：写一次", k: "name", label: "名称", ph: "地点名" },
            { sec: "静态：写一次", k: "aliases", label: "内部别名", ph: "俗称、旧名（顿号分隔）" },
            { sec: "静态：写一次", k: "geo", label: "地理位置", ph: "和哪些地点相邻、从 A 到 B 怎么走（地图比单点重要）", area: true, rows: 3 },
            { sec: "静态：写一次", k: "structure", label: "空间结构", ph: "几层、几间、进出口、死角", area: true, rows: 3 },
            { sec: "静态：写一次", k: "spots", label: "细分位置", ph: "堂门口、木牌底下、夹道、廊尾（顿号分隔）；位置轨迹按这些名字记成「地点（细分）」" },
            { sec: "静态：写一次", k: "senses", label: "感官标记", ph: "气味、声音、光线、温度", area: true, rows: 2 },
            { sec: "静态：写一次", k: "owner", label: "归属", ph: "归谁管、谁能进" },
            { sec: "静态：写一次", k: "accessRules", label: "进出规矩", ph: "什么时间开、要什么手续、谁能进（最该盯死）", area: true, rows: 2 },
            { sec: "静态：写一次", k: "text", label: "一句话概述", ph: "给上下文用的一句话", area: true, rows: 2 },
            { sec: "动态：每次登场更新", k: "occupied", label: "现在被谁占着", ph: "占着的人 / 开放时间" },
            { sec: "动态：每次登场更新", k: "state", label: "当前状态", ph: "完好 / 被封 / 被改 / 被毁" },
            { sec: "动态：每次登场更新", k: "events", label: "发生过哪些戏", ph: "第几章：谁在这里做了什么", area: true, rows: 3, full: true },
            { sec: "动态：每次登场更新", k: "familiar", label: "谁熟悉 / 谁吃过亏", ph: "谁知道暗道、谁在这里栽过", area: true, rows: 2, full: true },
          ],
        },
        items: {
          label: "物品", add: "+ 新建物品",
          sub: (x) => [x.type, x.holder].filter(Boolean).join(" · ") || x.text || "还没填持有人",
          fields: [
            { sec: "静态：写一次", k: "name", label: "名称", ph: "物品名" },
            { sec: "静态：写一次", k: "aliases", label: "俗称", ph: "别名、俗称（顿号分隔）" },
            { sec: "静态：写一次", k: "appearance", label: "外观触感", ph: "重量、温度、声音、手感", area: true, rows: 2 },
            { sec: "静态：写一次", k: "origin", label: "来历", ph: "怎么到主角手上的（读者不能接受凭空出现）", area: true, rows: 2 },
            { sec: "静态：写一次", k: "function", label: "功能", ph: "能做什么", area: true, rows: 2 },
            { sec: "静态：写一次", k: "limit", label: "限制", ph: "什么情况下没用" },
            { sec: "静态：写一次", k: "cost", label: "使用代价", ph: "用了要付什么" },
            { sec: "静态：写一次", k: "type", label: "类型", ph: "伏笔型 / 功能型 / 氛围型" },
            { sec: "静态：写一次", k: "text", label: "一句话概述", ph: "给上下文用的一句话", area: true, rows: 2 },
            { sec: "动态：每次转手更新", k: "holder", label: "当前持有人", ph: "现在在谁手里（最该盯死）" },
            { sec: "动态：每次转手更新", k: "state", label: "状态", ph: "完好 / 损坏 / 已交出 / 已销毁（最该盯死）" },
            { sec: "动态：每次转手更新", k: "whoKnows", label: "现在让谁知道什么", ph: "谁知道它存在 / 谁知道它在他手里", area: true, rows: 2, full: true },
            { sec: "动态：每次转手更新", k: "transferLog", label: "转移日志", ph: "第几章：从谁到谁，为什么，一行一条", area: true, rows: 3, full: true },
          ],
        },
        rules: {
          label: "规则", add: "+ 新建规则",
          sub: (x) => [x.level, x.text].filter(Boolean).join(" · ") || "还没填条文",
          fields: [
            { sec: "静态：写一次", k: "name", label: "规则短名", ph: "例如「夜里不能登记无名者」" },
            { sec: "静态：写一次", k: "text", label: "条文", ph: "用世界里的话写，不要用作者的话", area: true, rows: 3 },
            { sec: "静态：写一次", k: "judge", label: "判定者", ph: "谁执行、怎么知道违规了", area: true, rows: 2 },
            { sec: "静态：写一次", k: "cost", label: "代价", ph: "违反会怎样（必须可观察，最该盯死）", area: true, rows: 2 },
            { sec: "静态：写一次", k: "boundary", label: "边界与漏洞", ph: "什么时候不适用、漏洞在哪", area: true, rows: 2 },
            { sec: "静态：写一次", k: "level", label: "层级", ph: "铁律 / 惯例 / 谣言" },
            { sec: "静态：写一次", k: "source", label: "来源", ph: "这条规则从哪来（可延迟揭示）" },
            { sec: "静态：写一次", k: "keywords", label: "触发关键词", ph: "顿号分隔；体检时命中会报" },
            { sec: "静态：写一次", k: "note", label: "备注", ph: "给作者看的备注", area: true, rows: 2 },
            { sec: "动态：每次违规更新", k: "belief", label: "主角以为规则是什么", ph: "可能错；主角认知与真相分开记", area: true, rows: 2 },
            { sec: "动态：每次违规更新", k: "tested", label: "已实测的规则和结果", ph: "第几章：怎么试的，结果如何", area: true, rows: 2 },
            { sec: "动态：每次违规更新", k: "exploited", label: "已利用的漏洞", ph: "谁在什么时候钻了什么空子", area: true, rows: 2 },
            { sec: "动态：每次违规更新", k: "violationLog", label: "违规记录与代价落地", ph: "第几章：谁违规，是否真的受罚（最该盯死）", area: true, rows: 3, full: true },
          ],
        },
      };

      const assetWorkbench = () => {
        const meta = ASSET_META[assetTab];
        const rows = draft[assetTab] || [];
        const sel = rows[assetSel[assetTab]] ? assetSel[assetTab] : (rows.length ? 0 : -1);
        const cur = sel >= 0 ? rows[sel] : {};
        const upd = (k, v) => {
          if (sel < 0) return;
          const next = rows.slice();
          next[sel] = { ...next[sel], [k]: v };
          set(assetTab, next);
        };
        const add = () => {
          const next = [...rows, { name: "", _origName: "" }];
          set(assetTab, next);
          setAssetSel((s) => ({ ...s, [assetTab]: next.length - 1 }));
        };
        const del = () => {
          const nm = String(cur.name || "").trim();
          if (!window.confirm(`删掉「${nm || cur.text || "这条"}」？`)) return;
          if (nm) setDeletedAssets((d) => ({ ...d, [assetTab]: [...new Set([...(d[assetTab] || []), nm])] }));
          set(assetTab, rows.filter((_, i) => i !== sel));
          setAssetSel((s) => ({ ...s, [assetTab]: Math.max(0, sel - 1) }));
        };
        const cf = (f) => h(Field, { label: f.label },
          f.area
            ? h("textarea", {
                className: "nvs-area", style: { minHeight: (f.rows || 2) * 22, ...(f.full ? { gridColumn: "1 / -1" } : {}) },
                placeholder: f.ph, value: cur[f.k] ?? "", onChange: (e) => upd(f.k, e.target.value),
              })
            : h("input", {
                className: "nvs-input", placeholder: f.ph,
                value: Array.isArray(cur[f.k]) ? cur[f.k].join("、") : (cur[f.k] ?? ""),
                onChange: (e) => upd(f.k, e.target.value),
              }));
        const q = assetQuery.trim().toLowerCase();
        const filtered = rows.map((x, i) => ({ x, i })).filter(({ x }) => {
          if (!q) return true;
          return [x.name, ...aliasesToArray(x.aliases), x.text, x.nature, x.geo, x.type, x.level].join(" ").toLowerCase().includes(q);
        });
        const secs = [...new Set(meta.fields.map((f) => f.sec))];
        return h("div", { className: "nvs-card", style: { padding: "14px 16px" } },
          h("div", { className: "nvs-flex", style: { gap: 8, flexWrap: "wrap", marginBottom: 10 } },
            h("div", { className: "nvs-char-sub", style: { marginBottom: 0 } },
              Object.entries(ASSET_META).map(([k, m]) =>
                h("button", { key: k, type: "button", className: "nvs-chip", "aria-selected": assetTab === k ? "true" : "false", onClick: () => { setAssetTab(k); setAssetQuery(""); } }, m.label))),
            h("span", { className: "nvs-spacer" }),
            h("button", { className: "nvs-btn primary sm", onClick: add }, meta.add)),
          h("div", { style: { fontSize: 12, fontWeight: 700, margin: "2px 0 8px" } },
            `${meta.label}（${rows.length}）`,
            h("span", { className: "nvs-hint", style: { fontWeight: 400, marginLeft: 8 } },
              assetTab === "rules" ? "规则必须被违反一次，并且真的受罚；真假混编，主角认知和真相分开记。"
                : assetTab === "locations" ? "地图比单个地点重要：读者心里要有一张“从 A 到 B 怎么走”的图。"
                  : assetTab === "items" ? "只盯两栏：当前持有人、状态。九成穿帮都在这两栏。"
                    : "只盯两项：潜规则、他们以为主角是什么人。")),
          rows.length
            ? h("div", { className: "nvs-chars" },
                h("div", { className: "nvs-char-side" },
                  h("input", { className: "nvs-input", style: { marginBottom: 6, fontSize: 12.5 }, placeholder: `搜${meta.label}名、称呼、概述`, value: assetQuery, onChange: (e) => setAssetQuery(e.target.value) }),
                  h("div", { className: "nvs-char-list" }, filtered.length
                    ? filtered.map(({ x, i }) => h("button", {
                        key: i, type: "button", className: "nvs-char-item", "aria-current": sel === i ? "true" : "false",
                        onClick: () => setAssetSel((s) => ({ ...s, [assetTab]: i })),
                      },
                        h("span", { className: "nvs-char-item-main" },
                          h("b", null, x.name || "未命名"),
                          h("small", null, meta.sub(x)))))
                    : h("div", { className: "nvs-hint", style: { padding: "10px 6px" } }, "没有匹配的条目"))),
                h("div", { className: "nvs-char-main" },
                  h("div", { className: "nvs-char-title" },
                    h("div", null, h("b", null, cur.name || "未命名"), h("span", { className: "nvs-hint" }, "  " + (cur.text || ""))),
                    h("button", { className: "nvs-btn ghost sm", style: { color: "var(--nvs-danger,#DC2626)" }, onClick: del }, "删掉")),
                  secs.map((sec) => h("div", { className: "nvs-char-sec", key: sec },
                    h("h4", null, sec),
                    h("div", { className: "nvs-char-grid" }, meta.fields.filter((f) => f.sec === sec).map((f) => cf(f)))))))
            : h("div", { className: "nvs-note" }, `还没有${meta.label}。点「${meta.add}」手动加，或在「设定」页用 AI 补全。`));
      };

      return h("div", null,
        busy ? thinkRow(part === "characters" ? "正在推导人物、关系与信息差" : "正在拆解势力、地点、物品与硬规则") : null,
        showRest ? h(Card, { title: "设定补全", desc: ready
            ? "直接用大模型把大纲和世界观拆成人物、势力、地点、物品、硬规则、文风：已有的不覆盖，缺的自动补上。也可自己在下表里改后保存。"
            : "要先有「大纲」和「世界观」才能让 AI 补全。已有的大纲见「大纲」页，世界观见「世界观」页。" },
          h("div", { className: "nvs-flex", style: { alignItems: "center", gap: 8 } }, genBtn)) : null,

        showRest ? h(Card, { title: "文风与方向", desc: "禁用表达：正文里不许出现的词。当前方向：给 Agent 的写作要求，改完只影响后续章。"
            + (styleLocked ? " 第 1 章已写完，禁用表达与文风已锁定；只有「当前方向」还能改。" : " 写完第 1 章后文风锁定。") },
          h(Row, { label: "禁用表达", hint: "顿号或逗号分隔" },
            h("input", { className: "nvs-input", placeholder: "仿佛、不禁、一丝、嘴角上扬", value: draft.bannedText, disabled: styleLocked, onChange: (e) => set("bannedText", e.target.value) })),
          h(Row, { label: "当前方向", hint: "改方向后仅后续章生效" },
            h("textarea", { className: "nvs-area", style: { minHeight: 60 }, placeholder: "保持压抑克制的语气；主角越来越冷；节奏放慢", value: draft.direction, onChange: (e) => set("direction", e.target.value) }))) : null,

        showChars ? charactersPage() : null,

        showRest ? assetWorkbench() : null,

        showRest && (st.project.directionHistory && st.project.directionHistory.length)
          ? h(Card, { title: "方向变更记录", desc: "历次改方向的时间与生效章。" },
              h("div", { style: { display: "grid", gap: 6 } }, st.project.directionHistory.map((d, i) =>
                h("div", { key: i, className: "nvs-flex", style: { fontSize: 12 } },
                  h("span", { className: "nvs-pill" }, "第" + (d.atChapter || 0) + "章起"), h("span", { style: { color: "var(--nvs-sub)" } }, d.direction)))))
          : null);
    }

    /* --------------------------------- 进度 --------------------------------- */
    const vtag = (c) => {
      if (!c.reviewed) return h("span", { className: "tag wait" }, "已写 · 未审");
      const v = c.chapterVerdict || (c.verdict === "差" ? "needs_fix" : "pass");
      if (v === "pass") return h("span", { className: "tag ok" }, "已审 · 通过");
      return h("span", { className: "tag bad", title: "点这一章的「重写本章」，AI 会先体检再按问题重写" }, "已审 · 待修");
    };

    // 每章两个动作：体检 / 去味；细纲按 10 章一段的段落纲走，写正文时一起带上。
    function Progress({ st, dir, toast, onChanged }) {
      const [open, setOpen] = useState(null);
      const [chapter, setChapter] = useState(null);
      const [loading, setLoading] = useState(false);
      const [busyN, setBusyN] = useState(0);
      const [busyOp, setBusyOp] = useState("");
      const [writing, setWriting] = useState(false);
      const [exporting, setExporting] = useState(false);
      const [checkResult, setCheckResult] = useState(null); // {number, pass, findings, counts}
      const [batchResult, setBatchResult] = useState(null); // 按批体检结果
      const [batchBusy, setBatchBusy] = useState(false);
      const [logicResult, setLogicResult] = useState(null); // {number, scenes, issues[]}
      const [voiceResult, setVoiceResult] = useState(null); // {number, note, marks[]}
      const [search, setSearch] = useState(""); // 正文搜索：断层定位、找某句原话都用它
      // 每卷一条卷记忆，按卷尾章号对号入座（同一卷重盘会覆盖）
      const [volMemMap, setVolMemMap] = useState(() => {
        const m = {};
        for (const x of (st.volumeMemories || [])) m[Number(x.to)] = x;
        return m;
      });
      const [foldedVols, setFoldedVols] = useState({});
      const doCompileVolume = async (vol) => {
        const at = Number(vol?.from) || (st.project.currentChapter || 0);
        if (!at) { toast("还没有正文可以盘点"); return; }
        setBusyN(-1); setBusyOp("volume");
        try {
          const ms = readModelSel() || {};
          const r = await postJSON("memory-compile", { dir, number: at, provider: ms.provider || undefined, model: ms.model || undefined });
          if (r && r.ok) setVolMemMap((prev) => ({ ...prev, [Number(r.to)]: r }));
          toast(r && r.ok ? `已盘点「${r.volume.title}」（第${r.from}-${r.to}章）` : (r?.error || "盘点没成功"));
        } catch (e) { toast("卷盘点失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      const busy = (n, op) => busyN === n && busyOp === op;
      // 已存档章节合并成一个 txt，落在项目 exports/ 下；路径顺手复制到剪贴板
      const doExport = async () => {
        if (exporting) return;
        setExporting(true);
        try {
          const r = await postJSON("export", { dir, scope: "all", from: 1 });
          const file = (r.files || [])[0] || "";
          if (file) copyText(file);
          toast(`已导出 ${r.count} 章${file ? "：" + file + "（路径已复制）" : ""}`);
        } catch (e) { toast("导出失败：" + (e.message || e)); }
        setExporting(false);
      };
      const allChapters = st.chapters || [];
      // 「确认后才存档到进度」：未通过确认的章放「待你确认」，approved 的才进「已存档」
      const pending = allChapters.filter((c) => !c.approved);
      const archived = allChapters.filter((c) => c.approved);
      // 待确认的章：进页面自动跑一次该章体检（含 must-include/漏埋伏笔等全书级检查），把结果显示在行上，
      // 免得"刚写完看不到问题、存档后才发现"。key=章号，value={pass,counts,findings}
      const [preCheck, setPreCheck] = useState({});
      const ranPre = useRef({});
      // 自动存档：待确认的章进页面就挨个体检，体完直接存档（作者口径：先收进正文，再按体检结果逐章重写）。
      // 关掉自动存档的开关在「设置」页；关掉后回到手动点「存档」。
      const autoArchive = readAutoArchive();
      const autoRun = useRef(false);
      useEffect(() => {
        if (!autoArchive || autoRun.current || !pending.length) return () => {};
        autoRun.current = true;
        let alive = true;
        (async () => {
          for (const c of pending) {
            if (ranPre.current[c.number]) continue;
            ranPre.current[c.number] = true;
            try {
              const r = await postJSON("chapter-check", { dir, number: c.number, discardIfFail: false });
              const ck = r.check || r;
              if (alive) setPreCheck((prev) => ({ ...prev, [c.number]: { pass: Boolean(ck.pass), counts: ck.counts || {}, findings: ck.findings || [] } }));
            } catch (_) { ranPre.current[c.number] = false; continue; }
            if (!alive) break;
            try {
              await postJSON("approve", { dir, number: c.number, force: true });
            } catch (_) { /* 这一章存不进去就留给作者手动处理，不影响其它章 */ }
          }
          if (!alive) return;
          autoRun.current = false;
          toast(pending.length > 1 ? `已自动存档 ${pending.length} 章，问题见下面每章的体检` : "已自动存档，问题见下面体检");
          if (onChanged) await onChanged();
        })();
        return () => { alive = false; };
      }, [dir, autoArchive, JSON.stringify(pending.map((c) => c.number))]);
      const chapters = allChapters;
      const title = st.project.title || "这本书";
      const nextN = Number(st.nextChapter) || (Number(st.project.currentChapter) || 0) + 1;

      const view = async (n, keyword) => {
        // keyword：从断层结果点「在正文里定位」时带过来，直接展开并高亮
        if (open === n && !keyword) { setOpen(null); setChapter(null); setSearch(""); return; }
        setSearch(keyword || "");
        setOpen(n); setLoading(true); setChapter(null);
        try { setChapter(await getJSON(`chapter?dir=${q(dir)}&number=${n}`)); }
        catch (e) { toast("读不到这一章：" + e.message); setOpen(null); }
        setLoading(false);
      };

      // 一键复制本章正文：已展开就直接用内存里的，没展开就现读一次；不落盘、不改任何状态。
      const doCopy = async (n) => {
        try {
          let text = (open === n && chapter && Number(chapter.number) === Number(n)) ? chapter.text : "";
          if (!text) {
            const r = await getJSON(`chapter?dir=${q(dir)}&number=${n}`);
            text = r.text || "";
          }
          if (!text) { toast(`第 ${n} 章正文是空的`); return; }
          if (!copyText(text)) { toast("复制失败：当前环境不允许写剪贴板"); return; }
          const chars = String(text).replace(/\s+/gu, "").length;
          toast(`已复制第 ${n} 章正文（${chars} 字）`);
        } catch (e) { toast("复制失败：" + (e.message || e)); }
      };

      const doCheck = async (n) => {
        // 体检：确定性规则先跑，语义类候选再交给 AI 复核（引文核对不过就维持原判）。
        setBusyN(n); setBusyOp("check");
        try {
          const ms = readModelSel() || {};
          let ck;
          try {
            ck = await postJSON("chapter-review", { dir, number: n, provider: ms.provider || undefined, model: ms.model || undefined });
          } catch (e0) {
            const r = await postJSON("chapter-check", { dir, number: n, discardIfFail: false });
            ck = (r && r.check) || r;
          }
          setCheckResult({
            number: n, pass: Boolean(ck.pass), findings: ck.findings || [],
            counts: ck.counts || {}, reviewed: ck.reviewed || 0, reviewError: ck.reviewError || "",
          });
          const cleared = (ck.findings || []).filter((f) => f.ai && f.ai.verdict !== "real").length;
          if (ck.pass && onChanged) await onChanged();
          const say = ck.reviewError
            ? `第 ${n} 章体检完成（AI 复核没跑成：${ck.reviewError}）`
            : ck.pass
              ? `第 ${n} 章体检通过${cleared ? `（AI 复核清掉 ${cleared} 条误报）` : ""}`
              : `第 ${n} 章体检发现 ${((ck.findings || []).filter((f) => f.severity !== "info").length + (ck.debutMisses || []).length)} 个问题，见下方`;
          toast(say);
        } catch (e) { toast("体检失败：" + e.message); }
        setBusyN(0); setBusyOp("");
      };
      const dismissCheck = async (f) => {
        try {
          await postJSON("dismiss", { dir, kind: "continuity", code: f.code, message: f.message });
          setCheckResult((s) => (s ? { ...s, findings: s.findings.filter((x) => x !== f) } : s));
          toast("已标记为合理，这一章同类问题之后不再报");
        } catch (e) { toast("标记失败：" + (e.message || e)); }
      };

      // 存档后也能作废：直接对已存档的章作废（带二次确认）
      // 作废只清正文和记忆；伏笔/登场章列出来，作者点确认才清
      const offerDiscardCleanup = async (n, r) => {
        const im = (r && r.impacts) || {};
        const fs = im.foreshadows || [];
        const ppl = im.characters || [];
        if (!fs.length && !ppl.length) return;
        const parts = [];
        if (fs.length) parts.push("伏笔：" + fs.join("、"));
        if (ppl.length) parts.push("人物（登场章）：" + ppl.join("、"));
        if (!window.confirm(`第 ${n} 章还挂着：\n${parts.join("\n")}\n\n一起清理？清完伏笔移出未收，人物登场章清空，重写正文后可再补。`)) return;
        try {
          await postJSON("cleanup", { dir, number: n });
          toast("已清掉这一章挂着的伏笔/登场章");
        } catch (e) { toast("清理失败：" + (e.message || e)); }
      };
      const doDiscardArchived = async (n, isPending = false) => {
        const where = isPending ? `把待确认的第 ${n} 章作废？作废后它移入「废章」（稿子备份在废章页，可展开/恢复），章号释放、可立刻重写。` : `把已存档的第 ${n} 章作废？作废后它从「已存档」移入「废章」（稿子备份在废章页，可展开/恢复），字数与进度会回退。`;
        if (!window.confirm(where)) return;
        setBusyN(n); setBusyOp("discard");
        try {
          const r = await postJSON("discard", { dir, number: n, reason: isPending ? "作者在待确认阶段作废" : "作者在存档后手动作废" });
          toast(`第 ${n} 章已作废，移到废章页（可展开/恢复）；这一章的记忆已清`);
          await offerDiscardCleanup(n, r);
          if (onChanged) await onChanged();
        } catch (e) { toast("作废失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };

      // 在体检结果里点「作废本章」才真正进废章
      const doDiscardFromCheck = async (n) => {
        setBusyN(n); setBusyOp("discard");
        try {
          const r = await postJSON("discard", { dir, number: n, reason: "体检后作者确认作废" });
          toast(`第 ${n} 章已进废章（稿子在废章页可展开/恢复）；这一章的记忆已清`);
          await offerDiscardCleanup(n, r);
          setCheckResult(null);
          if (onChanged) await onChanged();
        } catch (e) { toast("作废失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };

      const doDeslop = async (n) => {
        // 去味：开一个会话让 AI 调去味技能，之后该章进废章、新章替换
        setBusyN(n); setBusyOp("deslop");
        try {
          const prompt = [
            `用 novel-studio 技能，把《${title}》第 ${n} 章去 AI 味。`,
            skillLines("deslop"),
            `1) novel_chapter op=read 读这一章原文；`,
            `2) 按 story-deslop 的清单逐段改掉 AI 痕迹，不许改剧情、不许删情节；`,
            `3) novel_gate rewrite ${n} 把旧稿退回 drafts/，再 novel_chapter 提交新的第 ${n} 章；`,
            `4) 提交后 novel_continuity 体检，然后停下等我确认。`,
          ].join("\n");
          const r = await openWritingSession(dir, prompt);
          toast(r.ok ? `已开会话给第 ${n} 章去味` : "已复制去味指令：" + r.reason);
        } catch (e) { toast("去味失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };

      // 写下一段：段落纲没有就让 Agent 先 novel_segment op=plan，再一章章写
      const startNext = async () => {
        setWriting(true);
        try {
          const seg = (st.segments || []).find((g) => nextN >= Number(g.from) && nextN <= Number(g.to)) || null;
          const size = Math.min(10, Math.max(1, (Number(st.project?.targetChapters) || nextN + 9) - nextN + 1));
          const r = await openWritingSession(dir, batchChapterPrompt(st, nextN, size, seg));
          if (!r.ok) toast("打开会话失败：" + r.reason);
        } catch (e) { toast("打开会话失败：" + (e.message || e)); }
        setWriting(false);
      };

      // 读本章正文，把新出现的人物/地点/物品/势力/硬规则补进设定（只补不覆盖）
      const syncChapterSettings = async (n) => {
        const ms = readModelSel() || {};
        const nums = Array.isArray(n) ? n : [n];
        const r = await postJSON("setting-sync", nums.length > 1
          ? { dir, numbers: nums, provider: ms.provider || undefined, model: ms.model || undefined }
          : { dir, number: nums[0], provider: ms.provider || undefined, model: ms.model || undefined });
        const a = (r && r.added) || {};
        const parts = [];
        if ((a.characters || []).length) parts.push("人物 " + a.characters.join("、"));
        if ((a.locations || []).length) parts.push("地点 " + a.locations.join("、"));
        if ((a.items || []).length) parts.push("物品 " + a.items.join("、"));
        if ((a.factions || []).length) parts.push("势力 " + a.factions.join("、"));
        if ((a.rules || []).length) parts.push("硬规则 " + a.rules.join("、"));
        // 批量补时 relations/infoGaps 在顶层；单章补时在 r.relations 下
        const relNew = (Array.isArray(r && r.relations) ? r.relations : (r && r.relations && r.relations.relations) || (r && r.relations0) || []);
        const gapNew = (Array.isArray(r && r.infoGaps) ? r.infoGaps : (r && r.relations && r.relations.infoGaps) || []);
        if (relNew.length) parts.push("关系矩阵 +" + relNew.length + " 对");
        if (gapNew.length) parts.push("信息差 +" + gapNew.length + " 条");
        const filled = (r && r.filled) || [];
        if (filled.length) parts.push("补全 " + filled.map((f) =>
          `${f.name}${(f.fields || []).includes("firstChapter") && f.firstChapter ? `（登场章→第${f.firstChapter}章）` : ""}`).join("、"));
        return parts;
      };

      const doApprove = async (n, force) => {
        setBusyN(n); setBusyOp("approve");
        try {
          const ap = await postJSON("approve", { dir, number: n, force: force ? true : undefined });
          const debut = (ap && ap.debutFilled) || [];
          const batchOk = Array.isArray(ap && ap.batchApproved) && ap.batchApproved.length > 1;
          const debutText = debut.length
            ? `；已按正文补首次登场：${debut.map((f) => `${f.name}（第${f.firstChapter}章）`).join("、")}`
            : "";
          toast(batchOk ? `本批第 ${ap.batchApproved[0]}-${ap.batchApproved[ap.batchApproved.length - 1]} 章已一次 review 通过${debutText}` : `第 ${n} 章已确认存档${debutText}`);
          if (onChanged) await onChanged();
          // 存档后两步（记忆 + 设定），顺序无所谓但都做：
          //  ① memory-distill：把本章精炼成叙事记忆写 ledger/memory.jsonl（写下一章时 narrativeMemory 会用它喂回前情）
          //  ② setting-sync：把本章新出现、设定里还没有的实体补进 bible
          try {
            const ms = readModelSel() || {};
            setBusyOp("sync");
            try {
              const md = await postJSON("memory-distill", { dir, number: n, provider: ms.provider || undefined, model: ms.model || undefined });
              if (md && md.ok && md.memory) toast(`已记住第 ${n} 章：${(md.memory.events || []).length} 个关键事件`);
            } catch (e0) { /* 记忆精炼失败不阻塞，narrativeMemory 会退回用 summary */ }
            // 整批通过：设定也一次补整批（不再一章一章补）
            let nums = Array.isArray(ap && ap.batchApproved) && ap.batchApproved.length > 1 ? ap.batchApproved : [n];
            // 单章 approve 时，若这一章之后还有同批待确认章，先只补这一章（整批补等批尾 approve 或点「补设定」）
            if (nums.length === 1 && Array.isArray(ap && ap.approvedChapters) && ap.approvedChapters.length > 1) nums = ap.approvedChapters;
            const parts = await syncChapterSettings(nums);
            const label = nums.length > 1 ? `第 ${nums[0]}-${nums[nums.length - 1]} 章（整批一次补）` : `第 ${n} 章`;
            if (parts.length) {
              toast(`已把 ${label} 新增/补全的设定写进骨架：${parts.join("；")}`);
              if (onChanged) await onChanged();
            } else {
              toast(`${label} 没有需要补充的设定`);
            }
          } catch (e2) {
            // 补设定失败不影响存档；只轻提示，作者可稍后在设定页手动补
            toast(`第 ${n} 章已存档；自动补设定没成功（${(e2.message || e2)}），可在「进度」页这一章点「补设定」重试`);
          }
        } catch (e) { toast("确认失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      // 手动补设定（自动补失败时用；只补不覆盖）。待确认里的章属于同一批：一次补整批。
      const doSyncChapter = async (n) => {
        const pend = new Set((st.chapters || []).filter((c) => !c.approved).map((c) => Number(c.number)));
        const batch = [...pend].sort((a, b) => a - b);
        const targets = batch.length > 1 ? batch : [n];
        const label = targets.length > 1 ? `第 ${targets[0]}-${targets[targets.length - 1]} 章（整批一次补）` : `第 ${n} 章`;
        setBusyN(n); setBusyOp("sync");
        try {
          const parts = await syncChapterSettings(targets);
          toast(parts.length ? `${label}设定已补充：${parts.join("；")}` : `${label}没有需要补充的设定`);
          if (parts.length && onChanged) await onChanged();
        } catch (e) {
          toast(`补设定失败：${e.message || e}`);
        }
        setBusyN(0); setBusyOp("");
      };
      // 统一把体检问题列表格式化成重写提示词——ALL 级别都在（high/mid/info 一条不漏），去重保序。
      const formatFindingsAll = (findings) => {
        const seen = new Set();
        const rows = (findings || [])
          .filter((f) => f && f.message && !(seen.has(f.message) ? true : (seen.add(f.message), false)))
          .map((f, i) => {
            const tag = f.severity === "high" ? "硬性问题" : f.severity === "mid" ? "提醒" : "参考";
            return `${i + 1}. [${tag}] ${f.message}${f.hint ? "（建议：" + f.hint + "）" : ""}`;
          });
        return rows.join("\n");
      };
      // 退回重写要带的「完整上下文」：本批段落纲、批次位置、旧稿、同批其他章摘要与结尾。
      // 只给问题清单，模型就只会照着清单补句子，剧情线会断。
      const buildRewriteContext = async (n) => {
        const lines = [];
        const seg = (st.segments || []).find((g) => Number(n) >= Number(g.from) && Number(n) <= Number(g.to)) || null;
        if (seg) {
          const pos = Number(n) - Number(seg.from) + 1;
          lines.push(`本批段落纲：第${seg.from}-${seg.to} 章（${seg.stages} 个台阶${seg.spine ? `，主线：${seg.spine}` : ""}），本章是批内第 ${pos} 章。`);
        }
        const sameBatch = seg
          ? (st.chapters || []).filter((c) => Number(c.number) >= Number(seg.from) && Number(c.number) <= Number(seg.to) && Number(c.number) !== Number(n))
          : [];
        if (sameBatch.length) {
          lines.push("同批其它章（保持剧情顺序衔接，重写后不能和它们矛盾）：");
          for (const c of sameBatch) {
            const mark = Number(c.number) < Number(n) ? "（在前）" : "（在后）";
            lines.push(`- 第${c.number}章《${c.title || ""}》${mark}：${c.summary || c.lead || "（无摘要）"}`);
          }
        }
        try {
          const ch = await getJSON(`chapter?dir=${q(dir)}&number=${n}`);
          if (ch && ch.text) lines.push(`旧稿（必须重写的版本，全文如下，约 ${String(ch.text).length} 字）：\n"""\n${String(ch.text).slice(0, 9000)}\n"""`);
        } catch (_) { /* 旧稿读不到就不带，上下文包仍然够用 */ }
        return lines.join("\n");
      };

      const doRewrite = async (n) => {
        // 把这一章已经查出的问题（含 info 参考项、登场缺席、AI 痕迹明细、断层、人设）全部写进重写要求
        const ck = checkResult && Number(checkResult.number) === Number(n) ? checkResult : null;
        const findings = [
          ...((preCheck[n] && preCheck[n].findings) || []),
          ...((ck && ck.findings) || []),
          // 登场缺席/迟到（checkChapter.debutMisses）
          ...((ck && ck.debutMisses) || []),
          // AI 痕迹明细（judge/tells 存在 preCheck 里时也并入，若有）
          ...(logicResult && Number(logicResult.number) === Number(n)
            ? (logicResult.issues || []).map((it) => ({ severity: "mid", message: ["叙事断层", it.between, it.issue].filter(Boolean).join("："), hint: it.suggestion || "" }))
            : []),
        ].filter((f) => f && f.message);
        const note = formatFindingsAll(findings);
        // 和「参考体检问题重写本章」同一个确认体验：旧稿进废章页可恢复，新稿提交后替换
        if (!window.confirm(`把第 ${n} 章退回重写？旧稿会存进废章页（可恢复），新稿提交后替换它。${note ? `\n\n会把下面 ${note.split("\n").length} 条问题一起交给 AI：\n${note}` : ""}`)) return;
        setBusyN(n); setBusyOp("rewrite");
        try {
          // 1) 正式退稿：写 review/rewrite-request.md、把旧稿移进 drafts/、gate 回退到 writing(n)
          await postJSON("rewrite", { dir, number: n, note });
        } catch (e) {
          toast("退回失败：" + (e.message || e));
          setBusyN(0); setBusyOp(""); return;
        }
        // 2) 立刻开写作会话，按这些问题重写（与「参考体检问题重写本章」一致）
        try {
          const list = note || "体检没报出硬问题：先读正文和上下文包里的本段段落纲，重点查人物是否按设定登场、每个事件的动机是否成立、场景衔接是否断层，改完再提交。";
          const ctx = await buildRewriteContext(n);
          const prompt = [
            `用 novel-studio 技能，把《${title}》第 ${n} 章退回重写。旧稿已作废进废章页（可恢复）。`,
            `第一步必须 novel_context ${n} 取完整上下文包：本段段落纲与本章所在台阶、出场角色卡（性格/欲望/秘密/口吻）、未回收伏笔与本章该埋的伏笔、硬规则与禁用表达、上一章收尾状态、文风样本。写作以这个包为唯一事实来源，不要凭记忆续写。`,
            ctx ? `\n本批上下文（面板补充，用来保持前后衔接）：\n${ctx}` : "",
            `\n这次重写要解决的问题（逐条处理，但不要只盯着这几条改句子）：\n${list}`,
            `要求：`,
            `1) 剧情走向、本章在整批台阶里的位置、章末要引出的下一章事件都保持不变；`,
            `2) 问题清单里点到的伏笔埋点、必须出现的要素、章尾钩子必须补上，且和上下文包里的人物状态一致；`,
            `3) 不要新增设定外的人物；不要把本来是伏笔的细节写成明说；`,
            `4) 字数不低于 1800 字。`,
            `写完用 novel_chapter 提交第 ${n} 章（批内带 batch:true），再 novel_continuity 体检，然后停下等我确认。`,
            `注意：正文一律用 novel_chapter op=read 读，不要去 exports/ 找 txt。`,
          ].join("\n");
          const r = await openWritingSession(dir, prompt);
          toast(r.ok ? `第 ${n} 章已退回重写${note ? `，${note.split("\n").length} 条问题已附进重写要求` : ""}，已开会话让 AI 重写` : `第 ${n} 章已退回（草稿在 drafts/），重写指令已复制：${r.reason}`);
        } catch (e) {
          toast(`第 ${n} 章已退回（草稿在 drafts/），但开会话失败：${e.message || e}`);
        }
        if (onChanged) await onChanged();
        setBusyN(0); setBusyOp("");
      };

      // 叙事断层检查（语义级，只报不拦）：抓「场景之间接不上」——跳步/瞬移/因果断裂
      const doLogic = async (n) => {
        setBusyN(n); setBusyOp("logic");
        try {
          const ms = readModelSel() || {};
          const r = await postJSON("logic-check", { dir, number: n, provider: ms.provider || undefined, model: ms.model || undefined });
          setLogicResult({ number: n, scenes: r ? r.scenes : 0, issues: (r && r.issues) || [] });
          const say = (r && r.summary) || (((r && r.issues) || []).length ? `发现 ${r.issues.length} 处叙事断层` : "场景衔接顺畅，没发现断层");
          toast(r && r.pass === false ? `第 ${n} 章：${say}，见下方（只提示不拦）` : `第 ${n} 章：${say}`);
        } catch (e) { toast("叙事断层检查失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      const dismissLogic = async (it) => {
        try {
          await postJSON("dismiss", {
            dir, kind: "logic", chapter: logicResult.number,
            between: it.between, issue: it.issue,
          });
          setLogicResult((s) => (s ? { ...s, issues: s.issues.filter((x) => x !== it) } : s));
          toast("已标记为合理，之后这条不再报");
        } catch (e) { toast("标记失败：" + (e.message || e)); }
      };

      const doVoice = async (n) => {
        setBusyN(n); setBusyOp("voice");
        try {
          const ms = readModelSel() || {};
          const r = await postJSON("voice-drift", { dir, chapter: n, provider: ms.provider || undefined, model: ms.model || undefined });
          const marks = (r && r.marks) || [];
          setVoiceResult({ number: n, note: (r && r.note) || "", marks });
          if (marks.length) {
            toast(`第 ${n} 章人设核对：${r.note || ""}，${marks.length} 句可能有走味（见下方，只提示不拦）`);
          } else {
            toast(`第 ${n} 章人设核对：${r.note || "未发现走味"}`);
          }
          if (onChanged) await onChanged();
        } catch (e) { toast("人设核对失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      const chapterRow = (c, isPending) => {
        const lead = c.lead || c.excerpt || "";
        const needFix = c.chapterVerdict === "needs_fix";
        // 正文搜索：把命中的片段包成 <mark>，断层定位也复用同一套
        const markText = (text, kw) => {
          const q = String(kw || "");
          if (!q) return text;
          const parts = String(text).split(q);
          if (parts.length === 1) return text;
          const out = [];
          parts.forEach((p, i) => { if (i) out.push(h("mark", { key: "m" + i }, q)); out.push(p); });
          return out;
        };
        const kw = open === c.number ? search.trim() : "";
        const hits = kw && chapter ? String(chapter.text).split(kw).length - 1 : 0;
        return h("div", { key: c.number, style: { borderTop: "1px solid var(--nvs-line)", paddingTop: 4, marginTop: 4 } },
          h("div", { className: "nvs-ch", onClick: () => view(c.number) },
            h("span", { className: "num" }, String(c.number).padStart(3, "0")),
            h("span", { className: "name" }, c.title || "未命名"),
            h("span", { className: "chars" }, (c.chars || 0) + " 字"),
            isPending ? h("span", { className: "tag wait" }, "待确认") : vtag(c),
            h("span", { className: "nvs-hint" }, open === c.number ? "收起" : "展开")),
          lead ? h("div", { className: "nvs-hint", style: { padding: "0 4px 4px 36px", lineHeight: 1.7 } }, lead + (lead.length >= 50 ? "…" : "")) : null,
          (needFix && (c.fixReasons || []).length)
            ? h("div", { className: "nvs-hint", style: { padding: "0 4px 4px 36px", color: "#DC2626" } }, "待修：" + c.fixReasons.join("；"))
            : null,
          (c.endHook && c.endHook.ok === false) ? h("div", { className: "nvs-hint", style: { padding: "0 4px 4px 36px", color: "#B45309" } }, "⚠ 章尾没钩子：" + (c.endHook.reason || "读者可能不追更")) : null,
          (preCheck[c.number])
            ? (preCheck[c.number].findings.length
                ? h("div", { style: { padding: "2px 4px 4px 36px" } },
                    h("div", { className: "nvs-hint", style: { color: preCheck[c.number].counts.high ? "#DC2626" : "#B45309" } },
                      `体检：${preCheck[c.number].counts.high} high / ${preCheck[c.number].counts.mid} mid`),
                    preCheck[c.number].findings.slice(0, 4).map((f, i) =>
                      h("div", { key: i, className: "nvs-hint", style: { paddingLeft: 8, color: f.severity === "high" ? "#DC2626" : "#8a8f98" } },
                        "· " + f.message)))
                : h("div", { className: "nvs-hint", style: { padding: "2px 4px 4px 36px", color: "#16A34A" } }, "体检：没发现连续性问题")) 
            : null,
          h("div", { className: "nvs-flex", style: { padding: "2px 4px 8px 36px", gap: 6, justifyContent: isPending ? "flex-end" : "flex-start" } },
            isPending
              ? [
                  // 按钮顺序：退回重写 → 审查 → 补设定 → 复制 → 存档（粉色，贴在右侧「待确认」标签旁）。
                  // 「删除」按作者标注去掉——要丢弃就退回重写，旧稿在废章页可恢复。
                  h("button", { key: "r", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doRewrite(c.number); } },
                    busy(c.number, "rewrite") ? "退回中…" : "退回重写"),
                  h("button", { key: "rv", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); reviewChapter(c.number); } },
                    busy(c.number, "review") ? "开会话中…" : "审查"),
                  h("button", { key: "s", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doSyncChapter(c.number); } },
                    busy(c.number, "sync") ? "补设定中…" : "补设定"),
                  h("button", { key: "cp", className: "nvs-btn sm", onClick: (e) => { e.stopPropagation(); doCopy(c.number); } }, "复制"),
                  h("button", { key: "a", className: "nvs-btn sm primary", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doApprove(c.number, true); } },
                    busy(c.number, "approve") ? "存档中…" : "存档"),
                ]
              : [
                  needFix
                    ? h("button", { key: "rw2", className: "nvs-btn sm primary", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doRewriteArchived(c.number); } },
                        busy(c.number, "check") ? "体检中…" : busy(c.number, "rewrite") ? "退回中…" : "重写本章")
                    : null,
                  h("button", { key: "c", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doCheck(c.number); } }, busy(c.number, "check") ? "体检中…" : "体检"),
                  h("button", { key: "l", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doLogic(c.number); } }, busy(c.number, "logic") ? "查断层中…" : "断层"),
                  h("button", { key: "d", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doDeslop(c.number); } }, busy(c.number, "deslop") ? "开会话中…" : "去味"),
                  h("button", { key: "rv", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); reviewChapter(c.number); } }, busy(c.number, "review") ? "开会话中…" : "审查"),
                  h("button", { key: "v", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doVoice(c.number); } }, busy(c.number, "voice") ? "核对中…" : "人设核对"),
                  h("button", { key: "s", className: "nvs-btn sm", disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doSyncChapter(c.number); } }, busy(c.number, "sync") ? "补设定中…" : "补设定"),
                  h("button", { key: "cp", className: "nvs-btn sm", onClick: (e) => { e.stopPropagation(); doCopy(c.number); } }, "复制"),
                  h("button", { key: "x", className: "nvs-btn sm", style: { color: "#DC2626" }, disabled: busyN === c.number, onClick: (e) => { e.stopPropagation(); doDiscardArchived(c.number); } }, busy(c.number, "discard") ? "作废中…" : "作废"),
                ]),
          open === c.number
            ? h("div", { style: { padding: "6px 4px 16px" } },
                loading ? h("div", { className: "nvs-hint" }, "读取中…")
                  : chapter ? h("div", null,
                      h("div", { className: "nvs-flex", style: { gap: 8, marginBottom: 6 } },
                        h("input", {
                          className: "nvs-input", style: { flex: 1, fontSize: 13, padding: "5px 9px" },
                          placeholder: "在正文里搜（断层位置、某句原话都可以）",
                          value: search, onChange: (e) => setSearch(e.target.value),
                        }),
                        h("span", { className: "nvs-hint", style: { flex: "none", minWidth: 56, textAlign: "right" } },
                          kw ? (hits ? `命中 ${hits} 处` : "没找到") : "")),
                      h("div", { className: "nvs-prose", style: { padding: "10px 2px", maxHeight: 520, overflow: "auto" } }, markText(chapter.text, kw)))
                  : null)
            : null);
      };

      if (!chapters.length) {
        return h(Card, { title: "还没有章节" },
          h("div", { className: "nvs-note" }, "回「概览」点「写第 1 章」，Agent 写完提交后这里就会有内容。"));
      }

      const sevColor = (sev) => sev === "high" ? "#DC2626" : sev === "mid" ? "#D97706" : "#6B7280";
      // 按批体检：整批一次看，每章只给结论；要重写的按章走「重写本章」
      const batchCheck = async () => {
        // 范围：gate 停的那章（正在写/待确认）所在的段落纲；没有段落纲就看最近一批。
        // 用 gate 而不是「最后一个待确认章」：批内写到一半、或某章被退回时，
        // 待确认列表可能是空的，按待确认章取范围会查到一个不相干的批次。
        const g = st.gate || st.project?.gate || null;
        const cur = Number(g && g.chapter) || nextN;
        const hitSeg = (st.segments || []).find((x) => cur >= Number(x.from) && cur <= Number(x.to)) || null;
        setBatchBusy(true); setBatchResult(null);
        try {
          const r = await postJSON("batch-check", hitSeg ? { dir, from: Number(hitSeg.from), to: Number(hitSeg.to) } : { dir });
          setBatchResult(r || null);
          // 把整批的问题直接铺到每一章的行上（作者口径：点了就在每章下面看到问题，再按章重写）
          const rows = (r && r.chapters) || [];
          if (rows.length) {
            setPreCheck((prev) => {
              const next = { ...prev };
              for (const row of rows) {
                if (row.missing) continue;
                // 按批体检是整批视角（含章首复述、片段偏离等跨章检查），以它为准；
                // 之后单章体检不再覆盖，避免「下面报了问题、上面批量里却没有」。
                next[row.number] = { pass: row.action === "ok", counts: row.counts || {}, findings: row.findings || [], fromBatch: true };
              }
              return next;
            });
            // 标记这些章已被整批体检过，单章体检不要回头覆盖
            for (const row of rows) if (!row.missing) ranPre.current[row.number] = true;
          }
          const todo = ((r && r.chapters) || []).filter((c) => c.action === "rewrite").map((c) => c.number);
          const block = ((r && r.blocking) || []).length;
          toast(`按批体检 第${r.from}-${r.to}章：${todo.length ? `第 ${todo.join("、")} 章要重写` : "没有要重写的章"}${block ? `；${block} 条整批问题` : ""}，问题已标在各章下面`);
        } catch (e) { toast("按批体检失败：" + (e.message || e)); }
        setBatchBusy(false);
      };
      // 按批体检的结果已经铺到每章行上（见 batchCheck），这里只留一行汇总 + 整批问题
      const batchCard = batchResult
        ? h(Card, {
            title: `按批体检 第${batchResult.from}-${batchResult.to}章`,
            desc: (() => {
              const rows = batchResult.chapters || [];
              const todo = rows.filter((c) => c.action === "rewrite").map((c) => c.number);
              const miss = rows.filter((c) => c.action === "missing").map((c) => c.number);
              const parts = [];
              parts.push(todo.length ? `要重写：第 ${todo.join("、")} 章` : "没有要重写的章");
              if (miss.length) parts.push(`还没写：第 ${miss.join("、")} 章`);
              if ((batchResult.blocking || []).length) parts.push(`整批问题 ${batchResult.blocking.length} 条`);
              return parts.join("；") + "。问题已标在下面每一章；要改点那一章的「重写本章」。";
            })(),
            right: h("div", { className: "nvs-flex", style: { gap: 6, flex: "none" } },
              h("button", { className: "nvs-btn sm", onClick: () => setBatchResult(null) }, "关闭")),
          },
            (batchResult.blocking || []).length
              ? h("div", { style: { display: "grid", gap: 4 } },
                  h("div", { className: "nvs-hint", style: { color: "#DC2626" } }, "整批问题（不属于某一章，批尾通过会被拦）："),
                  batchResult.blocking.map((f, i) => h("div", { key: i, className: "nvs-hint" }, `· ${f.message}${f.hint ? `（${f.hint}）` : ""}`)))
              : h("div", { className: "nvs-hint" }, "没有跨章的整批问题。"))
        : null;
      const checkCard = checkResult
        ? h(Card, {
            title: `第 ${checkResult.number} 章体检结果`,
            desc: checkResult.pass
              ? "硬性检查都过了（没吃书/没时间线倒退）。下面的提醒不影响存档，可自行取舍。"
              : "发现硬性问题（可能吃书/时间线倒退/文件丢失）。可以重写、去味，或确认作废。",
            right: h("div", { className: "nvs-flex", style: { gap: 6, flex: "none" } },
              checkResult.findings.length
                ? h("button", { className: "nvs-btn sm primary", disabled: busyN === checkResult.number,
                    onClick: () => rewriteWithFindings(checkResult.number, [...(checkResult.findings || []), ...(checkResult.debutMisses || [])]) }, `参考体检问题重写本章（${(checkResult.findings || []).length} 条）`)
                : null,
              h("button", { className: "nvs-btn sm", onClick: () => setCheckResult(null) }, "关闭"),
              !checkResult.pass
                ? h("button", { className: "nvs-btn sm", style: { color: "#DC2626" }, disabled: busyN === checkResult.number,
                    onClick: () => doDiscardFromCheck(checkResult.number) }, "作废本章")
                : null),
          },
            !checkResult.findings.length
              ? h("div", { className: "nvs-note ok" }, "没有发现问题。")
              : h("div", { style: { display: "grid", gap: 8 } },
                  checkResult.findings.map((f, i) =>
                    h("div", { key: i, style: { padding: "8px 12px", border: "1px solid var(--nvs-line)", borderRadius: 8, borderLeft: "3px solid " + sevColor(f.severity) } },
                      h("div", { style: { fontWeight: 600, fontSize: 13, color: sevColor(f.severity) } },
                        (f.severity === "high" ? "硬性问题 · " : f.severity === "mid" ? "提醒 · " : "参考 · ") + (f.code || "")),
                      h("div", { style: { fontSize: 13.5, marginTop: 3 } }, f.message),
                      f.hint ? h("div", { className: "nvs-hint", style: { marginTop: 2 } }, "→ " + f.hint) : null,
                      f.ai
                        ? h("div", { className: "nvs-hint", style: { marginTop: 3, color: f.ai.verdict === "real" ? undefined : "#16A34A" } },
                            "AI 复核：" + (f.ai.verdict === "invalid" ? "疑似误报" : f.ai.verdict === "intentional" ? "有意为之" : "真问题") +
                            (f.ai.reason ? "——" + f.ai.reason : "") + (f.ai.note ? "（" + f.ai.note + "）" : ""))
                        : null,
                      h("div", { className: "nvs-flex", style: { marginTop: 6 } },
                        h("button", { className: "nvs-btn sm", onClick: () => dismissCheck(f) }, "标记为合理"))))))
        : null;

      const sevColor2 = (sev) => sev === "high" ? "#DC2626" : sev === "mid" ? "#D97706" : "#6B7280";
      // 把断层塞进重写指令里，让 AI 参考着把这一章补顺（走重写：旧稿进 drafts，新稿替换）
      const rewriteWithIssues = async (chapNo, issues) => {
        if (!window.confirm(`让 AI 参考这 ${issues.length} 处断层重写第 ${chapNo} 章？旧稿会存进废章页（可恢复），新稿提交后替换它。`)) return;
        setBusyN(chapNo); setBusyOp("logic");
        try {
          const gaps = issues.map((it, i) =>
            `${i + 1}. ${it.between || ""}：${it.issue}${it.why ? "（读者会问：" + it.why + "）" : ""}`).join("\n");
          const ctx = await buildRewriteContext(chapNo);
          const prompt = [
            `用 novel-studio 技能，修补《${title}》第 ${chapNo} 章的叙事断层（旧稿已作废进废章页）。`,
            `先 novel_chapter op=discard ${chapNo}（若还没作废），再 novel_context ${chapNo} 取完整上下文包（段落纲、角色卡、未收伏笔、硬规则、上一章收尾、文风样本），写作以它为准。`,
            ctx ? `\n本批上下文（面板补充，保持前后衔接）：\n${ctx}` : "",
            `\n要修补的断层（场景之间读者接不上的地方，补出「怎么到的 / 怎么过渡的」）：\n${gaps}\n`,
            `要求：剧情走向和本章台阶位置不变，只把衔接补自然、把跳步补过渡；不新增设定外人物；字数不低于 1800 字。`,
            `写完 novel_chapter 提交第 ${chapNo} 章（批内带 batch:true），再 novel_continuity 体检，然后停下等我确认。`,
            `注意：正文一律用 novel_chapter op=read 读，不要去 exports/ 找 txt。`,
          ].join("\n");
          const r = await openWritingSession(dir, prompt);
          toast(r.ok ? `已开会话，让 AI 参考断层重写第 ${chapNo} 章` : "已复制重写指令：" + r.reason);
        } catch (e) { toast("重写失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      // 把「体检发现的问题」塞进重写指令，让 AI 按体检重写这一章
      const rewriteWithFindings = async (chapNo, findings) => {
        if (!window.confirm(`让 AI 参考这 ${findings.length} 条体检问题重写第 ${chapNo} 章？旧稿会存进废章页（可恢复），新稿提交后替换它。`)) return;
        setBusyN(chapNo); setBusyOp("check");
        try {
          const list = formatFindingsAll(findings) ||
            findings.map((f, i) => `${i + 1}. [${f.severity === "high" ? "硬性问题" : f.severity === "mid" ? "提醒" : "参考"}] ${f.message}${f.hint ? "（建议：" + f.hint + "）" : ""}`).join("\n");
          // 与「退回重写」同一套：先正式退稿（写 rewrite-request.md、旧稿移 drafts/、gate 回退），再开会话
          try { await postJSON("rewrite", { dir, number: chapNo, note: list }); } catch (e0) { /* 若已非待确认态，退稿失败也继续开会话 */ }
          const ctx = await buildRewriteContext(chapNo);
          const prompt = [
            `用 novel-studio 技能，把《${title}》第 ${chapNo} 章退回重写。旧稿已作废进废章页（可恢复）。`,
            `第一步必须 novel_context ${chapNo} 取完整上下文包（本章所在台阶的段落纲、角色卡、未收伏笔、硬规则、上一章收尾、文风样本），写作以它为准。`,
            ctx ? `\n本批上下文（面板补充，保持前后衔接）：\n${ctx}` : "",
            `\n这次重写要解决的问题：\n${list}
`,
            `要求：剧情走向和本章台阶位置不变；问题点到的要素/伏笔/章尾钩子补齐；不新增设定外人物；字数不低于 1800 字。`,
            `写完 novel_chapter 提交第 ${chapNo} 章（批内带 batch:true），再 novel_continuity 体检，然后停下等我确认。`,
            `注意：正文一律用 novel_chapter op=read 读，不要去 exports/ 找 txt。`,
          ].join("\n");
          const r = await openWritingSession(dir, prompt);
          toast(r.ok ? `已开会话，让 AI 按体检问题重写第 ${chapNo} 章` : "已复制重写指令：" + r.reason);
        } catch (e) { toast("重写失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      // 已存档的「待修」章：先体检拿到问题，再开重写会话（旧稿作废进废章页）
      const doRewriteArchived = async (n) => {
        setBusyN(n); setBusyOp("check");
        let findings = [];
        try {
          const ms = readModelSel() || {};
          let ck;
          try {
            ck = await postJSON("chapter-review", { dir, number: n, provider: ms.provider || undefined, model: ms.model || undefined });
          } catch (e0) {
            const r = await postJSON("chapter-check", { dir, number: n, discardIfFail: false });
            ck = (r && r.check) || r;
          }
          findings = [...((ck && ck.findings) || []), ...((ck && ck.debutMisses) || [])].filter((f) => f && f.message);
        } catch (e) {
          toast("体检没跑成，仍按待修重写：" + (e.message || e));
        }
        setBusyN(0); setBusyOp("");
        const list = findings.length
          ? formatFindingsAll(findings)
          : "体检没报出硬问题：先读正文和上下文包里的本段段落纲，重点查人物是否按设定登场、每个事件的动机是否成立、场景衔接是否断层，改完再提交。";
        if (!window.confirm(`让 AI 按下面的问题重写第 ${n} 章？旧稿会存进废章页（可恢复），新稿提交后替换它。\n\n${list}`)) return;
        setBusyN(n); setBusyOp("rewrite");
        try {
          const ctx = await buildRewriteContext(n);
          const prompt = [
            `用 novel-studio 技能，把《${title}》第 ${n} 章按下面的问题重写一遍。`,
            `先 novel_chapter op=discard ${n} 把旧稿作废（稿子留在废章页可恢复），再写新稿。`,
            `第一步必须 novel_context ${n} 取完整上下文包（本章所在台阶的段落纲、角色卡、未收伏笔、硬规则、上一章收尾、文风样本），写作以它为准。`,
            ctx ? `\n本批上下文（面板补充，保持前后衔接）：\n${ctx}` : "",
            `\n必须改掉的问题：\n${list}
`,
            `要求：剧情走向和本章台阶位置不变；问题点到的要素/伏笔/章尾钩子补齐；不新增设定外人物；字数不低于 1800 字。`,
            `写完 novel_chapter 提交第 ${n} 章（批内带 batch:true），再 novel_continuity 体检，然后停下等我确认。`,
            `注意：正文一律用 novel_chapter op=read 读，不要去 exports/ 找 txt。`,
          ].join("\n");
          const rr = await openWritingSession(dir, prompt);
          toast(rr.ok ? `已开会话，让 AI 重写第 ${n} 章` : "已复制重写指令：" + rr.reason);
        } catch (e) { toast("重写失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      const logicCard = logicResult
        ? h(Card, {
            title: `第 ${logicResult.number} 章叙事断层（${logicResult.scenes} 个场景）`,
            desc: "逐对检查相邻场景「读者能不能接上」。这是语义判断，只提示不拦——觉得是误报可直接忽略。",
            right: h("div", { className: "nvs-flex", style: { gap: 6, flex: "none" } },
              logicResult.issues.length
                ? h("button", { className: "nvs-btn sm primary", disabled: busyN === logicResult.number,
                    onClick: () => rewriteWithIssues(logicResult.number, logicResult.issues) },
                    "参考全部断层重写整章")
                : null,
              h("button", { className: "nvs-btn sm", onClick: () => setLogicResult(null) }, "关闭")),
          },
            !logicResult.issues.length
              ? h("div", { className: "nvs-note ok" }, "场景衔接顺畅，没发现断层。")
              : h("div", { style: { display: "grid", gap: 8 } },
                  logicResult.issues.map((it, i) =>
                    h("div", { key: i, style: { padding: "8px 12px", border: "1px solid var(--nvs-line)", borderRadius: 8, borderLeft: "3px solid " + sevColor2(it.severity) } },
                      h("div", { style: { fontWeight: 600, fontSize: 13, color: sevColor2(it.severity) } }, (it.between || "") + " · 接不上"),
                      h("div", { style: { fontSize: 13.5, marginTop: 3 } }, it.issue),
                      it.why ? h("div", { className: "nvs-hint", style: { marginTop: 2 } }, "→ 读者会问：" + it.why) : null,
                      it.before ? h("div", { className: "nvs-hint", style: { marginTop: 4 } }, "上一段结尾：「…" + it.before + "」") : null,
                      it.after ? h("div", { className: "nvs-hint" }, "下一段开头：「" + it.after + "…」") : null,
                      h("div", { className: "nvs-flex", style: { marginTop: 6 } },
                        (it.after || it.before)
                          ? h("button", { className: "nvs-btn sm", onClick: () => view(logicResult.number, String(it.after || it.before).slice(0, 18)) }, "在正文里定位")
                          : null,
                        h("button", { className: "nvs-btn sm primary", disabled: busyN === logicResult.number,
                          onClick: () => rewriteWithIssues(logicResult.number, [it]) }, "参考此断层重写这一章"),
                        h("button", { className: "nvs-btn sm", onClick: () => dismissLogic(it) }, "标记为合理"))))))
        : null;
      const rewriteWithVoice = async (chapNo, marks) => {
        if (!window.confirm(`让 AI 按人设核对结果重写第 ${chapNo} 章？只改走味的对话和人物反应，旧稿进废章页（可恢复）。`)) return;
        setBusyN(chapNo); setBusyOp("voice");
        try {
          const list = marks.map((m, i) =>
            `${i + 1}. 「${m.who || "?"}」第${m.index || i + 1}句：${m.issue || "口吻不对"}${m.line ? `（原句：${m.line}）` : ""}`).join("\n");
          const prompt = [
            `用 novel-studio 技能，修《${title}》第 ${chapNo} 章的人设走味（只改对话与人物反应，不改剧情）。`,
            `先 novel_chapter op=discard ${chapNo} 把旧稿作废（稿子留在废章页可恢复），再写新稿。`,
            `先 novel_context ${chapNo} 取完整上下文包（本章所在台阶的段落纲、角色卡 voice、未收伏笔、硬规则、上一章收尾），对照每个角色的 voice 与性格重写。`,
            `必须改掉的人设问题：`,
            list,
            `要求：剧情走向和节拍保持不变；每个角色说的话要像他自己（用词、语气、回避方式），不要改成统一的作者腔。`,
            `写完 novel_chapter 提交第 ${chapNo} 章，再 novel_continuity 体检，然后停下等我确认。`,
          ].join("\n");
          const r = await openWritingSession(dir, prompt);
          toast(r.ok ? `已开会话，按人设核对重写第 ${chapNo} 章` : "已复制重写指令：" + r.reason);
        } catch (e) { toast("重写失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };
      const voiceCard = voiceResult
        ? h(Card, {
            title: `第 ${voiceResult.number} 章人设核对`,
            desc: "抽本章对话，对照本章出场人物的 voice（只提示不拦）。觉得确实走味，可直接参考结果重写。",
            right: h("div", { className: "nvs-flex", style: { gap: 6, flex: "none" } },
              voiceResult.marks.length
                ? h("button", { className: "nvs-btn sm primary", disabled: busyN === voiceResult.number,
                    onClick: () => rewriteWithVoice(voiceResult.number, voiceResult.marks) }, "参考人设核对重写本章")
                : null,
              h("button", { className: "nvs-btn sm", onClick: () => setVoiceResult(null) }, "关闭")),
          },
            voiceResult.note ? h("div", { className: "nvs-hint", style: { marginBottom: 8 } }, voiceResult.note) : null,
            !voiceResult.marks.length
              ? h("div", { className: "nvs-note ok" }, "没发现明显走味。")
              : h("div", { style: { display: "grid", gap: 6 } },
                  voiceResult.marks.map((m, i) =>
                    h("div", { key: i, style: { padding: "6px 10px", border: "1px solid var(--nvs-line)", borderRadius: 8, fontSize: 13 } },
                      h("b", null, "「" + (m.who || "?") + "」"), " 第" + (m.index || i + 1) + "句：" + (m.issue || ""),
                      m.line ? h("div", { className: "nvs-hint", style: { marginTop: 2 } }, "原句：" + m.line) : null,
                      m.line ? h("div", { style: { marginTop: 4 } },
                        h("button", { className: "nvs-btn ghost sm", onClick: () => view(voiceResult.number, String(m.line).slice(0, 16)) }, "在正文里定位")) : null))))
        : null;

      const reviewChapter = async (n) => {
        setBusyN(n); setBusyOp("review");
        try {
          const prompt = [
            `用 novel-studio 技能，对《${title}》第 ${n} 章做多视角审查（只看不改）。`,
            skillLines("review"),
            `1) novel_chapter op=read ${n} 读原文再评，不要凭记忆；`,
            `2) 输出：真问题（带原句）→ 属于哪类（人设/节奏/逻辑/文风）→ 怎么改一句话。不要直接改正文。`,
          ].join("\n");
          const r = await openWritingSession(dir, prompt);
          toast(r.ok ? `已开会话审查第 ${n} 章` : "已复制审查指令：" + r.reason);
        } catch (e) { toast("审查失败：" + (e.message || e)); }
        setBusyN(0); setBusyOp("");
      };

      const targetTotal = Number(st.project.targetChapters) || 0;
      return h("div", null,
        PageHead({
          title: "进度",
          desc: `《${title}》的正文、确认和体检都在这一页。按 10 章一段写：段落纲先铺，写正文时一起带上。`,
          meta: [
            `目标 ${targetTotal ? targetTotal + " 章" : "未定"}`,
            `已存档 ${archived.length} 章`,
            pending.length ? `待确认 ${pending.length} 章` : "没有待确认",
            targetTotal ? `进度 ${Math.min(100, Math.round((archived.length / targetTotal) * 100))}%` : "",
          ].filter(Boolean),
          actions: [
            h("button", {
              key: "bchk", className: "nvs-btn sm", disabled: batchBusy || (!pending.length && !archived.length),
              title: "一次看整批（当前段落纲这一段），每章给结论：哪几章要重写",
              onClick: batchCheck,
            }, batchBusy ? "体检中…" : "按批体检"),
            h("button", {
              key: "exp", className: "nvs-btn sm", disabled: exporting || !archived.length,
              title: archived.length ? "把已存档章节合并成一个 txt，放到项目 exports/ 目录" : "还没有已存档的章节",
              onClick: doExport,
            }, exporting ? "导出中…" : "导出 txt"),
            h("button", {
              key: "next", className: "nvs-btn primary", disabled: writing || pending.length > 0 || busyN !== 0,
              title: pending.length ? "先把「待你确认」里的章处理完" : `开一个会话写第 ${nextN} 章`,
              onClick: startNext,
            }, writing ? "正在打开会话…" : pending.length ? `先确认第 ${pending[0].number} 章` : `写第 ${nextN} 章`),
          ],
        }),
        batchCard,
        checkCard,
        logicCard,
        voiceCard,
        pending.length
          ? h(Card, { title: "待你确认", desc: "AI 写完的章先放这里；点「通过并存档」才会收进下面的进度。" },
              pending.map((c) => chapterRow(c, true)))
          : null,
        (() => {
          const vols = Array.isArray(st.volumes) ? st.volumes : [];
          const curNo = Number(st.project.currentChapter) || 0;
          const volOf = (n) => vols.find((v) => Number(n) >= v.from && Number(n) <= v.to) || null;
          const curVol = volOf(curNo);
          // 一行章节 + 该卷的「盘点本卷记忆」；卷里还没写就只显示空态
          const volCard = (v, list) => {
            const mem = volMemMap[Number(v.to)] || null;
            const isCur = Boolean(curVol && curVol.from === v.from);
            const key = "v" + v.from;
            // 默认只展开「当前这卷」，其余卷默认收起；作者手动点过就以手动为准（foldedVols 覆盖默认）
            const folded = foldedVols[key] !== undefined ? Boolean(foldedVols[key]) : !isCur;
            return h(Card, {
              key: "vol" + v.from,
              title: v.title || `第${v.from}-${v.to}章`,
              desc: `第${v.from}-${v.to}章 · 已写 ${list.length} 章${isCur ? " · 当前这卷" : ""}。点一行展开正文；「去味」「审查」会开一个会话让 AI 去做，段落纲在开这一批时先铺好，写正文时直接带上。`,
              right: h("div", { className: "nvs-flex", style: { gap: 6, flex: "none" } },
                h("button", {
                  className: "nvs-btn sm", onClick: () => setFoldedVols((s) => ({ ...s, [key]: !(s[key] !== undefined ? s[key] : !isCur) })),
                }, folded ? "展开" : "收起"),
                h("button", {
                  className: "nvs-btn sm", disabled: busyN === -1 || !list.length,
                  title: list.length ? "把这一卷已写的章压成一段卷记忆" : "这一卷还没写正文",
                  onClick: () => doCompileVolume(v),
                }, busyN === -1 && busyOp === "volume" ? "盘点中…" : "盘点本卷记忆")),
            },
              folded
                ? h("div", { className: "nvs-hint" }, list.length ? `已折叠 ${list.length} 章，点右上「展开」查看。` : "这一卷还没写。")
                : h("div", null,
                    list.length
                      ? [...list].sort((a, b) => b.number - a.number).map((c) => chapterRow(c, false))
                      : h("div", { className: "nvs-hint" }, "这一卷还没写，先写再回来。"),
                    mem
                      ? h("div", { style: { marginTop: 10, display: "grid", gap: 4 } },
                          h("div", { className: "nvs-hint" }, `卷记忆 · 第${mem.from}-${mem.to}章 · ${mem.chapters} 章`),
                          h("div", { className: "nvs-prose", style: { whiteSpace: "pre-wrap", fontSize: 13 } }, mem.summary))
                      : null));
          };
          if (!vols.length) {
            return h(Card, { title: "章节（已存档）", desc: "大纲里还没写出卷区间（第 a-b 章），先按章号平铺。" },
              archived.length ? [...archived].sort((a, b) => b.number - a.number).map((c) => chapterRow(c, false)) : h("div", { className: "nvs-hint" }, "还没有确认存档的章节。"));
          }
          const rest = archived.filter((c) => !volOf(c.number));
          // 当前卷排到最上面（稳定排序：非当前卷保持原有先后）
          const orderedVols = curVol
            ? vols.filter((v) => v.from === curVol.from).concat(vols.filter((v) => v.from !== curVol.from))
            : vols;
          return h("div", null,
            orderedVols.map((v) => volCard(v, archived.filter((c) => volOf(c.number) === v))),
            rest.length
              ? h(Card, { title: "卷外章节", desc: "这些章号落在任何已识别卷之外。" }, [...rest].sort((a, b) => b.number - a.number).map((c) => chapterRow(c, false)))
              : null);
        })());
    }

    /* --------------------------------- 废章 --------------------------------- */
    // 体检没过 / 去味后旧稿作废的章节：显示被废弃的章号、原因、时间，草稿在 drafts/ 可找回。
    function Discarded({ st, dir, toast, onChanged }) {
      const list = st.discarded || [];
      const [open, setOpen] = useState(null);       // 正在展开的 draftFile
      const [text, setText] = useState(null);
      const [busy, setBusy] = useState(false);
      const toggle = async (d) => {
        if (open === d.draftFile) { setOpen(null); setText(null); return; }
        setOpen(d.draftFile); setText(null);
        try {
          const r = await getJSON(`discarded-read?dir=${q(dir)}&draftFile=${q(d.draftFile)}`);
          setText(r.text || "");
        } catch (e) { toast("读不到草稿：" + e.message); setText("（草稿读取失败）"); }
      };
      const restore = async (d) => {
        if (busy) return;
        setBusy(true);
        try {
          const r = await postJSON("discarded-restore", { dir, draftFile: d.draftFile, number: d.number, title: d.title });
          toast(`已把第 ${d.number} 章恢复到正文（在「进度」页，需重新确认存档）`);
          setOpen(null); setText(null);
          if (onChanged) await onChanged();
        } catch (e) { toast("恢复失败：" + (e.message || e)); }
        setBusy(false);
      };
      // 废稿也能一键复制（展开过就用内存里的，没展开就现读）
      const copyDraft = async (d) => {
        try {
          let t = open === d.draftFile ? text : null;
          if (t == null) {
            const r = await getJSON(`discarded-read?dir=${q(dir)}&draftFile=${q(d.draftFile)}`);
            t = r.text || "";
          }
          if (!t) { toast("这份废稿是空的"); return; }
          if (!copyText(t)) { toast("复制失败：当前环境不允许写剪贴板"); return; }
          toast(`已复制第 ${d.number || "?"} 章废稿（${String(t).replace(/\s+/gu, "").length} 字）`);
        } catch (e) { toast("复制失败：" + (e.message || e)); }
      };
      const purge = async (d) => {
        if (busy) return;
        if (!window.confirm(`永久删除第 ${d.number || "?"} 章的废稿？删掉后这个草稿再也找不回来了（仅清掉草稿文件，不影响正文）。`)) return;
        setBusy(true);
        try {
          await postJSON("discarded-purge", { dir, draftFile: d.draftFile });
          toast(`已永久删除第 ${d.number || "?"} 章的废稿`);
          if (open === d.draftFile) { setOpen(null); setText(null); }
          if (onChanged) await onChanged();
        } catch (e) { toast("删除失败：" + (e.message || e)); }
        setBusy(false);
      };
      return h("div", null,
        PageHead({
          title: "废章",
          desc: "体检没过或去味替换下来的旧稿。旧稿可看、可恢复，也可以永久删除。",
          meta: [`${list.length} 份废稿`],
        }),
        h(Card, {
          title: "废稿列表",
          desc: "展开可以看正文；恢复后回到进度页，需要重新确认存档。删除只清草稿文件，不影响正文。",
        },
          !list.length
            ? h("div", { className: "nvs-empty" }, h("b", null, "没有废稿"), "在「进度」页对某一章做体检，确认作废后旧稿会进这里。")
            : h("div", { style: { display: "grid", gap: 8 } },
                list.map((d, i) =>
                  h("div", { key: i, className: "nvs-fs", style: { padding: "10px 12px" } },
                    h("div", { className: "nm", style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 } },
                      h("span", null, "第 " + (d.number || "?") + " 章" + (d.title ? " · " + d.title : "")),
                      h("span", { style: { flex: "none", display: "flex", gap: 4 } },
                        h("button", { className: "nvs-btn ghost sm", style: { padding: "0 8px", lineHeight: "18px" }, onClick: () => toggle(d) }, open === d.draftFile ? "收起" : "看正文"),
                        h("button", { className: "nvs-btn ghost sm", style: { padding: "0 8px", lineHeight: "18px" }, onClick: () => copyDraft(d) }, "复制"),
                        h("button", { className: "nvs-btn ghost sm", disabled: busy, style: { padding: "0 8px", lineHeight: "18px" }, onClick: () => restore(d) }, busy ? "恢复中…" : "恢复"),
                        h("button", { className: "nvs-btn ghost sm", disabled: busy, style: { padding: "0 8px", lineHeight: "18px", color: "#DC2626" }, onClick: () => purge(d) }, "删除"))) ,
                    h("div", { className: "mt", style: { marginTop: 4 } },
                      d.reason ? "原因：" + d.reason : "未记原因",
                      d.chars ? " · " + d.chars + " 字" : "",
                      d.at ? " · " + String(d.at).replace("T", " ").slice(0, 19) : ""),
                    d.lead ? h("div", { className: "nvs-hint", style: { marginTop: 4, lineHeight: 1.7 } }, d.lead + (d.lead.length >= 60 ? "…" : "")) : null,
                    open === d.draftFile
                      ? h("div", { className: "nvs-prose", style: { marginTop: 8, padding: "10px 2px", maxHeight: 420, overflow: "auto" } }, text === null ? "读取中…" : text)
                      : null)))));
    }


    /* --------------------------------- 伏笔 --------------------------------- */
    function Foreshadow({ st, dir, toast, onChanged }) {
      const fs = st.foreshadow || { open: [], paid: [] };
      const open = fs.open || [];
      const paid = fs.paid || [];
      const total = Number(st.project?.targetChapters) || 0;
      const hasOutline = Boolean((st.setup?.outlineText || "").trim());
      const [busy, setBusy] = useState(false);
      const [form, setForm] = useState({ name: "", kind: "detail", source: "", plantChapter: "", plantBeat: "", dueChapter: "", revealWho: "", revealChange: "", hint: "" });
      const [showForm, setShowForm] = useState(false);
      const [q, setQ] = useState("");
      const [fsFilter, setFsFilter] = useState("all");
      // 伏笔网（跨章设计）：开一个会话，让 AI 用多视角审查的方法补三层伏笔并落账
      const webDesign = async () => {
        if (!hasOutline) { toast("先在「大纲」页生成或写好大纲，伏笔要从大纲的卷里来"); return; }
        const vols = Array.isArray(st.volumes) ? st.volumes : [];
        const volCount = Math.max(1, vols.length || Math.ceil((total || 120) / 40));
        const coreFs = 3, volFs = volCount * 2, plotFs = Math.max(4, Math.ceil((total || 120) / 6));
        const prompt = [
          `用 novel-studio 技能，给《${st.project?.title || ""}》设计伏笔网（不写正文）。`,
          skillLines("shadow"),
          `0) 先读齐再动手：①「概览」页的故事梗概；②novel_outline op=get 拿全书层/卷层大纲与世界观正文；③novel_bible op=query 拿人物、势力、地点、物品、硬规则；④novel_foreshadow op=list 看原伏笔网。不许脱离这些凭空埋。`,
          `1) 配额固定：全书 ${total || "未定"} 章、约 ${volCount} 卷——核心伏笔 ${coreFs} 条、卷级伏笔每卷 2 条共 ${volFs} 条、情节伏笔每 6 章 1 条共 ${plotFs} 条，合计约 ${coreFs + volFs + plotFs} 条。这次会话要铺满全书，不要只补一小批；已在账本里的先扣除，只补差额，不要重复登记。`,
          `2) 按主线（贯穿全书）/卷线（一卷内收）/细节（章内）三层补，每条七项都要给：名称、埋设章、埋在哪一拍、计划回收章、谁来揭、揭开会改变什么、中途提示。回收章必须在第 1-${total || "目标"} 章内，且不得早于埋设章 +3；卷线伏笔的回收章要落在同一卷区间内。`,
          `3) 用 novel_foreshadow op=plant 落账，并且必须把这些详情一起传进去：kind（main/volume/detail）、source（来自哪条硬规则/谁的秘密/哪个卷事件）、plant_beat、reveal_who、reveal_change、hint；只传名字和章号的话，伏笔页只会有两个章号、没有内容；`,
          `3b) 已有伏笔换了说法、同一个人/同一件器物/同一条规则的，合并成一条或跳过，不要重复登记。`,
          `4) 伏笔依赖的新设定（器物、规则、人情关系）不要自己写进 bible、大纲或世界观；把缺的清单列给我，由「设定」页统一补，避免三个地方各写一套；`,
          `5) 大纲和世界观正文不抄伏笔清单（账本才是唯一真相），只在它们确实要改时（新硬规则/新势力）才动手；`,
          `6) 落地完停下，把新增清单报给我。`,
          `7) 最后用 novel_studio_session return 交回面板（source 写「深入调整伏笔网」），但**不要传 outlineText / worldText**——这次只动伏笔账本，传了会把整份大纲覆盖掉；伏笔清单留在账本和你的回复里。`,
        ].join("\n");
        const r = await openWritingSession(dir, prompt);
        toast(r.ok ? "已开会话深入调整伏笔网" : "已复制指令：" + r.reason);
      };
      const [editing, setEditing] = useState(null); // 正在修改的伏笔名
      const [editForm, setEditForm] = useState({ dueChapter: "", note: "" });
      const KIND = { main: "主线", volume: "卷内", detail: "细节", "": "—" };

      const kindLabel = (k) => KIND[k] || k || "—";

      const startEdit = (f) => {
        setEditing(f.name);
        setEditForm({ dueChapter: f.dueChapter ? String(f.dueChapter) : "", note: f.hint || f.note || "" });
      };
      const saveEdit = async (name) => {
        if (busy) return;
        setBusy(true);
        try {
          await postJSON("foreshadow", { dir, op: "reschedule", name, dueChapter: Number(editForm.dueChapter) || undefined, note: editForm.note });
          toast("已更新「" + name + "」");
          setEditing(null);
          if (onChanged) await onChanged();
        } catch (e) { toast("修改失败：" + (e.message || e)); }
        setBusy(false);
      };
      const removeFs = async (name) => {
        if (busy) return;
        if (!window.confirm("确定删除伏笔「" + name + "」？（软删，事件历史保留，但不再出现在列表里）")) return;
        setBusy(true);
        try {
          await postJSON("foreshadow", { dir, op: "delete", name });
          toast("已删除伏笔「" + name + "」");
          if (onChanged) await onChanged();
        } catch (e) { toast("删除失败：" + (e.message || e)); }
        setBusy(false);
      };
      const payoff = async (name) => {
        if (busy) return;
        const ch = window.prompt("这条伏笔在第几章收回？（填当前或更早的章号）", String(st.project.currentChapter || ""));
        if (ch === null) return;
        setBusy(true);
        try {
          await postJSON("foreshadow", { dir, op: "payoff", name, chapter: Number(ch) || st.project.currentChapter || 1 });
          toast("已标记「" + name + "」回收");
          if (onChanged) await onChanged();
        } catch (e) { toast("标记回收失败：" + (e.message || e)); }
        setBusy(false);
      };

      const plant = async () => {
        if (!form.name.trim() || busy) return;
        setBusy(true);
        try {
          await postJSON("foreshadow", {
            dir, op: "plant", name: form.name.trim(),
            plantedChapter: Number(form.plantChapter) || st.project.currentChapter || 1,
            dueChapter: Number(form.dueChapter) || undefined,
            kind: form.kind, source: form.source, plantBeat: form.plantBeat,
            revealWho: form.revealWho, revealChange: form.revealChange, hint: form.hint,
          });
          toast("已埋「" + form.name.trim() + "」");
          setForm({ name: "", kind: "detail", source: "", plantChapter: "", plantBeat: "", dueChapter: "", revealWho: "", revealChange: "", hint: "" });
          setShowForm(false);
          if (onChanged) await onChanged();
        } catch (e) { toast("埋失败：" + e.message); }
        setBusy(false);
      };

      // 一行的可编辑/只读展示
      const fsRow = (f, kind) => {
        const isEditing = editing === f.name;
        return h("div", { key: f.name + kind, className: "nvs-fs" + (kind === "overdue" ? " overdue" : "") },
          h("div", { className: "nm", style: { display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6 } },
            h("span", null,
              h("span", { className: "nvs-pill", style: { marginRight: 6, fontSize: 11 } }, kindLabel(f.kind)),
              f.name,
              f.source ? h("span", { className: "nvs-hint", style: { marginLeft: 6 } }, "（来源 " + f.source + "）") : null),
            h("span", { style: { flex: "none", display: "flex", gap: 4 } },
              kind !== "paid" ? h("button", { className: "nvs-btn ghost sm", disabled: busy, style: { padding: "0 8px", lineHeight: "18px" },
                onClick: (e) => { e.stopPropagation(); isEditing ? setEditing(null) : startEdit(f); } }, isEditing ? "取消" : "改") : null,
              kind !== "paid" ? h("button", { className: "nvs-btn ghost sm", disabled: busy, style: { padding: "0 8px", lineHeight: "18px", color: "var(--nvs-accent,#EC4899)" },
                onClick: (e) => { e.stopPropagation(); payoff(f.name); } }, "标记回收") : null,
              h("button", { className: "nvs-btn ghost sm", disabled: busy, style: { padding: "0 8px", lineHeight: "18px", color: "var(--nvs-danger, #DC2626)" },
                onClick: (e) => { e.stopPropagation(); removeFs(f.name); } }, "删"))),
          isEditing
            ? h("div", { style: { marginTop: 8, display: "grid", gap: 6 } },
                h("div", { className: "nvs-flex" },
                  h("input", { className: "nvs-input", type: "number", style: { width: 130 }, placeholder: "计划回收章", value: editForm.dueChapter, onChange: (e) => setEditForm({ ...editForm, dueChapter: e.target.value }) }),
                  h("span", { className: "nvs-hint" }, "埋在第" + f.plantedChapter + "章")),
                h("input", { className: "nvs-input", placeholder: "中途提示 / 怎么收", value: editForm.note, onChange: (e) => setEditForm({ ...editForm, note: e.target.value }) }),
                h("div", { className: "nvs-flex" },
                  h("button", { className: "nvs-btn primary sm", disabled: busy, onClick: (e) => { e.stopPropagation(); saveEdit(f.name); } }, busy ? "保存中…" : "保存修改")))
            : h("div", { className: "mt", style: { lineHeight: 1.7 } },
                "第" + f.plantedChapter + "章埋" + (f.plantBeat ? "（" + f.plantBeat + "）" : ""),
                f.dueChapter ? " · 计划第" + f.dueChapter + "章收" : " · 未定回收章",
                kind === "overdue" ? " ⚠超期" : "",
                kind === "paid" && f.payoffChapter ? " · 第" + f.payoffChapter + "章已收" : "",
                f.revealWho ? h("div", { className: "nvs-hint" }, "谁揭：" + f.revealWho) : null,
                f.revealChange ? h("div", { className: "nvs-hint" }, "揭开后：" + f.revealChange) : null,
                f.hint ? h("div", { className: "nvs-hint" }, "中途提示：" + f.hint) : null,
                f.abandon ? h("div", { className: "nvs-hint" }, "收不回就：" + f.abandon) : null));
      };

      const col = (title, list, kind) =>
        h("div", null,
          h("div", { className: "nvs-col-h" }, title, h("span", { className: "ct" }, list.length)),
          list.length ? list.map((f) => fsRow(f, kind)) : h("div", { className: "nvs-hint" }, "（空）"));

      // 汇总成一张表：状态直接并进表格，不再单独放三列看板
      const allRows = [...open.map((f) => ({ f, kind: f.overdue ? "overdue" : "open" })), ...paid.map((f) => ({ f, kind: "paid" }))];
      const shownRows = allRows.filter(({ f, kind }) => {
        if (fsFilter === "open" && kind !== "open") return false;
        if (fsFilter === "overdue" && kind !== "overdue") return false;
        if (fsFilter === "paid" && kind !== "paid") return false;
        const kw = q.trim().toLowerCase();
        if (!kw) return true;
        return [f.name, f.source, f.hint, f.revealWho, f.revealChange].join(" ").toLowerCase().includes(kw);
      });
      const trs = shownRows.map(({ f, kind }, i) =>
        h("tr", { key: f.name + kind, style: kind === "overdue" ? { background: "rgba(220,38,38,.06)" } : null },
          h("td", { className: "cell", style: { textAlign: "right", color: "var(--nvs-sub)", width: 44 } }, i + 1),
          h("td", { className: "cell clip-md", title: f.name }, f.name),
          h("td", { className: "cell" }, kindLabel(f.kind)),
          h("td", { className: "cell clip-sm", title: f.source || "" }, f.source || "—"),
          h("td", { className: "cell clip-md", title: "第" + (f.plantedChapter || "?") + "章" + (f.plantBeat ? " · " + f.plantBeat : "") }, "第" + (f.plantedChapter || "?") + "章" + (f.plantBeat ? " · " + f.plantBeat : "")),
          h("td", { className: "cell" }, kind === "paid"
            ? (f.payoffChapter ? "第" + f.payoffChapter + "章（已收）" : (f.dueChapter ? "第" + f.dueChapter + "章" : "—"))
            : (f.dueChapter ? "第" + f.dueChapter + "章" : "—")),
          h("td", { className: "cell clip", title: [f.revealWho, f.revealChange].filter(Boolean).join("：") }, [f.revealWho, f.revealChange].filter(Boolean).join("：") || "—"),
          h("td", { className: "cell clip", title: f.hint || "" }, f.hint || "—"),
          h("td", { className: "cell", style: { color: kind === "paid" ? "#16A34A" : kind === "overdue" ? "#DC2626" : "var(--nvs-sub)", fontWeight: 600 } },
            kind === "paid" ? "已回收" : kind === "overdue" ? "超期未收" : "开着"),
          h("td", { className: "act" }, h("span", { style: { display: "flex", gap: 2 } },
            kind !== "paid" ? h("button", { className: "nvs-btn ghost sm", disabled: busy, style: { padding: "0 6px" }, onClick: () => startEdit(f) }, "改") : null,
            h("button", { className: "nvs-btn ghost sm", disabled: busy, style: { padding: "0 6px", color: "var(--nvs-danger,#DC2626)" }, onClick: () => removeFs(f.name) }, "删")))));
      const table = shownRows.length
        ? h("div", { className: "nvs-tbl-wrap", style: { marginTop: 4 } },
            h("table", { className: "nvs-tbl", style: { fontSize: 12.5 } },
              h("thead", null, h("tr", null,
                ["序号", "伏笔", "类型", "来源", "埋设（章节）", "回收章", "谁揭 / 揭开后", "中途提示", "回收状态", "操作"].map((t) => h("th", { key: t }, t)))),
              h("tbody", null, trs)))
        : h("div", { className: "nvs-empty" },
            h("b", null, allRows.length ? "没有符合条件的伏笔" : "还没有伏笔"),
            allRows.length ? "换个关键词或状态筛选。" : "点右上「生成伏笔」，按大纲和世界观一次性铺满整套伏笔；已有伏笔后同一个按钮会变成「深入调整伏笔网」继续补全。");
      const editRow = allRows.find((x) => x.f.name === editing);
      const editBar = editing
        ? h("div", { className: "nvs-note", style: { marginBottom: 8, display: "grid", gap: 6 } },
            h("div", { className: "nvs-flex" },
              h("b", { style: { flex: "none" } }, "改「" + editing + "」"),
              h("input", { className: "nvs-input", type: "number", style: { width: 130 }, placeholder: "计划回收章", value: editForm.dueChapter, onChange: (e) => setEditForm({ ...editForm, dueChapter: e.target.value }) }),
              h("input", { className: "nvs-input", style: { flex: "1 1 160px" }, placeholder: "中途提示 / 怎么收", value: editForm.note, onChange: (e) => setEditForm({ ...editForm, note: e.target.value }) }),
              h("button", { className: "nvs-btn primary sm", disabled: busy, onClick: () => saveEdit(editing) }, busy ? "保存中…" : "保存修改"),
              editRow && editRow.kind !== "paid" ? h("button", { className: "nvs-btn sm", disabled: busy, onClick: () => { const nm = editing; setEditing(null); payoff(nm); } }, "标记已回收") : null,
              h("button", { className: "nvs-btn ghost sm", onClick: () => setEditing(null) }, "取消")))
        : null;

      const design = async () => {
        setBusy(true);
        try {
          const ms = readModelSel() || {};
          // 数量由规模决定（后端按全书章数算），前端不再写死 10
          const r = await postJSON("foreshadow-gen", { dir, provider: ms.provider || undefined, model: ms.model || undefined });
          const w = r.written || 0, pc = r.parsedCount || 0;
          if (w > 0) toast(`已按大纲+世界观生成并登记 ${w} 条伏笔${pc > w ? `（另 ${pc - w} 条同名跳过）` : ""}${r.planned ? `；全书规模约需 ${r.planned} 条` : ""}，见下方表格`);
          else if (pc > 0) toast(`解析到 ${pc} 条但都已在账本里，无新增`);
          else toast("模型没返回可登记的伏笔，请重试");
          if (onChanged) await onChanged();
        } catch (e) { toast("设计失败：" + (e.message || e)); }
        setBusy(false);
      };
      const overdue = open.filter((f) => f.overdue).length;
      // 生成伏笔：一个按钮按状态分派 —— 还没有伏笔→一次性铺满；已有伏笔→开 Agent 会话补全伏笔网（都只增不覆盖、同名去重）
      const genForeshadow = async () => {
        if (busy) return;
        if (!hasOutline) { toast("先在「大纲」页生成或写好大纲，伏笔要从大纲的卷里来"); return; }
        if ((allRows.length) > 0) { await webDesign(); return; }
        await design();
      };
      // 伏笔按钮标签随状态变化
      const fsBtnLabel = (() => {
        if (busy) return "设计中…";
        if (allRows.length > 0) return "深入调整伏笔网";
        return "生成伏笔";
      })();
      return h("div", null,
        busy ? thinkRow("正在梳理伏笔的埋设、回收与延期") : null,
        PageHead({
          title: "伏笔",
          desc: "一条伏笔就是一次对读者的承诺。埋了什么、什么时候收、谁来揭，都要能在这张表里查到。",
          meta: [`共 ${allRows.length} 条`, `开着 ${open.length}`, overdue ? `超期 ${overdue}` : "没有超期", `已回收 ${paid.length}`],
          actions: [
            h("button", { key: "add", className: "nvs-btn sm", onClick: () => setShowForm((v) => !v) }, showForm ? "收起表单" : "+ 埋新伏笔"),
            h("button", {
              key: "gen", className: "nvs-btn primary sm", disabled: busy || !hasOutline,
              title: !hasOutline ? "先有大纲才能设计伏笔"
                : (allRows.length > 0 ? "先读大纲、硬规则和人物秘密，再按规模补全伏笔网（只增不覆盖）" : "依大纲与世界观一次性铺满整套伏笔"),
              onClick: genForeshadow,
            }, fsBtnLabel),
          ],
        }),
        h(Card, {
          title: "全部伏笔",
          desc: "表格一行一条；超期的会标红，要在本章处理。",
        },
          h("div", { className: "nvs-filterbar" },
            h("input", { className: "nvs-input", placeholder: "搜伏笔名、来源、谁揭…", value: q, onChange: (e) => setQ(e.target.value) }),
            [["all", "全部"], ["open", "开着"], ["overdue", "超期"], ["paid", "已回收"]].map(([k, label]) =>
              h("button", {
                key: k, type: "button", className: "nvs-chip", "aria-pressed": fsFilter === k ? "true" : "false",
                onClick: () => setFsFilter(k),
              }, label)),
            h("span", { className: "nvs-spacer" }),
            h("span", { className: "nvs-hint" }, `显示 ${shownRows.length} / ${allRows.length} 条`)),
          showForm ? h("div", { style: { marginBottom: 14, padding: "12px 14px", border: "1px solid var(--nvs-line)", borderRadius: 10, background: "var(--nvs-card2)" } },
            h("div", { className: "nvs-flex" },
              h("input", { className: "nvs-input", style: { flex: "1 1 160px" }, placeholder: "伏笔名称", value: form.name, onChange: (e) => setForm({ ...form, name: e.target.value }) }),
              h("select", { className: "nvs-input", style: { width: 110 }, value: form.kind, onChange: (e) => setForm({ ...form, kind: e.target.value }) },
                ["main", "volume", "detail"].map((k) => h("option", { key: k, value: k }, kindLabel(k)))),
              h("input", { className: "nvs-input", style: { width: 110 }, placeholder: "来源(如R2)", value: form.source, onChange: (e) => setForm({ ...form, source: e.target.value }) })),
            h("div", { className: "nvs-flex", style: { marginTop: 8 } },
              h("input", { className: "nvs-input", type: "number", style: { width: 110 }, placeholder: "埋设章", value: form.plantChapter, onChange: (e) => setForm({ ...form, plantChapter: e.target.value }) }),
              h("input", { className: "nvs-input", style: { flex: "1 1 140px" }, placeholder: "埋在哪个节拍·怎么顺带一提", value: form.plantBeat, onChange: (e) => setForm({ ...form, plantBeat: e.target.value }) }),
              h("input", { className: "nvs-input", type: "number", style: { width: 110 }, placeholder: "回收章", value: form.dueChapter, onChange: (e) => setForm({ ...form, dueChapter: e.target.value }) })),
            h("div", { className: "nvs-flex", style: { marginTop: 8 } },
              h("input", { className: "nvs-input", style: { flex: "1 1 120px" }, placeholder: "谁来揭开", value: form.revealWho, onChange: (e) => setForm({ ...form, revealWho: e.target.value }) }),
              h("input", { className: "nvs-input", style: { flex: "1 1 160px" }, placeholder: "揭开后改变了什么", value: form.revealChange, onChange: (e) => setForm({ ...form, revealChange: e.target.value }) })),
            h("input", { className: "nvs-input", style: { marginTop: 8 }, placeholder: "中途提示（可选）", value: form.hint, onChange: (e) => setForm({ ...form, hint: e.target.value }) }),
            h("div", { className: "nvs-flex", style: { marginTop: 10 } },
              h("button", { className: "nvs-btn primary sm", disabled: busy || !form.name.trim(), onClick: plant }, busy ? "埋下中…" : "埋下这条伏笔"))) : null,
          editBar,
          table));
    }

    /* --------------------------------- 大纲 --------------------------------- */
    // 两步：① 用梗概生成大纲（只写结构）② 用大纲生成叙事性世界观（设定页再拆条目）。
    const OL_CN = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
    const olNum = (raw) => {
      const s = String(raw || "").trim();
      if (/^\d+$/.test(s)) return Number(s);
      let n = 0, cur = 0;
      for (const ch of s) {
        if (OL_CN[ch]) cur = OL_CN[ch];
        else if (ch === "百") { n += (cur || 1) * 100; cur = 0; }
        else if (ch === "千") { n += (cur || 1) * 1000; cur = 0; }
      }
      return n + cur || null;
    };
    // 从大纲 Markdown 里抠章节导航：## 小节 + 卷头区间；只用于前端目录和覆盖率，不改账本。
    const olIndex = (text, total) => {
      const lines = String(text || "").split("\n");
      const vols = [], sections = [];
      let at = 0;
      for (const raw of lines) {
        const line = raw.trim();
        const h = /^##\s+(.+)$/.exec(line);
        if (h && !line.startsWith("###")) sections.push({ title: h[1].replace(/^\d+\s*[.、]\s*/, "").trim(), at });
        const v = /^[#>*+\-\s]*第\s*([0-9一二三四五六七八九十百千]+)\s*[卷部篇]\s*([^（(\n]{0,20}?)\s*[（(]?\s*第?\s*([0-9一二三四五六七八九十百千]+)\s*章?\s*[-–—~～至到]\s*第?\s*([0-9一二三四五六七八九十百千]+)\s*章/.exec(line);
        if (v) {
          const from = olNum(v[3]), to = olNum(v[4]);
          if (from && to && to >= from) {
            const name = v[2].replace(/[｜|:：].*$/, "").trim();
            vols.push({ no: olNum(v[1]) || null, name: name.length > 12 ? name.slice(0, 12) + "…" : name, from, to, at });
          }
        }
        at += raw.length + 1;
      }
      vols.sort((a, b) => a.from - b.from);
      const totalN = Number(total) || 0;
      const gaps = [];
      let covered = 0, cursor = 1;
      for (const v of vols) {
        if (v.from > cursor) gaps.push([cursor, v.from - 1]);
        covered += Math.max(0, v.to - Math.max(v.from, cursor) + 1);
        cursor = Math.max(cursor, v.to + 1);
      }
      if (totalN && cursor <= totalN) gaps.push([cursor, totalN]);
      return {
        vols, sections, gaps, covered,
        maxTo: vols.length ? Math.max(...vols.map((v) => v.to)) : 0,
        words: String(text || "").replace(/\s+/g, "").length,
      };
    };
    // 轻量 Markdown：标题 / 列表 / 表格 / 引用 / 代码块 / 粗体与行内码，够大纲和世界观用
    const mdToNodes = (src) => {
      const lines = String(src || "").replace(/\r/g, "").split("\n");
      const out = [];
      let i = 0;
      let key = 0;
      const inline = (text) => {
        const parts = [];
        const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
        let last = 0;
        let m;
        while ((m = re.exec(text))) {
          if (m.index > last) parts.push(text.slice(last, m.index));
          const t = m[0];
          parts.push(t[0] === "*"
            ? h("strong", { key: "b" + key++ }, t.slice(2, -2))
            : h("code", { key: "c" + key++ }, t.slice(1, -1)));
          last = m.index + t.length;
        }
        if (last < text.length) parts.push(text.slice(last));
        return parts;
      };
      const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((x) => x.trim());
      const isSep = (line) => /^\s*\|?\s*:?-{3,}/.test(line) && line.includes("|");
      while (i < lines.length) {
        const line = lines[i];
        if (!line.trim()) { i += 1; continue; }
        if (/^\s*```/.test(line)) {
          const body = [];
          i += 1;
          while (i < lines.length && !/^\s*```/.test(lines[i])) { body.push(lines[i]); i += 1; }
          i += 1;
          out.push(h("pre", { key: "p" + key++ }, body.join("\n")));
          continue;
        }
        const head = line.match(/^(#{1,6})\s+(.*)$/);
        if (head) {
          out.push(h("h" + head[1].length, { key: "h" + key++ }, inline(head[2])));
          i += 1;
          continue;
        }
        if (/^\s*(---|\*\*\*)\s*$/.test(line)) { out.push(h("hr", { key: "r" + key++ })); i += 1; continue; }
        if (/^\s*>\s?/.test(line)) {
          const body = [];
          while (i < lines.length && /^\s*>\s?/.test(lines[i])) { body.push(lines[i].replace(/^\s*>\s?/, "")); i += 1; }
          out.push(h("blockquote", { key: "q" + key++ }, inline(body.join("\n"))));
          continue;
        }
        if (line.includes("|") && i + 1 < lines.length && isSep(lines[i + 1])) {
          const rows = [cells(line)];
          i += 2;
          while (i < lines.length && lines[i].includes("|") && lines[i].trim()) { rows.push(cells(lines[i])); i += 1; }
          const headCells = rows.shift();
          out.push(h("div", { key: "t" + key++, className: "nvs-md-tbl" },
            h("table", null,
              h("thead", null, h("tr", null, headCells.map((c, x) => h("th", { key: x }, inline(c))))),
              h("tbody", null, rows.map((r, y) => h("tr", { key: y }, headCells.map((_, x) => h("td", { key: x }, inline(r[x] || "")))))))));
          continue;
        }
        if (/^\s*[-*+]\s+/.test(line)) {
          const items = [];
          while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*[-*+]\s+/, "")); i += 1; }
          out.push(h("ul", { key: "u" + key++ }, items.map((t, x) => h("li", { key: x }, inline(t)))));
          continue;
        }
        if (/^\s*\d+[.)]\s+/.test(line)) {
          const items = [];
          while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+[.)]\s+/, "")); i += 1; }
          out.push(h("ol", { key: "o" + key++ }, items.map((t, x) => h("li", { key: x }, inline(t)))));
          continue;
        }
        const para = [];
        while (i < lines.length && lines[i].trim() && !/^\s*(#{1,6}\s|[-*+]\s|\d+[.)]\s|>|```|---|\*\*\*)/.test(lines[i])) { para.push(lines[i]); i += 1; }
        out.push(h("p", { key: "g" + key++ }, inline(para.join("\n"))));
      }
      return out;
    };

    function Outline({ st, dir, toast, onChanged, go, part = "outline" }) {
      const s = st.setup || {};
      const isWorld = part === "world";
      const [outlineText, setOutlineText] = useState(s.outlineText || "");
      const [worldText, setWorldText] = useState(s.worldText || "");
      const [busy, setBusy] = useState(false);
      const [dirty, setDirty] = useState(false);
      const [outlineDirty, setOutlineDirty] = useState(false);
      const [genBusy, setGenBusy] = useState(false);
      const [worldBusy, setWorldBusy] = useState(false);
      const [sessionPending, setSessionPending] = useState(null); // 开会话按钮：正在打开时显示进度
      const [worldDirty, setWorldDirty] = useState(false); // 世界观只在自己改过时才回传，避免保存大纲时清空 AI 生成的世界观
      const [manualEdit, setManualEdit] = useState(false); // 没有大纲时，作者选择自己写而不是让 AI 生成
      const [worldManual, setWorldManual] = useState(false);
      const [olMode, setOlMode] = useState("edit"); // 大纲：编辑 / markdown 预览
      const [worldMode, setWorldMode] = useState("edit"); // 世界观：编辑 / markdown 预览
      const editorRef = useRef(null);
      const worldRef = useRef(null);
      const hasOutline = outlineText.trim().length > 0;
      // 提前声明：genOutline / outlineBtnLabel 等渲染期内会用到，必须早于它们的定义（避免 TDZ）
      const total = Number(st.project?.targetChapters) || 0;
      const done = Number(st.project?.currentChapter) || 0;
      const synopsis = (s.synopsis || "").trim();

      // 会话里深入调整大纲/深入设计世界观交回后，窗口拿回焦点就把最新文本刷进输入框（手改未保存时不覆盖）
      const dirtyRef = useRef(dirty);
      dirtyRef.current = dirty;
      useEffect(() => {
        if (typeof window === "undefined" || !window.addEventListener) return undefined;
        const refresh = () => {
          setOutlineText(s.outlineText || "");
          setWorldText(s.worldText || "");
          setDirty(false);
          setOutlineDirty(false);
          setWorldDirty(false);
        };
        const guard = () => { if (!dirtyRef.current) refresh(); };
        window.addEventListener("focus", guard);
        if (typeof window.__nvsRefresh === "function") window.__nvsRefresh(refresh);
        return () => {
          window.removeEventListener("focus", guard);
          if (window.__nvsRefresh === refresh) delete window.__nvsRefresh;
        };
      }, [s.outlineText, s.worldText]);

      // 生成大纲：按当前状态自动分派，一个按钮覆盖「首生成 / 续铺补全 / 重新生成」
      //   · 没有大纲              → 一次性生成整份（快）
      //   · 有大纲但没铺满/有断档 → 开 Agent 会话增量续铺（保住手改过的部分，只补后面）
      //   · 有完整大纲            → 一次性重写（会覆盖，先确认）
      const genOutline = async () => {
        if (genBusy) return;
        if (!(s.synopsis || "").trim()) { toast("先在「概览」页写一段故事梗概，再来生成大纲"); return; }
        const hasOl = (outlineText || "").trim().length > 0;
        const curIdx = hasOl ? olIndex(outlineText, total) : null;
        const incomplete = hasOl && (curIdx.gaps.length > 0 || (total && curIdx.maxTo < total * 0.95));
        if (incomplete) {
          // 已有大纲但没铺满 → 续铺（agent 会话，先读再补，不覆盖）
          runVolume();
          return;
        }
        if (hasOl && !incomplete) {
          const ok = typeof window !== "undefined" && window.confirm
            ? window.confirm("已有完整大纲，重新生成会整份覆盖现在的版本。继续？")
            : true;
          if (!ok) return;
        }
        setGenBusy(true);
        try {
          const ms = readModelSel() || {};
          const r = await postJSON("outline-gen", { dir, tone: s.tone || undefined, provider: ms.provider || undefined, model: ms.model || undefined });
          if (r && r.outlineText != null) setOutlineText(r.outlineText);
          setDirty(true);
          if (onChanged) await onChanged();
          toast(r && r.warning ? "大纲已生成，但" + r.warning : "大纲已生成，看过没问题就去生成世界观");
        } catch (e) {
          toast("生成大纲失败：" + (e.message || e));
        } finally {
          setGenBusy(false);
        }
      };
      // 按钮标签随状态变化，让作者知道这次点下去会发生什么
      const outlineBtnLabel = (() => {
        if (genBusy) return "生成中…";
        if (sessionPending === "深入调整大纲") return "正在打开会话…";
        const hasOl = (outlineText || "").trim().length > 0;
        if (!hasOl || manualEdit) return "生成大纲";
        const curIdx = olIndex(outlineText, total);
        const incomplete = curIdx.gaps.length > 0 || (total && curIdx.maxTo < total * 0.95);
        return incomplete ? "补全/续铺大纲" : "重新生成";
      })();

      // 一次性从大纲生成世界观（强制重写路径）
      const genWorldOnce = async () => {
        if (worldBusy) return;
        if (!hasOutline) { toast("先生成/写好大纲，再生成世界观"); return; }
        const hadWorld = (worldText || "").trim().length > 0;
        setWorldBusy(true);
        try {
          const ms = readModelSel() || {};
          const r = await postJSON("world-gen", {
            dir, outlineText,
            // 已有世界观时把旧版一并传过去，让模型沿用专名、只补不改，而不是整份推翻
            oldWorldText: hadWorld ? worldText : undefined,
            provider: ms.provider || undefined, model: ms.model || undefined,
          });
          if (r && r.worldText != null) { setWorldText(r.worldText); setWorldDirty(false); }
          setDirty(true);
          if (onChanged) await onChanged();
          toast(hadWorld
            ? "世界观已按原设定补深更新；下一步去「设定」页点「AI 补全设定」，把人物/势力/硬规则拆出来落账"
            : "世界观已生成；下一步去「设定」页点「AI 补全设定」，把人物/势力/硬规则拆出来落账，或再点本按钮「深入设计世界观」");
        } catch (e) {
          toast("生成世界观失败：" + (e.message || e));
        } finally {
          setWorldBusy(false);
        }
      };
      // 生成世界观：一个按钮按状态分派 —— 没有世界观→一次性生成；已有世界观→开 Agent 会话深入设计
      const genWorld = async () => {
        if (worldBusy) return;
        if (!hasOutline) { toast("先生成/写好大纲，再生成世界观"); return; }
        // 已有世界观正文 → 走「深入设计世界观」会话（在现有基础上补深，不覆盖）
        if (worldText.trim().length > 0) {
          runWorld();
          return;
        }
        await genWorldOnce();
      };
      // 世界观按钮标签随状态变化
      const worldBtnLabel = (() => {
        if (worldBusy) return "生成中…";
        if (sessionPending === "深入设计世界观") return "正在打开会话…";
        if (!worldText.trim()) return "生成世界观";
        return "深入设计世界观";
      })();

      const saveOutline = async () => {
        setBusy(true);
        try {
          // 保存大纲正文 + 世界观文本：outline op=set 传 outlineText（不传 beats）→ 后端只存文本、不动细纲账本
          const body = { dir, op: "set" };
          if (!isWorld) body.outlineText = outlineText;
          // 只有作者真的改过世界观文本框才提交它，否则会把生成好的世界观文本清空
          if (isWorld || worldDirty) body.worldText = worldText;
          await postJSON("outline", body);
          // 保存即视为确认大纲：自动推进到「建设定」阶段，不需要单独的确认按钮
          if (!isWorld && outlineText && outlineText.trim()) {
            try { await postJSON("outline", { dir, op: "accept", outlineText }); } catch (_) {}
          }
          setDirty(false);
          setOutlineDirty(false);
          setWorldDirty(false);
          if (onChanged) await onChanged();
          toast(isWorld ? "世界观已保存" : "大纲已保存，可以接着生成世界观");
        } catch (e) { toast("保存失败：" + (e.message || e)); }
        setBusy(false);
      };

      const canVolume = hasOutline && Boolean(synopsis) && !genBusy;
      // 深度设计是「在已有世界观上继续推演」，没有现成世界观就没得推演，按钮直接不给点
      const hasWorldNow = worldText.trim().length > 0;
      const pageDirty = isWorld ? worldDirty : outlineDirty;
      const openSession = (prompt, label, okMsg) => runSession({
        dir, prompt, label, okMsg, toast, pending: sessionPending, setPending: setSessionPending,
      });

      // 区块头：标题 + 一句话说明 + 主操作；状态用文字，不靠颜色区分
      const Head = ({ title, desc, right }) =>
        h("div", { className: "nvs-ol-head" },
          h("div", { style: { minWidth: 0 } }, h("h3", null, title), desc ? h("p", { className: "desc" }, desc) : null),
          right ? h("div", { className: "nvs-flex", style: { gap: 8, flex: "none" } }, right) : null);

      // 编辑器底部工具行：左边状态/提示，右边次操作
      const Tools = ({ state, hint, children }) =>
        h("div", { className: "nvs-ol-tools" },
          h("div", { className: "st" }, state || (hint ? h("span", { className: "nvs-hint" }, hint) : null)),
          h("div", { className: "nvs-flex", style: { gap: 8, flexWrap: "wrap", justifyContent: "flex-end" } }, children));

      const runVolume = () => openSession([
        `用 novel-studio 技能，给《${st.project?.title || ""}》深入调整大纲（只改大纲，不写正文）。`,
        skillLines("volume"),
        `0) 先读：novel_outline op=get 拿现有大纲原文，再看「概览」页的故事梗概；人物/硬规则只当约束，不往大纲里抄。不许凭印象重写。`,
        `约束：全书定死 ${total} 章，已写到第 ${done} 章——第 1-${Math.max(1, done)} 章已经成文，它们所在卷的卷名和已发生事件不能改，也不许改这些章的章号；卷区间必须从第 1 章一路铺到第 ${total} 章。`,
        `卷数：按目标章数定，约 round(${total}/50) 卷，允许 ±20% 浮动；不允许连续两卷都取上限或下限。`,
        `层级：只保留「全书层 + 卷层」两层，卷层直接写卷一、卷二……不要写「第一部 / 第二部」，也不要把多卷并成一行。`,
        `只改结构：全书层 + 卷层。人物卡、势力、硬规则、伏笔清单不要写进大纲；确实需要新增设定时，只在卷里写一句「待设定页补：…」，不要展开。`,
        `做法：1) 找出后半本空着、卷数不够、或者章号断档的地方；2) 补全书层（六节点、支线、对手阶梯）和卷层，每卷写清「### 第N卷 卷名（第a-b章）」、要完成什么、主要阻力、卷末钩子、情绪落点、卷末状态快照；3) 用 novel_studio_session return 交回完整的 outlineText（不要传 worldText）——大纲正文只在「大纲」页保存或由会话交回落盘，不要用 op=set 覆盖；4) 不要动设定账本和伏笔账本；5) 停下让我过目。`,
      ].join("\n"), "深入调整大纲", "已开会话深入调整大纲");

      const runWorld = () => openSession([
        `用 novel-studio 技能，给《${st.project?.title || ""}》深入设计世界观（不写正文）。`,
        skillLines("worldDeep"),
        `0) 先读：①「概览」页的故事梗概；②novel_outline op=get 拿全书层/卷层大纲；③现有世界观正文（项目文件 ${dir}/project.json 的 worldText）。三样缺一不可，不许凭印象重写。`,
        `以现有世界观为蓝本：在它的叙事结构上补深、补严、补自洽，保留已成立的东西，不要另起炉灶重写一遍。`,
        `保留原来的「## 1. …」小节编号，只增补和改写叙事内容；梗概里的核心冲突、主角处境、结局方向必须在世界观里有对应。`,
        `1) 读 novel_bible op=query 里已有的人物/世界/规则当参考，这一轮只读不改；`,
        `2) 用 novel-creator 的方法把世界基底、历史、地理、体系怎么运作、势力恩怨、日常氛围推演一遍，只写叙事，不列硬规则清单和人物卡；`,
        `3) 用 novel_studio_session return 回写完整 worldText（不要传 outlineText），设定账本和大纲这一轮都不要动；`,
        `4) 停下，提醒我去「设定」页点「AI 补全设定」，把新增内容拆成可执行条目。`,
      ].join("\n"), "深入设计世界观", "已开会话深入设计世界观");

      const idx = olIndex(outlineText, total);
      const pct = total ? Math.min(100, Math.round((idx.covered / total) * 100)) : 0;
      const gapText = idx.gaps.length
        ? "缺口：" + idx.gaps.slice(0, 3).map(([a, b]) => (a === b ? `第${a}章` : `第${a}-${b}章`)).join("、") + (idx.gaps.length > 3 ? " 等" : "")
        : (idx.vols.length ? `已覆盖 1-${total || idx.maxTo} 章` : "");
      const jumpTo = (at) => {
        setOlMode("edit");
        setTimeout(() => {
          const el = (typeof document !== "undefined" && document.getElementById("nvs-ol-md")) || editorRef.current;
          if (!el) return;
          el.focus();
          try { el.setSelectionRange(at, at); } catch (_) {}
          const ratio = outlineText.length ? at / outlineText.length : 0;
          el.scrollTop = Math.max(0, ratio * el.scrollHeight - el.clientHeight / 3);
        }, 30);
      };
      const widx = olIndex(worldText, 0);
      const jumpWorld = (at) => {
        setWorldMode("edit");
        setTimeout(() => {
          const el = (typeof document !== "undefined" && document.getElementById("nvs-world-md")) || worldRef.current;
          if (!el) return;
          el.focus();
          try { el.setSelectionRange(at, at); } catch (_) {}
          const ratio = worldText.length ? at / worldText.length : 0;
          el.scrollTop = Math.max(0, ratio * el.scrollHeight - el.clientHeight / 3);
        }, 30);
      };

      const secLinks = idx.sections.map((x, i) =>
        h("button", { key: "s" + i, type: "button", className: "nvs-ol-navbtn", onClick: () => jumpTo(x.at) },
          h("span", { className: "t" }, x.title)));
      const volLinks = idx.vols.map((v, i) =>
        h("button", { key: "v" + i, type: "button", className: "nvs-ol-navbtn", title: `跳到第${v.from}-${v.to}章`, onClick: () => jumpTo(v.at) },
          h("span", { className: "n", "aria-hidden": "true" }, v.no || i + 1),
          h("span", { className: "t" }, v.name || "未命名卷"),
          h("span", { className: "r" }, `${v.from}-${v.to}`)));
      const navCard = h("aside", { className: "nvs-ol-nav", "aria-label": "大纲导航" },
        idx.sections.length
          ? h("div", null, h("h4", null, "结构"), h("div", { className: "nvs-ol-navlist" }, secLinks))
          : null,
        h("h4", null, `卷目${idx.vols.length ? ` · ${idx.vols.length}` : ""}`),
        idx.vols.length
          ? h("div", { className: "nvs-ol-navlist" }, volLinks)
          : h("div", { className: "nvs-hint", style: { padding: "2px 4px", lineHeight: 1.6 } },
              "还没识别到卷头。每卷写成「### 第N卷 卷名（第a-b章）」，这里就会出现卷目。"));
      const editorCard = h("section", { className: "nvs-card nvs-ol-main", "aria-label": "全书大纲正文" },
        h("div", { className: "nvs-ol-bar" },
          h("div", { className: "l" },
            "大纲正文",
            outlineDirty
              ? h("span", { className: "nvs-badge-dirty" }, "有未保存的改动")
              : h("span", { className: "nvs-hint", style: { fontWeight: 400 } }, "已保存")),
          h("div", { className: "r" },
            h("div", { className: "nvs-seg", role: "group", "aria-label": "大纲显示方式" },
              h("button", { type: "button", className: olMode === "edit" ? "on" : "", onClick: () => setOlMode("edit") }, "编辑"),
              h("button", { type: "button", className: olMode === "preview" ? "on" : "", onClick: () => setOlMode("preview") }, "预览")),
            h("button", {
              className: "nvs-btn sm", disabled: !canVolume || Boolean(sessionPending),
              title: canVolume ? "参考梗概与现有大纲，把卷续铺到全书规模（不会覆盖你手改过的部分）" : "先有梗概和大纲才能续铺",
              onClick: genOutline,
            }, sessionPending === "深入调整大纲" ? "正在打开会话…" : "补全/续铺大纲"))),
        olMode === "preview"
          ? h("div", { className: "nvs-md", role: "document", "aria-label": "全书大纲预览" },
              outlineText.trim() ? mdToNodes(outlineText) : h("div", { className: "nvs-hint" }, "还没有内容，切回「编辑」写或生成。"))
          : h("textarea", {
          id: "nvs-ol-md", ref: editorRef, className: "nvs-area nvs-ol-md", spellCheck: false, rows: 20,
          "aria-label": "全书大纲正文",
          placeholder: "## 0. 素材研判\n…\n## 1. 全书层\n一句话故事核：…\n## 2. 卷层\n### 第1卷 卷名（第1-52章）\n…",
          value: outlineText, onChange: (e) => { setOutlineText(e.target.value); setDirty(true); setOutlineDirty(true); },
        }),
        h("div", { className: "nvs-ol-tips" },
          h("span", null, "卷头固定写「### 第N卷 卷名（第a-b章）」，进度页才能按卷分组"),
          h("span", null, "全书层 · 卷层 · 自检")));
      const emptyCard = h("section", { className: "nvs-card nvs-ol-empty", "aria-label": "还没有大纲" },
        h("div", { className: "ico", "aria-hidden": "true" }, "≡"),
        h("h3", null, "还没有全书大纲"),
        h("p", null, "大纲决定这本书能不能写到目标章数。先生成一版，之后随时可以在下面改。"),
        h("div", { className: "steps" },
          h("div", null, h("b", null, "1. "), "按故事梗概拆出全书层：故事核、六节点、支线、对手阶梯。"),
          h("div", null, h("b", null, "2. "), "把卷层一路铺到第 ", total || "目标", " 章，每卷写清任务、节拍、卷末钩子和状态快照。"),
          h("div", null, h("b", null, "3. "), "保存后 Agent 写正文会先读它；卷头格式错，进度页会分错卷。")),
        h("div", { className: "nvs-flex", style: { gap: 8, marginTop: 4 } },
          h("button", { className: "nvs-btn primary", disabled: genBusy || !synopsis, onClick: genOutline }, genBusy ? "生成中…" : "生成大纲"),
          h("button", { className: "nvs-btn", onClick: () => setManualEdit(true) }, "自己写")));
      // 「反差虐点」开关：只影响大纲提示词，加的是结构要求（反命题表 / 每卷拿走谁什么），不是句式模板。
      // 每次进页面重新读 studio，保证开关状态不会被父组件的旧快照拖住。
      const [tone, setToneState] = useState(s.tone === "contrast" ? "contrast" : "");
      const [toneBusy, setToneBusy] = useState(false);
      const toneOn = tone === "contrast";
      const flipTone = async () => {
        if (toneBusy) return;
        setToneBusy(true);
        const next = toneOn ? "" : "contrast";
        try {
          await postJSON("setup", { dir, tone: next });
          setToneState(next);
          if (onChanged) await onChanged();
          toast(next ? "已开启：下次生成大纲会按「反差虐点」结构排" : "已关闭反差要求（已生成的大纲不会变）");
        } catch (e) { toast("切换失败：" + (e.message || e)); }
        setToneBusy(false);
      };
      const toneCard = h("section", { className: "nvs-card", "aria-label": "写作基调" },
        h("div", { className: "nvs-flex", style: { alignItems: "center", gap: 12, flexWrap: "wrap" } },
          h("div", { style: { flex: "1 1 320px", minWidth: 0 } },
            h("div", { style: { fontWeight: 650, fontSize: 13.5 } }, "写作基调：反差虐点"),
            h("div", { className: "nvs-hint", style: { marginTop: 4, lineHeight: 1.7 } },
              toneOn
                ? "已开启。生成/重写大纲时会要求：每个核心角色都有一个「最想要/最骄傲」的东西，结局把它拧到反面；每卷写清「拿走了谁的什么」，至少三处用具体画面结算，结局留一口气。"
                : "这本书想要强烈反差（曾经最重要的东西最后被夺走 / 人变成最不想成为的人）就打开。只影响之后生成或重写的大纲，不动已写正文。")),
          h("button", {
            className: "nvs-btn " + (toneOn ? "primary" : ""), disabled: toneBusy, "aria-pressed": toneOn ? "true" : "false",
            style: { flex: "none", minWidth: 128 }, onClick: flipTone,
          }, toneBusy ? "切换中…" : toneOn ? "反差虐点：已开启" : "打开反差虐点")),
        h("div", { className: "nvs-hint", style: { marginTop: 8 } },
          "想改得更狠就去「设定」页的「当前方向」里补一句，例如「第 30 章后主角必须失去他最信任的人」——方向对后续章直接生效。"));
      const outlineView = h("div", null,
        h("div", { className: "nvs-ol-top" },
          h("div", { style: { minWidth: 0 } },
            h("h2", { className: "nvs-ol-title" }, "全书大纲"),
            h("p", { className: "nvs-ol-sub" }, "先把两层的骨架排到最后一章。写正文时按 10 章一段排段落纲，Agent 每次写正文前都会先读这里。"),
            h("div", { className: "nvs-ol-meta" },
              h("span", { className: "nvs-ol-chip" }, "目标 ", h("b", null, total ? `${total} 章` : "未定")),
              h("span", { className: "nvs-ol-chip" }, "已识别 ", h("b", null, `${idx.vols.length} 卷`)),
              h("span", { className: "nvs-ol-chip" }, "覆盖 ", h("b", null, idx.maxTo ? `1-${idx.maxTo} 章` : "—")),
              h("span", { className: "nvs-ol-chip" }, "正文 ", h("b", null, `${idx.words.toLocaleString()} 字`)))),
          h("div", { className: "nvs-flex", style: { gap: 8, flex: "none", flexWrap: "wrap" } },
            hasOutline
              ? h("button", { className: "nvs-btn sm", disabled: genBusy || Boolean(sessionPending), onClick: genOutline }, outlineBtnLabel)
              : h("button", { className: "nvs-btn primary sm", disabled: genBusy, onClick: genOutline }, outlineBtnLabel))),
        genBusy ? thinkRow("正在把梗概铺到全书规模") : null,
        h("div", { style: { marginBottom: 12 } }, toneCard),
        !hasOutline && !manualEdit
          ? emptyCard
          : h("div", null,
              h("div", { className: "nvs-ol-cover" },
                h("div", { className: "row" },
                  h("span", { className: "k" }, "卷层覆盖"),
                  h("span", { className: "v" }, gapText || "还没有识别到卷头")),
                h("div", { className: "nvs-ol-track", role: "progressbar", "aria-valuenow": pct, "aria-valuemin": 0, "aria-valuemax": 100, "aria-label": "大纲覆盖全书进度" },
                  h("div", { className: "nvs-ol-fill", style: { width: pct + "%" } })),
                idx.gaps.length ? h("div", { className: "nvs-hint", style: { marginTop: 7, color: "var(--nvs-warn)" } }, gapText + "；补上这些卷才能一路写到结局。") : null),
              h("div", { className: "nvs-ol-grid" }, navCard, editorCard)));

      const worldSecLinks = widx.sections.map((x, i) =>
        h("button", { key: "w" + i, type: "button", className: "nvs-ol-navbtn", onClick: () => jumpWorld(x.at) },
          h("span", { className: "t" }, x.title)));
      const worldNav = h("aside", { className: "nvs-ol-nav", "aria-label": "世界观目录" },
        h("h4", null, `设定目录${widx.sections.length ? ` · ${widx.sections.length}` : ""}`),
        widx.sections.length
          ? h("div", { className: "nvs-ol-navlist" }, worldSecLinks)
          : h("div", { className: "nvs-hint", style: { padding: "2px 4px", lineHeight: 1.6 } },
              "还没有小标题。用「## 1. 世界基底」这类标题分节，这里会出现目录。"));
      const worldEditor = h("section", { className: "nvs-card nvs-ol-main", "aria-label": "世界观正文" },
        h("div", { className: "nvs-ol-bar" },
          h("div", { className: "l" },
            "世界观正文",
            worldDirty
              ? h("span", { className: "nvs-badge-dirty" }, "有未保存的改动")
              : h("span", { className: "nvs-hint", style: { fontWeight: 400 } }, "已保存")),
          h("div", { className: "r" },
            h("div", { className: "nvs-seg", role: "group", "aria-label": "世界观显示方式" },
              h("button", { type: "button", className: worldMode === "edit" ? "on" : "", onClick: () => setWorldMode("edit") }, "编辑"),
              h("button", { type: "button", className: worldMode === "preview" ? "on" : "", onClick: () => setWorldMode("preview") }, "预览")),
            h("button", {
              className: "nvs-btn sm", disabled: worldBusy || Boolean(sessionPending),
              title: worldText.trim()
                ? "参考梗概、大纲与现有世界观，打开 Agent 会话把设定推演得更深"
                : "以大纲为素材一次性生成世界观",
              onClick: genWorld,
            }, worldBtnLabel))),
        worldMode === "preview"
          ? h("div", { className: "nvs-md", role: "document", "aria-label": "世界观预览" },
              worldText.trim() ? mdToNodes(worldText) : h("div", { className: "nvs-hint" }, "还没有内容，切回「编辑」写或生成。"))
          : h("textarea", {
          id: "nvs-world-md", ref: worldRef, className: "nvs-area nvs-ol-md", spellCheck: false, rows: 20,
          "aria-label": "世界观正文",
          placeholder: "## 1. 世界基底\n…\n## 3. 势力\n…\n## 5. 硬规则\n…",
          value: worldText, onChange: (e) => { setWorldText(e.target.value); setWorldDirty(true); setDirty(true); },
        }),
        h("div", { className: "nvs-ol-tips" },
          h("span", null, "叙事里要讲清「能做 / 不能做 / 代价」，才能在设定页拆成可检查的规则"),
          h("span", null, `${widx.words.toLocaleString()} 字 · ${widx.sections.length} 个小节`)));
      const worldEmpty = h("section", { className: "nvs-card nvs-ol-empty", "aria-label": "还没有世界观" },
        h("div", { className: "ico", "aria-hidden": "true" }, "◍"),
        h("h3", null, "还没有世界观"),
        h("p", null, "世界观会跟着大纲长出来，写正文时 Agent 会一直参考它。"),
        h("div", { className: "steps" },
          h("div", null, h("b", null, "1. "), "以已生成的大纲为素材，写叙事性世界观：世界基底、历史、地理、体系、势力恩怨、日常氛围、自洽检查。"),
          h("div", null, h("b", null, "2. "), "不在这里列规则和人物卡；生成后去「设定」页点「AI 补全设定」，由它统一拆成可执行条目。"),
          h("div", null, h("b", null, "3. "), "生成后同一个按钮会变成「深入设计世界观」，可以再点它把体系推演得更深。")),
        hasOutline
          ? h("div", { className: "nvs-flex", style: { gap: 8, marginTop: 4 } },
              h("button", { className: "nvs-btn primary", disabled: worldBusy, onClick: genWorld }, worldBusy ? "生成中…" : "生成世界观"),
              h("button", { className: "nvs-btn", onClick: () => setWorldManual(true) }, "自己写"))
          : h("div", { className: "nvs-note warn", style: { margin: 0 } }, "先把「大纲」页写好并保存，再来生成世界观。"));
      const worldView = h("div", null,
        PageHead({
          title: "世界观",
          desc: "这里只放叙事性内容：世界基底、历史、地理、体系怎么运作、势力恩怨、日常氛围。人物卡、硬规则、势力字段由「设定」页的 AI 补全从大纲和这里拆出来。",
          meta: [
            `正文 ${widx.words.toLocaleString()} 字`,
            `${widx.sections.length} 个小节`,
            `已落账设定 ${["characters", "factions", "locations", "items", "rules"].reduce((a, k) => a + ((st.setup && st.setup[k]) || []).length, 0)} 条`,
          ],
          actions: hasWorldNow
            ? [
                h("button", { key: "g", className: "nvs-btn sm", disabled: worldBusy || Boolean(sessionPending), onClick: genWorld }, worldBtnLabel),
                h("button", { key: "regen", className: "nvs-btn sm", disabled: worldBusy, onClick: () => {
                  if (typeof window !== "undefined" && window.confirm && !window.confirm("重新生成会整份覆盖现有世界观，继续？")) return;
                  genWorldOnce();
                } }, "重新生成"),
              ]
            : [],
        }),
        worldBusy ? thinkRow("正在从大纲推演世界观") : null,
        !hasOutline ? h("div", { className: "nvs-note warn", style: { marginBottom: 12 } }, "先把「大纲」页写好，再来生成世界观。") : null,
        !hasWorldNow && worldManual ? h("div", { className: "nvs-note", style: { marginBottom: 12 } }, "自己写不需要等 AI；保存后就能用「深入设计世界观」继续推演。") : null,
        !hasWorldNow && !worldManual
          ? worldEmpty
          : h("div", { className: "nvs-ol-grid" }, worldNav, worldEditor));

      return h("div", null,
        !synopsis ? h("div", { className: "nvs-note warn", style: { marginBottom: 12 } }, "还没写故事梗概。先去「概览」页写一段，大纲和世界观都从它长出来。") : null,
        isWorld ? null : outlineView,

        isWorld ? worldView : null,

        h("div", { className: "nvs-ol-savebar" },
          h("div", { className: "nvs-flex", style: { gap: 10, alignItems: "center" } },
            pageDirty ? h("span", { className: "nvs-badge-dirty" }, "有未保存的改动") : h("span", { className: "nvs-hint" }, isWorld ? "世界观已保存" : "大纲已保存"),
            h("span", { className: "nvs-hint" }, "保存后 Agent 写正文就会看到最新版本")),
          h("button", { className: "nvs-btn primary", disabled: busy || !pageDirty, onClick: saveOutline }, busy ? "保存中…" : pageDirty ? (isWorld ? "保存世界观 ·" : "保存大纲 ·") : (isWorld ? "保存世界观" : "保存大纲"))));
    }

    /* --------------------------------- 细纲 --------------------------------- */
    // 批量模式只有段落纲：逐章细纲的生成入口、展示、删除都已下线（老书账本仍在，Agent 用 novel_outline op=get 读得到）。
    function Detail({ st, dir, toast, onChanged }) {
      const segs = [...(st.segments || [])].sort((a, b) => Number(a.from) - Number(b.from));
      const [busy, setBusy] = useState("");
      const remove = async (g) => {
        if (busy) return;
        if (!window.confirm(`删掉第 ${g.from}-${g.to} 章的段落纲？\n已经写的章不会丢，只是这些章之后改按上一章收尾续写；要再按段落纲写就重新 plan 这一段。`)) return;
        setBusy(`${g.from}-${g.to}`);
        try {
          await postJSON("segment-delete", { dir, from: g.from, to: g.to });
          toast(`已删掉第 ${g.from}-${g.to} 章段落纲`);
          if (onChanged) await onChanged();
        } catch (e) { toast("删除失败：" + (e.message || e)); }
        setBusy("");
      };
      return h("div", null,
        PageHead({
          title: "细纲",
          desc: "按 10 章一段规划：一段一份段落纲（3-5 个台阶），写正文时 Agent 按本章所在的台阶走，不再逐章排细纲。",
          meta: [`段落纲 ${segs.length} 段`, segs.length ? `覆盖第 ${segs[0].from}-${segs[segs.length - 1].to} 章` : ""].filter(Boolean),
        }),
        h(Card, {
          title: "批次段落纲",
          desc: "每段覆盖连续 10 章左右。写正文时上下文包会带本章所在台阶的目标、转折和预计现场；整批写完一次 review。",
        },
          !segs.length
            ? h("div", { className: "nvs-empty" },
                h("b", null, "还没有段落纲"),
                "回「概览」点「写第 N-M 章」，Agent 会先 novel_segment op=plan 规划这一段，你确认台阶方向后落账。")
            : h("div", { style: { display: "grid", gap: 10 } },
                segs.map((g) => {
                  const plan = g.plan || {};
                  const stages = Array.isArray(plan.stages) ? plan.stages : [];
                  return h("div", { key: `${g.from}-${g.to}`, className: "nvs-fs", style: { padding: "10px 12px" } },
                    h("div", { className: "nvs-flex", style: { alignItems: "flex-start", gap: 10 } },
                      h("b", { style: { flex: "none", minWidth: 96 } }, `第${g.from}-${g.to}章`),
                      h("span", { className: "nvs-hint", style: { flex: 1 } }, `${g.stages} 个台阶`),
                      h("button", { className: "nvs-btn sm", style: { color: "#DC2626", flex: "none" }, disabled: Boolean(busy), onClick: () => remove(g) },
                        busy === `${g.from}-${g.to}` ? "删除中…" : "删除")),
                    g.spine ? h("div", { className: "mt", style: { marginTop: 4 } }, g.spine) : null,
                    stages.length
                      ? h("div", { style: { marginTop: 6, display: "grid", gap: 6 } },
                          stages.map((s, i) => {
                            const fs = s.foreshadow || {};
                            return h("div", { key: i, style: { borderLeft: "2px solid var(--nvs-line)", paddingLeft: 10 } },
                              h("div", { style: { fontWeight: 600, fontSize: 12.5 } }, `台阶${i + 1}（第${(s.chapters || []).join("、")}章）· 节奏${s.pace || "—"}`),
                              h("div", { className: "nvs-hint" }, `目标：${s.goal || "—"}`),
                              h("div", { className: "nvs-hint" }, `转折：${s.turn || "—"}`),
                              (fs.plant || []).length ? h("div", { className: "nvs-hint" }, `本台阶埋：${fs.plant.join("、")}`) : null,
                              (fs.payoff || []).length ? h("div", { className: "nvs-hint" }, `本台阶收：${fs.payoff.join("、")}`) : null,
                              (s.places || []).length ? h("div", { className: "nvs-hint" }, `预计现场：${s.places.join("、")}`) : null);
                          }))
                      : h("div", { className: "nvs-hint", style: { marginTop: 4 } }, "这段只有批次记录，没有台阶内容（老数据）；删掉重 plan 即可。"));
                }))));
    }

    /* --------------------------------- 设置 --------------------------------- */
    function Settings({ st, dir, toast, onChanged }) {
      const [models, setModels] = useState(null);
      const [sel, setSel] = useState(() => readModelSel() || { provider: "", model: "" });
      const [pluginInfo, setPluginInfo] = useState(null);
      const [repairBusy, setRepairBusy] = useState(false);

      useEffect(() => {
        getJSON("models").then((r) => {
          if (!r) return;
          setModels(r);
          if (!readModelSel() && r.current && r.current.provider) setSel({ provider: r.current.provider, model: r.current.model });
        }).catch(() => {});
        getJSON("ping").then((r) => { if (r) setPluginInfo(r); }).catch(() => {});
      }, []);

      const change = (e) => {
        const [p, m] = e.target.value.split("::");
        const next = { provider: p, model: m };
        setSel(next); saveModelSel(next); toast("已记住这个模型");
      };

      const doRepair = async () => {
        if (!dir || repairBusy) return;
        setRepairBusy(true);
        try {
          const r = await postJSON("repair", { dir });
          const rp = r.repair || {};
          const lines = (rp.ledger || []).reduce((a, x) => a + (x.removed || 0), 0);
          const debut = rp.debutFilled || [];
          const debutText = debut.length
            ? `；已按正文补首次登场：${debut.map((f) => `${f.name}（第${f.firstChapter}章）`).join("、")}`
            : "";
          toast(`已修复：${rp.chapters || 0} 章，索引已按正文重建${lines ? `，账本清掉 ${lines} 行坏数据` : ""}${debutText}`);
          if (onChanged) await onChanged();
        } catch (e) { toast("修复失败：" + (e.message || e)); }
        setRepairBusy(false);
      };

      return h("div", null,
        PageHead({
          title: "设置",
          desc: "插件用的模型、可用技能和版本信息。写作时以 DSH 会话里选的模型为准。",
          meta: [
            pluginInfo ? `v${pluginInfo.version}` : "版本读取中",
            pluginInfo && pluginInfo.skills ? `${pluginInfo.skills.length} 个技能` : "",
            sel && sel.model ? `当前 ${sel.model}` : "未选模型",
          ].filter(Boolean),
        }),
        h(Card, { title: "插件用的模型", desc: "生成选题、设定、大纲时用。写作时以 DSH 会话里选的模型为准。" },
          models && models.available === false
            ? h("div", { className: "nvs-note warn" }, "当前环境没有可用模型（DSH 里没配 key），生成选题、设定、大纲都不可用。")
            : h(Row, { label: "选择模型", hint: "DSH 支持的都列在这里" },
                h("select", { className: "nvs-input", style: { width: "auto", minWidth: 240 }, value: sel.provider + "::" + sel.model, onChange: change },
                  modelOptions(models, sel).map((o) => h("option", { key: o.value, value: o.value }, o.label)))),
          models && models.current ? h("div", { className: "nvs-hint", style: { marginTop: 6 } }, "DSH 当前默认：" + models.current.provider + " · " + models.current.model) : null),

        h(Card, { title: "插件拥有的技能", desc: "这些是面板内置、可被 Agent 调用的写小说技能；写作时 Agent 会自动按需使用。" },
          (pluginInfo && pluginInfo.skills && pluginInfo.skills.length)
            ? h("div", { style: { display: "grid", gap: 10 } },
                pluginInfo.skills.map((s) =>
                  h("div", { key: s.name, className: "nvs-fs", style: { padding: "10px 12px" } },
                    h("div", { className: "nm" }, s.title || s.name, h("span", { className: "nvs-hint", style: { marginLeft: 8, fontFamily: "var(--nvs-mono)", fontSize: 11 } }, s.name)),
                    h("div", { className: "mt", style: { marginTop: 4 } }, s.desc || ""))))
            : h("div", { className: "nvs-hint" }, "读取中…"),
          (pluginInfo && pluginInfo.tools && pluginInfo.tools.length)
            ? h("div", { style: { marginTop: 12 } },
                h("div", { className: "nvs-hint", style: { marginBottom: 6 } }, "配套工具（Agent 通过它们把设定/伏笔/章节写成账本）："),
                h("div", { style: { display: "flex", flexWrap: "wrap", gap: 6 } },
                  pluginInfo.tools.map((t) => h("span", { key: t, className: "nvs-pill mono", style: { fontSize: 11, fontFamily: "var(--nvs-mono)" } }, t))))
            : null),

        (() => {
          const on = readAutoArchive();
          return h(Card, { title: "自动存档", desc: "AI 写完的章进「进度」页时先体检，然后直接存档进正文，问题列在每章下面；要改就点「重写本章」。关掉后需要手动点「存档」。" },
            h("div", { className: "nvs-flex", style: { gap: 10 } },
              h("button", { className: "nvs-btn" + (on ? " primary" : ""), onClick: () => { writeAutoArchive(!on); toast(!on ? "已开启自动存档" : "已关闭自动存档，改成手动点「存档」"); if (onChanged) onChanged(); } },
                on ? "自动存档：已开启" : "自动存档：已关闭（手动）"),
              h("span", { className: "nvs-hint" }, on ? "写完就进正文，体检问题不影响存档" : "待确认的章要你自己点「存档」")));
        })(),

        h(Card, { title: "项目维护", desc: "章节列表对不上、项目打不开、门控状态卡住时，按 chapters/ 里的正文重建索引并对齐状态。修复前自动备份 project.json / index.json / bible.json。" },
          h("div", { className: "nvs-flex" },
            h("button", { className: "nvs-btn", disabled: !dir || repairBusy, onClick: doRepair }, repairBusy ? "修复中…" : "检查并修复这个项目"),
            h("span", { className: "nvs-hint" }, "只修结构，不改正文；坏掉的账本行会单独留证。"))),

        h(Card, { title: "关于", desc: "本插件把小说状态交给代码管，模型只负责写。" },
          h("div", { style: { display: "grid", gap: 6, fontSize: 12.5 } },
            h("div", { className: "nvs-flex" }, h("span", { className: "nvs-hint", style: { width: 88 } }, "版本"), h("span", { className: "nvs-mono" }, pluginInfo ? pluginInfo.version : "—")),
            h("div", { className: "nvs-flex" }, h("span", { className: "nvs-hint", style: { width: 88 } }, "项目目录"), h("span", { className: "nvs-mono", style: { fontSize: 11.5, wordBreak: "break-all" } }, dir || "—")))));
    }

    /* --------------------------------- 主壳 --------------------------------- */
    function Studio({ dir, toast, onChanged }) {
      const [st, setSt] = useState(null);
      const [err, setErr] = useState("");
      const [tab, setTab] = useState("overview");

      const load = useCallback(async () => {
        if (!dir) return;
        try { const r = await getJSON("studio?dir=" + q(dir)); setSt(r); setErr(""); }
        catch (e) { setErr(e.message); setSt(null); }
      }, [dir]);

      useEffect(() => { load(); }, [load]);

      // 会话里改完（novel_studio_session 交回）后，切回窗口就自动刷新；正在改设定时别冲掉手改内容
      const dirtyRef = useRef(false);
      useEffect(() => {
        if (typeof window === "undefined" || !window.addEventListener) return undefined;
        const onFocus = () => { if (!dirtyRef.current) load(); };
        window.addEventListener("focus", onFocus);
        document.addEventListener("visibilitychange", onFocus);
        return () => { window.removeEventListener("focus", onFocus); document.removeEventListener("visibilitychange", onFocus); };
      }, [load]);

      // hook 全部在 return 之前
      const setupDirty = useRef(false);
      const setupSave = useRef(null);
      const [, forceTick] = useState(0);
      const markDirty = useCallback((v) => { setupDirty.current = v; dirtyRef.current = v; forceTick((n) => n + 1); }, []);
      const doSave = () => { if (setupSave.current) setupSave.current(); };

      if (err) {
        return h("div", { className: "nvs-pane" },
          h("div", { className: "nvs-body" }, h("div", { className: "nvs-wrap" },
            h("div", { className: "nvs-note err" }, err),
            h("div", { className: "nvs-flex", style: { marginTop: 12 } },
              h("button", { className: "nvs-btn", onClick: load }, "重试")))));
      }
      if (!st) return h("div", { className: "nvs-pane" }, h("div", { className: "nvs-loading" }, "读取中…"));

      const TABS = [
        { id: "overview", label: "概览" },
        { id: "outline", label: "大纲", flag: Boolean((st.setup?.outlineText || "").trim()) },
        { id: "world", label: "世界观", flag: Boolean((st.setup?.worldText || "").trim()) },
        { id: "characters", label: "人物", flag: (st.setup?.characters || []).length > 0 },
        { id: "setup", label: "设定", flag: Boolean((st.setup?.synopsis || "").trim() || (st.setup?.rules || []).length) },
        { id: "foreshadow", label: "伏笔", flag: Boolean((st.foreshadow?.plan || "").trim() || (st.foreshadow?.open || []).length || st.foreshadow?.paidCount) },
        { id: "detail", label: "细纲", flag: (st.segments || []).length > 0 },
        { id: "progress", label: "进度" },
        { id: "discarded", label: "废章", flag: (st.discarded || []).length > 0 },
        { id: "settings", label: "设置" },
      ];

      const body = () => {
        if (tab === "characters") return h(Setup, { st, dir, onSaved: (r) => setSt(r), toast, onDirty: markDirty, saveRef: setupSave, go: setTab, part: "characters" });
        if (tab === "setup") return h(Setup, { st, dir, onSaved: (r) => setSt(r), toast, onDirty: markDirty, saveRef: setupSave, go: setTab, part: "setup" });
        if (tab === "outline") return h(Outline, { st, dir, toast, onChanged: load, go: setTab, part: "outline" });
        if (tab === "world") return h(Outline, { st, dir, toast, onChanged: load, go: setTab, part: "world" });
        if (tab === "foreshadow") return h(Foreshadow, { st, dir, toast, onChanged: load });
        if (tab === "detail") return h(Detail, { st, dir, toast, onChanged: load });
        if (tab === "progress") return h(Progress, { st, dir, toast, onChanged: load });
        if (tab === "discarded") return h(Discarded, { st, dir, toast, onChanged });
        if (tab === "settings") return h(Settings, { st, dir, toast, onChanged: load });
        return h(Overview, { st, dir, go: setTab, toast, onChanged: load });
      };

      return h("div", { className: "nvs-pane" },
        h("div", { className: "nvs-body" },
          h("div", { className: "nvs-wrap" },
            h("div", { className: "nvs-flex", style: { marginBottom: 10 } },
              h("span", { className: "nvs-hint nvs-mono", style: { fontSize: 11 } }, dir),
              h("span", { className: "nvs-spacer" }),
              (tab === "setup" || tab === "characters")
                ? h("button", {
                    className: "nvs-btn sm " + (setupDirty.current ? "primary" : ""),
                    disabled: !setupDirty.current,
                    onClick: doSave,
                  }, setupDirty.current ? (tab === "characters" ? "保存人物 •" : "保存设定 •") : "已保存")
                : null,
              h("button", { className: "nvs-btn ghost sm", onClick: load }, "刷新")),
            h("nav", { className: "nvs-nav", "aria-label": "小说工作台" },
              h("div", { className: "nvs-nav-row", role: "tablist" }, TABS.map((t) =>
                h("button", {
                  key: t.id, type: "button", role: "tab", className: "nvs-tab",
                  "aria-selected": tab === t.id ? "true" : "false", onClick: () => setTab(t.id),
                }, t.label, t.flag !== undefined ? h("i", { className: "dot" + (t.flag ? " ok" : "") }) : null)))),
            body())));
    }

    /* ------------------------------ 错误边界 ------------------------------ */
    class Boundary extends React.Component {
      constructor(p) { super(p); this.state = { err: null }; }
      static getDerivedStateFromError(err) { return { err }; }
      componentDidCatch(err, info) { try { console.error("[novel-studio]", err, info); } catch (_) {} }
      render() {
        if (this.state.err) {
          return h("div", { className: "nvs-root" },
            h("div", { className: "nvs-body" }, h("div", { className: "nvs-wrap" },
              h("div", { className: "nvs-note err" }, "界面出错了：" + (this.state.err && this.state.err.message ? this.state.err.message : String(this.state.err))),
              h("div", { className: "nvs-hint", style: { marginTop: 8 } }, "点下面重试；如果反复出现，把这段错误告诉开发者。"),
              h("div", { className: "nvs-flex", style: { marginTop: 12 } },
                h("button", { className: "nvs-btn primary", onClick: () => this.setState({ err: null }) }, "重试")))));
        }
        return this.props.children;
      }
    }

    /* ------------------------------ 书架 ------------------------------ */
    function Shelf({ books, loading, dir, onPick, onNew, onAskDelete }) {
      return h("aside", { className: "nvs-shelf", "aria-label": "书架" },
        h("div", { className: "nvs-shelf-head" },
          h("b", null, "书架"),
          h("span", { className: "nvs-spacer" }),
          h("button", { className: "nvs-btn primary sm", onClick: onNew },
            h(PlusIcon, { size: 13 }), "新建小说")),
        h("div", { className: "nvs-shelf-list" },
          loading
            ? h("div", { className: "nvs-shelf-empty" }, "正在翻书架…")
            : !books.length
              ? h("div", { className: "nvs-shelf-empty" }, "书架空着。点右上「新建小说」开一本，或者导入已有项目。")
              : books.map((b) =>
                  h("div", {
                    key: b.dir, role: "button", tabIndex: 0, className: "nvs-book",
                    "aria-current": dir === b.dir ? "true" : "false",
                    onClick: () => onPick(b.dir),
                    onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(b.dir); } },
                  },
                    h("span", { className: "t" }, b.title || "未命名"),
                    h("span", { className: "d" }, b.dir),
                    h("span", { className: "p" },
                      h("span", null, `${b.currentChapter || 0}/${b.targetChapters || "?"} 章 · ${fmtWan(b.totalChars)}`),
                      h("span", {
                        className: "del", role: "button", tabIndex: 0, "aria-label": `删除《${b.title || "未命名"}》`,
                        onClick: (e) => { e.stopPropagation(); onAskDelete(b); },
                        onKeyDown: (e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); e.preventDefault(); onAskDelete(b); } },
                      }, h(TrashIcon, { size: 14 })))))));
    }

    /* ------------------------------ 空状态 ------------------------------ */
    function EmptyDetail({ onNew }) {
      return h("div", { className: "nvs-empty" },
        h("div", { className: "nvs-empty-in" },
          h("div", { className: "ic" }, h(BookIcon, { size: 26 })),
          h("h2", null, "选一本书，或者开新书"),
          h("p", null, "左边点书名进这本书的配置；还没有书就点下面新建——书名、题材、大纲都可以让 AI 先出 3 个候选，你挑一个再开写。"),
          h("button", { className: "nvs-btn primary", onClick: onNew }, h(PlusIcon, { size: 14 }), "新建小说")));
    }

    /* --------------------------------- 页面 --------------------------------- */
    function NovelPageInner() {
      const [books, setBooks] = useState(null);
      const [dir, setDirState] = useState(() => readDirs()[0] || "");
      const [showNew, setShowNew] = useState(false);
      const [delTarget, setDelTarget] = useState(null);
      const [deleting, setDeleting] = useState(false);
      const [home, setHome] = useState("");
      const [defaultDir, setDefaultDir] = useState("");
      const [toastMsg, setToastMsg] = useState("");
      const toastRef = useRef(0);

      const toast = useCallback((text) => {
        setToastMsg(text);
        toastRef.current += 1;
        const mine = toastRef.current;
        setTimeout(() => { if (toastRef.current === mine) setToastMsg(""); }, 2600);
      }, []);

      const refreshShelf = useCallback(async () => {
        try { const r = await getJSON("shelf"); setBooks(r.books || []); }
        catch (_) { setBooks([]); }
      }, []);

      useEffect(() => {
        refreshShelf();
        getJSON("ping").then((r) => { setHome(r.home || ""); setDefaultDir(r.defaultDir || ""); }).catch(() => {});
        // 把浏览器里已选的模型同步给服务端，Agent 工具调用才能用同一个模型
        const saved = readModelSel();
        if (saved && saved.provider && saved.model) postJSON("model", saved).catch(() => {});
      }, [refreshShelf]);

      const setDir = useCallback((d) => {
        setDirState(d);
        try { if (d) localStorage.setItem(LS_DIR, d); else localStorage.removeItem(LS_DIR); } catch (_) {}
      }, []);

      const onCreated = useCallback((d) => {
        setShowNew(false);
        setDir(d);
        refreshShelf();
      }, [setDir, refreshShelf]);

      const doDelete = useCallback(async () => {
        if (!delTarget || deleting) return;
        setDeleting(true);
        try {
          await postJSON("delete", { dir: delTarget.dir });
          toast(`《${delTarget.title || "未命名"}》已删除`);
          if (dir === delTarget.dir) setDir("");
          setDelTarget(null);
          await refreshShelf();
        } catch (e) { toast("删除失败：" + e.message); }
        setDeleting(false);
      }, [delTarget, deleting, dir, setDir, refreshShelf, toast]);

      return h("div", { className: "nvs-root" },
        h("div", { className: "nvs-shell" },
          h(Shelf, {
            books, loading: books === null, dir,
            onPick: setDir, onNew: () => setShowNew(true), onAskDelete: setDelTarget,
          }),
          h("div", { className: "nvs-detail" },
            dir
              ? h(Studio, { key: dir, dir, toast, onChanged: refreshShelf })
              : h(EmptyDetail, { onNew: () => setShowNew(true) }))),
        showNew ? h(NewBookWizard, { home, defaultDir, onClose: () => setShowNew(false), onCreated, toast }) : null,
        delTarget ? h(DeleteDialog, { book: delTarget, busy: deleting, onClose: () => setDelTarget(null), onConfirm: doDelete }) : null,
        toastMsg ? h("div", { className: "nvs-toast", role: "status" }, toastMsg) : null);
    }

    function NovelPage() {
      return h(Boundary, null, h(NovelPageInner));
    }

    /* --------------------------------- 注册 --------------------------------- */
    function apply(ctx) {
      injectStyles();
      ROOT_CTX = ctx;
      const slots = ctx.get ? ctx.get("slots") : undefined;
      if (!slots) return;
      slots.inject("sidebar.panellist", () =>
        slots.register({ name: "sidebar.panellist", id: PANEL_ID, order: 20, label: () => "小说工作台" }, BookIcon));
      slots.inject("main", () => slots.register({ name: "main", key: PANEL_ID }, NovelPage));
    }

    const inject = ["slots"];
    const NovelIcon = BookIcon;
    const module = { exports: {} };
    module.exports = { apply, inject, PANEL_ID, NovelPage, NovelIcon };
    // 仅供自检脚本（scripts/client-test.mjs）直接挂载大纲/进度页；界面不依赖
    module.exports.__pages = { Outline, Studio, Progress, Overview, Setup, Foreshadow, Detail, Discarded, Settings, NewBookWizard };
    return module.exports;
  },
});
