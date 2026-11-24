# 返修试验室规程交班台账

制造厂返修试验室从工艺台账取得待试规程。白班试验员先点查登记等级的试件，再移交固定的规程版本。夜班质控员比较同一试件换版后的首次动作差异，安排对应拍次的复查，并在下一班按报告号领取当时使用的证据。

## 运行

使用 Python 3.11 标准库。在工程根目录执行：

```sh
python3 -B check_project.py
python3 -B demo.py
```

控制台在物化时提供 `check_project.py`。完整套件也可直接运行 `python3 -B -m unittest discover`。演示在临时目录使用两份独立 SQLite 库，从 `samples/` 装入三个完整规程输入。两版首拍进站，次拍的返检和留线互换，手算该拍首差概率为 1。演示移走白班库后完成对照签发，再登记一次更正并重开夜班库领取原报告。

## 规程输入与拍次

`register` 的规程号是非空文本。规程对象有 `start`、`terminals`、`states` 和可选私有 `note`。`states` 的键为可执行状态，值为转移行数组，每行有 `lower`、`upper`、`action`、`next`。终止状态单独列出，起点和所有后继必须存在。每个可执行状态的转移分区互斥、非空且完整覆盖 `[0,1)`。等级及端点接受 `Fraction`、整数或有理数字符串，字符串可写为 `1/2` 或 `0.5`。浮点和布尔值拒绝。

拍次从 1 开始。转移在本拍产生一个非空公开动作。到达终止位置后，下一拍才观察到结束。例如第二拍转移到终止位置，观察两拍时结束拍为 `None`，观察三拍时结束拍为 3。零拍成功记录为空，起点也可以是终止位置。结束独立于所有动作文本，包括名为「结束」的动作。等级 `1/2` 落在以 `1/2` 开始的区间。现场及整个对照使用同一个等级。

## Python 接口

```python
from contextlib import closing
from pathlib import Path
import json

from intake.catalog import IntakeCatalog
from intake.receive import receive
from issue.codec import encode_packet
from issue.freeze import freeze
from issue.register import IssueRegister
from labdb import open_database
from report.compare import compare
from report.read import read
from report.store import ReportStore
from rules.catalog import RuleCatalog
from rules.importer import register
from trial.history import ReplayHistory
from trial.session import preview

with closing(open_database('day.sqlite3')) as day:
    rules = RuleCatalog(day)
    history = ReplayHistory(day)
    issues = IssueRegister(day, 'repair-lab')
    old = register(rules, 'R-17', json.loads(Path('samples/old.json').read_text(encoding='utf-8')))
    new = register(rules, 'R-17', json.loads(Path('samples/swapped.json').read_text(encoding='utf-8')))
    observation = preview(rules, history, old, '1/2', 3)
    old_packet = encode_packet(freeze(rules, issues, old))
    new_packet = encode_packet(freeze(rules, issues, new))

with closing(open_database('night.sqlite3')) as night:
    intake = IntakeCatalog(night)
    store = ReportStore(night)
    left = receive(intake, old_packet)
    right = receive(intake, new_packet)
    signed = compare(intake, store, left.intake_id, right.intake_id)
    original = read(store, signed.report_id)
```

白班的规程、现场和发行所有者使用同一连接。夜班的实收与签发所有者使用另一个连接。`open_database` 启用 SQLite 外键。构造所有者及调用写接口时使用空闲连接，写接口管理自身事务。同一个连接由调用方串行使用。发行站名由部署方选定并固定在白班库，跨站使用不同站名。每次成功发行、实收和签发各分配本库流水。以同一件作两侧输入合法，父件仍有顺序。

- `register(catalog, code, rules)` 返回新修订号。`catalog.current_revision(code)` 查询现行版，`catalog.get_revision(id)` 查询固定版。`InvalidRules` 拒绝不完整分区、非法引用和坏输入。
- `preview(catalog, history, revision_id, grade, beats)` 返回 `ReplayRecord`。其中 `trace.actions` 是动作元组，`trace.ended_at` 是观察到的结束拍。错版、非法等级或拍数抛出 `InvalidReplay`。`history.get(record_id)` 领取原观察记录。
- `freeze(catalog, issues, revision_id)` 返回已登记的 `IssueEnvelope`，未知版抛出 `UnknownRevision`。`issues.get(issue_id)` 读回固定原件。`encode_packet` 输出可交换字节。
- `receive(intake, packet_bytes)` 返回包含 `intake_id` 和 `receipt` 的 `AcceptedPacket`。非法结构、摘要或正文抛出 `InvalidPacket`。合法重复实收各有自己的实收号。
- `compare(intake, store, left_id, right_id)` 返回 `SignedReport`。`draft.parents` 是有序双实收出处，`draft.first_differences` 是升序 `(拍次, Fraction)` 元组，`draft.always_same` 是 `Fraction`。缺父件或证据坏抛出 `InvalidComparison`。SQLite 写入或提交错误原样上报，失败事务没有新增报告或回执。
- `read(store, report_id)` 返回持久定稿和其回执，未知号抛出 `ReportNotFound`。查询原修订、现场记录、发行件或实收件的底层保管接口在查无编号时返回 `None`。

## V1 固定件与报告口径

交换件是按键排序、无多余空白的 UTF-8 JSON。外层字段为 `version`、`station`、`issue_id`、`rule_code`、`revision_id`、`body`、`digest`。`digest` 是其余字段规范编码的 SHA-256 十六进制值，用于核对来件内容与出处是否相符。交班渠道负责确认实际送件站。`body.traces` 是按下界升序的完整等级分区，每行含有规范分数字符串 `lower`、`upper`、公开 `actions` 及 `repeat_from`。`repeat_from` 为 `null` 时，最后一个动作之后的下一拍结束。整数表示从动作数组的该零起始下标重复到数组末尾。正文仅移交公开动作及其适用等级，内部状态号和私有备注保存在规程修订中。

每个共同等级段的质量等于其长度。两条已固定轨迹发生动作不同或仅一方结束的第一拍计入首差，双方同拍结束且此前一致计入始终一致。无限轨迹在该段内两侧位置组合重复且此前动作一致时计入始终一致。概率质量总和为 1，全一致时首差元组为空。定稿固定双实收号、发行站、发行号、源规程号、源修订和摘要。回执绑定同一报告及同一有序父件。重开重复初始化保留已保存的数据，领取旧报告直接从原定稿与回执读取。

## 外协窗口复查接口

外部窗口复查的格式与口径见 WINDOW_REVIEW.md。窗口签发另有入口，与 V1 共用同一批所有者与编号空间：

```python
from intake.receive import pin_window_issue, receive_window
from issue.freeze import freeze_window, make_window_packet
from report.compare import compare_window

issue_id, credential = freeze_window(catalog, issues, revision_id)
pin_window_issue(intake, station, issue_id, credential)          # 可信渠道预置
packet = make_window_packet(issues, issue_id, '1/4', '3/4')      # 按原段交付
receipt = receive_window(intake, station, issue_id, '1/4', '3/4', packet)
signed = compare_window(intake, store, left_id, right_id)
```

- `freeze_window` 固定指定修订并返回 `(issue_id, credential)`；凭据是不透明 `bytes`，未知修订沿用 `UnknownRevision`。
- `pin_window_issue` 按站号与发行号预置凭据，重复相同字节成功，冲突抛 `ValueError` 且保留原凭据；持久化在外协库。
- `make_window_packet` 以发行时原段为准交付 `[lo, hi)` 窗口件，只含与窗口有正长交集的全部原段，保留原段边界；未知/未窗口发行的号码及非法窗口抛 `ValueError`。
- `receive_window` 按请求的发行、窗口和预置凭据核验来件；缺凭据、错发行、错窗、漏段、越窗段或被改写均抛 `ValueError` 且不落库。成功返回 `IntakeReceipt`，`digest` 为实际收件字节的 SHA-256。
- `compare_window` 接受两个已核定窗口实收号，`draft.window` 为 `(Fraction, Fraction)`，`draft.parents` 为按输入顺序的实际双实收回执；缺父件、任一父件非窗口实收或两窗不同抛 `InvalidComparison`。定稿与回执可经 `read(store, report_id)` 复领。

窗口件是 `version` 为 2 的规范 JSON，含 `body.window`、`body.traces` 与 `body.proof`。`proof` 用预置凭据所含 MAC 密钥对发行身份、窗口和交付原段签名，来件自述摘要不能替代预置凭据。每个共同原段的质量为窗内交叠长度除以窗长，首差只列升序非零项。

