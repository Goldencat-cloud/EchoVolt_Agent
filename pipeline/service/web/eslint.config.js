// ESLint 平面配置（8.1）。首次使用：npm install 后 `npm run lint`。
// 关注正确性与安全（未转义注入），不引入风格规则——风格交给 Prettier。
export default [
  {
    files: ["*.js", "tests/*.mjs"],
    ignores: ["node_modules/**", "test-results/**"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        // 浏览器运行时（app.js 为传统脚本，依赖全局 DOM API）
        window: "readonly", document: "readonly", localStorage: "readonly",
        crypto: "readonly", fetch: "readonly", URL: "readonly", Blob: "readonly",
        setTimeout: "readonly", clearTimeout: "readonly", console: "readonly",
        Event: "readonly", KeyboardEvent: "readonly", getComputedStyle: "readonly",
        location: "readonly", history: "readonly", navigator: "readonly",
        CustomEvent: "readonly", FormData: "readonly",
      },
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["warn", { args: "none", caughtErrors: "none" }],
      "no-implicit-globals": "error",
      "no-eval": "error",
      "no-new-func": "error",
      "script-url": "off",
      eqeqeq: ["error", "smart"],
      "prefer-const": "warn",
      "no-var": "error",
      "no-throw-literal": "error",
    },
  },
];
