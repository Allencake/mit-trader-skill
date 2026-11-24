# mit-trader：把 MIT 量化金融公开课做成一个 Claude skill

MIT 在 OpenCourseWare 上免费公开了 18.S096《Topics in Mathematics with Applications in Finance》（2013 秋季）：
数学部分由 MIT 的老师讲，应用部分请业界从业者讲，其中多位来自摩根士丹利。

这个仓库把课里能落到交易上的方法，做成了一个 Claude skill：

- `/mit-trader research`：夜里把策略库挨个测一遍，样本外、运气检验、交易成本三关全过才 APPROVED
- `/mit-trader today`：看通过的策略今天有没有信号，用 GARCH 定止损、蒙特卡洛 + Kelly 定仓位、VaR 查组合风险，出交易单等你批
- `/mit-trader explain <概念>`：哪个数看不懂，就让它用大白话讲，并告诉你对应哪一讲

默认只写模拟账本。每一笔都要你回 `yes` 才会记进去，这个版本不接真实券商。

> 不是 MIT 官方出品，只是基于它公开的免费课程。

## 安装

**最省事**：在 Claude Code 里把本仓库链接贴给 Claude，说「安装 skill」。它会照 SKILL.md 里的步骤装好。

**手动**：

```bash
git clone https://github.com/Allencake/mit-trader-skill ~/.claude/skills/mit-trader
cd ~/.claude/skills/mit-trader
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/test_smoke.py      # 不联网的自检，看到 smoke tests passed 就行
```

Claude Code 会读取 `~/.claude/skills/mit-trader/SKILL.md`。只想在某个项目里用，就把仓库放到项目的 `.claude/skills/mit-trader`。

需要 Python 3.10 以上。数据免费，不需要任何 API key：
- 股票、ETF：yfinance
- 加密：ccxt 公共行情，默认 OKX。所在地区访问不了的话，在 `config.yaml` 里把 `crypto_exchange` 改成 binance、kraken 或 coinbase

## 命令

在 Claude 里直接说就行，它会替你跑；也可以自己在终端跑（下面的 `python` 指 `.venv/bin/python`）：

| 你说 | 实际运行 |
|---|---|
| /mit-trader research | `python -m mit_trader research` |
| /mit-trader today | `python -m mit_trader today` |
| 这笔 yes | `python -m mit_trader approve <交易单ID> --answer yes` |
| 这笔不要 | `python -m mit_trader reject <交易单ID>` |
| 看模拟账本 | `python -m mit_trader ledger` |
| /mit-trader explain Kelly | `python -m mit_trader explain kelly` |

先想看看整条流程是不是正常，加 `--planted`：用一个合成的测试市场跑，里面只有一条序列埋了真实的动量优势，其余全是噪声。正常的结果是只有它被找出来。

```bash
python -m mit_trader research --planted
python -m mit_trader today --planted
```

## 三关

| 关卡 | 做法 | 默认门槛（config.yaml） |
|---|---|---|
| 1 样本外 | walk-forward：前 3 年起训练段挑参数，后面切 5 段，每段都用没见过的数据打分 | 样本外 Sharpe ≥ 0.5，且 ≥ 60% 分段为正 |
| 2 运气检验 | 持仓按 20 天一块打乱，置换 2000 次，再做 Benjamini-Hochberg 校正；加 deflated Sharpe | FDR ≤ 10%，DSR ≥ 0.95 |
| 3 成本 | 扣手续费和滑点；成本翻倍再测一次 | 净 Sharpe ≥ 0.3，成本 ×2 后 > 0 |

全部 REJECTED 是很常见的结果，说明这一轮没有站得住的东西。不要为了出单去放宽门槛。

## today 怎么算一张交易单

1 先检查模拟账本里已有持仓的止损
2 通过的策略今天有信号才往下走
3 止损：GARCH(1,1) 预测一日波动 σ，止损距离 = 2 × σ × √5（第 9 讲）
4 仓位：用该策略样本外的日收益抽样，模拟 10000 次 5 天持有，碰止损按止损算，得出 Kelly。Kelly ≤ 0 就不下；否则用 1/4 Kelly，再按单笔上限、单笔风险上限、总敞口截断
5 组合风险：加上这笔后算一日 99% VaR（历史法和参数法，第 7 讲），超上限就缩仓，缩不下来就不下
6 输出交易单，等你逐笔回 yes

所有上限都在 `config.yaml` 的 `limits` 里，用中文注释写清了。

## 策略库

| 策略 | 依据 |
|---|---|
| 时间序列动量 | 第 1 讲讲义把 momentum 列为系统化策略的一类 |
| 均值回归 | 第 8 讲 Time Series Analysis I（平稳性、自回归） |
| 通道突破 | 非课程内容，作为对照组 |
| 协整配对 | 第 12 讲 Time Series Analysis III（协整） |

参数网格写在 `mit_trader/strategies.py`，参数由 walk-forward 在训练段里挑，不在全样本上挑。

## 课程出处

只标在 OCW 讲义里核实过的讲次：

- 第 1 讲 Introduction, Financial Terms and Concepts
- 第 7 讲 Value At Risk (VAR) Models
- 第 8 讲 Time Series Analysis I
- 第 9 讲 Volatility Modeling
- 第 12 讲 Time Series Analysis III
- 第 14 讲 Portfolio Theory
- 第 25 讲 Ross Recovery Theorem（讲义引用 Kelly 1956）

课程主页：https://ocw.mit.edu/courses/18-s096-topics-in-mathematics-with-applications-in-finance-fall-2013/

非课程来源：Kelly (1956)；Benjamini & Hochberg (1995)；Bailey & López de Prado (2014) The Deflated Sharpe Ratio。

## 定时示例

下面是 crontab **示例**，时间请按你的时区和市场改（`crontab -e`）：

```cron
# 示例：每晚 2 点跑研究
0 2 * * *      cd ~/.claude/skills/mit-trader && .venv/bin/python -m mit_trader research >> ~/.mit-trader/research.log 2>&1
# 示例：工作日 9:50 跑 today（美股开盘后，按你服务器时区换算）
50 9 * * 1-5   cd ~/.claude/skills/mit-trader && .venv/bin/python -m mit_trader today >> ~/.mit-trader/today.log 2>&1
# 示例：加密每 2 小时看一次
0 */2 * * *    cd ~/.claude/skills/mit-trader && .venv/bin/python -m mit_trader today >> ~/.mit-trader/today.log 2>&1
```

定时任务只会生成交易单，不会替你批。

## 文件放在哪

`~/.mit-trader/`（可用环境变量 `MIT_TRADER_HOME` 改）：

- `cache/`：行情缓存（CSV），12 小时内不重复下载
- `runs/`：每次 research 的完整结果
- `approved.json`：最近一次三关全过的策略
- `tickets/`：每天的交易单
- `paper_ledger.json`：模拟账本

## 已知限制

- 日线级别，信号按收盘价算，模拟成交按参考价加滑点，跟真实成交会有差距
- 蒙特卡洛只从历史样本外收益里抽，市场换了性格就不准
- 配对交易的止损按价差算，模拟账本暂时不会自动触发配对止损，today 会提示
- 只支持模拟账本

---

不构成投资建议，与 MIT 官方无关。
