// 用 JS 原版（novel-studio/lib/metrics.js）生成 golden，供 backend/tests/test_metrics.py 比对。
// 只在移植期用；插件那边 metrics.js 改了要重跑一次，否则 golden 落后。
import fs from 'node:fs';
const PLUGIN = '/Users/chenxingyu/Desktop/mine/dsh/novel-studio';
const m = await import(`${PLUGIN}/lib/metrics.js`);
const samples = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = samples.map((t) => ({
  chars: m.countChars(t),
  tokens: m.estimateTokens(t),
  metrics: m.textMetrics(t),
  tells: m.detectAiTells(t),
  verdict: m.verdict(m.textMetrics(t), m.detectAiTells(t)),
  hook: m.checkChapterEndHook(t),
}));
fs.writeFileSync(process.argv[3], JSON.stringify(out));
