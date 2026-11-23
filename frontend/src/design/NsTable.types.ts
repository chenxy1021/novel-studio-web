export type Column<T = Record<string, unknown>> = {
  key: string
  label: string
  width?: string
  align?: 'left' | 'right' | 'center'
  numeric?: boolean
  render?: (row: T) => string
}
