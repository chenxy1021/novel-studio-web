"""``/api/projects`` 路由组，按领域拆在各自的模块里。

所有子 router 都是 ``prefix="/projects"``，由这里汇总成一个 router 挂到 ``/api``；
URL 与拆分前完全一致。

- :mod:`.books`   书架、建/开/删书、总览、章节与设定读取
- :mod:`.studio`  开书流水线（选题/大纲/设定/伏笔/细纲/正文/段落/卷）
- :mod:`.style`   文风、写作技能、书级写作参数、虐文模式
- :mod:`.memory`  记忆页与记忆生成
- :mod:`.review`  审阅写回环（体检/存档/驳回/改写/伏笔/废稿）

请求体在 :mod:`.schemas`，异常到 HTTP 的映射在 :mod:`.errors`。
"""

from __future__ import annotations

from fastapi import APIRouter

from . import books, memory, review, studio, style

router = APIRouter()
for _part in (books, studio, style, memory, review):
    router.include_router(_part.router)
