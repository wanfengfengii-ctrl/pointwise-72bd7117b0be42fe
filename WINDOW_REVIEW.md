# 外协等级窗口复查

厂内整域复查沿用 README.md。外协每次只接收申请窗口中适用的轨迹，用于核定两版在该窗口内对同一等级试件的首差。白班先固定发行，交班人员从可信渠道把发行凭据预置在外协库，窗口随后确定。普通送件可被替换或改写，可信渠道与外协库本身由交班人员控制。送件接口不得登记或替换可信凭据。

## 调用约定

沿用现有 Python 与 SQLite 所有者、串行调用和空闲连接约定。

- `issue.freeze.freeze_window(catalog, issues, revision_id)` 固定指定修订的发行，返回 `(issue_id, credential)`。`credential` 是通过可信渠道传递的 `bytes`，外部调用方把它视为不透明值。未知修订沿用 `UnknownRevision`。
- `intake.receive.pin_window_issue(intake, station, issue_id, credential)` 预置发行凭据，返回 `None`。同一站及发行号重复预置相同字节可成功，冲突凭据抛 `ValueError` 并保留原凭据。预置结果重开外协库后仍可使用。
- `issue.freeze.make_window_packet(issues, issue_id, lo, hi)` 从该站的指定固定发行生成窗口件，返回 `bytes`。以发行时的原段为准，后续登记修订不影响它。未知或未经窗口发行的号码及非法窗口抛 `ValueError`。
- `intake.receive.receive_window(intake, station, issue_id, lo, hi, packet)` 按请求指定的发行和窗口验收，成功返回现有形状的 `IntakeReceipt`。`digest` 为实际收件字节的 SHA-256 小写十六进制值，合法重复实收分别给号。非法请求或来件抛 `ValueError`，保存来件和回执须一并成功。
- `report.compare.compare_window(intake, store, left_id, right_id)` 使用两个已核定的窗口实收号，返回带原报告属性和回执的结果。`draft.window` 是两个 `Fraction` 的元组，`draft.parents` 是按输入顺序排列的实际双实收回执。`draft.first_differences` 与 `draft.always_same` 沿用原类型。缺父件、任一父件不是窗口实收或两窗不同均抛 `InvalidComparison`。通过 `report.read.read(store, report_id)` 可取回同一定稿及回执，回执仍绑定该报告号与有序双实收。SQLite 写入及提交错误沿用旧接口的上报和回滚方式。

发行号在同站内、实收号及报告号在各自夜班库内均沿用各自的单一编号空间。V1 与窗口签发入口分别接收自己的实收件。旧 V1 发行、实收、报告和历史领取继续使用现有接口及格式。

## 来件与计算口径

`lo`、`hi` 沿用 README.md 的精确有理数输入类型，且 `0 <= lo < hi <= 1`。窗口件为按键排序、无多余空白的 UTF-8 JSON。外层字段为 `version`（整数 2）、`station`、`issue_id`、`rule_code`、`revision_id` 和 `body`。`body` 含 `window`、`traces` 和 `proof`。`window` 为两个规范分数字符串，`traces` 内每行沿用 V1 的 `lower`、`upper`、`actions`、`repeat_from`，按原段顺序完整提供。`proof` 为用于独立核验的 JSON 值，可以为空值。凭据编码与 `proof` 内部格式由实现决定。

窗口件的身份须匹配请求及事先预置的凭据。须核实每段的原始边界、实际动作与循环信息，接收且只接收与窗口有正长度交集的全部原段。跨过窗界的原段按原样交运，在计算时才截取窗内部分。只碰到端点的原段不交付。凭据与窗口件可以携带边界、摘要及核验所需的结构信息，不能携带可直接读取或解码的窗外轨迹。每份来件须以本件及预置凭据完成核验。来件自行声明的摘要无法代替预置凭据。

按 README.md 的动作、结束与循环规则比较同等级轨迹。每个共同原段在窗内的交叠长度除以窗长，即为该段的概率质量。概率总质量为 1，首差只列升序非零项。实收之后，签报及复领只依赖外协库。

## 样例与运行

`samples/window_review.json` 提供可直接登记的两版规程。它们只在 [1/2,2/3) 的第二拍动作不同，整域首差为 1/6。以 [1/4,3/4) 复查，两端均切在原段内部，签报应给出第二拍首差 1/3、始终一致 2/3。「窗外低档」和「窗外高档」均在该窗之外。以 [1/2,2/3) 复查时，紧邻两端的原段均不交付，该窗第二拍首差为 1。

`window_fixture.load_case()` 读取样例。`window_fixture.preload_credentials(install, station, *issued)` 依次通过交班调用递交 `(issue_id, credential)`，其中 `install` 接受站名、发行号和凭据。`python3 -B window_fixture.py` 可在旧链路上核对样例的整域结果。

沿用根目录的 `.pointwise-runtime.json`。其中 `version` 为 1、`kind` 为 `cli`，`setup` 列准备命令的参数数组，`verify` 和 `demo` 各为一个命令参数数组。将 `verify` 接上原完整回归和窗口业务核验，任一检查失败用非零退出码。窗口核验须覆盖合法双件断源签发、拒绝伪件或漏段、窗口不匹配及按号复领。`demo` 展示样例的实际窗口定稿、父件和复领结果。
