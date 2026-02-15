# React2Shell (CVE-2025-55182) 漏洞完整复现说明

本文档面向无安全/React 背景的读者，从漏洞是什么、为什么能利用、到如何在本仓库（homepage 项目）中一步步复现，均做详细说明。

---

## 怎么跑复现（快速）

在 **homepage 项目根目录** 执行：

```bash
./run_react2shell_repro.sh
```

脚本会：安装依赖 → 释放 3011 端口 → 启动 Next.js dev（`-p 3011`）→ 等约 45 秒 → 对首页 `POST /` 打 POC。成功会看到 `[+] 命令输出: <用户名>`，退出时自动杀掉占 3011 的进程。

- 换端口：`PORT=3012 ./run_react2shell_repro.sh`
- 手动：先 `npm run dev -- -p 3011`，等就绪后另开终端执行  
  `python3 scripts/react2shell_poc.py --url http://localhost:3011 --cmd whoami`

---

## 一、漏洞简介

- **CVE 编号**：CVE-2025-55182（Next.js 侧相关缓解见 CVE-2025-66478）  
- **俗称**：React2Shell  
- **披露时间**：2025 年 12 月初  
- **危害**：在满足一定条件下，攻击者可通过单次恶意 HTTP 请求在服务器上执行任意 JavaScript，进而执行任意命令（RCE），无需认证。  
- **根本原因**：React Server Components (RSC) 使用的 **Flight 协议**在服务端反序列化时，未对“属性解析”做限制，攻击者可通过精心构造的 payload 污染原型链，使 `response._formData.get` 等被替换为 `Function` 构造函数，从而执行 `Function(恶意代码)`，实现 RCE。

---

## 二、必要背景知识（帮助理解“完整链路”）

### 2.1 React Server Components 与 Flight 协议

- **React Server Components (RSC)**（React 19 起）允许部分组件只在服务端运行，结果通过序列化传给客户端。  
- 服务端与客户端之间用 **React Flight** 协议传输：服务端把组件树序列化成一种带特殊标记的格式（如 `$@` 引用、`$B` Blob 等），客户端再反序列化并渲染。  
- 当使用 **Server Action**（表单调用的服务端函数）时，Next.js 会接收带 `Next-Action` 头的 POST，请求体为 multipart，其中包含 Flight 格式的 payload，服务端会**反序列化**这些数据。

### 2.2 Flight 反序列化中的“属性路径”

- Flight 解码时会根据引用（如 `$1:constructor:constructor`）解析对象属性。  
- 解析时使用类似 `obj[key]` 的访问方式，会沿 **原型链** 查找，未限制“只能访问自身属性”。  
- 因此攻击者可以构造引用，使解码逻辑访问到 `constructor.constructor`，即 JavaScript 的 **Function** 构造函数。

### 2.3 Blob 分支与 `_formData.get`

- 在 Flight 服务端代码（如 `react-server-dom-webpack`）中，处理 `$B`（Blob）引用时会执行类似：  
  `response._formData.get(response._prefix + id)`  
- 若通过伪造的 Chunk 对象，把 `_formData.get` 污染成 **Function**，把 `_prefix` 污染成**恶意 JS 字符串**，则上述调用会变成：  
  `Function(恶意字符串 + id)()`  
- 即**动态构造并执行函数**，恶意字符串里可写 `require('child_process').execSync('whoami')` 等，实现 RCE。

### 2.4 为何“纯客户端 React”不受影响

- 漏洞出在**服务端**对 Flight payload 的**反序列化**逻辑中。  
- 仅使用客户端 React、无 RSC/Server Action 的应用不会处理此类 payload，故不受影响。  
- 本复现通过在本项目中启用 **Next.js App Router** 和 **Server Action**，使 Next.js 在收到 `Next-Action` 请求时走 RSC 解码路径，从而触发漏洞。

---

## 三、漏洞完整利用链路（从一次请求到 RCE）

1. **攻击者向“挂载了 Server Action 的页面”发送恶意 POST**  
   - 目标：本复现中为 **POST /**（项目**首页**由 App Router 根页面渲染，复用 `pages/index.jsx` 的组件与数据，仅在此挂载 `action={noop}` 的 form，注册 Server Action）。  
   - 请求头：`Next-Action: x`，`Content-Type: multipart/form-data; boundary=...`  
   - 请求体（multipart part `"0"`）为一段**伪造的 Flight Chunk**，其中：  
     - `then`、`status`、`value` 等模仿 RSC 的 Chunk 结构，诱导服务端进入 Blob 处理分支。  
     - `_response._formData.get` 通过引用设为 **`$1:constructor:constructor`**（解析后得到 Function）。  
     - `_response._prefix` 设为**恶意 JS 字符串**，例如：  
       `var res=process.mainModule.require('child_process').execSync('whoami').toString().trim();throw Object.assign(new Error('NEXT_REDIRECT'), {digest:res});`  
       这样既执行了命令，又把结果塞进 `NEXT_REDIRECT` 的 `digest`，便于在响应中回显。

2. **Next.js 将请求交给 RSC/Server Action 处理**  
   - 识别到 `Next-Action` 和 multipart 体后，进入 Flight 解码流程。  
   - 解码器处理伪造的 Chunk，解析 `$B1337` 等引用时，会执行 `response._formData.get(response._prefix + obj)`。

3. **原型链污染导致 `get` → Function、`_prefix` → 恶意代码**  
   - 因反序列化时按“属性路径”解析，攻击者已把 `_formData.get` 指向 `Function`，`_prefix` 指向上述恶意字符串。  
   - 实际执行变为：**Function(恶意字符串 + "1337")()**，即执行 `execSync('whoami')` 等，并把结果放入 `digest`。

4. **服务端抛出带 `digest` 的 NEXT_REDIRECT 错误**  
   - 恶意代码中 `throw Object.assign(new Error('NEXT_REDIRECT'), {digest:res})` 被 Next 捕获，返回 500 且响应体中含有 `"digest":"命令输出"`。

5. **攻击者从响应中读取命令执行结果（RCE 完成）**  
   - POC 解析响应中的 `"digest":"..."`，打印出 `whoami` 等命令的输出。

**小结**：  
- 漏洞本质 = **Flight 反序列化时未限制属性解析** + **原型链污染** + **Blob 分支中 `_formData.get(_prefix+id)` 被滥用于 Function(恶意代码)**。  
- 利用链：**恶意 POST（伪造 Flight Chunk）→ Next 进入 RSC 解码 → 污染 _formData.get / _prefix → 执行 Function(恶意代码) → 命令执行结果通过 digest 回显**。

---

## 四、受影响条件（必须同时满足）

| 条件 | 说明 |
|------|------|
| React 版本 | 19.0.0、19.1.0、19.1.1、**19.2.0**（本仓库在复现时固定为 19.2.0） |
| 使用 RSC 的包 | `react-server-dom-webpack` / `react-server-dom-parcel` / `react-server-dom-turbopack` 等对应上述版本 |
| Next.js 版本 | 15.0.x 未打补丁版本（本复现使用 **15.0.3**）；15.0.5+、15.5.7+ 等已修复） |
| 部署方式 | 使用 **App Router** 且存在会处理 `Next-Action` 的 Server Action（或等效 RSC 请求） |
| 接口可访问性 | 攻击者能对“挂载了 Server Action 的页面”发起 POST（本复现为项目首页 **/**） |

---

## 五、本仓库复现环境说明

- **项目**：homepage（Next.js 前端项目），复现**基于项目本身的首页**：原为 Pages Router（`src/pages/index.jsx`），为触发 RSC 解码路径，增加 App Router 根页面并**复用同一套首页组件与数据**，仅在该页挂载 Server Action。  
- **为何这样复现**：  
  - homepage 本身只有 Pages Router，无 Server Action，**天然不经过 Flight 解码**；  
  - 用 **App Router 接管根路径 `/`**，`src/app/page.js` 调用 `pages/index.jsx` 的 `getStaticProps` 与 `Index` 组件，首页内容与原先一致；  
  - 在根页面挂一个隐藏的 `form action={noop}`，使 **POST /** 进入 RSC 解码，复现的是「对项目首页发恶意请求」而非单独造一个无关页面。  
- **复现相关文件**：  
  - **package.json**：`react` / `react-dom` 固定为 19.2.0，`next` / `eslint-config-next` 固定为 15.0.3（仅复现用）。  
  - **src/app/layout.js**、**src/app/page.js**、**src/app/actions.js**：App Router 根页面渲染真实首页（`Index` + `getStaticProps`），并挂 Server Action，使 **POST /** 接受 Next-Action。  
  - **scripts/react2shell_poc.py**：向 **/** 发送恶意 POST，从响应中解析 `digest`。  
  - **run_react2shell_repro.sh**：一键安装、启动（端口 3011）、执行 POC、退出时清理进程。

---

## 六、复现前准备（环境与依赖）

### 6.1 本机需要安装

- **Node.js**（建议 18+）：用于运行 Next.js 与 npm/pnpm。  
- **npm 或 pnpm**：安装依赖；项目原配置为 pnpm，脚本在无 pnpm 时会用 `npm install --ignore-scripts`。  
- **Python 3** 及 **requests**：用于运行 `scripts/react2shell_poc.py`。

### 6.2 本仓库为复现已做的修改（了解即可）

- **package.json**：  
  - `react` / `react-dom` 固定为 **19.2.0**；  
  - `next` / `eslint-config-next` 固定为 **15.0.3**（有洞版本）。  
- **src/app/**：新增 App Router 根页面（`page.js` 复用 `pages/index.jsx` 的首页），并挂 `"use server"` 的 `noop`，使 **POST /** 走 RSC 解码。  
- **scripts/react2shell_poc.py**：POC 请求发往 **/**（项目首页），命中根页面的 Server Action。  
- **run_react2shell_repro.sh**：结束或 Ctrl+C 时会执行 **cleanup**（杀 npm 子树 + 按端口杀进程），避免留下有洞的 next-server 进程。

---

## 七、详细复现步骤

以下在 **homepage 项目根目录**执行。

### 步骤 1：进入项目目录

```bash
cd /scr/hongwei/projects/adk-python/homepage
```

### 步骤 2：一键复现（推荐）

```bash
./run_react2shell_repro.sh
```

该脚本会依次：

1. **安装依赖**（pnpm 或 npm，无 pnpm 时用 `npm install --legacy-peer-deps --ignore-scripts`）；  
2. **释放端口 3011**（若被占用则 kill）；  
3. **启动 Next.js dev server**：`npm run dev -- -p 3011`；  
4. **等待约 45 秒**（等待 Ready）；  
5. **运行 POC**：`python3 scripts/react2shell_poc.py --url http://localhost:3011 --cmd whoami`；  
6. **退出时自动执行 cleanup**：杀 npm 及占 3011 的进程（含 next-server），**不留下有洞的服务**。

若复现成功，终端会看到类似：

```text
[+] 命令输出: hongwei
[6] Done.
[cleanup] Stopping repro server on port 3011...
```

且 **POST /**（首页）返回 500，响应体中含有 `"digest":"hongwei"`（或当前用户名）。

### 步骤 3（可选）：指定端口或手动执行

- 指定端口：`PORT=3012 ./run_react2shell_repro.sh`  
- 若 3011 被占用且脚本无法释放，可先手动：`sudo kill -9 $(lsof -ti:3011)`，再执行脚本。

手动分步示例：

```bash
npm install --legacy-peer-deps --ignore-scripts   # 或无 pnpm 时
npm run dev -- -p 3011 &
sleep 45
python3 scripts/react2shell_poc.py --url http://localhost:3011 --cmd whoami
# 结束后务必杀进程，例如：
lsof -ti:3011 | xargs kill -9
```

### 步骤 4：验证 RCE

- POC 成功时会在响应中看到 **`"digest":"<命令输出>"`**，脚本已解析并打印 `[+] 命令输出: <命令输出>`。  
- 可指定其他命令：`python3 scripts/react2shell_poc.py --url http://localhost:3011 --cmd id`（需在 dev server 仍运行且未关进程时执行）。

---

## 八、POC 在做什么（简要）

- **请求**：对 **POST /**（首页）发送 `Next-Action: x` 和 **multipart/form-data** 体，其中 part `"0"` 为伪造的 Flight Chunk（含 `then`、`status`、`value`、`_response._prefix`、`_response._formData.get` 等），诱导服务端执行 `Function(_prefix + id)()`，从而执行 `execSync('whoami')` 并把结果放入 `NEXT_REDIRECT.digest`。  
- **解析**：从响应正文中正则匹配 `"digest":"([^"]*)"`，若匹配则打印 `[+] 命令输出: ...`。  
- **结论**：若得到 500 且 `digest` 为命令输出，则 RCE 复现成功。

---

## 九、修复与缓解建议（了解即可）

- **根本修复**：  
  - 将 **React** 升级到 ≥19.0.1 / ≥19.1.2 / **≥19.2.1**（建议 RSC 19.2.3+ 以覆盖后续 CVE）；  
  - 将 **Next.js** 升级到已修复版本（如 15.0.5、15.5.7 等，见 [CVE-2025-66478](https://nextjs.org/blog/CVE-2025-66478)）。  
- **复现结束后**：若仅做实验，可将 `package.json` 中 `react`/`react-dom` 改回 18.x、`next` 改回 ^15.5.x 并重新安装依赖，避免日常开发环境长期停留在有洞版本。

---

## 十、清理环境

- **脚本自动清理**：`run_react2shell_repro.sh` 在正常结束或 Ctrl+C 时会执行 **cleanup**（杀 npm 子树 + 按端口 3011 杀进程），无需再手动关有洞进程。  
- **若端口仍被占用**：可手动执行  
  `kill -9 $(lsof -ti:3011)`  
  或（需权限时）  
  `sudo kill -9 $(lsof -ti:3011)`。  
- **恢复依赖版本**：若希望项目恢复为无洞版本，请修改 `package.json` 中 `react`、`react-dom`、`next`、`eslint-config-next` 到上述安全版本并重新 `pnpm install` 或 `npm install`。

---

## 十一、参考资料

- [React2Shell / CVE-2025-55182 说明与补丁状态](https://react2shell.info/)  
- [Next.js 安全公告 CVE-2025-66478](https://nextjs.org/blog/CVE-2025-66478)  
- 本仓库 `REPRO_REACT2SHELL.md`（若存在）：简短复现与修复说明  

以上即为 React2Shell 在本仓库中的完整漏洞链路与复现方法；若某一步报错，可先对照“复现前准备”和“受影响条件”检查环境与版本。
