import type {
  BatchCheck,
  BibleCharacter,
  Book,
  Chapter,
  Discard,
  Faction,
  Finding,
  Foreshadow,
  OutlineVolume,
  Rule,
  Segment,
  SegmentStage,
  TimelineRow,
  UsagePoint,
  WorldHabit,
} from './types'

// 完全虚构的演示书，只用来跑界面；不来自任何真实书稿。
export const book: Book = {
  dir: '~/novel-studio/demo/mist-mail',
  title: '雾城夜邮',
  genre: '悬疑 · 山城 · 夜班',
  platform: '番茄',
  logline: '雾城最后一班夜邮只在午夜后送信，新来的邮差发现，每封信的收件人都在第二天消失。',
  synopsis:
    '雾城依山而建，午夜后起雾，夜邮局只在这个时段派件。沈夜接手最旧的一条邮路，师父老邮只交代一句：信送到就走，不要看收件人。第三晚，他在邮袋底部摸到一封写给自己的信，邮戳日期是十年前。',
  theme: '送信的人最后要决定，哪一封信该留在自己手里。',
  targetChapters: 80,
  currentChapter: 10,
  wordsPerChapter: 2200,
  minChars: 1800,
  segmentSize: 10,
  tone: '冷雾 · 慢悬疑',
  gate: {
    phase: 'writing',
    chapter: 11,
    reason: '第1-10章一次 review 通过，开始写第11章',
    at: '2026-11-23 12:38',
  },
  gates: { brief: true, bible: true, outline: true },
  updatedAt: '2026-11-23 12:46',
  spine: '沈夜想证明夜邮只是送信，代价是他必须承认自己一直在替十年前的人送信。',
}

export type RawChapter = {
  number: number
  title: string
  chars: number
  summary: string
  characters: string[]
  hookOk?: boolean
  approved?: boolean
}

export const raw: RawChapter[] = [
  { number: 1, title: '第一班夜邮', chars: 2240, characters: ['沈夜', '老邮'], summary: '沈夜接过最旧的夜邮线，老邮只交代三条规矩，第一封信的收件栏却是空的。', approved: true },
  { number: 2, title: '收件人不在', chars: 2110, characters: ['沈夜', '站长'], summary: '沈夜按地址走到半山，屋主一家已经搬空，桌上留着一封没拆的信。', approved: true },
  { number: 3, title: '邮戳上的旧日期', chars: 2305, characters: ['沈夜', '老邮', '阿禾'], summary: '沈夜核对邮戳，发现日期比夜邮局挂牌还早十年，阿禾说那晚钟楼也慢了一拍。', approved: true },
  { number: 4, title: '山道上的第二盏灯', chars: 1980, characters: ['沈夜', '老邮'], summary: '雾里有人提灯跟着他，他停对方也停；老邮要他别回头，也别数灯。', approved: true },
  { number: 5, title: '不要看收件人', chars: 2250, characters: ['沈夜', '阿禾'], summary: '沈夜拆开一封退信，里面是自己的笔迹，落款日期却是他还没进城的那一年。', approved: true },
  { number: 6, title: '老邮的抽屉', chars: 2080, characters: ['沈夜', '老邮'], summary: '老邮的抽屉锁着十年来的退信，钥匙却一直挂在门后的钉子上。', approved: true },
  { number: 7, title: '钟楼慢一拍', chars: 2360, characters: ['沈夜', '阿禾'], summary: '阿禾翻出抄表本：每封夜邮送达的钟点，钟楼都会慢一拍，十年没漏过一次。', approved: true },
  { number: 8, title: '空白的收件栏', chars: 2180, characters: ['沈夜', '站长'], summary: '一封退信被水浸过，收件栏只剩一个「沈」字，站长第一次改了班表。', approved: true },
  { number: 9, title: '十年后的回信', chars: 2010, characters: ['沈夜', '阿禾'], summary: '沈夜在旧码头找到寄信人的回信，信封上的收件人是他，邮戳是十年后。', hookOk: false, approved: true },
  { number: 10, title: '雾散之前', chars: 2400, characters: ['沈夜', '老邮', '站长'], summary: '沈夜决定把最后一封信送给自己，老邮提着灯站在邮局门口等他。', hookOk: false, approved: false },
]

// 体检 issue 挂在 chapter 上，由 makeBatchCheck 一并铺到那一章行下；跨章问题单列在 blocking。
export const chapterIssues: Record<number, Finding[]> = ({
  2: [{ severity: 'mid', code: 'pacing', message: '第2章找地址的过程偏长', hint: '山道来回写了三轮，收件人搬空的时间点没交代' }],
  4: [
    { severity: 'high', code: 'foreshadow-missed', message: '第4章伏笔「第三盏灯」未埋', hint: '第4章应埋设，但正文只写了第二盏灯' },
    { severity: 'info', code: 'metric', message: '第4章对话比 0.18，低于本书 0.22 均值' },
  ],
  6: [{ severity: 'mid', code: 'timeline', message: '第6章时间线与第3章邮戳冲突', hint: '第3章写「挂牌第十年」，本章写「第十一年」' }],
  9: [{ severity: 'mid', code: 'end-hook', message: '第9章章尾钩子偏弱', hint: '以「阿禾没说话」收尾，读者缺少追问点' }],
  10: [{ severity: 'high', code: 'unapproved', message: '第10章还在待确认，先存档或重写', hint: '待确认章不进正文统计' }],
} as Record<number, Finding[]>)

export const chapters: Chapter[] = raw.map((r) => {
  const issues = chapterIssues[r.number] ?? []
  return {
    number: r.number,
    title: r.title,
    chars: r.chars,
    summary: r.summary,
    characters: r.characters,
    approved: r.approved ?? true,
    verdict: issues.some((f) => f.severity === 'high') ? '差' : issues.length ? '中' : '良',
    chapterVerdict: issues.some((f) => f.severity === 'high') ? 'needs_fix' : 'pass',
    fixReasons: issues.filter((f) => f.severity === 'high').map((f) => f.message),
    endHook: r.hookOk === false ? { ok: false, reason: '以沉默收尾，没有问句、反转或倒计时' } : { ok: true, reason: '意外动作收尾' },
    dialogueRatio: r.number === 4 ? 0.18 : 0.24,
    searchText: `${r.summary} 沈夜 夜邮 邮戳 退信 老邮 阿禾 雾城`.repeat(3),
  }
})

export function makeBatchCheck(from: number, to: number): BatchCheck {
  const rows = chapters.filter((c) => c.number >= from && c.number <= to)
  const perChapter = rows.map((c) => {
    const findings = chapterIssues[c.number] ?? []
    return { number: c.number, pass: !findings.some((f) => f.severity === 'high'), findings, canRewrite: true }
  })
  const blocking: Finding[] = [
    {
      severity: 'mid',
      code: 'batch-recap',
      message: `第${from + 2}章开头复述了第${from + 1}章结尾的三个动作，整批读下来像重复`,
      hint: '整批视角问题，不属于某一章，批尾通过会被拦',
    },
    {
      severity: 'mid',
      code: 'batch-drift',
      message: '本批四处的「慢一拍」写法不一致（慢一拍 / 慢半拍 / 停一拍）',
      hint: '把时间写法统一成「慢一拍」，后续章节沿用',
    },
    {
      severity: 'info',
      code: 'batch-pacing',
      message: '节奏全压在沈夜一个人的夜路上，配角在本批只有老邮出手一次',
      hint: '11-20 章至少让阿禾有一次主动行动',
    },
  ]
  return { from, to, chapters: perChapter, blocking, checkedAt: '刚刚' }
}

export const segments: Segment[] = [
  {
    from: 1,
    to: 10,
    at: '2026-11-23T11:09:40.000Z',
    status: 'done',
    ...(() => {
      const spine = '从「夜邮只是送信」到「信在挑收件人」——本段只回答一个问题：那条最旧的邮路上，到底是谁在寄信。'
      const stages: SegmentStage[] = [
        {
          chapters: [1, 2, 3, 4],
          goal: '沈夜先拿到本段的第一条实证，但因此坏了老邮的规矩',
          turn: '沈夜想靠熟悉山路把最旧的邮路跑顺，结果碰到「收件栏空白也能寄出」的怪事，他把「送到就走」当成「我还能控制」，宁可自己核对也不肯把信交回局里。',
          foreshadow: { plant: ['没有收件人的信', '老邮不问不答'], payoff: [] },
          pace: '紧',
          places: ['夜邮局', '半山旧宅'],
          cast: ['沈夜', '老邮'],
        },
        {
          chapters: [5, 6, 7],
          goal: '把「沈夜想独占这条邮路」推到不可退的位置，逼老邮第一次正面拦他',
          turn: '本段最大的错：他认定退信只是地址写错，坚持把十年退信摊开比对，没有先问老邮为什么一直不扔。',
          foreshadow: { plant: ['第三盏灯', '钥匙挂在门后', '钟楼慢一拍'], payoff: [] },
          pace: '缓',
          places: ['夜邮局后院', '钟楼'],
          cast: ['沈夜', '阿禾'],
        },
        {
          chapters: [8, 9, 10],
          goal: '收束本段：实证落地，同时把「谁在收信」的代价提前亮给读者',
          turn: '老邮摊牌，阿禾的抄表本把十年前那一晚推到台前；沈夜不得不承认，他跑的不是邮路，是别人留给他的回信。',
          foreshadow: { plant: [], payoff: ['老邮不问不答'] },
          pace: '紧',
          places: ['旧码头', '夜邮局门口'],
          cast: ['沈夜', '老邮', '站长'],
        },
      ]
      return { spine, stages: stages.length, plan: { from: 1, to: 10, spine, stages } }
    })(),
  },
  {
    from: 11,
    to: 20,
    at: '',
    status: 'planned',
    ...(() => {
      const spine = '「另一个寄信人」第一次露脸，沈夜被迫用他最不信的方式（把信交出去）换来一条线索。'
      const stages: SegmentStage[] = [
        {
          chapters: [11, 12, 13],
          goal: '让沈夜第一次读到寄信人的完整落款',
          turn: '落款是他自己十年未用的旧名——对方学的是他，而不是另一个人。',
          foreshadow: { plant: ['沈夜进城前的旧名'], payoff: [] },
          pace: '紧',
          places: ['夜邮局分拣室', '旧码头'],
          cast: ['沈夜', '站长'],
        },
        {
          chapters: [14, 15, 16, 17],
          goal: '把站长从「排班的人」变成「知道点什么的人」',
          turn: '站长认得出寄信人的封口习惯，却不肯说自己怎么知道的。',
          foreshadow: { plant: ['站长手上的旧墨渍'], payoff: ['沈夜进城前的旧名'] },
          pace: '平',
          places: ['旧码头', '夜邮局'],
          cast: ['沈夜', '站长', '阿禾'],
        },
        {
          chapters: [18, 19, 20],
          goal: '沈夜第一次把信交出去，换回一条通往山那边旧邮路的路线',
          turn: '交信当晚，那条邮路上多了一封没有寄件人的回信。',
          foreshadow: { plant: ['回信只写四个字'], payoff: [] },
          pace: '紧',
          places: ['旧邮路', '山那边'],
          cast: ['沈夜', '老邮'],
        },
      ]
      return { spine, stages: stages.length, plan: { from: 11, to: 20, spine, stages } }
    })(),
  },
]

export const foreshadows: Foreshadow[] = [
  { id: 'fs-1', name: '没有收件人的信', kind: 'main', plantedChapter: 3, dueChapter: 41, status: 'open', source: '规则 · 夜邮只送不收', plantBeat: '拍3 分拣室多出一封空收件栏的信', revealWho: '老邮', revealChange: '空收件栏是寄信人留给收信人的位置', hint: '41 老邮翻旧班表时停顿；67 雾里出现第二盏灯' },
  { id: 'fs-2', name: '名单上少掉的名字', kind: 'main', plantedChapter: 8, dueChapter: 52, status: 'open', source: '人物 · 站长', plantBeat: '拍2 沈夜整理旧退信时划掉一行', revealWho: '站长', revealChange: '十年前那次改班不是意外，两人旧账翻出', hint: '29 沈夜梦里念一个名字' },
  { id: 'fs-3', name: '钟楼慢一拍', kind: 'main', plantedChapter: 5, dueChapter: 33, status: 'open', overdue: true, source: '规则 · 夜邮送达钟楼必慢一拍', plantBeat: '拍1 阿禾抄表本上画一道杠', revealWho: '阿禾', revealChange: '阿禾早知道夜邮的钟点不对', hint: '33 阿禾抱怨有人提前敲钟' },
  { id: 'fs-4', name: '老邮不问不答', kind: 'volume', plantedChapter: 3, dueChapter: 18, status: 'open', source: '人物 · 老邮', revealWho: '老邮', revealChange: '老邮其实知道另一个寄信人是谁', hint: '18 老邮第一次答非所问' },
  { id: 'fs-5', name: '旧码头的锈味', kind: 'volume', plantedChapter: 9, dueChapter: 24, status: 'open', source: '地点 · 旧码头', revealWho: '沈夜', revealChange: '码头仓库里留着一批没送出的夜邮', hint: '24 撬开仓库后墙的木板' },
  { id: 'fs-6', name: '阿禾的抄表本', kind: 'volume', plantedChapter: 9, dueChapter: 26, status: 'open', source: '人物 · 阿禾', revealWho: '阿禾', revealChange: '抄表本是按时间线排的证词', hint: '26 第十页没有日期' },
  { id: 'fs-7', name: '站长账本上的代号', kind: 'detail', plantedChapter: 6, dueChapter: 15, status: 'open', source: '势力 · 夜邮局', revealWho: '站长', revealChange: '代号指向旧码头的门房', hint: '15 站长翻账本时停了半拍' },
  { id: 'fs-8', name: '挂牌那天的第一封夜邮', kind: 'detail', plantedChapter: 2, dueChapter: 12, status: 'paid', payoffChapter: 10, source: '历史 · 建局档案', revealWho: '老邮', revealChange: '夜邮局不是为送信建的' },
  { id: 'fs-9', name: '退信柜上的第三道刻痕', kind: 'detail', plantedChapter: 4, dueChapter: 11, status: 'paid', payoffChapter: 9 },
  { id: 'fs-10', name: '旧地名「半山」的来由', kind: 'detail', plantedChapter: 1, dueChapter: 30, status: 'abandoned' },
]

/** mock 只填演示要用的字段，其余走默认值，避免每加一个字段就改一遍样例。 */
function cast(c: Partial<BibleCharacter> & Pick<BibleCharacter, 'name' | 'role' | 'identity' | 'want' | 'fear' | 'secret' | 'voice' | 'status' | 'appears' | 'color'>): BibleCharacter {
  return {
    aliases: [], importance: '', tier: '', gender: '', age: '', race: '', personality: '',
    appearance: '', bottomLine: '', flaw: '', ability: '', abilityLimit: '', abilityCost: '',
    location: '', locationAt: 0, locationHistory: [], currentGoal: '', knowledge: '',
    ignorance: '', misconception: '', changeLog: '', appearanceStatus: '', finalStatus: '', statusLog: [],
    firstChapter: 0, exitChapter: 0, ...c,
  }
}

export const characters: BibleCharacter[] = [
  cast({ name: '沈夜', role: '主角 · 夜邮邮差', identity: '刚接最旧一条夜邮线的新人', importance: '核心', tier: '主角', gender: '男', age: '二十八', race: '人类', personality: '遇事先记路线，嘴上不多说', want: '把这条邮路跑成自己的', fear: '自己的名字出现在退信栏', secret: '进城前用过另一个名字', voice: '短句，先报时间地点，再说判断', location: '夜邮局分拣室', locationAt: 10, locationHistory: [{ chapter: 1, place: '夜邮局' }, { chapter: 10, place: '夜邮局门口', note: '老邮提灯等他' }], currentGoal: '查清空收件栏的信是谁寄的', status: 'active', firstChapter: 1, appears: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], color: '#e0357f' }),
  cast({ name: '老邮', role: '师父 · 旧邮局看守', identity: '跑了三十年夜邮的老邮差，说话只认规矩', importance: '主要', tier: '常驻配角', gender: '男', age: '五十多', race: '人类', personality: '只认规矩，凡事先问送出去没有', want: '把最后一条旧邮路交出去', fear: '自己成了被留在局里的人', secret: '知道另一个寄信人的身份', voice: '反问句多，凡事先问「送到了没有」', location: '夜邮局后院', locationAt: 8, status: 'active', firstChapter: 1, appears: [1, 3, 4, 6, 10], color: '#2f5f8a' }),
  cast({ name: '阿禾', role: '钟楼抄表员 · 记录者', identity: '在钟楼抄了十年钟点，随身带一本旧抄表本', importance: '主要', tier: '常驻配角', gender: '女', age: '十九', race: '人类', personality: '话少，先记下来再问', want: '弄明白钟楼为什么总慢一拍', fear: '哪天钟不慢了，没人告诉她', secret: '抄表本里记着一段不属于她的钟声', voice: '话很少，答话常是复述对方的前半句', location: '钟楼', locationAt: 9, status: 'active', firstChapter: 3, appears: [3, 5, 7, 9], color: '#9a7b3f' }),
  cast({ name: '站长', role: '夜邮局负责人 · 排班人', identity: '管着夜邮局班表和退信柜的人，手上有旧墨渍', importance: '次要', tier: '单卷配角', gender: '男', personality: '客套话在前，决定藏在第二句', want: '把夜邮局撑到月底', fear: '旧账被翻出来', secret: '认得寄信人的封口习惯', voice: '客套话在前，价码藏在第二句', location: '夜邮局', locationAt: 10, status: 'active', firstChapter: 2, appears: [2, 8, 10], color: '#2f7d5b' }),
  cast({ name: '陌生人', role: '暗中寄信的人', identity: '身份未明，封口用的是旧邮局那一套', importance: '主要', tier: '反派', personality: '从不露面，只借别人的名字寄信', want: '不明确', fear: '不明确', secret: '用沈夜进城前的名字落款', voice: '只有信，没有对白', location: '不明', locationAt: 7, status: 'missing', firstChapter: 7, appears: [7], color: '#b4232c' }),
]

export const world: WorldHabit[] = [
  { key: 'fog', name: '午夜雾', detail: '雾城午夜后起雾，夜邮只在这段时间派件；老邮差靠雾里的灯数判断自己走到了哪一段。' },
  { key: 'slow', name: '慢一拍', detail: '夜邮送达的钟点，钟楼总会慢一拍。抄表员把它当误差，老邮差把它当规矩。' },
  { key: 'return', name: '退信柜', detail: '送不出去的信不销毁，锁进柜台，等寄信人自己来取；十年没人来取过。' },
  { key: 'blank', name: '空收件栏', detail: '收件栏空白的信照常派送，送到谁手里，谁就是收件人。' },
  { key: 'lamp', name: '山道灯语', detail: '山道上提灯的人不回头、不数灯；灯数是给后面的人看的，不是给自己看的。' },
]

export const rules: Rule[] = [
  { id: 'r1', name: '夜邮只送不收', text: '夜邮局只负责送信，不替人收信、不替人回信', enforce: '铁律', enforcer: '夜邮局', cost: '破了规矩，邮路就不再认这个邮差', loophole: '寄信人自己把回信塞进邮袋', boundary: '只在大雾夜成立', tested: '第3章、第7章实测', forbidden: ['替收件人回信', '把信带回家'] },
  { id: 'r2', name: '送到就走', text: '信送到门口就走，不看收件人，不等人拆', enforce: '惯例', enforcer: '老邮差', cost: '多看一封信，就多背一段不属于自己的事', loophole: '收件人追出来问', boundary: '熟人之间可以多站一会', tested: '第5章沈夜拆退信', forbidden: [] },
  { id: 'r3', name: '雾里不回头', text: '山道上听见有人叫名字，不能回头', enforce: '契约', enforcer: '旧邮路', cost: '回头的人会把自己的名字留在雾里', loophole: '第二盏灯亮起时可以停', boundary: '灯数超过三盏就失效', tested: '未实测', forbidden: ['在雾里应声'] },
  { id: 'r4', name: '退信不过夜', text: '退信必须在当天夜里送回局里，否则算寄信人自己取走', enforce: '谣言', enforcer: '站长', cost: '留一夜，信上的名字就会换人', loophole: '无人监督的退信', boundary: '这条是站长吓人的说法，老邮从没按时交过', tested: '第6章老邮的抽屉', forbidden: [] },
]

export const factions: Faction[] = [
  { name: '夜邮局', nature: '雾城唯一的夜间邮路，管着班表和退信柜', leader: '站长', representatives: '站长、老邮', openRule: '按班表派件', hiddenRule: '旧邮路的信不登记', debt: '欠老邮一条跑了三十年的邮路', state: '人手见底，靠老邮撑最后一班', stateAt: 0, attitude: '表面照章办事，暗中压着旧账' },
  { name: '钟楼管理处', nature: '管钟点和抄表的机构，只剩阿禾一个人值夜', leader: '阿禾', representatives: '阿禾', openRule: '钟点为准', hiddenRule: '谁抄表，谁定义那一拍', debt: '欠阿禾一个十年的解释', state: '名存实亡，只剩一本抄表本', stateAt: 0, attitude: '需要夜邮的送达记录为钟楼作证' },
  { name: '旧码头帮', nature: '旧码头仓库的实际话事人', leader: '门房', representatives: '门房', openRule: '先到先得', hiddenRule: '仓库里的旧信才是货', debt: '记着沈夜当众驳过他面子', state: '人杂货乱，内部按仓号分账', stateAt: 0, attitude: '提防且记仇' },
]

export const outline: OutlineVolume[] = [
  { index: 1, title: '夜邮还送', range: [1, 20], done: 10, task: '跑顺旧邮路，第一次意识到信在挑收件人', hook: '那封信的落款是沈夜进城前的名字', beats: ['第一班夜邮', '收件人搬空', '邮戳早了十年', '山道第二盏灯', '空收件栏'] },
  { index: 2, title: '交信', range: [21, 50], done: 0, task: '被迫把信交出去，用夜邮的班次换一条山那边的路', hook: '交信当晚，旧邮路上多了一封没有寄件人的回信', beats: ['山那边的旧邮路', '阿禾抄表本第十页', '旧码头断信', '老邮摊牌', '回信之后全城改了钟'] },
  { index: 3, title: '第二间邮局', range: [51, 80], done: 0, task: '发现山那边还有一间不挂牌的邮局，夜邮差不止一个', hook: '那间邮局的班表上，落款也是沈夜', beats: ['仓库后墙的木板', '旧地名的来由', '没送出的第一批夜邮', '陌生人现身', '夜邮局不是为送信建的'] },
  { index: 4, title: '把信送完', range: [81, 100], done: 0, task: '最后一班夜邮：把收件权交给全城', hook: '夜邮还在送，只是跑邮路的人换成了阿禾', beats: ['全城接力', '最后一个不在班表上的人', '空收件栏留给所有人', '山道上的雾', '第一百天'] },
]

export const timeline: TimelineRow[] = raw.map((r) => ({ chapter: r.number, inWorldDay: r.number, summary: r.summary }))

export const usage: UsagePoint[] = Array.from({ length: 24 }, (_, i) => {
  const ch = (i % 10) + 1
  return {
    at: `2026-11-23 ${String(8 + Math.floor(i / 3)).padStart(2, '0')}:${String((i * 17) % 60).padStart(2, '0')}`,
    kind: i % 4 === 0 ? 'context' : 'commit',
    chapter: ch,
    tokens: 6000 + ((i * 7919) % 9000),
    verdict: i % 5 === 0 ? 'needs_fix' : 'pass',
    rejected: i % 5 === 0,
  }
})

export const discarded: Discard[] = [
  { number: 10, title: '雾散之前（第二稿）', reason: '章尾没收住，老邮提灯的伏笔提前被点破', chars: 1890, at: '2026-11-23 12:31', draftFile: 'drafts/010-雾散之前-discard-mwt8a1.md', lead: '沈夜站在邮局门口，脚边是最后一只空邮袋。他蹲下去，手指碰到袋底一封信——收件栏写着他的名字，墨迹还没干透。' },
  { number: 9, title: '十年后的回信（旧稿）', reason: '回信出现得太早，把第十年的悬念吃掉了', chars: 2040, at: '2026-11-23 12:12', draftFile: 'drafts/009-十年后的回信-discard-mwt7f3.md', lead: '旧码头的仓库门虚掩着。沈夜推开一条缝，里面整整齐齐码着十年前的邮袋，最上面那封的收件人是他。' },
  { number: 6, title: '老邮的抽屉（旧稿）', reason: '时间写成了第十一年，与第3章第十年冲突', chars: 1760, at: '2026-11-23 11:48', draftFile: 'drafts/006-老邮的抽屉-discard-mwt6c9.md', lead: '第十一年冬，后院的风已经带着霜。老邮拉开抽屉，里面是十年来的退信，每一封都用细麻绳捆着。' },
  { number: 4, title: '山道上的第二盏灯（旧稿）', reason: '第二盏灯给得太实，没有留出追查空间', chars: 1830, at: '2026-11-23 11:30', draftFile: 'drafts/004-山道上的第二盏灯-discard-mwt5d2.md', lead: '雾从山坳里漫上来。沈夜走到半山，前面忽然亮起第二盏灯，灯下没有人，只有一只搁在石阶上的邮袋。' },
]

export const spineText: Record<number, string> = {
  1: '雾还没起，夜邮局的灯先亮了。\n\n沈夜把最后一袋信甩上肩，老邮在他身后说，三条规矩：送到就走，不看收件人，雾里不回头。\n\n他点头，低头看了眼最上面那封信。\n\n收件栏是空的。',
  10: '雾从街口漫过来，把邮局的招牌吞掉一半。\n\n沈夜把最后那封信塞进邮袋，收件栏上只写了一个「沈」字。\n\n老邮提着灯站在门口，没问他要去哪。\n\n「送到了就回来。」老邮说。',
}
