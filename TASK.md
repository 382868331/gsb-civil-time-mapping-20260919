# 完整首轮任务

离线日志归一化组件需要按显式时区表解释重复或缺失的本地时刻。请从零实现“显式时区转换表的民用时间映射库”。

1. 实现整数秒时区映射，给定umin<umax的有限UTC半开域[umin,umax)、初始offset及严格递增转换(utc,newOffset)，转换点须在域内部，点上即用新offset；local=utc+offset。不读取系统时区/IANA数据库，不解析真实日历。
2. UTCToLocal越域报错。LocalToUTC返回域内升序唯一候选；all无候选返回[]，earliest/latest无候选报gap，reject只接受恰好一个候选。多个候选为fold，不假定最多2个。
3. 本地[l,r)映射为所有符合条件的域内UTC区间，升序合并相邻段，不能只转换端点。反向映射UTC区间先裁剪到域内，再输出本地覆盖计数恒定的最大半开段；空区间为空，反向区间报错。
4. 有限递推local_j=start+j*step，step>0、0<=j<count；gap选择skip/reject，fold选择earliest/latest/all/reject。输出(j,utc)按utc再j排序；每个UTC最多对应一个j，每个j可对应多个UTC，不实现无意义的跨j去重。
5. 转换表<=1000项，count<=10000，整数运算精确，用分段区间算法不逐秒扫描。用小UTC域逐秒枚举参考验证多重fold、区间覆盖计数和边界；演示回拨三候选与跳空，不做预约系统。

验收重点：跳空、回拨三候选、30秒变化、转换点、域裁剪、空区间、反向区间拒绝、覆盖计数、按UTC重排递推。

工程约束：全新0-1核心库，仅用Python 3.14.7标准库，在Windows原生离线运行，无第三方依赖、外部服务、Docker或前后端。交付实现、聚焦上述边界的测试及简短README；演示命令`python demo.py`用小案例在约8秒内打印正常结果和一种真实失败，测试命令`python -m unittest discover -s tests -v`。固定种子随机验证只用少量小样本，避免长压测和额外平台功能，不限制正常纠错所需工具调用。
一次首轮完成，不要求用户追加“继续”。只操作当前仓库，不读取用户配置、密钥、环境变量清单或其他工作区；不添加Actions/CI/部署/Dependabot、不远程推送，不硬编码演示或虚报验证。
