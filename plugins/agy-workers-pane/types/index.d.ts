export type AgyRow = {
  id: string
  title: string
  model: string
  startedAt: number
  lastEventAt: number | null
  tools: number
  steps: number
  output: number
  cached: number
  input: number
}

declare module 'claude-code' {
  interface PluginState {
    'agy-workers': { rows: AgyRow[] }
  }
}
