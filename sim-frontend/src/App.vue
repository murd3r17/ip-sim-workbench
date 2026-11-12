<template>
  <el-config-provider :locale="zhCn">
    <router-view />
  </el-config-provider>
</template>

<script setup lang="ts">
import { ElConfigProvider } from 'element-plus/es/components/config-provider/index'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
</script>

<style>
html:root {
  /* 组件及传送到 body 的弹层共用同一浅色主题，侧栏和终端自行定义深色。 */
  color-scheme: light;
  --el-bg-color: var(--v7b-surface);
  --el-bg-color-page: var(--v7b-bg);
  --el-bg-color-overlay: var(--v7b-surface);
  --el-fill-color: #edf1f5;
  --el-fill-color-light: var(--v7b-surface-2);
  --el-fill-color-lighter: #fafbfd;
  --el-fill-color-extra-light: #fcfdfe;
  --el-fill-color-blank: var(--v7b-surface);
  --el-fill-color-dark: #e5ebf1;
  --el-fill-color-darker: #d9e2eb;
  --el-text-color-primary: var(--v7b-text);
  --el-text-color-regular: var(--v7b-muted);
  --el-text-color-secondary: var(--v7b-muted);
  --el-text-color-placeholder: #697989;
  --el-border-color: var(--v7b-line-strong);
  --el-border-color-light: var(--v7b-line);
  --el-border-color-lighter: #e7edf3;
  --el-border-color-extra-light: #eff3f7;
  --el-mask-color: rgba(23, 35, 49, 0.45);
  --el-color-primary: var(--v7b-accent);
  --el-color-primary-light-3: #316db3;
  --el-color-primary-light-5: #a3bfdf;
  --el-color-primary-light-7: #c8daed;
  --el-color-primary-light-8: #dbe7f4;
  --el-color-primary-light-9: #edf3fa;
  --el-color-primary-dark-2: #255994;
  --el-color-success: var(--v7b-ok);
  --el-color-success-light-3: #22764b;
  --el-color-success-light-5: #8dbfa6;
  --el-color-success-light-7: #c4dfd0;
  --el-color-success-light-8: #dceee4;
  --el-color-success-light-9: #eef8f2;
  --el-color-success-dark-2: #13613b;
  --el-color-warning: var(--v7b-warn);
  --el-color-warning-light-3: #936000;
  --el-color-warning-light-5: #d1ad66;
  --el-color-warning-light-7: #e7d3aa;
  --el-color-warning-light-8: #f0e3c9;
  --el-color-warning-light-9: #fff8e8;
  --el-color-warning-dark-2: #7b5000;
  --el-color-danger: var(--v7b-danger);
  --el-color-danger-light-3: #ba352b;
  --el-color-danger-light-5: #d9948e;
  --el-color-danger-light-7: #ecc4c1;
  --el-color-danger-light-8: #f3dcda;
  --el-color-danger-light-9: #fff1f0;
  --el-color-danger-dark-2: #901c13;
  --el-color-info: var(--v7b-muted);
  --el-color-info-light-3: #5d6b79;
  --el-color-info-light-5: #abb4bd;
  --el-color-info-light-7: #d2d9e0;
  --el-color-info-light-8: #e3e8ee;
  --el-color-info-light-9: #f1f4f7;
  --el-color-info-dark-2: #424d57;
  --el-table-bg-color: var(--v7b-surface);
  --el-table-tr-bg-color: var(--v7b-surface);
  --el-table-header-bg-color: #f5f8fb;
  --el-table-row-hover-bg-color: #f1f6fb;
  --el-table-border-color: var(--v7b-line);
  --el-table-text-color: var(--v7b-text);
  --el-table-header-text-color: var(--v7b-muted);
}
html, body, #app { width: 100%; min-width: 320px; min-height: 100%; margin: 0; }
body { overflow: hidden; background: var(--v7b-bg); color: var(--v7b-text); }
.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell {
  background: var(--v7b-surface-2);
}
*, *::before, *::after { box-sizing: border-box; }
button, input, select, textarea { font: inherit; letter-spacing: 0; }

/* Thin scrollbars (Chrome/Edge + Firefox) */
* {
  scrollbar-width: thin;
  scrollbar-color: #3a4d5f transparent;
}
*::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
*::-webkit-scrollbar-track {
  background: transparent;
}
*::-webkit-scrollbar-thumb {
  background: #3a4d5f;
  border-radius: 999px;
  border: 1px solid transparent;
  background-clip: padding-box;
}
*::-webkit-scrollbar-thumb:hover {
  background: #4d6478;
  background-clip: padding-box;
}
*::-webkit-scrollbar-corner {
  background: transparent;
}
</style>
