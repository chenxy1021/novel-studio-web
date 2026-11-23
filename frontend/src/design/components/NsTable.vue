<script setup lang="ts" generic="T">
import type { Column } from '../NsTable.types'

withDefaults(
  defineProps<{
    columns: Column<T>[]
    rows: T[]
    rowKey?: string
    dense?: boolean
    striped?: boolean
    clickable?: boolean
  }>(),
  { rowKey: '', dense: false, striped: false, clickable: false },
)
defineEmits<{ rowClick: [row: T] }>()

function field(row: T, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}

function cell(row: T, col: Column<T>): unknown {
  return col.render ? col.render(row) : field(row, col.key)
}
</script>

<template>
  <div class="ns-table-wrap" :class="{ 'ns-table-wrap--clickable': clickable }">
    <table class="ns-table" :class="{ 'ns-table--dense': dense, 'ns-table--striped': striped }">
      <thead>
        <tr>
          <th
            v-for="col in columns"
            :key="col.key"
            :style="{ width: col.width, textAlign: col.align ?? (col.numeric ? 'right' : 'left') }"
            scope="col"
          >
            {{ col.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="(row, i) in rows" :key="rowKey ? String(field(row, rowKey)) : i" @click="$emit('rowClick', row)">
          <td
            v-for="col in columns"
            :key="col.key"
            :class="{ 'ns-num': col.numeric }"
            :style="{ textAlign: col.align ?? (col.numeric ? 'right' : 'left') }"
          >
            <slot :name="`cell:${col.key}`" :row="row" :value="cell(row, col)">
              {{ cell(row, col) }}
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.ns-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--ns-line);
  border-radius: var(--ns-r-md);
  background: var(--ns-card);
}
.ns-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--ns-fs-13);
}
.ns-table th {
  text-align: left;
  font-size: var(--ns-fs-11);
  font-weight: 600;
  letter-spacing: 0.02em;
  color: var(--ns-ink-3);
  background: var(--ns-card-2);
  padding: 8px 12px;
  border-bottom: 1px solid var(--ns-line);
  white-space: nowrap;
}
.ns-table td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--ns-line);
  vertical-align: top;
  color: var(--ns-ink-2);
}
.ns-table tr:last-child td {
  border-bottom: 0;
}
.ns-table--dense td {
  padding: 6px 10px;
}
.ns-table--dense th {
  padding: 6px 10px;
}
.ns-table--striped tbody tr:nth-child(even) {
  background: color-mix(in srgb, var(--ns-card-2) 55%, transparent);
}
.ns-table-wrap--clickable tbody tr {
  cursor: pointer;
}
.ns-table-wrap--clickable tbody tr:hover {
  background: var(--ns-card-2);
}
</style>
