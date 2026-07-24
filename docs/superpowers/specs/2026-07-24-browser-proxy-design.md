# 浏览器代理配置设计

## 目标

参考 `.tmp/app.py` 的代理配置方式，为 `icehost_run.py` 中的 SeleniumBase 浏览器增加可选代理支持，同时保持默认直连行为以及现有的 UC、Xvfb、Cookie 注入和 Cloudflare 重连逻辑不变。

## 配置接口

使用以下环境变量：

- `IS_PROXY`：代理开关。仅当值忽略大小写后等于 `true` 时启用代理，默认值为 `false`。
- `S5_PROXY`：首选代理地址。
- `PROXY_SERVER`：备用代理地址。

代理地址读取优先级为：

1. `S5_PROXY`
2. `PROXY_SERVER`
3. `socks://127.0.0.1:1080`

## 实现设计

在 `run()` 中创建 SeleniumBase 启动参数字典，保留现有的 `uc=True` 和 `xvfb=True`。当 `IS_PROXY=true` 时，将解析出的代理地址写入 `proxy` 参数，再通过 `SB(**sb_options)` 启动浏览器；否则不传入 `proxy` 参数，保持直连。

启动时输出当前是否启用代理。为避免泄露带认证信息的代理凭据，日志不输出完整代理地址，只说明代理已启用或当前使用直连。

## 数据流

1. 读取 `IS_PROXY`。
2. 按优先级读取代理地址。
3. 构造 SeleniumBase 启动参数。
4. 根据开关决定是否加入 `proxy` 参数。
5. 使用最终参数启动 SeleniumBase。
6. 继续执行现有面板访问、Cookie 注入、续期和 Cookie 导出流程。

## 错误处理

- 未设置 `IS_PROXY` 时默认直连。
- `IS_PROXY=true` 但未提供代理地址时，沿用参考实现的本地默认地址 `socks://127.0.0.1:1080`；若该代理不可用，浏览器访问将按 SeleniumBase 现有异常路径失败。
- 不新增代理连通性预检，避免引入额外网络请求和依赖。
- 不记录可能包含用户名或密码的完整代理 URL。

## 验证

1. 运行 Python 语法编译检查。
2. 未设置 `IS_PROXY` 时，确认构造的参数不包含 `proxy`。
3. 设置 `IS_PROXY=true` 和 `S5_PROXY` 时，确认优先使用 `S5_PROXY`。
4. 未设置 `S5_PROXY`、设置 `PROXY_SERVER` 时，确认使用 `PROXY_SERVER`。
5. 确认现有 `uc=True`、`xvfb=True`、Cookie 注入及 Cloudflare 重连代码未被改变。

## 范围限制

本次只修改 `icehost_run.py` 的浏览器启动配置，不修改 GitHub Actions Secret、工作流触发条件、代理服务部署方式或其他业务逻辑。
