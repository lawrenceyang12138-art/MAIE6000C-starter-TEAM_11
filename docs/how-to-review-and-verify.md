# 怎么审查这份工作（写给不写代码的人）

*English note: this is a Chinese-language guide for the team member who owns
this branch. It explains how to verify the work without reading code: which
commands to run, what a good result looks like, and what a meaningless green
result looks like. The evidence itself is in `evidence/` and
`submissions/week07/`.*

---

## 一、你不需要读代码：审查就是问三个问题

工程审查听起来像"要能看懂代码"，其实不是。**你只需要问三个问题**，而且它们都能用命令回答：

1. **这个数字是哪条命令产生的？** 如果一句话里有数字，却找不到产生它的命令，那它就无法被验证——不管写得多详细。
2. **现在重跑一遍，还是这个数吗？** 数字必须能被别人复现，否则它只是"某人当时看到过"。
3. **如果这个数字是错的，会有什么东西报错？**
   这个问题最狠。**很多东西错了是不会报错的**：测试被跳过、检查变成"自己检自己"、失败被吞掉——结果看起来全是绿色。凡是"错了也不吭声"的地方，都要多问一句。

---

## 二、五条命令，你自己跑一遍

前提：你在这台电脑上，且 Docker Desktop 是开着的。每条命令我都会写"应该看到什么"和"危险信号"。

先进入仓库并让 Docker 可用：

```bash
cd /Users/zhangjintong/MAIE6000C-starter-jintong-zhang
export PATH="$HOME/.docker/bin:$PATH"
docker compose up -d db
```

### 1. 全量测试：到底跑了多少条

```bash
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/tests:/app/tests" \
  -v "$PWD/scripts:/app/scripts" -v "$PWD/alembic:/app/alembic" \
  api pytest -q -rs
```

**应该看到**：最后一行类似 `100 passed, 1 skipped`，并且 `-rs` 会**列出每一条被跳过的原因**。
**危险信号**：
- 出现 `skipped` 却没人解释它为什么被跳过 → 说明有一块**根本没验**；
- 出现 `no tests ran` 或者数量突然变少 → 测试文件没被采集（文件名不对就会这样，本项目真的发生过）；
- `failed` 或 `error` 当然就更不用说了。

> 注意：`-v` 那几行**不能省**。镜像里存着一份旧代码，不挂载就等于在测旧版本——这是这个项目真实踩过的坑。

### 2. 质量数字：解析出来的文本好不好

```bash
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "/Users/zhangjintong/HKUST/HKUST-6000C:/fixtures:ro" api \
  python scripts/check_parsing_quality.py \
    "/fixtures/Week 5 — Lab.pdf" \
    "/fixtures/Week 4 — Data Persistence and Schema Design.pdf" \
    "/fixtures/Week 5 — APIs and Network Communication.pdf"
```

**应该看到**：一张表 + 一行汇总，包含 `0 corrupt characters`、`20/20 fragments found on their page`、`headers ... 0`。
**危险信号**：`corrupt` 数字不为 0、或"片段找到"少于 20/20，而文档里却写着没问题。

### 3. 页码是否可信：用另一个工具来判

```bash
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "/Users/zhangjintong/HKUST/HKUST-6000C:/fixtures:ro" api \
  python scripts/verify_page_attribution.py \
    "/fixtures/Week 5 — Lab.pdf" \
    "/fixtures/Week 4 — Data Persistence and Schema Design.pdf" \
    "/fixtures/Week 5 — APIs and Network Communication.pdf" --per-file 4
```

**应该看到**：第一行写着 `reference extractor: PyMuPDF (independent)`，最后是 `12/12 agree`。
**危险信号**：
- 出现 `(NOT independent)` 或 `refused:` → 说明**它拒绝用自己检查自己**（这是好事，但要按提示补上第二个库才能得到结论）；
- 结论是"12/12"，但第一行显示的判官和被测的是同一个工具 → 这就是**自己判自己**，什么都没证明。

### 4. 人工复核能不能被偷偷覆盖

```bash
docker compose run --rm --no-deps \
  -v "$PWD/services:/app/services" -v "$PWD/scripts:/app/scripts" \
  -v "$PWD/tests:/app/tests" api \
  python scripts/demo_relation_review.py tests/fixtures/relations/entities.pdf
```

**应该看到**：A 在版本 1 确认 → B 拿着旧版本被**拒绝**（`review_conflict`）→ B 重读后在版本 2 否决 → 一次没写清"改成什么"的纠正被**拒绝**。
**危险信号**：B 没有被拒绝，而是"成功写入"——那说明防冲突机制没生效。

### 5. 团队仓库那边到底是什么状态

```bash
cd /Users/zhangjintong/MAIE6000C-team11-scratch
git ls-remote origin | sed 's/\t/  /'        # 远端有哪些分支、指向哪个提交
git log --oneline -1 origin/w7-parsing        # 顶端提交
git rev-list --count origin/main..origin/w7-parsing   # 比 main 多多少个提交
git merge-base --is-ancestor origin/main origin/w7-parsing && echo "可以快进合并，不会冲突"
```

**应该看到**：`main` 指向初始提交（**没被任何人动过**）、`w7-parsing` 存在且比 main 多 54 个提交、最后一行打印"可以快进合并"。
**危险信号**：`main` 的提交号变了（说明有人往 main 推了东西）、或者"可以快进合并"没打印出来（说明合并会有冲突）。

---

## 三、让"绿色"变假的五种情况

这五种是最常见的"看起来通过了，其实什么也没证明"，你以后看任何人的结果都可以拿这五条去问：

1. **测试被跳过。** 「N passed」和「N passed + 12 skipped」是两回事。永远看一眼 `skipped`。
2. **自己检自己。** 用同一个工具产生结果、再用它检查结果，永远是对的。必须换一个独立来源。
3. **数字没有命令。** 无法复现的数字 = 无法审查的数字。
4. **测的不是那件事。** "所有测试通过"不等于"我做的那个功能是对的"——要问：哪条测试对应这个结论？删掉它结论还成立吗？
5. **引用的是旧一次运行。** 代码改了之后，旧数字自动作废。要问：这个数是最近一次跑出来的吗？

---

## 四、你可以问我的五个问题（很难糊弄过去）

下次你怀疑某个结论时，直接问这五句里的任意一句：

1. **"这个数字是哪条命令产生的？现在能不能重跑给我看？"**
2. **"如果这个数字是错的，哪个东西会报错？"**（如果答案是"不会报错"，那就要警惕）
3. **"你说验证过——具体跑了什么？失败长什么样？"**
4. **"这条结论用了几个文件/几个样本？"**（三个文件和一个语料库不是一回事）
5. **"有哪些东西你**没有**验证？"**（愿意主动列出来的，通常更可信）

---

## 五、术语小词典

你会在这些材料里遇到的词，一句话一个：

| 词 | 白话意思 |
|---|---|
| 仓库 repository | 这个项目的代码存放处（本地一份，GitHub 上一份） |
| 提交 commit | 一次"存档"：一组改动的快照 + 一句说明 |
| 分支 branch | 从主线分出来的独立工作线；本项目要求每人一条，不要直接改 main |
| main | 主线分支，团队的共同版本 |
| 远端 remote | GitHub 上那份副本 |
| push | 把本地提交送上去 |
| fetch / pull | 把远端的更新拿下来 |
| merge（合并） | 把另一条分支的改动并进当前分支 |
| rebase（重放） | 把一串提交按顺序"重新贴"到另一个起点上；会改变提交号 |
| 冲突 conflict | 两个人改了同一处，Git 无法自动决定，需要人工选 |
| 标签 tag | 给某个提交起的固定名字，比如 `w03-readiness` |
| CI | 自动检查：代码推上去之后由机器跑测试与检查 |
| PR / pull request | 请求把某条分支合并进主线，通常顺带触发 CI |
| 测试 test | 一段自动检查代码行为的程序 |
| passed / skipped / failed | 通过 / 被跳过 / 失败（**跳过要特别留意**） |
| 断言 assert | 测试里的"我要求这里必须等于 X" |
| smoke test（冒烟测试） | 最基础的端到端检查：整套服务起来后走一遍主流程 |
| regression（回归） | 确保"以前能用的现在还能用"的一组测试 |
| lint / ruff | 静态检查：不运行程序，只看代码里明显的坏味道 |
| 迁移 migration | 数据库结构的"版本升级脚本" |
| 镜像 image / 容器 container | 打包好的运行环境 / 它跑起来的一个实例 |
| 哈希 hash | 一段内容的指纹；内容变一个字，指纹就完全不同 |
| 代码树 tree | 某个提交里所有文件内容的整体指纹 |
| 事务 transaction | 一组数据库操作要么全成功、要么全回滚 |
| 外键 / 级联删除 | 表之间的引用关系；被引用的行删掉时，引用它的行会跟着被删 |
| 幂等 idempotent | 同样的操作做两次，结果和做一次一样 |
| 证据 evidence | 支撑某个结论的可见材料（数字、命令、截图） |
| 限制 limitation | 明确写出来的"这里做不到/做得不好"，主动写出来是加分项 |

---

## 六、如果只记一句话

**不要问"你做完了吗"，问"我怎么能自己确认你做完了"。**

一份可信的交付，应该让一个不懂代码的人也能在十分钟内亲手验证一遍——这份清单就是为了这个。
