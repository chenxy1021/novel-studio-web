"""作家文风预设：作为「参照写法」注入提示词，不复制原句；本书字段优先。

全部 8 项都可用于正文（``kind`` 只表示是否附带顾问式特征，不再限制用途）。
字段值沿用 ``style`` 的现有词表，方便直接合并进 ``bible.style``。

``samples`` 是**静态核对过出处**的代表性开篇片段（每段 ≤300 字），选预设且本书还没有
样章时补入 ``bible.style.samples``；``note`` 只作出处说明，不进入提示词。
样章不由「拆设定」生成，也不在运行时联网抓取。
"""

from __future__ import annotations

from typing import Any

PRESETS: list[dict[str, Any]] = [
    {
        "id": "aiqianshuidewuzhe",
        "name": "爱潜水的乌贼",
        "kind": "prose",
        "advisor": False,
        "summary": "逻辑严密的西式悬疑，设定随事件揭示，恐怖落在具体细节上。",
        "traits": [
            "中长句、逻辑连接词密",
            "英伦翻译腔的礼貌对白",
            "恐怖来自逻辑对不上的细节",
            "主角分析型、留后手、带自嘲",
            "设定随事件揭示",
        ],
        "fields": {
            "pov": "第三人称限制",
            "person": "他/她",
            "sentence": "中长句为主（20–35 字），逻辑连接词密",
            "paragraph": "3–5 句",
            "rhythm": "张弛",
            "dialogueRatio": "中 20–40%",
            "banned": ["网络烂梗", "绝绝子", "yyds", "破防", "血腥猎奇", "旁白讲设定", "打脸喊口号"],
            "notes": "英伦翻译腔的礼貌对白；恐怖靠「逻辑对不上」的具体细节；主角分析型、留后手、带自嘲；设定随事件揭示。",
        },
        "samples": [
            {
                "label": "《诡秘之主》开场",
                "text": "痛！好痛！头好痛！光怪陆离满是低语的梦境迅速支离破碎，熟睡中的周明瑞只觉脑袋抽痛异常，仿佛被人用棒子狠狠抡了一下，不，更像是遭尖锐的物品刺入太阳穴并伴随有搅动！",
                "note": "爱潜水的乌贼《诡秘之主》第一章 · 出处：https://yuedu.novel.qq.com/bqq/njiqhvvx",
            },
        ],
    },
    {
        "id": "chendong",
        "name": "辰东",
        "kind": "prose",
        "advisor": False,
        "summary": "宏大意象与时空尺度，短句对仗，悲壮苍凉，章末以诗化判词收束。",
        "traits": [
            "宏大意象与时空尺度",
            "四字句与短句，关键处对仗/排比",
            "悲壮苍凉，关键台词极短",
            "章末诗化或判词收束",
            "爽点后接代价",
        ],
        "fields": {
            "pov": "第三人称",
            "person": "他/她",
            "sentence": "四字句与短句为主，关键处对仗/排比",
            "paragraph": "1–3 句",
            "rhythm": "紧",
            "dialogueRatio": "低 10–20%",
            "banned": ["现代网络梗", "轻佻吐槽", "日常流", "小格局宫斗", "白开水叙述"],
            "notes": "宏大意象与时空尺度；悲壮苍凉；关键台词极短；章末诗化或判词收束；爽点后接代价。",
        },
        "samples": [
            {
                "label": "《遮天》开场",
                "text": "生命是世间最伟大的奇迹。四方上下曰宇。宇虽有实，而无定处可求。往古来今曰宙。宙虽有增长，不知其始之所至。",
                "note": "辰东《遮天》第一章 · 出处：https://m.qidian.com/bookrecommend/sqcc71f034e84701c5/",
            },
        ],
    },
    {
        "id": "enyang",
        "name": "恩养",
        "kind": "prose",
        "advisor": False,
        "summary": "短句、书面、精确，技艺口诀与中式诡异，细节即伏笔，冷静收尾。",
        "traits": [
            "短句、书面、精确",
            "技艺口诀感",
            "细节即伏笔",
            "中式诡异：规矩被破",
            "对白留三分，冷静收尾",
        ],
        "fields": {
            "pov": "第三人称限制",
            "person": "他/她",
            "sentence": "短句为主，书面、精确",
            "paragraph": "1–3 句",
            "rhythm": "张弛",
            "dialogueRatio": "低 10–20%",
            "banned": ["冗长大场面", "甜宠狗血", "无支撑反转", "网络口语", "纯血腥"],
            "notes": "技艺口诀感；细节即伏笔；中式诡异的「规矩被破」；对白留三分；冷静收尾。",
        },
        "samples": [
            {
                "label": "《相术师》开场",
                "text": "我家是相术师血脉，能测生死无常。大姐辨人善恶，二姐知人寿数，我能看到别人的死法。除了四妹是捡来的，只会抱我的大腿。",
                "note": "恩养《相术师》第一章 · 出处：https://www.800xs.tv/shu/4700895.html",
            },
        ],
    },
    {
        "id": "liucixin",
        "name": "刘慈欣",
        "kind": "prose",
        "advisor": False,
        "summary": "平静语调写震撼画面，通俗类比讲硬概念，情感压缩进决定与沉默。",
        "traits": [
            "平静语调写震撼画面",
            "通俗类比讲硬概念",
            "长短交错，段末短句收束",
            "情感压缩进决定与沉默",
            "反转靠逻辑",
        ],
        "fields": {
            "pov": "第三人称",
            "person": "他/她",
            "sentence": "长短交错，段末短句收束",
            "paragraph": "3–5 句",
            "rhythm": "张弛",
            "dialogueRatio": "低 10–20%",
            "banned": ["华丽辞藻", "滥情", "网络梗", "魔法式设定", "巧合解围", "生活流"],
            "notes": "平静语调写震撼画面；通俗类比讲硬概念；情感压缩进决定与沉默；反转靠逻辑。",
        },
        "samples": [
            {
                "label": "《三体》开场",
                "text": "汪淼觉得，来找他的这四个人是一个奇怪的组合：两名警察和两名军人，如果那两个军人是武警还算正常，但这是两名陆军军官。",
                "note": "刘慈欣《三体》第一章 · 出处：https://www.tedala.teda.gov.cn/contents/199/3587.html",
            },
        ],
    },
    {
        "id": "sanjiuyinyu",
        "name": "三九音域",
        "kind": "prose",
        "advisor": False,
        "summary": "动作分镜化，短句独立成段，旁观者反应放大主角，章末必留钩子。",
        "traits": [
            "动作分解如分镜",
            "短句为主，多独立成段",
            "旁观者反应放大主角",
            "关键台词有仪式感",
            "章末必留钩子",
            "规则浅显能打",
        ],
        "fields": {
            "pov": "第三人称限制",
            "person": "他/她",
            "sentence": "短句为主，多独立成段",
            "paragraph": "1–3 句",
            "rhythm": "紧",
            "dialogueRatio": "中 20–40%",
            "banned": ["拖沓文青抒情", "长篇环境描写", "晦涩设定", "一路无敌", "纯耍嘴炮"],
            "notes": "动作分解如分镜；旁观者反应放大主角；关键台词有仪式感；章末必留钩子；规则浅显能打。",
        },
        "samples": [
            {
                "label": "《我不是戏神》开场",
                "text": "苍白的雷光闪过如墨云层，雨流狂落，神怒般的雷雨浇灌在泥泞大地，涟漪层叠的水洼倒影中，一道朱红色的人影支离破碎。那是位披着大红戏袍的少年，他好似醉酒般踉跄淌过满地泥泞，宽大的袖摆在狂风中飘舞。",
                "note": "三九音域《我不是戏神》第 1 章 · 出处：https://fanqienovel.com/keyword/1297769",
            },
        ],
    },
    {
        "id": "maoni",
        "name": "猫腻",
        "kind": "prose+advisor",
        "advisor": True,
        "summary": "古今混搭、文白交错，借人物之口讲道理，群像各有判词式定性。",
        "traits": [
            "长短交错，文言句式夹现代口语",
            "古今混搭",
            "借人物之口直接讲道理",
            "人物不写成纯粹好坏",
            "群像各有一句判词式定性",
            "幽默是调料，不连续掉书袋",
        ],
        "fields": {
            "pov": "第三人称限制",
            "person": "他/她",
            "sentence": "长短交错，文言句式里可夹现代口语",
            "paragraph": "3–5 句",
            "rhythm": "张弛",
            "dialogueRatio": "中 20–40%",
            "banned": ["纯古典词汇堆砌", "把道理完全藏起来"],
            "notes": "古今混搭；借人物之口直接讲道理；人物不写成纯粹好坏；群像各有一句判词式定性；幽默是调料，不连续掉书袋。",
        },
        "samples": [
            {
                "label": "《庆余年》开场",
                "text": "澹州港在庆国的东面，虽然靠着大海，但由于最近南方的几个港口已经建设起来了，预计中的往西方去的海路也早已经联通，所以国家的贸易重心已经移往了南方。这个港口就渐渐显出了颓败。",
                "note": "猫腻《庆余年》第一章 · 出处：https://xuges.com/xh/qyn/0002.htm",
            },
        ],
    },
    {
        "id": "fenghuo",
        "name": "烽火戏诸侯",
        "kind": "prose+advisor",
        "advisor": True,
        "summary": "文白夹杂，诗词化用点到为止，判词式人物，道理藏在情节与留白里。",
        "traits": [
            "文白夹杂，长短交错",
            "诗词化用点到为止",
            "判词式人物",
            "道理藏在情节与留白里",
            "群像如珠帘，一人一面",
            "情节门槛高，不靠降智",
        ],
        "fields": {
            "pov": "第三人称",
            "person": "他/她",
            "sentence": "文白夹杂，长短交错",
            "paragraph": "1–3 句",
            "rhythm": "张弛",
            "dialogueRatio": "低 10–20%",
            "banned": ["现代俚语混搭", "金句/诗词连续堆砌"],
            "notes": "文白夹杂；诗词化用点到为止；判词式人物；道理藏在情节与留白里；群像如珠帘，一人一面；情节门槛高，不靠降智。",
        },
        "samples": [
            {
                "label": "《雪中悍刀行》开场",
                "text": "黄昏中，官道上一老一少被余晖拉长了身影，老的背负着一个被破布包裹的长条状行囊，衣衫褴褛，一头白发，还夹杂几根茅草。他牵着一匹瘦骨嶙峋的跛马。",
                "note": "烽火戏诸侯《雪中悍刀行》第 1 章 · 出处：https://www.qidian.com/bookrecommend/sq7ca627b1f0e944bc",
            },
        ],
    },
    {
        "id": "yuhua",
        "name": "余华",
        "kind": "prose+advisor",
        "advisor": True,
        "summary": "短句白描、口语化，先感官后意义，苦难写得平静克制。",
        "traits": [
            "短句白描，口语化",
            "先感官后意义",
            "用故事代替断言",
            "苦难写得平静",
            "克制，不端着",
        ],
        "fields": {
            "pov": "第一人称或第三人称限制",
            "person": "我/他",
            "sentence": "短句为主",
            "paragraph": "1–3 句",
            "rhythm": "张弛",
            "dialogueRatio": "中 20–40%",
            "banned": ["华丽辞藻", "书面腔", "抽象议论", "煽情"],
            "notes": "短句白描；口语化；先感官后意义；用故事代替断言；苦难写得平静；克制，不端着。",
        },
        "samples": [
            {
                "label": "《活着》开场",
                "text": "我比现在年轻十岁的时候，获得了一个游手好闲的职业，去乡间收集民间歌谣。那一年的整个夏天，我如同一只乱飞的麻雀，游荡在知了和阳光充斥的村舍田野。",
                "note": "余华《活着》第一章 · 出处：https://www.lfstsg.com/information/1205",
            },
        ],
    },
]

_BY_ID = {preset["id"]: preset for preset in PRESETS}


def get_preset(preset_id: Any) -> dict[str, Any] | None:
    return _BY_ID.get(str(preset_id or "").strip())


def preset_samples(preset: dict[str, Any]) -> list[dict[str, Any]]:
    """预设自带的样章，统一打上 ``origin="preset"``，切换预设时可安全替换。"""
    return [
        {**sample, "origin": "preset"}
        for sample in (preset.get("samples") or [])
        if isinstance(sample, dict) and str(sample.get("text") or "").strip()
    ]


def preset_sample_texts() -> set[str]:
    """所有预设样章的正文，用于识别旧数据里没有 ``origin`` 的预设样章。"""
    return {
        str(sample.get("text") or "").strip()
        for preset in PRESETS
        for sample in (preset.get("samples") or [])
        if isinstance(sample, dict) and sample.get("text")
    }


def list_presets() -> list[dict[str, Any]]:
    """API view: every preset is usable for prose in slice 1."""
    return [
        {**preset, "samples": preset_samples(preset), "applicable": True}
        for preset in PRESETS
    ]
