<template>
  <section class="config-diff" aria-label="配置文本差异">
    <div class="diff-title"><strong>{{ leftLabel }} → {{ rightLabel }}</strong><span>新增 {{ diff.counts.added }} · 删除 {{ diff.counts.removed }} · 替换 {{ diff.counts.changed }}</span></div>
    <p v-if="differentDevices" class="diff-warning">A/B 属于不同设备；这里只对照文本，不能据此判断某台设备的变更或恢复。</p>
    <p class="diff-help">原始行号保留；替换表示两侧文本对照，不代表CLI已执行。{{ diff.hiddenCredentials ? '凭据行已隐藏，其内容变化无法由本视图判断。' : '' }}</p>
    <p v-if="diff.positional" class="diff-warning">差异区块较大，当前按位置对照；请结合 A/B 原文核对，不使用最简编辑计数。</p>
    <div class="diff-controls"><el-checkbox v-model="onlyChanges">仅看差异及相邻行</el-checkbox><el-checkbox v-model="ignoreFormatting">忽略空白与注释</el-checkbox><el-button @click="exportDisplay">导出可见差异</el-button></div>
    <p v-if="!displayRows.length">未见可展示的文本差异{{ diff.hiddenCredentials ? '；凭据字段无法判断' : '' }}。</p>
    <div v-else class="diff-scroll" tabindex="0" aria-label="差异行横向阅读区域">
      <table><colgroup><col class="line-number"><col><col class="line-number"><col></colgroup><thead><tr><th>A 行</th><th>{{ leftLabel }}</th><th>B 行</th><th>{{ rightLabel }}</th></tr></thead><tbody>
        <tr v-for="(row,index) in visibleRows" :key="index" :class="`diff-${row.kind}`"><td>{{ row.left?.number ?? '—' }}</td><td><small>{{ row.left?.context }}</small><code>{{ row.left?.text || (row.left ? '（空行）' : '—') }}</code></td><td>{{ row.right?.number ?? '—' }}</td><td><small>{{ row.right?.context }}</small><code>{{ row.right?.text || (row.right ? '（空行）' : '—') }}</code></td></tr>
      </tbody></table>
    </div>
    <el-button v-if="displayRows.length > shown" @click="shown += 1500">继续显示（{{ shown }} / {{ displayRows.length }} 行）</el-button>
    <details><summary>A / B 脱敏原文</summary><div class="source-grid"><pre>{{ diff.leftText }}</pre><pre>{{ diff.rightText }}</pre></div></details>
    <details v-if="legacy"><summary>原始差异 JSON（兼容旧接口）</summary><pre>{{ JSON.stringify(legacy,null,2) }}</pre></details>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { buildConfigDiff, configDiffContext } from '../utils/configTextDiff'
const props = withDefaults(defineProps<{left:string;right:string;leftLabel?:string;rightLabel?:string;differentDevices?:boolean;legacy?:unknown}>(),{leftLabel:'配置 A',rightLabel:'配置 B',differentDevices:false})
const onlyChanges=ref(true),ignoreFormatting=ref(true),shown=ref(1500)
const diff=computed(()=>buildConfigDiff(props.left,props.right,ignoreFormatting.value))
const displayRows=computed(()=>onlyChanges.value?configDiffContext(diff.value.rows):diff.value.rows)
const visibleRows=computed(()=>displayRows.value.slice(0,shown.value))
watch(()=>[props.left,props.right,onlyChanges.value,ignoreFormatting.value],()=>{shown.value=1500})
const exportDisplay=()=>{
  const text=JSON.stringify({left:props.leftLabel,right:props.rightLabel,scope:'display_text_only',positional:diff.value.positional,credentials_hidden:diff.value.hiddenCredentials,counts:diff.value.counts,rows:diff.value.rows},null,2)
  const url=URL.createObjectURL(new Blob([text],{type:'application/json;charset=utf-8'})),link=document.createElement('a');link.href=url;link.download='config-visible-diff.json';link.click();URL.revokeObjectURL(url)
}
</script>
<style scoped>
.config-diff{margin:16px 0;min-width:0;color:var(--v7b-text)}.diff-title,.diff-controls{display:flex;gap:14px;align-items:center;justify-content:space-between;flex-wrap:wrap}.diff-controls{justify-content:flex-start;margin:10px 0}.diff-title strong{overflow-wrap:anywhere}.diff-title span,.diff-help{color:var(--v7b-muted);font-size:12px;line-height:1.7}.diff-warning{color:#87571d;font-size:13px}.diff-scroll{max-height:460px;overflow:auto;border:1px solid var(--v7b-line)}table{border-collapse:collapse;min-width:740px;width:100%;font-size:12px}th,td{border:1px solid var(--v7b-line);padding:7px 9px;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#edf3fa;z-index:1}td:nth-child(1),td:nth-child(3){width:48px;color:#627187;text-align:right}code{display:block;white-space:pre;min-width:260px;font-family:Consolas,monospace;line-height:1.7}small{display:block;color:#687891;margin-bottom:4px}.diff-added{background:#eff8f2}.diff-removed{background:#fff1f0}.diff-changed{background:#fff7e7}details{margin-top:12px}summary{color:var(--v7b-accent);cursor:pointer}.source-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}pre{background:#f4f7fb;padding:10px;max-height:300px;overflow:auto;white-space:pre;font-size:12px;line-height:1.7}.diff-controls :deep(.el-checkbox__label){color:var(--v7b-muted)}@media(max-width:750px){.source-grid{grid-template-columns:minmax(0,1fr)}}
table{table-layout:fixed}.line-number{width:48px}th{overflow-wrap:anywhere}code{white-space:pre-wrap;overflow-wrap:anywhere;min-width:0}
</style>
