# Customer Requirement Clarifier

客户提需求经常缺东西——目标系统什么版本、接口怎么对接、怎么认证、数据怎么同步。这些不问清楚,方案根本没法做。这个工具就是帮你把这些缺的信息列出来、盯着补全。

跟 `ai-poc-advisor` 是一套的,这个管更前面那段:需求澄清。那边管后面的评估对比。

它不判断方案可不可行,不生成方案,不报价,也不调用任何 AI,整个项目一次外部 API 都不碰。

## 现在能干嘛

能建售前项目,一个项目下挂多条需求。需求类型目前只做了"系统集成"一种,以后要加别的类型就是在 `requirements.py` 里加个字段定义的事。

系统集成需求有五项必填:目标系统、版本、接口方式、认证方式、同步方式。缺哪个就生成哪条澄清问题,模板是固定的,"请问贵方目标系统是什么版本?"这种,不涉及 AI。五项齐了状态变 ready。

这里措辞我卡得比较死:填齐了只说"可进入方案评估",不会说"方案一定可行"。信息完整跟方案可行是两码事,工具不越这个界。

## 状态

incomplete / ready / confirmed 三个。前两个是点检查自动判的,confirmed 只能人手动点。字段补得再齐也不会自动变 confirmed——机器把信息补齐了不代表人认可了,这两件事必须分开。

确认之后要是又改了核心字段,状态自动退回去(信息还齐退 ready,有缺退 incomplete),得重新确认。主要是防"早就确认过了,但内容其实早变了"这种事。

## 来源

每个字段能记个来源,就三个选项:客户说的、内部资料查的、售前自己整理的。因为同样一句"版本 3.2",客户白纸黑字写的和你从旧资料翻出来的,可信度完全不一样,记下来以后回溯有据可查。

改了字段值,之前记的来源会自动清掉重新选。值都变了,旧来源说明的是旧值,留着是误导。

来源不参与完整性判断,字段有值就算完整,没记来源最多页面提醒一句。

澄清项不是单独维护的一套,直接从字段推出来:字段有值对应澄清项就是已确认,空着就是待处理,所以不会出现字段填了澄清项还挂着的情况。

## 跑起来

```bash
pip install -r requirements.txt
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

打开 http://127.0.0.1:8000。数据库默认在 `backend/data/clarifier.db`,要改设 `CRC_DB_PATH`。

测试:

```bash
cd backend
python -m pytest tests -q
```

顺手也可以跑下 `python -m compileall -q app tests` 和 `node --check app/static/app.js`,几秒钟的事。

## 接口

```
GET    /api/health
GET    /api/requirement-types
GET    /api/sources

GET    /api/projects
POST   /api/projects
GET    /api/projects/{id}
DELETE /api/projects/{id}

POST   /api/projects/{id}/requirements
GET    /api/projects/{id}/requirements
GET    /api/requirements/{id}
PATCH  /api/requirements/{id}
DELETE /api/requirements/{id}

POST   /api/requirements/{id}/check      # 完整性检查 -> incomplete/ready
POST   /api/requirements/{id}/confirm    # 人工确认,只有 ready 能确认
GET    /api/requirements/{id}/summary
```

存数据、跑检查、人工确认走三个不同接口,各管各的。PATCH 只存数据不改状态,/check 只出 incomplete 或 ready,confirmed 只能靠 /confirm。你在 PATCH 里直接塞 status 会被拒(400)——就是防止绕过确认这步。

## 流程

建项目 → 建需求 → 填信息记来源 → 保存检查 → 看缺什么 → 找客户补 → 再检查 → 齐了 → 人工点确认 → 拿摘要走下一步。

## 不做的事

不用 AI,不接外部 API。不判断客户说的是不是真话,不判断方案可不可行,不做方案不报价。没有登录权限多租户,单机小工具一个。

