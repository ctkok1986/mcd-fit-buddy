# MCP 接入与调用流程说明

> 本项目真实使用 **麦当劳中国官方 MCP Server**（`mcp.mcd.cn`），
> 通过 Model Context Protocol 的 `streamablehttp` 传输方式接入 WorkBuddy。

---

## 一、使用的 MCP Server

| 项目 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 服务地址 | `https://mcp.mcd.cn` |
| 传输协议 | `streamablehttp` |
| 官方仓库 | [M-China/mcd-mcp-server](https://github.com/M-China/mcd-mcp-server) |
| 鉴权方式 | HTTP Header `Authorization: Bearer <MCP_TOKEN>` |

Token 通过官方开放平台 `open.mcd.cn/mcp` 申请，**不写入代码、不提交仓库**。

---

## 二、使用的 MCP Tools

### 配餐模块

| Tool | 用途 | 关键入参 |
|---|---|---|
| `list-nutrition-foods` | **数据地基**：158 项餐品营养表（热量/蛋白/脂肪/碳水/钠/钙） | 无 |
| `query-meals` | 取门店真实在售商品与价格、`productCode` | `storeCode` / `orderType` / `beType` |
| `query-nearby-stores` | 定位门店，取 `storeCode` | `beType` / `searchType` / `city` / `keyword` |
| `calculate-price` | 真实计价（验证方案可下单、算出实付） | `storeCode` / `orderType` / `beType` / `items[]` |

### 下单比价模块

| Tool | 用途 | 关键入参 |
|---|---|---|
| `delivery-query-addresses` | 取配送地址 `addressId` | 无 |
| `delivery-query-stores` | 按地址查可配送门店，取 `beCode` | `addressId` / `beType=2` |
| `query-nearby-stores` | 查到店自提门店，取 `storeCode` | `beType=1` / `searchType` / `city` / `keyword` |
| `calculate-price` | 逐渠道试算（含运费、打包费、券） | `storeCode` / `orderType` / `beType` / `items[]` |
| `create-order` | 创建订单（写入，需显式确认） | `storeCode` / `orderType` / `beType` / `takeWayCode` / `items[]` |

### 领券与活动模块

| Tool | 用途 |
|---|---|
| `auto-bind-coupons` | 一键领取全部可领券（写入操作） |
| `query-my-coupons` | 券仓全量 + 有效期（做临期预警） |
| `available-coupons` | 可领未领的券（找漏领损失） |
| `campaign-calendar` | 当月活动日历（进行中 / 往期 / 未来） |
| `query-my-account` | 积分账户（含过期积分字段） |

---

## 三、核心调用流程

### 流程 A：配餐求解

```
list-nutrition-foods           # 1. 拉取官方营养表（158 项）
        │
        ▼
  本地落盘 data/nutrition.csv
        │
        ▼
scripts/meal_planner.py        # 2. 纯本地求解（不依赖网络）
   ├─ Mifflin-St Jeor → BMR
   ├─ × 活动系数 → TDEE
   ├─ 施加双护栏 → 每日热量目标
   ├─ 1.8 g/kg → 蛋白目标
   └─ 槽位枚举 + 词典序打分 → 三餐组合
        │
        ▼
query-nearby-stores            # 3. 定位门店取 storeCode
        │
        ▼
query-meals                    # 4. 匹配 productCode 与实时价格
        │
        ▼
calculate-price                # 5. 验证方案真实可下单、算出实付金额
```

> **关键设计**：营养计算与配餐求解**完全在本地完成**（`data/nutrition.csv` 快照 + 纯标准库 Python）。
> 这样即使 MCP 连接中断，配餐功能依然可用；只有当用户要下单时才必须联网。

### 流程 B：麦麦早报

```
auto-bind-coupons   → 领光可领券（写入，需用户确认）
query-my-coupons    → 券仓 + 临期预警
query-my-account    → 积分过期预警
campaign-calendar   → 当日活动
        │
        ▼
   输出「今日麦当劳简报」
```

### 流程 C：下单比价（自动挑最优惠）

```
query-nearby-stores (beType=1)      # 1. 自提门店，取 storeCode，不传 beCode
delivery-query-addresses            # 2. 取 addressId
delivery-query-stores (beType=2)    # 3. 外送门店，取 storeCode + beCode
        │
        ▼
query-meals × 2                     # 4. 【关键】两渠道分别拉菜单
        │                             自提与外送 productCode 体系完全不同
        ▼
query-my-coupons                    # 5. 券按绑定的 productCode 判断适用渠道
        │
        ▼
calculate-price × N                 # 6. 逐渠道试算（含券/不含券）
        │                             必须核对返回的 productList 件数
        ▼
order_optimizer.py                  # 7. 本地比价 + 成本拆解 + 缺货预警
        │
        ▼
   用户显式确认金额
        │
        ▼
create-order                        # 8. 下单（写入）
```

> **为什么必须走两遍 `query-meals`**：自提与外送的商品编码是两套体系，
> 且无统一映射规则（`1120`→`901120` 看似九补零，但 `4648`→`900138` 就失效）。
> 必须按商品名分别查。

### 流程 D：方案落地到可支付

```
配餐方案 → 渠道比价 → 用户确认 → create-order → 用户支付
```

---

## 四、参数传递规则（易错点）

`orderType` 与 `beType` 必须配对：

| 场景 | beType | orderType | beCode |
|---|---|---|---|
| 到店自取 | 1 | 1 | 不传 |
| 得来速 DT | 5 | 1 | 必传 |
| 麦乐送 | 2 | 2 | 必传 |
| 企业团餐 | 6 | 2 | 必传 |

其他约束：
- `storeCode` 必须为**纯数字**
- `beCode` 只能由 `query-nearby-stores` / `delivery-query-stores` 返回，**不可编造**
- 价格字段单位是**分**，展示前需 ÷100
- `couponId` 与 `couponCode` 必须**配对**传递

---

## 五、业务价值

### 解决了什么真实问题

1. **把"随便吃点健康的"变成可验证的数学问题**
   用户输入身体参数，工具输出的是**在麦当劳菜单上数学可解的**最优组合，而不是泛泛的"少油少盐"。

2. **把不可达的目标提前暴露**
   减脂三大目标（热量/蛋白/钠）在麦当劳餐单上常常互斥。工具在**点餐前**就指出这一点，
   用户可以选择"今天控钠"还是"今天补蛋白"，而不是吃完才发现。

3. **守住安全边界**
   两条硬护栏（缺口 ≤ TDEE×25%、摄入 ≥ BMR×1.1）防止用户用极端节食伤害自己。
   实测中两条护栏都会被真实触发，工具如实报告并重算周期。

4. **闭环到可支付**
   方案不是纸上谈兵——通过 `query-meals` + `calculate-price` 可以验证方案真实可下单并算出实付金额。

---

## 六、安全与合规

- Token 通过环境变量 / 配置占位符管理，**仓库内不含任何真实 Token**
- 配餐计算**纯本地**，只有下单/领券等写入操作才需要联网
- `auto-bind-coupons`、`create-order` 等**写入操作必须经用户显式确认**
- **不接入任何社交数据**：麦当劳 MCP 无社交接口，本项目也不构造任何陌生人交互功能
- 所有营养数据以官方接口为准；本工具输出**不构成医疗或营养学建议**
