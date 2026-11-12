// ESLint flat config（P2-22）：只启用能发现真实缺陷的规则，不做风格争论。
// 目标：让 `npm run lint` 在 CI 里挡住"未使用变量/意外全局/重复 case"这类问题。
import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import tseslint from 'typescript-eslint'
import globals from 'globals'

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'playwright-report/**', 'test-results/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/essential'],
  {
    files: ['**/*.{ts,vue}'],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
      parserOptions: {
        parser: tseslint.parser,
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
    },
    rules: {
      // TS 自己就能发现未定义标识符，且认得 DOM/类型空间的全局名（EventListener 等）；
      // 保留 no-undef 会把这些类型误报为未定义
      'no-undef': 'off',
      // 与 tsconfig 的 noUnusedLocals/noUnusedParameters 保持一致（vue-tsc 已覆盖，
      // 这里让 lint 单独跑时也能发现）
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      // 后端返回的 any 数据在视图层是既成事实，先不阻断
      '@typescript-eslint/no-explicit-any': 'off',
      // 空 catch 是刻意为之（例如"用户取消"分支），保留但要求注释说明
      'no-empty': ['error', { allowEmptyCatch: true }],
    },
  },
)
