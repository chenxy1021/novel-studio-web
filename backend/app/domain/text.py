"""人名匹配、硬规则命中、场景切分、地点轨迹——纯确定性文本判定。

移植自 novel-studio/lib/domain.js 里不读写账本的那部分（normName…nameHitsInText、
hardRuleHits、splitScenes、detectPlace、knownPlaceNames、spotsIn、spotScenes、
chapterScenes、knownScenesIn、formatScenes、lastKnownBase、learnSpots）。
"""

from __future__ import annotations

import re
from typing import Any

from .memory import aliases_of

# ------------------------------ 人名 ------------------------------

_NORM_DROP = re.compile(r"[\s·・/\-—_,，、()（）「」『』]")
# 身份描述（赵家长工、会院守井老汉）不是名字，不能靠包含关系认成同一人，也不能当别名
ROLE_TAIL_RE = re.compile(r"(长工|老汉|伙计|丫鬟|家丁|车夫|掌柜|账房|守卫|门房|更夫|学徒|弟子|婆子|妇人|少年|少女|老人|汉子)$")

# 已退场/死亡/失踪的人不再参与「该登场却缺席」和「提前登场」检查
GONE_STATUS = {"dead", "exited", "missing", "退场", "已死"}

SHORT_ALIAS_STOP = {
    "三指", "生面孔", "老头", "老汉", "少年", "少女", "老人", "汉子", "妇人", "婆子",
    "长工", "伙计", "掌柜", "账房", "守卫", "门房", "更夫", "学徒", "弟子", "丫鬟",
    "家丁", "车夫", "众人", "有人", "那人", "这人",
}
_PERSON_LIKE_SHORT = re.compile(r"^[老小阿大][\u4e00-\u9fff]$")
_DOUBLE_CHAR_NAME = re.compile(r"^([\u4e00-\u9fff])\1$")

_NAME_FUZZ = re.compile(r"[\s·・/\-—_,，、()（）「」『』【】《》。.!！?？;；:：]\"'“”‘’")
_NAME_FILLER = re.compile(r"[的了着地得个一之其吗呢啊吧嘛哦]")


def norm_name(x: Any) -> str:
    return _NORM_DROP.sub("", str(x or "").lower())


def is_gone_character(ch: dict[str, Any] | None) -> bool:
    return str((ch or {}).get("status") or "").strip() in GONE_STATUS


def role_core_names(name: Any) -> list[str]:
    """身份描述里可再认一次的核心叫法：「新麻绳扣的猎团领头」→「猎团领头」。"""
    s = str(name or "").strip()
    if not s:
        return []
    out = []
    cut = s.rfind("的")
    if 0 < cut < len(s) - 1:
        out.append(s[cut + 1:])
    m = ROLE_TAIL_RE.search(s)
    if m and m.start() > 0:
        out.append(s[m.start():])
    return [x for x in out if x and x != s]


def is_appearance_alias(name: Any) -> bool:
    s = str(name or "").strip()
    if not s or s in SHORT_ALIAS_STOP:
        return False
    if len(s) <= 2 and not _PERSON_LIKE_SHORT.match(s) and not _DOUBLE_CHAR_NAME.match(s):
        return False
    return True


def appearance_names(ch: dict[str, Any] | None) -> list[str]:
    """登场判定用的写法：主名 + 可用别名 + 身份描述切出的核心叫法。"""
    out: list[str] = []
    for nm in [(ch or {}).get("name"), *[a for a in aliases_of(ch or {}) if is_appearance_alias(a)]]:
        for x in [nm, *role_core_names(nm)]:
            if x and x not in out:
                out.append(x)
    return out


def fuzz_fold(s: Any) -> str:
    return _NAME_FILLER.sub("", _NAME_FUZZ.sub("", str(s or "").lower()))


def _is_part_of_longer_name(text: str, at: int, name: str, known_names: list[str]) -> bool:
    """「陆青荷」不该算「陆青」出场，「小陆青」也不该算。只看前后各一个字。"""
    before = text[max(0, at - 1):at]
    after = text[at + len(name):at + len(name) + 1]
    longer = [x for x in known_names if x and x != name and len(x) > len(name) and name in x]
    for long in longer:
        idx = long.find(name)
        want_before = long[idx - 1] if idx > 0 else ""
        want_after = long[idx + len(name)] if idx + len(name) < len(long) else ""
        if (not want_before or before == want_before) and (not want_after or after == want_after):
            return True
    return False


def name_positions(text: Any, names: list[str] | None, known_names: list[str] | None = None) -> list[int]:
    """精确名字命中（不做折叠），并排除「长名字的一部分」。"""
    t = str(text or "")
    known = known_names or []
    out: set[int] = set()
    for raw in names or []:
        nm = str(raw or "").strip()
        if len(nm) < 2:  # 单字名误撞太多，宁漏不误
            continue
        at = t.find(nm)
        while at >= 0:
            if not _is_part_of_longer_name(t, at, nm, known):
                out.add(at)
            at = t.find(nm, at + len(nm))
    return sorted(out)


def name_hits_in_text(text: Any, names: list[str] | None) -> list[int]:
    flat = str(text or "")
    flat_fold = fuzz_fold(flat)
    hits = []
    for nm in names or []:
        key = fuzz_fold(nm)
        if len(key) < 2:  # 折叠后不足 2 字太容易误撞
            continue
        at = flat_fold.find(key)
        while at >= 0:
            hits.append(min(len(flat), int(at / max(1, len(flat_fold)) * len(flat))))
            at = flat_fold.find(key, at + len(key))
    return hits


def is_role_descriptor(name: Any) -> bool:
    return bool(ROLE_TAIL_RE.search(norm_name(name)))


def clean_aliases(name: Any, aliases: Any) -> list[str]:
    if isinstance(aliases, list):
        lst = aliases
    elif isinstance(aliases, str):
        lst = re.split(r"[、,，/\s]+", aliases)
    else:
        lst = []
    out: list[str] = []
    for a in lst:
        t = str(a or "").strip()
        if t and t != name and not is_role_descriptor(t) and t not in out:
            out.append(t)
    return out


def same_person(a: Any, b: Any) -> bool:
    x, y = norm_name(a), norm_name(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if is_role_descriptor(x) or is_role_descriptor(y):
        return False
    short, long = (x, y) if len(x) <= len(y) else (y, x)
    # 单字名（镜）只认「无册者·镜」这种修饰·名字的写法
    if len(short) == 1:
        src = a if short in str(a) else b
        return bool(re.search(r"[·・/\-—]", str(src))) and long.endswith(short)
    return short in long


def find_same(rows: list[dict[str, Any]] | None, name: Any, aliases: Any) -> dict[str, Any] | None:
    """在已有条目里找同一个人（名字或别名任一对上）。"""
    cands = [x for x in [name, *clean_aliases(name, aliases)] if x]
    for x in rows or []:
        have = [x.get("name"), *(x.get("aliases") if isinstance(x.get("aliases"), list) else [])]
        if any(h and any(same_person(h, c) for c in cands) for h in have):
            return x
    return None


# ------------------------------ 硬规则 ------------------------------

def hard_rule_hits(rules: list[dict[str, Any]] | None, text: str) -> list[dict[str, str]]:
    """只认 forbiddenKeywords。trigger 是「这条规则何时适用」的上下文提示，不是禁用词。"""
    out = []
    for r in rules or []:
        kws = r.get("forbiddenKeywords") if isinstance(r.get("forbiddenKeywords"), list) else []
        hits = [str(w).strip() for w in kws if w and str(w).strip() and str(w).strip() in text]
        if hits:
            out.append({"rule": r.get("name") or r.get("text") or "硬规则", "matched": "、".join(hits)})
    return out


# ------------------------------ 场景切分 ------------------------------

_PARA_SPLIT = re.compile(r"\n{2,}")
_HEAD_SHIFT = re.compile(
    r"^(次日|翌日|第二天|当晚|当夜|片刻后|半[个]?小时[后之]|数小时后|几个小时后|三小时后|几小时后|一小时后|十分钟后|稍后|稍顷"
    r"|与此同时|另一边|另一头|回到|回到家|回家|来到|赶往|走进|踏进|推门|跨进|离开|出了|走出|到了|赶到|傍晚|清晨|深夜|午后"
    r"|天亮了|天亮时|后来|第二天一早|警局|医院|门口)"
)


def _js_round(x: float) -> int:
    import math
    return int(math.floor(x + 0.5))


def split_scenes(text: Any) -> list[dict[str, Any]]:
    """把一章正文按「场景跳转」切成若干段，返回 [{i, text}]。

    判据：空行分节；或段首出现时间/地点跳转词。不是语义理解，只提供可读的段边界。
    """
    raw = str(text or "").replace("\r\n", "\n")
    paras = [b.strip() for b in _PARA_SPLIT.split(raw) if b.strip()]
    scenes: list[str] = []
    cur: list[str] = []
    for para in paras:
        if cur and _HEAD_SHIFT.match(para):
            scenes.append("\n".join(cur))
            cur = []
        cur.append(para)
    if cur:
        scenes.append("\n".join(cur))

    def regroup(want: int) -> list[dict[str, Any]]:
        per = max(1, -(-len(paras) // want))
        groups = ["\n".join(paras[i:i + per]) for i in range(0, len(paras), per)]
        return [{"i": i + 1, "text": g} for i, g in enumerate(groups)]

    # 转场太少时按字数补充切分，保证长章至少有 ~900 字/段
    total_len = len("".join(paras))
    want_min = max(2, min(8, _js_round(total_len / 900)))
    if len(scenes) < want_min:
        return regroup(want_min) if paras else []
    if len(scenes) <= 1:
        return regroup(max(3, min(6, -(-len(paras) // 8)))) if paras else []
    return [{"i": i + 1, "text": t} for i, t in enumerate(scenes)]


# ------------------------------ 地点 ------------------------------

_PLACE_TAIL = re.compile(
    r"(?:在|到了|来到|进了|走进|走回|回到|回了|守在|坐在|蹲在|站在)"
    r"([\u4e00-\u9fa5]{0,8}(?:局|院|家|楼|室|房|店|铺|街|路|站|桥|巷|庙|衙署|码头|门口|门槛|台阶|墙根|墙|街口|大厅|办公室|现场))"
)


def detect_place(tail: Any) -> str:
    """正文结尾最后出现的地点；「门槛/台阶」这类站位退一格取前面的地点名。"""
    hits = [m.group(1) for m in _PLACE_TAIL.finditer(str(tail or "")) if m.group(1)]
    place = hits[-1] if hits else ""
    if place in ("门槛", "台阶", "墙根", "街口", "门口") and len(hits) > 1:
        place = hits[-2]
    return place


def known_place_names(bible: dict[str, Any] | None) -> list[dict[str, str]]:
    """章内轨迹只认设定里的地点名；一地点名 2 字起，单字太容易撞普通用词。"""
    rows: list[dict[str, str]] = []

    def push(s: Any, label: str, spot: str = "") -> None:
        v = str(s or "").strip()
        if len(v) >= 2:
            rows.append({"s": v, "label": label, "spot": spot})

    for loc in (bible or {}).get("locations") or []:
        base = str(loc.get("name") or "").strip()
        if not base:
            continue
        push(base, base)
        for a in loc.get("aliases") or []:
            push(a, base)
        raw_spots = loc.get("spots")
        spots = raw_spots if isinstance(raw_spots, list) else re.split(r"[、,，/｜|\s]+", str(raw_spots or ""))
        for sp in spots:
            v = str(sp or "").strip()
            push(v, base, v)
    # 长名优先，避免「堂口」先吃掉「第一堂口」
    return sorted(rows, key=lambda r: -len(r["s"]))


_SUB_PLACE = re.compile(
    r"的?(?:(?:堂|院|楼|屋|店|铺|庙|厅|廊|窗|门)?"
    r"(?:门口|门前|门内|门外|门边|堂下|堂前|堂后|堂外|院内|院中|院外|楼下|楼上|屋里|屋外|廊下|廊前|窗下|台阶|门槛|墙根|后院|前厅|侧厅|偏厅)"
    r"|(?:木牌|牌子|牌|门|堂|树|墙)?底下|木牌下|牌子下|牌下)"
)
_SPOT = re.compile(
    r"(?:走到|走进|走入|走过|走近|来到|赶到|回到|退回|退到|进了|入了|出了|站在|坐在|蹲在|守在|靠在|停在|穿过|转进|转向"
    r"|上了|下了|从|沿|往|向|在)"
    r"((?:(?!坐|站|走|跑|看|说|笑|问|答|抬|转|伸|退|进)[\u4e00-\u9fa5]){1,4}(?:口|尾|尽头|底下|之下|侧|后|前|内|外|上|下))"
)
_SPOT_NOISE = {
    "之后", "以前", "以上", "以下", "以后", "身后", "背后", "眼下", "手下", "脚下", "头上",
    "身上", "心里", "面上", "世上", "天下", "地下", "底下", "边上", "中途", "其中",
    "案上", "案下", "瓦上", "簿上", "纸上", "桌上", "床上", "椅上", "柜上", "架上", "凳上",
    "榻上", "席上", "手上", "膝上", "肩上", "背上", "膝下",
    "最上", "最下", "最前", "最后",
}
_BODY_OR_THING = re.compile(r"[身体心眼手脚头脸胸背腰膝腿肩肋额嘴鼻耳脖腕颈穴眉喉腹臀颧鬓痕案桌床椅柜架凳瓦纸笔簿册伞]")
_SPOT_SUFFIX = re.compile(r"(?:尽头|底下|之下|口|尾|侧|后|前|内|外|上|下)$")


def spots_in(para: Any) -> list[str]:
    out: list[str] = []
    for m in _SPOT.finditer(str(para or "")):
        w = re.sub(r"^的", "", m.group(1) or "")
        if re.match(r"^[他她我你]", w):
            w = w[1:]
        if len(w) < 2 or w in _SPOT_NOISE:
            continue
        if re.match(r"^[这那该每各此]", w):
            continue
        # 「就把我扣下」「哪本簿子上」这类是整个短句，不是位置
        if re.search(r"[我你他她它这那哪就都把被本]", w):
            continue
        if _BODY_OR_THING.search(_SPOT_SUFFIX.sub("", w)):
            continue
        if not out or w != out[-1]:
            out.append(w)
        if len(out) >= 10:
            break
    return out


def _scan_spots(paragraphs: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for para in paragraphs:
        for w in spots_in(para):
            if not out or w != out[-1]:
                out.append(w)
            if len(out) >= limit:
                break
        if len(out) >= limit:
            break
    return out


def spot_scenes(text: Any, names: list[str] | None) -> list[str]:
    paras = [s.strip() for s in re.split(r"\n+", str(text or "")) if s.strip()]
    wanted = [n for n in (names or []) if n]
    # 先只看提到这个人的段落；太少就退到整章（POV 章节里同一场戏常不重复点人名）
    own = _scan_spots([p for p in paras if not wanted or any(n in p for n in wanted)], 10)
    return own if len(own) >= 3 else _scan_spots(paras, 10)


def chapter_scenes(text: Any, names: list[str] | None, known: list[dict[str, str]]) -> list[dict[str, str]]:
    """一章里按出现顺序排出的地点序列；给了 names 就只看提到这些人的段落。"""
    paras = [s.strip() for s in re.split(r"\n+", str(text or "")) if s.strip()]
    wanted = [n for n in (names or []) if n]
    out: list[dict[str, str]] = []
    last_base = ""
    for para in (paras if known else []):
        if wanted and not any(n in para for n in wanted):
            continue
        scenes = known_scenes_in(para, known, last_base)
        if scenes:
            for sc in scenes:
                if sc["base"]:
                    last_base = sc["base"]
                if not out or out[-1]["base"] != sc["base"] or out[-1]["spot"] != sc["spot"]:
                    out.append(sc)
        else:
            # 这一段只写了「牌后 / 廊尾」这种具体位置，父地点由上一拍或上一章补
            for w in spots_in(para):
                hit = next((n for n in known if n["s"] != w and w.startswith(n["s"]) and n["label"]), None)
                out.append(
                    {"base": hit["label"], "spot": re.sub(r"^的", "", w[len(hit["s"]):])} if hit
                    else {"base": "", "spot": w}
                )
        if len(out) >= 12:
            break
    if out:
        return out[:12]
    res = []
    for w in spot_scenes(text, wanted):
        hit = next((n for n in known if n["s"] != w and w.startswith(n["s"]) and n["label"]), None)
        res.append({"base": hit["label"], "spot": re.sub(r"^的", "", w[len(hit["s"]):])} if hit else {"base": "", "spot": w})
    return res


def known_scenes_in(para: str, known: list[dict[str, str]], last_base: str) -> list[dict[str, str]]:
    """一段里出现的设定地点；「带着街上的潮气」「回忆阴司档房」这类不算。"""
    out: list[dict[str, str]] = []
    i = 0
    while i < len(para):
        best = None
        for n in known:
            at = para.find(n["s"], i)
            if at < 0:
                continue
            if best is None or at < best["at"] or (at == best["at"] and len(n["s"]) > len(best["s"])):
                best = {"at": at, **n}
        if best is None:
            break
        end = best["at"] + len(best["s"])
        m = _SUB_PLACE.match(para[end:end + 14])
        sub = re.sub(r"^的", "", m.group(0) if m else "")
        before = para[max(0, best["at"] - 2):best["at"]]
        after = para[end] if end < len(para) else ""
        is_spot = best["label"] != best["s"]
        if not sub and (after == "的" or re.search(r"[着的地得]$", before)):
            i = end
            continue
        near = para[max(0, best["at"] - 8):end + 8]
        if not is_spot and not sub and not re.search(r"[在进到回出来去走跑站坐蹲守望看等穿过跨退转靠沿往向离]", near):
            i = end
            continue
        # 学到的细分位置不能反过来把别的章节硬拽到自己名下
        spot_only = is_spot and best["label"] != last_base and best["label"] not in para
        out.append({"base": "" if spot_only else best["label"], "spot": best["spot"] if spot_only else (sub or best["spot"] or "")})
        i = end
    return out


def base_of(place: Any) -> str:
    """「档房（牌后）」里的父地点，用来接住只有细分位置的那些拍。"""
    return re.sub(r"（.*?）\s*$", "", str(place or "")).strip()


def format_scenes(scenes: list[dict[str, str]], prev_place: Any, valid_names: set[str]) -> list[str]:
    """写成显示用的「父地点（细分）」；没有父地点时退回上一章的地点。"""
    prev_base = base_of(prev_place)
    last_base = prev_base if prev_base in (valid_names or set()) else ""
    out = []
    for s in scenes:
        if s["base"]:
            last_base = s["base"]
            out.append(f"{s['base']}（{s['spot']}）" if s["spot"] else s["base"])
        else:
            out.append(f"{last_base}（{s['spot']}）" if last_base else s["spot"])
    return out


def location_name_set(bible: dict[str, Any] | None) -> set[str]:
    st: set[str] = set()
    for loc in (bible or {}).get("locations") or []:
        if loc.get("name"):
            st.add(str(loc["name"]).strip())
        for a in loc.get("aliases") or []:
            if a:
                st.add(str(a).strip())
    return st


def last_known_base(text: Any, known: list[dict[str, str]]) -> str:
    """整章最后提到的那个设定地点，用来给「只有细分位置」的拍当父地点。"""
    at, label = -1, ""
    for n in known:
        if n["spot"]:
            continue
        i = str(text or "").rfind(n["s"])
        if i > at:
            at, label = i, n["label"]
    return label


def learn_spots(bible: dict[str, Any], places: list[str] | None) -> bool:
    """正文里学到的细分位置写回地点设定，下次同一个词能直接挂到父地点上。"""
    changed = False
    for p in places or []:
        m = re.match(r"^(.+?)（(.+)）$", str(p or ""))
        if not m:
            continue
        base, spot = m.group(1), m.group(2)
        loc = next((x for x in (bible.get("locations") or [])
                    if x.get("name") == base or base in (x.get("aliases") or [])), None)
        if not loc:
            continue
        raw = loc.get("spots")
        lst = list(raw) if isinstance(raw, list) else [x for x in re.split(r"[、,，/｜|\s]+", str(raw or "")) if x]
        if spot not in lst:
            lst.append(spot)
            loc["spots"] = lst[-20:]
            changed = True
    return changed
