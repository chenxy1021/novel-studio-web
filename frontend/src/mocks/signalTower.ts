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

export const book: Book = {
  dir: '~/Desktop/mine/xiaoshuo/最后一座信号塔',
  title: '最后一座信号塔',
  genre: '末日 · 广播 · 守塔人',
  platform: '番茄',
  logline: '全城只剩一座还在广播的信号塔，守塔人每天念一遍撤离令，直到他听见自己的声音从塔外传来。',
  synopsis:
    '断讯第七年，季恒守着城郊的高塔，每天在两百兆赫上念一遍撤离令。城里没人知道他还活着，只把那九分半钟的广播当成末日里唯一准点的钟。直到某天夜里，他从日志里翻出一条不属于自己的发射记录——时间戳早于他重启高塔的那一刻。',
  theme: '守住一件东西的人，最后要学会把发令权交出去。',
  targetChapters: 100,
  currentChapter: 10,
  wordsPerChapter: 2200,
  minChars: 1800,
  segmentSize: 10,
  tone: '冷写实 · 克制的悲悯',
  gate: {
    phase: 'writing',
    chapter: 11,
    reason: '第1-10章一次 review 通过，开始写第11章',
    at: '2026-11-23 12:38',
  },
  gates: { brief: true, bible: true, outline: true },
  updatedAt: '2026-11-23 12:46',
  spine: '季恒想证明这座塔还活着，代价是他必须承认自己早就不是唯一在发令的人。',
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
  // approved 缺省 = true；显式 approved:false 表示场景种子里的「待确认」，别再用 unapproved 之类的临时字段。
  { number: 1, title: '第一段广播', chars: 2240, characters: ['季恒', '陈工'], summary: '季恒重启信号塔，播出第一段撤离令，靠六十秒空白证明自己还在。旧同事陈工赶来，逼他停播核对日志。', approved: true },
  { number: 2, title: '你的令还作数吗', chars: 2110, characters: ['季恒', '管账的', '女孩'], summary: '西柳收容站派管账的上塔谈交易，要用补给线换「自家人先走」的特批令，季恒一口回绝。', approved: true },
  { number: 3, title: '谁在替我念', chars: 2305, characters: ['季恒', '陈工', '女孩'], summary: '季恒带九分半的录音去找陈工核时间戳，两人第一次确认频段上有人借塔发令。', approved: true },
  { number: 4, title: '第四十一台的回执', chars: 1980, characters: ['季恒', '陈工'], summary: '第三天的回执从第四十一台发出，季恒追到旧配电房，只找回一枚被拆掉的继电器。', approved: true },
  { number: 5, title: '数据干净吗', chars: 2250, characters: ['季恒', '女孩'], summary: '女孩的抄本上多了三道杠。季恒开始怀疑每晚等他念令的那个孩子，比他更早发现了节奏不对。', approved: true },
  { number: 6, title: '纸上的名字', chars: 2080, characters: ['季恒', '陈工'], summary: '季恒整理七年前的撤离名单，发现自己那一行被人动过笔，墨色比周围新。', approved: true },
  { number: 7, title: '窄带上的生人', chars: 2360, characters: ['季恒', '接管者'], summary: '一阵陌生的杂音挤进两百兆赫，季恒听出对方用的是旧应急办的呼叫格式。', approved: true },
  { number: 8, title: '名单上少掉的', chars: 2180, characters: ['季恒', '陈工'], summary: '陈工摊开旧档案：当年没出来的不止七个人，还有一份被人从根上删掉的名单。', approved: true },
  { number: 9, title: '女孩的录音本', chars: 2010, characters: ['季恒', '女孩'], summary: '女孩把录下的十七盘磁带摆在桌上，季恒第一次听见自己念令时背景里的第二个呼吸。', hookOk: false, approved: true },
  { number: 10, title: '塔下焦土', chars: 2400, characters: ['季恒', '陈工', '管账的'], summary: '季恒下塔，走到塔脚那片焦土，挖出一截当天就该断掉的馈线——它不是断的，是被人拧紧的。', hookOk: false, approved: false },
]

// 体检 issue 挂在 chapter 上，由 makeBatchCheck 一并铺到那一章行下；跨章问题单列在 blocking。
export const chapterIssues: Record<number, Finding[]> = ({
  2: [{ severity: 'mid', code: 'pacing', message: '第2章交易细节偏多', hint: '谈话来回三轮，塔外广播中断的时间没交代' }],
  4: [
    { severity: 'high', code: 'foreshadow-missed', message: '第4章伏笔「第三遍回呼的规矩」未埋', hint: '第4章应埋设，但正文没有出现「念第三遍才回」' },
    { severity: 'info', code: 'metric', message: '第4章对话比 0.18，低于本书 0.22 均值' },
  ],
  6: [{ severity: 'mid', code: 'timeline', message: '第6章时间线与第3章日志冲突', hint: '第3章写「断讯第七年冬」，本章写「第七年秋」' }],
  9: [{ severity: 'mid', code: 'end-hook', message: '第9章章尾钩子偏弱', hint: '以「女孩没说话」收尾，读者缺少追问点' }],
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
    searchText: `${r.summary} 季恒 广播 两百兆赫 撤离令 陈工 女孩 馈线 焦土`.repeat(3),
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
      message: '本批四处的「九分半」时长写法不一致（九分半 / 十分钟 / 近十分钟）',
      hint: '把时长统一成「九分半」，后续章节沿用',
    },
    {
      severity: 'info',
      code: 'batch-pacing',
      message: '节奏全部压在季恒一个人的独白上，配角在本批只有陈工出手一次',
      hint: '11-20 章至少让女孩有一次主动行动',
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
      const spine = '从「塔还活着」到「有人在借塔说话」——本段只回答一个问题：频段上到底有没有第二个人。'
      const stages: SegmentStage[] = [
        {
          chapters: [1, 2, 3, 4],
          goal: '季恒先拿到本段的第一条实证，但因此暴露一个弱点',
          turn: '季恒想靠精通信号调试把全城唯一广播硬推，结果碰到「两百兆赫窄带上有人收听到撤离广播」，他把「广播还在响」当成「我还在负责」，宁可一人扛也不肯把发令权分给别人。',
          foreshadow: { plant: ['信号塔的假令源', '旧同事不问不答'], payoff: [] },
          pace: '紧',
          places: ['城郊高塔'],
          cast: ['季恒', '陈工'],
        },
        {
          chapters: [5, 6, 7],
          goal: '把「季恒想独占发令权」推到不可退的位置，逼对手第一次正面出手',
          turn: '本段最大的错：他认定只有自己能发令、能核令，坚持把证据攥在手里不交给任何一支小队公开比对。',
          foreshadow: { plant: ['第三遍回呼的规矩', '第三遍才应的手台', '塔下焦土的铁味'], payoff: [] },
          pace: '缓',
          places: ['旧城区枢纽', '配电房'],
          cast: ['季恒', '女孩'],
        },
        {
          chapters: [8, 9, 10],
          goal: '收束本段：实证落地，同时把「发令权」的代价提前亮给读者',
          turn: '陈工摊牌，女孩的录音本把第二个呼吸推到台前；季恒不得不承认，他守的不是塔，是「必须由他来说」这件事。',
          foreshadow: { plant: [], payoff: ['旧同事不问不答'] },
          pace: '紧',
          places: ['塔脚焦土', '塔顶'],
          cast: ['季恒', '陈工', '女孩'],
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
      const spine = '「另一个发令者」第一次露脸，季恒被迫用他看不起的方式（分权）换来一条线索。'
      const stages: SegmentStage[] = [
        {
          chapters: [11, 12, 13],
          goal: '让季恒第一次听见对方的完整口令',
          turn: '口令是他自己三年未用的呼号——对方学的是他，而不是另一个人。',
          foreshadow: { plant: ['三年前小队换粮的旧账'], payoff: [] },
          pace: '紧',
          places: ['塔顶控制室', '西柳收容站'],
          cast: ['季恒', '管账的'],
        },
        {
          chapters: [14, 15, 16, 17],
          goal: '把管账的从「交易对手」变成「知道点什么的人」',
          turn: '管账的认出念令者的停顿习惯，却不肯说自己怎么知道的。',
          foreshadow: { plant: ['管账的手腕上的旧疤'], payoff: ['三年前小队换粮的旧账'] },
          pace: '平',
          places: ['西柳收容站', '粮站'],
          cast: ['季恒', '管账的', '女孩'],
        },
        {
          chapters: [18, 19, 20],
          goal: '季恒第一次把发令权分出去，换回一条通往第四十一台的路线',
          turn: '分权当晚，塔被别人用来念了一段假令。',
          foreshadow: { plant: ['假令只念了四遍'], payoff: [] },
          pace: '紧',
          places: ['第四十一台', '旧水塔'],
          cast: ['季恒', '陈工'],
        },
      ]
      return { spine, stages: stages.length, plan: { from: 11, to: 20, spine, stages } }
    })(),
  },
]

export const foreshadows: Foreshadow[] = [
  { id: 'fs-1', name: '信号塔的假令源', kind: 'main', plantedChapter: 3, dueChapter: 41, status: 'open', source: '规则 · 两百兆赫未被污染', plantBeat: '拍3 日志末尾一行乱码指令', revealWho: '接管者', revealChange: '接管者即借塔发令者，同频筛选真相', hint: '41 旧同事翻日志停顿；67 塔顶广播混入半句陌生口令' },
  { id: 'fs-2', name: '名单上少掉的名字', kind: 'main', plantedChapter: 8, dueChapter: 52, status: 'open', source: '人物 · 接管者', plantBeat: '拍2 季恒整理旧撤离名单时划掉一行', revealWho: '陈工', revealChange: '当年遗弃非故意，两人旧账翻出', hint: '29 季恒梦里念一个名字' },
  { id: 'fs-3', name: '第三遍回呼的规矩', kind: 'main', plantedChapter: 5, dueChapter: 33, status: 'open', overdue: true, source: '规则 · 听见念自己队名第三遍才回', plantBeat: '拍1 女孩抄本上画三道杠', revealWho: '女孩', revealChange: '女孩早发现假令回呼节奏不对', hint: '33 队长抱怨有人第二遍就应', },
  { id: 'fs-4', name: '旧同事不问不答', kind: 'volume', plantedChapter: 3, dueChapter: 18, status: 'open', source: '人物 · 陈工', revealWho: '陈工', revealChange: '陈工其实知道第二个发令者是谁', hint: '18 陈工第一次答非所问' },
  { id: 'fs-5', name: '塔下焦土的铁味', kind: 'volume', plantedChapter: 9, dueChapter: 24, status: 'open', source: '地点 · 塔脚焦土', revealWho: '季恒', revealChange: '焦土里有被烧掉的第二座塔的地基', hint: '24 挖到焦土层下的混凝土' },
  { id: 'fs-6', name: '女孩的录音本', kind: 'volume', plantedChapter: 9, dueChapter: 26, status: 'open', source: '人物 · 女孩', revealWho: '女孩', revealChange: '录音本是按时间线排的证词', hint: '26 第17盘磁带没有标签' },
  { id: 'fs-7', name: '周头目账本上的代号', kind: 'detail', plantedChapter: 6, dueChapter: 15, status: 'open', source: '势力 · 粮站', revealWho: '管账的', revealChange: '代号指向收容站的门卫', hint: '15 管账的翻账本时停了半拍' },
  { id: 'fs-8', name: '四十年前的第一次广播', kind: 'detail', plantedChapter: 2, dueChapter: 12, status: 'paid', payoffChapter: 10, source: '历史 · 建塔档案', revealWho: '陈工', revealChange: '塔不是为撤离建的' },
  { id: 'fs-9', name: '继电器上的第三道刻痕', kind: 'detail', plantedChapter: 4, dueChapter: 11, status: 'paid', payoffChapter: 9 },
  { id: 'fs-10', name: '旧地名「西柳」的来由', kind: 'detail', plantedChapter: 1, dueChapter: 30, status: 'abandoned' },
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
  cast({ name: '季恒', role: '主角 · 守塔人', identity: '前应急办广播员，断讯后在城郊高塔独自维持六十秒空白', importance: '核心', tier: '主角', gender: '男', age: '三十四', race: '人类', personality: '遇事先算时间，嘴上不饶人', want: '让全城相信塔还活着', fear: '自己的声音被证明是多余的', secret: '三年前用发令时段换过粮', voice: '短句，少形容词，习惯用频率和时间说话', location: '信号塔控制室', locationAt: 10, locationHistory: [{ chapter: 1, place: '信号塔控制室' }, { chapter: 10, place: '塔下焦土', note: '下塔挖馈线' }], currentGoal: '查清馈线是谁拧紧的', status: 'active', firstChapter: 1, appears: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], color: '#e0357f' }),
  cast({ name: '陈工', role: '旧同事 · 对手兼证人', identity: '前基站维护班组长，说话只认日志', importance: '主要', tier: '常驻配角', gender: '男', age: '四十出头', race: '人类', personality: '只认日志，凡事先问核过没有', want: '把当年那份被改过的记录翻出来', fear: '自己成了被留下的人', secret: '知道第二个发令者的身份', voice: '反问句多，凡事先问「你核过没有」', location: '旧配电房', locationAt: 8, status: 'active', firstChapter: 1, appears: [1, 3, 4, 6, 8, 10], color: '#2f5f8a' }),
  cast({ name: '女孩', role: '塔下的听众 · 记录者', identity: '收容站长大的孩子，随身带一台旧录音机', importance: '主要', tier: '常驻配角', gender: '女', age: '十二', race: '人类', personality: '话少，先记下来再问', want: '留住每天九分半钟的声音', fear: '哪天没声音了，没人告诉她', secret: '录音里记着一段不属于季恒的呼吸', voice: '话很少，答话常是复述对方的前半句', location: '塔下铁皮屋', locationAt: 9, status: 'active', firstChapter: 2, appears: [2, 3, 5, 9], color: '#9a7b3f' }),
  cast({ name: '管账的', role: '西柳收容站 · 交易人', identity: '收容站派出谈判的人，手腕有旧疤', importance: '次要', tier: '单卷配角', gender: '男', personality: '客套话在前，价码藏在第二句', want: '用一条补给线换特批令', fear: '空手回去', secret: '认得念令者的停顿习惯', voice: '客套话在前，价码藏在第二句', location: '西柳收容站', locationAt: 10, status: 'active', firstChapter: 2, appears: [2, 10], color: '#2f7d5b' }),
  cast({ name: '接管者', role: '暗中借塔发令的人', identity: '身份未明，呼叫格式是旧应急办那一套', importance: '主要', tier: '反派', personality: '从不露面，只借别人的声音', want: '不明确', fear: '不明确', secret: '用季恒三年前的呼号发令', voice: '只有录音，没有对白', location: '不明', locationAt: 7, status: 'missing', firstChapter: 7, appears: [7], color: '#b4232c' }),
]

export const world: WorldHabit[] = [
  { key: 'wind', name: '塔下的风', detail: '高塔在城郊风口，风穿过铁塔的声音像有人压着嗓子数数；老听众靠这段风声判断广播是不是录播。' },
  { key: 'nine', name: '九分半钟', detail: '撤离令固定九分半，多一秒就有别的信号混进来。全城人拿这九分半对表。' },
  { key: 'blank', name: '六十秒空白', detail: '每天广播开始前的六十秒空白是季恒的「我还在」暗号，一旦没空，大家就知道守塔的人走了。' },
  { key: 'ferrule', name: '铁皮喇叭', detail: '没有机器的街区靠铁皮喇叭转播，声音传三层楼，音质差到只剩名字和方向。' },
  { key: 'call3', name: '第三遍才应', detail: '听见念自己队名第三遍才回话，是对面有人在听的唯一证明；回早了等于把位置交出去。' },
]

export const rules: Rule[] = [
  { id: 'r1', name: '两百兆赫唯一干净', text: '两百兆赫是唯一没被尸群电磁干扰污染的频段', enforce: '铁律', enforcer: '物理环境', cost: '被筛选出来的代价是所有人都能听见', loophole: '因此也能被冒用', boundary: '只在夜间干扰最强时成立', tested: '第3章、第7章实测', forbidden: ['三百兆赫', '备用频道'] },
  { id: 'r2', name: '第三遍才回', text: '听见念自己队名第三遍才回', enforce: '惯例', enforcer: '各队队长', cost: '回早了会暴露位置', loophole: '假令只能念四遍', boundary: '熟人之间可以少念一遍', tested: '第5章女孩抄本', forbidden: [] },
  { id: 'r3', name: '一台发射机', text: '塔只有一台发射机，一次只能发一个人的声音', enforce: '契约', enforcer: '塔本身', cost: '要发别人的令，就得把季恒的令掐掉', loophole: '空白六十秒没人听得出', boundary: '机器修好后可以并线，但会烧线圈', tested: '未实测', forbidden: ['两台发射机同时工作'] },
  { id: 'r4', name: '中断即失守', text: '撤离令一旦中断，收容站按「塔已失守」处理', enforce: '谣言', enforcer: '收容站', cost: '停播一次就等于宣告全城放弃', loophole: '无人监督的中断', boundary: '这条是收容站吓人的说法，塔从未因此停过', tested: '第2章管账的以此为筹码', forbidden: [] },
]

export const factions: Faction[] = [
  { name: '西柳收容站', nature: '城西最大收容点，粮与药的分配枢纽', openRule: '按人头配给', hiddenRule: '把特批令当硬通货在转手', debt: '欠旧水厂一批粮，至今没结', state: '粮药见底，靠配给维持秩序', stateAt: 0, attitude: '表面合作，暗中压价' },
  { name: '旧应急办残余', nature: '断讯前的官方机构残部，只剩档案和几台手台', openRule: '文件为准', hiddenRule: '谁保管档案，谁定义事实', debt: '欠陈工一个当年被改过的记录', state: '名存实亡，只剩档案权', stateAt: 0, attitude: '需要季恒的广播为他们作证' },
  { name: '粮站 · 周头目一系', nature: '城郊粮站的实际话事人', openRule: '先到先得', hiddenRule: '账本上的代号才是人', debt: '头目记着季恒当众驳过他面子', state: '粮足人杂，内部按代号分账', stateAt: 0, attitude: '提防且记仇' },
]

export const outline: OutlineVolume[] = [
  { index: 1, title: '塔还响着', range: [1, 20], done: 10, task: '守住广播，第一次意识到同频上还有别人', hook: '对方念的是季恒三年前的呼号', beats: ['第一段广播', '管账的上塔', '九分半里的第二个呼吸', '馈线没有断', '接管者第一次完整发令'] },
  { index: 2, title: '发令权', range: [21, 50], done: 0, task: '被迫分权，用发令时段换粮换路', hook: '分权当天，塔被拿去念了一段假令', beats: ['四十一台的援兵', '女孩录音本第十七盘', '西柳断粮', '陈工摊牌', '假令之后全城不再回头'] },
  { index: 3, title: '第二座塔', range: [51, 80], done: 0, task: '发现焦土下另一座塔的地基，守塔人不止一个', hook: '第二座塔的日志里，落款也是季恒', beats: ['焦土层下的混凝土', '旧地名的来由', '被烧掉的第一次广播', '接管者现身', '塔不是为撤离建的'] },
  { index: 4, title: '把话说清楚', range: [81, 100], done: 0, task: '最后一次广播：把发令权交给全城', hook: '塔还在响，只是念令的人换成了女孩', beats: ['全城接力', '最后一个不在名册上的人', '六十秒空白留给所有人', '塔下的风', '第一百天'] },
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
  { number: 10, title: '塔下焦土（第二稿）', reason: '章尾没收住，馈线伏笔提前被点破', chars: 1890, at: '2026-11-23 12:31', draftFile: 'drafts/010-塔下焦土-discard-mwt8a1.md', lead: '季恒站在塔脚，脚尖下面是焦黑的土。他蹲下去，手指碰到一截冷铁。那截馈线没有断，断口是被钳子拧出的一圈毛刺——' },
  { number: 9, title: '女孩的录音本（旧稿）', reason: '录音本出现得太早，把第17盘磁带的悬念吃掉了', chars: 2040, at: '2026-11-23 12:12', draftFile: 'drafts/009-女孩的录音本-discard-mwt7f3.md', lead: '女孩把十七盘磁带在桌上摊开，像摊开一副牌。她说：「叔，你每天晚上念的令，后面还有一个人在喘气。」' },
  { number: 6, title: '纸上的名字（旧稿）', reason: '时间写成了秋天，与第3章冬天冲突', chars: 1760, at: '2026-11-23 11:48', draftFile: 'drafts/006-纸上的名字-discard-mwt6c9.md', lead: '第七年秋，塔顶的风已经带着霜。季恒翻出那份撤离名单，纸边卷起，他的名字在第三行，墨色却比周围新。' },
  { number: 4, title: '第四十一台的回执（旧稿）', reason: '继电器线索给得太实，没有留出追查空间', chars: 1830, at: '2026-11-23 11:30', draftFile: 'drafts/004-第四十一台的回执-discard-mwt5d2.md', lead: '配电房的门虚掩着。季恒用胳膊肘顶开，手电扫过去，继电器躺在地上，外壳已经被人拆掉，只剩下三根铜线。' },
]

export const spineText: Record<number, string> = {
  1: '天还没擦黑，塔下的风声先到。\n\n季恒把发射机的开关按住三秒，红灯亮起来。全城的九分半，从一段空白开始。\n\n他对着话筒，把第一句撤离令念得不快不慢：「西柳、北岸、旧水厂，听清方向，往东走。」\n\n念到第七分钟，他停了一下。\n\n频段里有人跟着他，把最后一个字轻轻咬了半拍。',
  10: '他把账本末页那道拓痕又摸了摸，那斜勾硌在指尖上，凉。\n\n「开闸前，」他低声道，「把老黄的暗口接上。」\n\n天，彻底亮了。',
}
