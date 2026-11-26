import type { Book, BibleCharacter, Chapter, Segment, SegmentStage } from './types'
import { book as mail, characters as mailChars, discarded as mailDiscarded } from './demoMail'

// 第二本演示书：完全虚构，只负责把「已写很多章、正在写下一批」的状态跑出来。
export const book: Book = {
  ...mail,
  dir: '~/novel-studio/demo/night-market',
  title: '夜市最后一摊',
  genre: '市井 · 美食 · 群像',
  logline: '老夜市月底拆迁，最后一摊的掌勺人想守住一口老灶，却发现整条街的摊主都在等他先说散。',
  synopsis:
    '临江夜市长街要改造成步行街，摊主们被通知月底清场。林小满接下父亲留下的最后一摊「小满夜宵」，本想靠这一个月攒够搬迁费，却发现老主顾、隔壁摊和收租的人都在等他说一句「散了吧」。',
  theme: '守着一口灶的人，最后要学会把火种分出去。',
  targetChapters: 120,
  currentChapter: 15,
  wordsPerChapter: 2000,
  tone: '烟火气 · 轻喜 · 群像',
  gate: { phase: 'writing', chapter: 16, reason: '第15章已通过，开始写第16章', at: '2026-11-23 09:09' },
  updatedAt: '2026-11-23 09:11',
  spine: '林小满想把「小满夜宵」原样搬走，代价是他得先承认，摊子早就不是父亲那一口灶了。',
}

const market: Array<[number, string, number, boolean]> = [
  [1, '最后一锅汤', 2201, true],
  [2, '你这个价不对', 2104, true],
  [3, '长街要亮灯', 2310, true],
  [4, '谁先签字', 1988, true],
  [5, '一碗不给钱', 2050, true],
  [6, '赵叔的炭', 2170, true],
  [7, '第一口老灶', 2240, true],
  [8, '阿青的账', 2090, true],
  [9, '陈婆婆的碗', 2130, true],
  [10, '最后一笔进货', 2280, true],
  [11, '泼出去的那碗汤', 2005, true],
  [12, '验货开锣', 2210, true],
  [13, '墙根的旧账', 2090, true],
  [14, '接老二', 2150, true],
  [15, '火种', 2260, false],
]

export const chapters: Chapter[] = market.map(([number, title, chars, approved]) => ({
  number,
  title,
  chars,
  summary: `第${number}章 · ${title}：林小满在长街与灶台之间周旋，用一锅夜宵换一次谈判，同时欠下新的人情。`,
  characters: ['林小满', '赵叔', '阿青'],
  approved,
  verdict: '良',
  chapterVerdict: 'pass',
  fixReasons: [],
  endHook: { ok: true, reason: '意外动作收尾' },
  dialogueRatio: 0.26,
  searchText: `林小满 长街 夜市 老灶 赵叔 阿青 陈婆婆 ${title}`.repeat(3),
}))

export const segments: Segment[] = [
  {
    from: 1,
    to: 10,
    at: '2026-10-02T08:00:00.000Z',
    status: 'done',
    ...(() => {
      const spine = '掌勺人接下最后一摊：本段只回答一个问题——这口老灶，在一条要拆的街上到底值不值得留下。'
      const stages: SegmentStage[] = [
        {
          chapters: [1, 2, 3],
          goal: '让林小满从「替父亲看摊」走到「自己决定开不开火」',
          turn: '管委会当天贴出清场通知，他把第一锅汤照样烧开',
          foreshadow: { plant: ['旧搪瓷碗的来路'], payoff: [] },
          pace: '紧',
          places: ['小满夜宵', '长街口'],
          cast: ['林小满', '赵叔'],
        },
        {
          chapters: [4, 5, 6, 7],
          goal: '让读者亲眼看一次「街坊怎么选」',
          turn: '先签字的摊主拿到新位置，长街第一次分成两拨人',
          foreshadow: { plant: ['陈婆婆碗底的旧门牌'], payoff: ['旧搪瓷碗的来路'] },
          pace: '紧',
          places: ['长街中段', '赵叔烧烤摊'],
          cast: ['林小满', '赵叔'],
        },
        {
          chapters: [8, 9, 10],
          goal: '林小满把账摊开，发现摊子早就不赚钱',
          turn: '阿青的流水和陈婆婆的碗把「留下」变成一笔算不清的账',
          foreshadow: { plant: [], payoff: ['陈婆婆碗底的旧门牌'] },
          pace: '平',
          places: ['小满夜宵', '长街墙根'],
          cast: ['林小满', '赵叔', '阿青'],
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
      const spine = '清场前最后一个月，林小满第一次主动把摊子交出去——他尝到「散了也能活」的滋味。'
      const stages: SegmentStage[] = [
        {
          chapters: [11, 12, 13],
          goal: '林小满发现清场表上的摊位号比实际多出一个',
          turn: '多出来的摊位不是管委会写的，是老摊主自己补的',
          foreshadow: { plant: ['清场表上缺的那一个摊号'], payoff: ['墙根的旧账'] },
          pace: '紧',
          places: ['长街口', '管委会临时棚'],
          cast: ['林小满', '赵叔'],
        },
        {
          chapters: [14, 15, 16],
          goal: '把「多出来的摊」逼到必须当面对质',
          turn: '对质时林小满才发现，父亲当年也算过这笔账',
          foreshadow: { plant: [], payoff: ['清场表上缺的那一个摊号'] },
          pace: '平',
          places: ['长街墙根', '旧码头'],
          cast: ['林小满', '马管理员'],
        },
        {
          chapters: [17, 18, 19, 20],
          goal: '林小满把老灶的火种分给整条街，换回一次重新开火的机会',
          turn: '他以为交出去的是灶，接回来的是一整条街的摊',
          foreshadow: { plant: ['每家灶台上留一勺老汤'], payoff: [] },
          pace: '紧',
          places: ['长街中段', '新夜市'],
          cast: ['林小满', '赵叔', '阿青'],
        },
      ]
      return { spine, stages: stages.length, plan: { from: 11, to: 20, spine, stages } }
    })(),
  },
]

type CastSeed = Partial<BibleCharacter> & Pick<BibleCharacter, 'name' | 'role' | 'identity' | 'want' | 'fear' | 'secret' | 'voice' | 'status' | 'appears' | 'color'>
const cast = (c: CastSeed): BibleCharacter => ({
  aliases: [], importance: '', tier: '', gender: '', age: '', race: '', personality: '',
  appearance: '', bottomLine: '', flaw: '', ability: '', abilityLimit: '', abilityCost: '',
  location: '', locationAt: 0, locationHistory: [], currentGoal: '', knowledge: '',
  ignorance: '', misconception: '', changeLog: '', appearanceStatus: '', finalStatus: '', statusLog: [],
  firstChapter: 0, exitChapter: 0, ...c,
})

export const characters: BibleCharacter[] = [
  ...mailChars.map((c) => ({ ...c })),
  cast({ name: '林小满', role: '主角 · 掌勺人', identity: '「小满夜宵」的二代摊主，父亲留下的老灶只认他掌火', want: '把摊子原样搬进新夜市', fear: '自己成为最后一个关火的人', secret: '他早算过搬迁费不够', voice: '市井口吻，先报菜价再讲道理，不服软', status: 'active', appears: [1, 2, 3, 15], color: '#e0357f' }),
  cast({ name: '赵叔', role: '隔壁摊主 · 后方', identity: '长街烧烤摊主，替林小满盯着后半夜的炉子', want: '长街散了以后还有地方摆摊', fear: '摊没了，人就散了', secret: '替林小满扛过一笔不能再提的赊账', voice: '话头一截一截，先说行情再说人', status: 'active', appears: [1, 6, 61], color: '#9a7b3f' }),
  cast({ name: '阿青', role: '帮工 · 账房', identity: '在小满夜宵帮工三年，管着流水和进货', want: '把摊子的账算明白', fear: '账算明白了，人也就散了', secret: '早在第三个月就知道摊子不赚钱', voice: '拍板极快，只说数字', status: 'active', appears: [8, 65], color: '#2f5f8a' }),
  cast({ name: '马管理员', role: '长街管委会 · 清场人', identity: '拿着清场表挨家谈条件的人', want: '月底前把长街清空', fear: '最后一户不签', secret: '清场表上有一个摊号是他自己补的', voice: '客套话在前，期限藏在第二句', status: 'active', appears: [4, 10], color: '#2f7d5b' }),
  cast({ name: '陈婆婆', role: '老主顾 · 见证者', identity: '在长街吃了三十年夜宵的老人，家里收着一只旧搪瓷碗', want: '再吃一次父亲那一锅汤', fear: '没人记得长街原来的样子', secret: '碗底刻着长街旧门牌', voice: '话少，先吃一口再开口', status: 'active', appears: [5, 9], color: '#b4232c' }),
]

export const discarded = mailDiscarded.map((d, i) => ({ ...d, number: 15 - i }))
