import type { NewsItem } from '../types'

/** 每个分类 Tab 独立缓存一份视图状态（含其搜索条件），按标签切换回来时立即恢复。 */
export interface NewsViewCache {
  items: NewsItem[]
  total: number
  page: number
  finished: boolean
  search: string
}

// 分类 → 缓存。模块级作用域：NewsView 切换 Tab 会被卸载，Map 让缓存跨组件存活（会话内有效）。
const cacheMap = new Map<string, NewsViewCache>()
// 最后浏览的分类：Tab 整体切走再切回时，恢复到该分类
let lastCategory = '全部'

export function getNewsViewCache(category: string): NewsViewCache | null {
  const c = cacheMap.get(category)
  return c ? { ...c, items: c.items.slice() } : null
}

export function setNewsViewCache(category: string, next: NewsViewCache) {
  cacheMap.set(category, { ...next, items: next.items.slice() })
}

export function getLastCategory(): string {
  return lastCategory
}

export function setLastCategory(c: string) {
  lastCategory = c
}

/**
 * 静默更新时对比「当前第一页」与「最新第一页」做局部合并：
 * - 新增（最新热点）：插到最前
 * - 字段变化（热度分/摘要/标题等）：原地替换为新值
 * - 已消失条目：先保留（避免列表闪动）
 * 返回 small=true 表示变化小（局部刷新即可），false 表示变化大（应整体替换）。
 */
export function mergeNewsDiff(
  current: NewsItem[],
  fresh: NewsItem[],
): { items: NewsItem[]; small: boolean } {
  const freshById = new Map(fresh.map((i) => [i.id, i]))
  const currentIds = new Set(current.map((i) => i.id))

  let added = 0
  let changed = 0
  const merged: NewsItem[] = []

  for (const it of current) {
    const f = freshById.get(it.id)
    if (!f) {
      merged.push(it) // 排名掉出/已下线：先保留，避免闪动
      continue
    }
    const dirty =
      f.hot_score !== it.hot_score ||
      f.title !== it.title ||
      f.summary !== it.summary ||
      f.source !== it.source ||
      f.published_at !== it.published_at ||
      f.image_url !== it.image_url
    if (dirty) {
      changed++
      merged.push(f)
    } else {
      merged.push(it) // 无变化：保留原引用，避免多余重渲染
    }
  }
  for (const it of fresh) {
    if (!currentIds.has(it.id)) {
      added++
      merged.unshift(it) // 最新热点插到最前
    }
  }

  // 小变更判定：Jaccard 重叠率（新增/移除都会拉低重叠率）≥ 0.7 视为小变更。
  // 交集 = fresh 里与当前重叠的数量；并集 = fresh + 被移除的旧条目。
  const removed = current.length - (fresh.length - added)
  const union = fresh.length + removed
  const overlap = union ? (fresh.length - added) / union : 1
  const small = overlap >= 0.7
  return { items: merged, small }
}
