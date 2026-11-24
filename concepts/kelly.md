# Kelly 公式：一次该下多大

想象你玩一个游戏：赢的概率是 p，赢了赚 b，输了亏 a（都按投入金额的比例算）。
Kelly 回答的是：每次拿出账户的多少比例来玩，长期下来账户涨得最快。

    最优比例 f* = p / a − (1 − p) / b

- 算出来是负数或零：这个游戏长期不划算，一分都不该下。mit-trader 遇到这种情况直接不出单。
- 算出来很大：全 Kelly 波动大到受不了，实际只用 config.yaml 里的 kelly_fraction（默认四分之一），再按你的单笔上限截断。

mit-trader 里 p、a、b 从哪来：today 把策略在样本外的历史日收益重新抽样，模拟上万次持有过程，碰到止损就按止损算，最后数一数赢的比例和平均赢亏。

出处：Kelly (1956)《A New Interpretation of Information Rate》；Ed Thorp 把它用到了赌场和市场。
MIT 18.S096 第 25 讲（Ross Recovery Theorem）的讲义在讲增长最优组合时引用了 Kelly (1956)；课程没有单独一讲讲 Kelly。
