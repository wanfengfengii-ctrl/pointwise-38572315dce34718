# 榆湾涂层复检交班台账

白班检验员登记每次母缺陷复检及其同次后继。质控员冻结完结样本，夜班在白班源库关闭后，从固定模型签发报告。质控用清卷概率判断还可能长期返检的份额，排班用指定轮的条件同现概率判断是否预留两类检位。

## 运行

使用 Python 3.11 和标准库。从仓库根目录运行。

```sh
python3 -B check_project.py
python3 -B demo.py
```

`check_project.py` 由交付环境提供，运行 `tests` 包下的完整回归。演示在临时目录创建两个库，读取 `samples/workday.json`，走公开接口，比较手算值并打印实际下游结果。临时库随演示结束清理。

## 白班到夜班的工作顺序

1. 对空闲的 SQLite 连接调用 `demo.initialize_source(conn)` 和 `demo.initialize_receiver(conn)`，分别准备源库和接收库。初始化可重复执行，保留此前提交的台账、勘误和成果。`demo.load_workday(source)` 是供演示使用的独立样例录入入口。
2. 用 `BatchStore(source).open(batch_id)` 登记批次。可先用 `InspectionStore(source).start(batch_id, inspection_id, kind)` 登记待结账身份，然后调用 `trials.completion.record(source, batch_id, inspection_id, kind, offspring)`。`record` 也接受尚未登记的唯一复检号。组合传列表或元组，`()` 表示完结且无后继。A 可产生无、A、B 或 AB，B 可产生无或 A。复检号在同一源库唯一。
3. 用 `RevisionStore(source).create_base()` 获取当前原始完结台账的截止点。`cohort.amendments.amend(source, base_revision_id, inspection_id, offspring)` 在指定修订上更正一条已可见观察，返回新修订。派生修订继承原截止点和本分支的勘误。后来完结的观察通过新基修订选用。沿一条继承链，以距请求修订最近的对应勘误为准。
4. 用 `cohort.freeze.freeze(source, revision_id, inspection_ids)` 冻结确切的复检号集合。返回 `FrozenCohort`，成员依复检号排序。`read_frozen_cohort(source, cohort_id)` 可按号重取原观察、有效组合和勘误出处。一个成员不可见即整次拒绝。重复列出的号只算一次。
5. 用 `models.publish.fit(source, cohort_id)` 发布 `ModelEdition`。每类完结数是该类分母，全部合法组合依固定顺序存放，未观察到的组合质量为零。缺任一母类时抛出 `MissingClassError`。`read_publication(source, model_id)` 可重取已发布件。
6. 将 `edition.text` 交给 `risk.accept.accept(receiver, edition.text)`，取得 `AcceptedModel.accepted_id`，随后可关闭源库。V1 JSON 对正文及其内外冻结出处做一致性核对。接收端可核对样本数、分布支持、概率和与整数计数；源端保留逐次观察供复算。摘要用于一致性检查。
7. 用 `reports.issue.issue(receiver, accepted_id, initial_kind, round_number)` 签发报告。由第 0 轮的单个初始缺陷出发，各母件独立按其类别的固定联合律同步产生后继。最终清卷指有限轮内首次没有待检缺陷。指定轮末 A、B 数量均为正才计入同现。报告返回最终清卷概率和在最终清卷条件下的同现概率。前者为零时，条件值为 `None`。若清卷可能而该轮同现不可能，条件值为 `Fraction(0)`。
8. 更正后重新冻结、发布和接纳即可签发独立报告。`reports.history.read(receiver, report_id)` 领取原签发结果，未知号抛出 `ReportNotFoundError`。`reports.export.export_report` 返回固定来源及原值的 JSON，分数用 `[分子, 分母]`，条件空值用 `null`。`reports.compare.compare_reports(receiver, old_id, new_id)` 同时返回两份报告。同初始类且同轮次的可定义概率才计算新减旧。

业务写入口持有自己的 SQLite 事务，请传入空闲连接。输入不合约时抛出 `ValueError` 或其子类，未知源端身份、固定号和接纳号抛出 `KeyError`。SQLite 写入或提交错误向调用方传播，失败事务不会返回新成果。接纳号和报告号在其接收库内使用；冻结号和模型号可随发行件携带。

样例的 A 测得无、AB、AB、AB，B 测得单 A。夜班从 A 启动，清卷为 1/3，首、次轮的条件同现分别为 1/4、1/16。按样例的 1/8 检位预留线，首轮预留两类检位，次轮无需同时预留。白班将一次 AB 更正为无后，重新签发的首轮报告清卷为 1、同现为 1/2。旧报告及其模型出处仍可按号领取。编号用于区分成果，计算和公开演示输出不依赖编号或随机种子。
