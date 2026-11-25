# store（文件层）接口

只做磁盘语义：路径、原子写、JSONL 追加 + 折叠读、章索引、项目锁。
**不写任何领域判断**（门控、体检、字数估算、折叠成"业务状态"都在 `app/domain/`）。
`app/store` 永不 import `app/domain`；`app/domain` → `app/store` 单向依赖。

书稿格式与 `novel-studio/lib/io.js` 完全一致，现有书目录直接可读、可写回，不迁移。

## 目录布局

```python
from app.store import LAYOUT, LEDGER

LAYOUT = {
  "project": "project.json",        # 可写
  "bible": "bible.json",            # 可写
  "map": "map.json",                # 可写：AI 画的地图（独立 SVG）
  "relation_map": "relation_map.json",  # 可写：AI 画的人物关系图（独立 SVG）
  "chapters": "chapters",
  "chapter_index": "chapters/index.json",
  "ledger": "ledger",
  "review": "review",
  "drafts": "drafts",
  "exports": "exports",
}

LEDGER = {
  "bible": "bible.json",
  "foreshadow": "ledger/foreshadow.jsonl",
  "timeline": "ledger/timeline.jsonl",
  "segments": "ledger/segments.jsonl",
  "outline": "ledger/outline.jsonl",
  "review": "ledger/review.jsonl",
  "dismissed": "ledger/dismissed.jsonl",
  "usage": "metrics/usage.jsonl",
  "memory": "ledger/memory.jsonl",
}

LEDGER_KEYS = {   # 折叠读时定位当前状态的字段；None = 事件流，不折叠
  "foreshadow": "id", "timeline": "chapter", "segments": ("from", "to"),
  "outline": "chapter", "review": None, "dismissed": "key", "usage": None, "memory": "chapter",
}
```

章节文件：`chapters/{NNN}-{章名}.md`，章名只保留中英文数字，最多 30 字。

## 路径（`app/store/paths.py`）

```python
LAYOUT, LEDGER
DEFAULT_PROJECTS_DIR                       # DSH_NOVEL_HOME 或 ~/Desktop/mine/xiaoshuo
realpath_loose(p) -> Path                  # 不存在的路径解析父目录再拼末段（防软链绕过）
assert_writable_root(p, *, creating=False, extra_roots=None) -> Path
assert_browsable_root(p) -> Path
safe_join(root, rel) -> Path               # index.json 里的 file 字段用；越界抛 PermissionError
project_path(root, rel) -> Path            # 不做越界检查，只给代码里的固定相对路径用
ensure_dir(p) -> Path
list_files(dir) -> list[str]               # 跳过以 . 开头的
is_project(dir) -> bool                    # 有 project.json
list_project_dirs(base) -> list[Path]
pad3(n) -> str
chapter_file_path(root, number, title) -> Path
```

`assert_writable_root`：
- `creating=False`：已有项目原地读写，只拒系统目录与家目录本身。
- `creating=True`：还必须落在 `DEFAULT_PROJECTS_DIR` / 临时目录 / `DSH_NOVEL_ALLOWED_ROOTS` 内。
- 临时目录先放行（macOS `/var` → `/private/var` 两种形态都认）。

## JSON / 文本（`app/store/project.py`）

```python
read_json(file, fallback=...) -> Any        # 缺文件且给 fallback 时返回深拷贝；坏 JSON 抛 ValueError
write_json(file, value) -> Path             # 原子写，indent=2，末尾换行
read_text(file) -> str
write_text(file, text) -> Path              # 原子写
load_project(root) -> dict | None           # 无 project.json 返回 None
save_project(root, project) -> Path
load_bible(root) -> dict                    # 永远补齐 characters/world/rules/style/factions/locations/items/relations/infoGaps
save_bible(root, bible) -> Path
```

原子写（`fsatomic.atomic_write`）：同目录 `mkstemp` → 写入 → `fsync` → `os.replace`。
不会留下半截文件；崩溃时最多留一个隐藏的 `.xxx.tmp-*`。

## JSONL 账本（`app/store/jsonl.py`）

```python
read_jsonl(file) -> list[dict]     # 缺文件 = []；空行跳过；坏行 → {"__corrupt": True, "line": n, "raw": str}
append_jsonl(file, record) -> None # 追加一行 + fsync；永不改写已有行
is_corrupt(row) -> bool
corrupt_lines(rows) -> list[dict]  # 只挑坏行（repair 用）
rewrite_clean_jsonl(file, rows) -> int   # 原子写回好行，返回删掉的坏行数（repair 用）

fold_by_key(rows, key_field, apply=None) -> list[dict]
fold_foreshadow(rows) -> list[dict]   # op=payoff → paid, op=abandon → abandoned
fold_segments(rows) -> list[dict]     # 同 from-to 后写覆盖；op=delete 移除；按 from,to 排序
fold_outline(rows) -> list[dict]      # deleted:true 移除；chapter=0 是全书层
fold_timeline(rows) -> list[dict]
fold_dismissed(rows) -> list[dict]
fold_review(rows) -> list[dict]       # 事件流，原样返回好行，语义由 domain 定
```

**末行损坏跳过**：`read_jsonl` 永远不抛，坏行进结果，折叠函数自动忽略。
所以写一半崩掉时，下一次读到的就是"最后一条事件作废，前面的都还在"。

## 章节（`app/store/chapter.py`）

索引是**按章号**读写的，不假设连续：真实书有跳号，`number` 才是主键。

```python
count_chars(text) -> int                  # 只数汉字（与 metrics 的 chars 口径不同，这里只用于快速预览）
read_index(root) -> list[dict]            # number 转 int，按 number 排序；坏 index 抛 ValueError
write_index(root, rows) -> Path           # 原子写，按 number 排序
read_index_entry(root, number) -> dict | None
add_to_index(root, entry) -> list[dict]   # 按 number upsert（合并：新字段覆盖，旧字段保留），写盘
chapter_path(root, entry) -> Path         # 用 entry["file"]，过 safe_join；缺 file 时用 layout 规则
read_chapter(root, number) -> str | None  # 索引里没有 → None；有索引没文件 → FileNotFoundError
write_chapter(root, number, title, text) -> (Path, rel)
        # 写正文（strip + 末尾一个 \n）；章名变了会删掉旧文件；不碰索引
scan_chapter_files(root) -> list[{number, fileTitle, file, text}]   # 重建索引的输入
ensure_chapter_dirs(root) -> None         # chapters/ ledger/ review/ drafts/ exports/
```

`write_chapter` + `add_to_index` 是提交一章的两步；两步都应在 `project_lock` 里。

## 项目锁（`app/store/lock.py`）

```python
with project_lock(root, timeout=20.0):
    ...                       # 同线程可重入；跨线程/跨进程互斥
describe_holder(root) -> str  # 诊断用
```

实现：`<root>/.novel-studio.lock` 上 `fcntl.flock(LOCK_EX)`，非阻塞轮询到超时。
锁文件**保留不删**作为锚点（删掉会让两个持锁者指向不同 inode）；内容每次持锁时改写为 `{"pid": n}`。

⚠️ 同一个进程里两个线程各持一个 fd，`flock` 也会互相阻塞；同线程嵌套靠 `threading.local`
深度计数放行。所以锁内可以放心调用 `domain/segment.py` 里也加锁的函数，不会自锁。

## 用法约定

```python
from app.store import project_lock, append_jsonl, fold_segments, read_jsonl
from app.store.paths import LEDGER, project_path

with project_lock(root):
    rows = read_jsonl(project_path(root, LEDGER["segments"]))
    append_jsonl(project_path(root, LEDGER["segments"]), event)
    segs = fold_segments(rows)
```

- 账本只追加：改状态 = 再追加一条事件，绝不 `write_text` 覆盖整本（`repair` 的坏行清理除外）。
- 写入路径必须先过 `assert_writable_root`；新建项目用 `creating=True`。
- 任何"缺项目 / 缺章 / 越界"的失败都用异常返回，由 API 层映射成 400/404/403。

## 自测

```bash
cd backend && uv run pytest tests/test_store_*.py tests/test_api.py -q
```

`tests/test_store_real_books.py` 直接读 `~/Desktop/mine/xiaoshuo/` 下的
`最后一座信号塔`（10 章）和 `猎场第一百层`（68 章），逐章校验 `index.json` ↔ `chapters/*.md`。

## API 层的目录解析（不在 store 内）

`app/core/paths.py`：

```python
list_books() -> list[{dir, title, genre, targetChapters, currentChapter, chapterCount, updatedAt}]
recent_books(limit=5) -> [... + openedAt]
resolve_book(dir) -> Path      # assert_browsable_root → 目录存在 → 有 project.json
book_summary(path) -> dict
```

`app/api/deps.py` 暴露的（普通函数，不是 `Depends`）：

```python
def book_dir(dir: str | None) -> Path
```

映射：缺 `dir`/非项目 → 400，目录不存在 → 404，系统目录 → 403。
写盘路由在拿到 `Path` 之后自行 `assert_writable_root(path)` 或直接进 `project_lock(path)`。
