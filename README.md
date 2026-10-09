# Customer Requirement Clarifier

也是个售前工具,但解决的问题比 POC 那个更靠前一步:客户提了个技术需求,信息缺这缺那的,你根本没法直接开始做方案,得先把缺的东西问清楚。这个工具就是帮你把"问清楚"这件事管起来。

边界先说在前面:它只管需求澄清。不判断方案可不可行,不生成解决方案,不报价,也不调用任何 AI——整个项目一次外部 API 都不碰,全靠固定的规则跑。

## 现在能做什么

能建售前项目,一个项目下面能挂多条需求。需求类型目前只做了"系统集成"这一种,以后要加别的类型也不难,在代码里加个字段定义就行。

每条系统集成需求,有五样信息是必须问清楚的:目标系统叫什么、什么版本、用什么接口方式对接、怎么认证、数据怎么同步。这五项里只要有一项空着,这条需求就是"不完整",工具会按缺失的字段顺序自动生成几个澄清问题——就是"请问贵方的目标系统是什么版本?"这种,模板固定的,不涉及 AI。五项都填齐了,状态就变成"信息已基本完整,可以进入方案评估"。

注意这里有个措辞上的讲究:填齐了只说"可进入评估",不会说"方案一定可行"。信息完整和方案可行是两码事,工具不越这个界。

## 状态是怎么流转的

一条需求有三种状态:

- **incomplete**:必填信息有缺的,不能往下走
- **ready**:字段都填齐了,可以进入人工确认
- **confirmed**:售前自己看过、明确点了"确认"按钮

前两个状态是点"检查"时系统自动判的,第三个只能人手动点。字段补得再齐也永远不会自动变成 confirmed——机器补全了信息,不代表人认可了,这两件事必须分开。

确认之后如果又改了某个核心字段,状态会自动退回去(信息还齐就退回 ready,有缺就退回 incomplete),得重新确认一遍。这样能避免"早就确认过了,但内容其实已经变了"的坑。

## 信息从哪来的

每个字段还能记一条"来源",就三个选项:客户说的、内部资料查的、售前自己整理的。这个设计是考虑实际工作中同样一句"版本是 3.2",有的是客户白纸黑字写的,有的是售前从旧资料里翻的,可靠程度不一样,记下来以后回溯的时候心里有数。

有个规则得知道:改了字段值,之前记的来源会自动清掉,得重新选。因为值变了,旧的来源说明的是旧值,留着是误导。另外来源只是个记录,不参与"信息完不完整"的判断——字段有值就算完整,哪怕没记来源,页面最多提醒一句,不会因此判你 incomplete。

至于澄清问题本身,它不是单独维护的一套东西,就是从字段直接推出来的:字段有值,对应澄清项就是已确认;字段空着,就是待处理。所以不会出现"字段明明填了、澄清项还挂着没确认"这种前后不一致的情况,一个地方改,两边跟着变。

## 目录

```
customer-requirement-clarifier/
├─ backend/
│  ├─ app/
│  │  ├─ main.py            # FastAPI 路由
│  │  ├─ db.py              # SQLite 访问,没用 ORM
│  │  ├─ schema.sql         # projects / requirements 两张表
│  │  ├─ requirements.py    # 需求类型定义 + 完整性检查的纯函数
│  │  └─ static/            # index.html / app.js / style.css
│  ├─ tests/                # pytest 测试
│  └─ data/                 # 数据库文件,第一次跑自动建
├─ requirements.txt
└─ README.md
```

## 怎么跑

```bash
pip install -r requirements.txt
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

打开 http://127.0.0.1:8000 就行。数据库默认在 `backend/data/clarifier.db`,想换位置设 `CRC_DB_PATH` 环境变量。

## 跑测试

```bash
cd backend
python -m pytest tests -q
```

顺手也可以跑下这两个,都是几秒钟的事:

```bash
python -m compileall -q app tests
node --check app/static/app.js
```

## 接口

```
GET    /api/health
GET    /api/requirement-types
GET    /api/sources                    # 三种来源枚举

GET    /api/projects
POST   /api/projects
GET    /api/projects/{id}
DELETE /api/projects/{id}

POST   /api/projects/{id}/requirements
GET    /api/projects/{id}/requirements
GET    /api/requirements/{id}
PATCH  /api/requirements/{id}
DELETE /api/requirements/{id}

POST   /api/requirements/{id}/check      # 跑完整性检查
POST   /api/requirements/{id}/confirm    # 人工确认(只有 ready 能确认)
GET    /api/requirements/{id}/summary    # 确认摘要
```

有件事值得说一下:保存数据、跑检查、人工确认,这三件事走的是三个不同接口,职责分得很清楚。PATCH 只管存数据,不改状态;/check 只产出 incomplete 或 ready;confirmed 只能靠 /confirm。你直接在 PATCH 里塞 status 字段,它会拒绝你(返回 400)。这么设计是防止绕过确认这一步——状态必须走它该走的路产生。

## 整个流程串起来

建项目 → 建需求 → 填结构化信息(顺手记下来源)→ 保存并检查 → 看缺什么、生成澄清项 → 找客户把缺的补上 → 再检查 → 字段齐了、澄清项都确认了 → 你人工点确认 → 拿着确认摘要去下一步。

## 边界

- 不用 AI,不接外部 API
- 不判断客户说的是不是真话,信息真不真实它管不着
- 不判断技术方案可不可行,不做方案,不报价
- confirmed 只代表"这条需求信息我确认过了",不代表方案没问题
- 没有登录、权限、多租户这些,就是个单机小工具
