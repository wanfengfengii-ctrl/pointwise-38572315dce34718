# 重叠冻队合算签报

白班准备可供夜班选择的冻队，随后可以关闭源库。夜班用收到的合算件签一张布岗报告。现有单队工作流和概率口径见 `README.md`。

## 调用

连接用 `demo.initialize_source` 和 `demo.initialize_receiver` 分别初始化。业务调用使用空闲连接。两个库可分别重开并重复初始化。

- `models.publish.publish_pool(source, cohort_ids) -> str` 读取同一源库中的至少两个不同冻结号，返回 V2 合算件 JSON 文本。读取指定冻队固存的成员、有效后继和出处。允许包内某个冻队只含一类样本，也允许包内存在勘误分歧。
- `risk.accept.accept_pool(receiver, text) -> str` 验证并固定合算件，返回接纳号。接收库独立于源库。
- `reports.issue.issue_pool(receiver, accepted_id, cohort_ids, initial_kind, round_number)` 按本次选队签发并返回报告对象。所选冻队必须是该实收件的非空子集。合算按源库实检身份去重。同一实检在所选冻队中的有效后继相同，计一笔。原观察或勘误号不同但有效组合相同时也按同值处理。同一实检在所选队中取值不一则拒签，未选队的分歧不影响签发。结果中任一母类的计数总和为零也拒签。
- `reports.history.read_pool_report(receiver, report_id)` 按号读取原签发对象。读取使用落库结果，源端勘误和接收库重开均不改变既有报告。

两个 `cohort_ids` 参数均用列表或元组传入，各号互异。入参顺序不影响选队资格和计数。源端冻结号和 V2 接纳号、报告号均为非空白字符串且不得包含 NUL。V2 的接纳和报告编号在各自接收库及入口内使用。V1 的接纳和报告整数号传入 V2 入口属于非法输入。

## 合算件与定稿

合算件最外层是 JSON 对象，字段为 `version`、`body` 和 `body_sha256`，版本为整数 `2`。`body` 的字段为 `origins` 和 `evidence`。`origins` 列出每个冻队的 `cohort_id`、`revision_id`、`cohort_digest`，字段取值沿用 `models.codec.encode_origin` 对应的 `LawOrigin`。每个冻结号只列一次。`body_sha256` 是正文按 UTF-8 编码后计算的 SHA-256 小写十六进制摘要。正文采用 `json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)` 的值。JSON 中的对象字段名不得重复。

`evidence` 的内部格式由实现决定。件内只带冻队出处和汇总证据。实检号、原观察和任何逐实检链接令牌均留源，包括为实检号逐条生成的哈希。汇总证据须足以让夜班对每种合法选择判断冲突并核定精确计数。接纳时核对版本、摘要、出处的结构与唯一性，以及证据中的冻队引用、类别、后继组合、计数和所用格式的内部一致性。摘要用于一致性核对，夜班按可信白班的发行事实办理。交付时在本文中记明实际的 `evidence` 格式及有效性约定。

签发和领取返回的对象包含以下属性。

| 属性 | 内容 |
| --- | --- |
| `report_id` | 接收库中的 V2 定稿号 |
| `accepted_id` | 当次使用的合算件接纳号 |
| `origins` | 仅包含实际所选冻队的 `LawOrigin` 元组，按 `cohort_id` 升序 |
| `initial_kind`、`round_number` | 初始母类 `A` 或 `B`，轮次为 1 至 6 的非布尔整数 |
| `counts_a` | 非负整数元组，依次对应空后继、A、B、AB |
| `counts_b` | 非负整数元组，依次对应空后继、A |
| `clearance` | `Fraction` 型最终清卷概率 |
| `conditional_cooccurrence` | 最终清卷条件下指定轮末 A、B 同现的 `Fraction`，清卷概率为零时为 `None` |

各母类用自己的计数总和归一。沿 V1 从第 0 轮的单个初始母件出发，各母件按自己的完整联合律独立、同步产生后继。最终清卷指有限轮内到达无待检缺陷。清卷有正概率而该轮不能同现时，条件值为 `Fraction(0)`。

坏件、错误版本、非法请求、合算件外选队、所选队间冲突或合并缺类抛 `ValueError`。发行时合法但未知的冻结号，以及合法但未知的接纳号或定稿号抛 `KeyError`。V1 发行件不能走 V2 接纳，V2 合算件也不能走 V1 接纳。接纳和签发各自整次提交，报告号及其完整内容同次可见。SQLite 写入或提交异常照传，失败无本次新成果，原请求可重试。V1 接口、件编码、历史定稿和原回归继续可用。

## 样例与核验

`pool_fixture.load_pool_sample(source)` 向已初始化的空源库登记并冻结样例，返回具名场景及各自有序的 `FrozenCohort` 元组。`x、y、z、w` 都是 A 类空后继，`p` 是 A 类产生 AB，`b` 是 B 类产生 A。字母是样例中实检号的末尾，实检号随源库留存。

| 场景 | 队一 | 队二 | 队三 |
| --- | --- | --- | --- |
| `common_three` | x、y、p、b | x、z、b | x、w、b |
| `separate_pairs` | x、y、p、b | x、z、b | y、z、b |
| `swapped` | x、p、b | 同一批 x、p、b，在新修订中 x 改为 AB、p 改为空 | b |
| `split` | x、p | b | |

`common_three` 和 `separate_pairs` 的对应单队计数完全相同。任取两队，其交集均是一笔 A 类空后继和一笔 B 类产生 A。选择全部三队，从 A 签首轮，前者的 `counts_a` 是 `(4, 0, 0, 1)`，后者是 `(3, 0, 0, 1)`。两者的 `counts_b` 都是 `(0, 1)`，清卷都为 `1`，条件同现分别为 `1/5` 与 `1/4`。预留线为 `1/4`，等额达线。

`swapped` 的前两队分别独选均签 `1/2`，队一与队三合选也签 `1/2`。前两队一同选入时，即使两队的整队直方图相等，也必须拒签。`split` 的两队合选可签 `1/2`，只选任一队因缺类拒签。

以下是关源后选择一份样例合算件的调用顺序。

```python
import sqlite3
from demo import initialize_receiver, initialize_source
from models.publish import publish_pool
from pool_fixture import load_pool_sample
from reports.issue import issue_pool
from risk.accept import accept_pool

source = sqlite3.connect(':memory:')
initialize_source(source)
cohorts = load_pool_sample(source)['common_three']
ids = [cohort.cohort_id for cohort in cohorts]
text = publish_pool(source, ids)
source.close()

receiver = sqlite3.connect(':memory:')
initialize_receiver(receiver)
accepted_id = accept_pool(receiver, text)
report = issue_pool(receiver, accepted_id, ids, 'A', 1)
assert report.counts_a == (4, 0, 0, 1)
assert str(report.conditional_cooccurrence) == '1/5'
receiver.close()
```

仓库根目录的 `python3 -B pool_fixture.py` 用正常 V1 接口核对样例的单队分母和频率。沿现有 `.pointwise-runtime.json` 接通合算业务回归，核验失败须非零退出。演示从关库后的合算件择队，展示布岗结果并重开接收库按号领取。保留 `check_project.py` 的完整原回归和 `demo.py` 的原工作日演示能力。
