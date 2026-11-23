# reference/ — 旧 DSH 插件的 JS 原版（只读）

网页版是从 DSH 插件 `novel-studio` 移植过来的。插件已在 2026-11 删除，
这里保留 `lib/*.js` 原样，只为两件事：

1. **golden 回归**：`backend/tests/fixtures/*.json` 是用这些 JS 跑出来的，
   `scripts/gen_*_golden.mjs` 也从这里 import。没有它就无法重生成、无法复现差异。
2. **迁移未完的部分**：`domain.js`（门控 / 章节提交 / 连续性体检）、`api.js`、`index.js`
   仍在逐模块往 `backend/app/domain/` 搬，照着这里的行为对齐。

`client.js` / `index.js` 是 DSH 面板与工具定义，网页版不用，仅作行为参考。

**不要再改这里的文件。** 它是冻结的对照基准；要改行为请改 `backend/`，
改完用 `make test` 验证。需要重跑 golden 时：

```bash
node scripts/gen_metrics_golden.mjs backend/tests/fixtures/metrics_samples.json /tmp/out.json
```
