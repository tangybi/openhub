/** 前端 Agent Tab 定义（图标在本页登记，可用性以后端 /api/agents 为准）。 */
export const AGENT_TABS = [
  { name: 'news', label: '热点新闻', icon: '🔥' },
  { name: 'paste', label: 'Pastebin', icon: '📋' },
  { name: 'finance', label: '金融分析', icon: '📈' },
  { name: 'brand', label: '品牌竞品', icon: '🏷️' },
  { name: 'learning', label: '学习', icon: '🎓' },
]

export function agentIcon(name: string): string {
  return AGENT_TABS.find((t) => t.name === name)?.icon ?? '🤖'
}
