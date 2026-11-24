# 运气检验：是真本事还是撞大运

同时测几十个策略，总有几个会因为运气看起来很好。mit-trader 的第二关有两道题，都要过：

1 置换检验：把策略的持仓时间段打乱（按 20 天一块打乱）再配上真实行情，重复 2000 次。
  真实结果要明显好过这些「乱买乱卖」的结果才算数。所有候选的 p 值再做 Benjamini-Hochberg 校正，
  控制通过的里面靠运气混进来的比例（默认 10%）。
2 Deflated Sharpe：考虑到一共测了多少个候选、它们的 Sharpe 本来就分得多散，
  算出「这个 Sharpe 不是挑出来的幸运儿」的概率，默认要 ≥ 95%。

出处：Benjamini & Hochberg (1995)；Bailey & López de Prado (2014)《The Deflated Sharpe Ratio》。
这部分不是 MIT 18.S096 的课程内容。
