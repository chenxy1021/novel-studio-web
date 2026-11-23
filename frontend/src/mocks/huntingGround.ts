import type { Book, BibleCharacter, Chapter, Segment, SegmentStage } from './types'
import { book as signal, characters as signalChars, discarded as signalDiscarded } from './signalTower'

export const book: Book = {
  ...signal,
  dir: '~/Desktop/mine/xiaoshuo/猎场第一百层',
  title: '猎场第一百层',
  genre: '末日 · 异能 · 副本攀塔',
  logline: '末世唯一游戏化猎场，通关者才能分粮。肉贩子陈九斤要爬到第一百层，把留在塔里的兄弟一个个拆出来。',
  synopsis:
    '大灾变后，一座半透明的巨塔压在废墟城中央，塔里每天刷新异兽和资源。陈九斤是巷子里最不起眼的肉贩子，觉醒的异能「分肉」能把任何东西按纹理拆开。可越往上走，塔的规则越像在筛选：每过一层，就有队友被塔留下，变成下一层的看守。',
  theme: '把人和事都当零件算的人，最后要学会算「不划算」的那一笔。',
  targetChapters: 200,
  currentChapter: 68,
  wordsPerChapter: 2000,
  tone: '市井烟火 · 硬爽',
  gate: { phase: 'writing', chapter: 69, reason: '第68章已通过，开始写第69章', at: '2026-11-23 09:09' },
  updatedAt: '2026-11-23 09:11',
  spine: '陈九斤一路「最优拆分」正是塔筛选他的方式；他要在第一百层拆开的，是自己算账的那颗心。',
}

const hunting: Array<[number, string, number, boolean]> = [
  [1, '肉案当众拆甲', 2201, true],
  [2, '你给的价不够这壳的纹', 2104, true],
  [3, '塔门开的那声闷响', 2310, true],
  [4, '什么叫留下', 1988, true],
  [5, '一层不过就不分粮', 2050, true],
  [6, '老蔫儿的肉票', 2170, true],
  [7, '第一刀的纹理', 2240, true],
  [8, '岑守拙的小队', 2090, true],
  [9, '田有余放的话', 2130, true],
  [10, '骨架换粮', 2280, true],
  [11, '泼出去的那碗汤', 2005, true],
  [12, '验货开锣', 2210, true],
  [13, '墙根的旧账', 2090, true],
  [14, '接老二', 2150, true],
  [15, '腕上烙的账', 2260, false],
]

export const chapters: Chapter[] = hunting.map(([number, title, chars, approved]) => ({
  number,
  title,
  chars,
  summary: `第${number}章 · ${title}：陈九斤在肉巷与塔门之间周旋，用「分肉」拆开一层新的东西，同时欠下新的人情。`,
  characters: ['陈九斤', '老蔫儿', '岑守拙'],
  approved,
  verdict: '良',
  chapterVerdict: 'pass',
  fixReasons: [],
  endHook: { ok: true, reason: '意外动作收尾' },
  dialogueRatio: 0.26,
  searchText: `陈九斤 塔 猎场 第一百层 分肉 老蔫儿 岑守拙 ${title}`.repeat(3),
}))

export const segments: Segment[] = [
  {
    from: 1,
    to: 10,
    at: '2026-10-02T08:00:00.000Z',
    status: 'done',
    ...(() => {
      const spine = '肉贩子挤进塔门：本段只回答一个问题——「分肉」这种东西，在靠杀怪立身的塔里到底值不值一条命。'
      const stages: SegmentStage[] = [
      {
        chapters: [1, 2, 3],
        goal: '让陈九斤凭一手拆分从肉案走到塔门口',
        turn: '头目当场压价，他把壳纹拆给所有人看',
        foreshadow: { plant: ['壳纹易价的来路'], payoff: [] },
        pace: '紧',
        places: ['肉巷', '塔门'],
        cast: ['陈九斤', '老蔫儿'],
      },
      {
        chapters: [4, 5, 6, 7],
        goal: '让读者亲眼看一次「留下」',
        turn: '全队过了第一层，塔从队里拿走一个人',
        foreshadow: { plant: ['看守化的旧队友'], payoff: ['壳纹易价的来路'] },
        pace: '紧',
        places: ['塔内第一层'],
        cast: ['陈九斤', '岑守拙'],
      },
      {
        chapters: [8, 9, 10],
        goal: '陈九斤把五个人的杂牌队盘成第一笔生意',
        turn: '田有余放话，分配权成了新的战场',
        foreshadow: { plant: [], payoff: ['看守化的旧队友'] },
        pace: '平',
        places: ['粮站', '肉巷'],
        cast: ['陈九斤', '老蔫儿', '岑守拙'],
      },
      ]
      return { spine, stages: stages.length, plan: { from: 1, to: 10, spine, stages } }
    })(),
  },
  {
    from: 11,
    to: 20,
    at: '',
    status: 'writing',
    ...(() => {
      const spine = '账本上多出来的名字把陈九斤推到「主动换个兄弟上去」的门槛前——他第一次尝到赢也是输。'
      const stages: SegmentStage[] = [
      {
        chapters: [11, 12, 13],
        goal: '陈九斤发现账本上的名字比实际多出一个',
        turn: '多出来的名字不是塔写的，是活人补的',
        foreshadow: { plant: ['看守名录里缺的那一个名字'], payoff: ['塔根的刻痕'] },
        pace: '紧',
        places: ['肉巷', '塔门'],
        cast: ['陈九斤', '老蔫儿'],
      },
      {
        chapters: [14, 15, 16],
        goal: '把「多出来的人」逼到必须当面对质',
        turn: '对质时陈九斤才发现，自己早就算过这笔账',
        foreshadow: { plant: [], payoff: ['看守名录里缺的那一个名字'] },
        pace: '平',
        places: ['墙根', '旧水厂'],
        cast: ['陈九斤', '岑守拙'],
      },
      {
        chapters: [17, 18, 19, 20],
        goal: '陈九斤腕上烙下一个账，得到去第一百层的资格',
        turn: '他以为拿到了钥匙，钥匙背后写着「下一个留下谁」',
        foreshadow: { plant: ['手腕上等级旁的刻名'], payoff: [] },
        pace: '紧',
        places: ['塔内第一层', '塔门'],
        cast: ['陈九斤', '老蔫儿', '岑守拙'],
      },
      ]
      return { spine, stages: stages.length, plan: { from: 11, to: 20, spine, stages } }
    })(),
  },
]

export const characters: BibleCharacter[] = [
  ...signalChars.map((c) => ({ ...c })),
  { name: '陈九斤', role: '主角 · 肉贩子', identity: '肉巷肉摊伙计，异能「分肉」', want: '把留在塔里的兄弟拆出来', fear: '自己成为「留下别人」的那一个', secret: '他算过谁最该被留下', voice: '市井口吻，报价、讲理、不服软', status: 'active', appears: [1, 2, 3, 15], color: '#e0357f' },
  { name: '老蔫儿', role: '旧邻 · 后方', identity: '替陈九斤守摊的旧邻，管一条粮线', want: '肉摊别再被黑市拖垮', fear: '摊子没了人也就散了', secret: '替陈九斤扛过一笔不能再提的黑市债', voice: '话头一截一截，先说行情再说人', status: 'active', appears: [1, 6, 61], color: '#9a7b3f' },
  { name: '岑守拙', role: '杂牌队队长', identity: '把小队盘成底层招牌的人', want: '全队活着上一层', fear: '队里再有一个人被留下', secret: '早在第二层就知道「留下」的规律', voice: '拍板极快，只说结论', status: 'active', appears: [8, 65], color: '#2f5f8a' },
]

export const discarded = signalDiscarded.map((d, i) => ({ ...d, number: 68 - i }))
