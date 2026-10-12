# 麦当劳中国 MCP Server · 完整工具清单

> 接口地址：`https://mcp.mcd.cn`（streamablehttp）、鉴权 `Authorization: Bearer <token>`
> 本文是**全量清单（35 个工具）**；本项目实际用到的 12 个速查见 [`mcp-tools.md`](mcp-tools.md)
> 整理时间：2026-10-12 ｜ 来源：MCP 服务器 `tools/list` 返回的工具定义原文

---

## 总览

| 类别 | 数量 | 作用 |
|---|---|---|
| 一、营养与餐品 | 5 | 配餐求解的地基 |
| 二、门店与地址 | 4 | 定位「能点哪家」 |
| 三、订单 | 5 | 下单、查询、取消、满意度 |
| 四、优惠券与账户 | 5 | 券仓、领券、门店可用券、积分 |
| 五、活动与营销 | 2 | 活动日历、团餐促销规则 |
| 六、积分商城 | 5 | 积分兑换商品 |
| 七、派对与活动预约 | 5 | 生日派对 / 主题派对 / 品鉴会等包场拼团 |
| 八、积分抽奖 | 3 | 抽奖信息、抽奖、我的奖品 |
| 九、工具 | 1 | 服务器当前时间 |

### ⚠️ 写入类操作（会改变账户/订单状态）

| 工具 | 影响 |
|---|---|
| `create-order` | 创建真实订单 |
| `cancel-order` | 取消订单 |
| `auto-bind-coupons` | 领取全部可领券 |
| `delivery-create-address` | 新增配送地址 |
| `mall-create-order` | 积分兑换下单 |
| `party-order-create` | 派对下单 |
| `draw-lottery` | 消耗积分/次数抽奖 |

---

## 一、营养与餐品（5）

### `list-nutrition-foods`
- **用途**：获取麦当劳餐品营养成分（能量、蛋白质、脂肪、碳水、钠、钙）
- **入参**：无
- **本项目用法**：据此生成 `data/nutrition.csv`（158 项快照）
- **注意**：返回是 `\n` 分隔的类 CSV 字符串，需自行解析；部分行含中文描述（如「能量约清水1杯」），要容错

### `query-meals`
- **用途**：门店真实菜单（含价格、是否可下单）
- **必传**：`storeCode`、`orderType`、`beType`
- **可选**：`beCode`（得来速/外送/团餐必传）、`reservationDate`（预约场景）
- **注意**：`storeCode` 与营养表餐品名**并非一一对应**，需按名称匹配取 `productCode`

### `query-meal-detail`
- **用途**：餐品详情——套餐组成、**特调选项**（selectedKey / unselectedKey）
- **必传**：`storeCode`、`orderType`、`beType`、`code`
- **内置展示规则**：`supportModify=true` 要标【可特调】；不主动展开特调列表

### `calculate-price`
- **用途**：真实计价（含优惠），验证方案**能否真下单**
- **必传**：`storeCode`、`orderType`、`beType`
- **items[]**：`productCode` / `quantity` / `couponId` / `couponCode` / `modification` / `roundList`（套餐子项）
- **其他**：`withOrder`（随单购）、`needTableware`、`gmServiceCode`（团餐）
- **注意**：价格单位是**分**，展示前 ÷100

### `query-meal-assistance`
- **用途**：团餐助餐服务（选完商品、计价前拿 `gmServiceCode`）
- **限制**：**仅企业团餐（beType=6）**可用

---

## 二、门店与地址（4）

### `query-nearby-stores`
- **用途**：到店场景查可点餐门店
- **必传**：`beType`（1 到店自提 / 5 得来速）、`searchType`（1 搜收藏 / 2 按位置搜）
- **注意**：`beType=5` 返回带 `beCode`，后续**必须**传；`beType=1` 无 `beCode`

### `delivery-query-stores`
- **用途**：外送场景——按 `addressId` 查可配送门店，取 `beCode`
- **必传**：`beType`（2 麦乐送 / 6 团餐）、`addressId`

### `delivery-query-addresses`
- **用途**：配送地址列表（取 `addressId`）
- **入参**：无

### `delivery-create-address`
- **用途**：新增配送地址 ⚠️ 写入
- **必填**：`city` / `contactName` / `phone`（11 位纯数字）/ `address` / `addressDetail`

---

## 三、订单（5）

### `create-order`
- **用途**：创建真实订单 ⚠️ 写入
- **必传**：`storeCode`、`orderType`、`beType`
- **到店场景**：`takeWayCode` 必传（取自 `calculate-price` 的 `takeWayList[].code`，**严禁硬编码**——实测不同门店值不同）
- **外送场景**：`addressId` 必传；可传 `remark`（≤50 字）
- **items[]**：与 `calculate-price` 同构

### `query-order`
- **用途**：订单详情 / 状态（下单后引导用户支付，回来查状态）
- **必传**：`orderId`

### `order-list`
- **用途**：历史订单（**非**商城订单）
- **入参**：无

### `cancel-order`
- **用途**：取消订单 ⚠️ 写入
- **必传**：`orderId`、`cancelReasonCode`
- **原因码**：1 改主意 / 2 重复下单 / 3 点错 / 4 地址电话错 / 5 送达时间错 / -1 其它

### `query-survey-coupon`
- **用途**：按订单号查 CSAT 满意度答卷 + 关联奖券（核销状态、点餐方式）
- **必传**：`orderId`（由用户提供，**不得自行编造**）

---

## 四、优惠券与账户（5）

### `query-my-coupons`
- **用途**：卡包里的券（存量 + 有效期）
- **入参**：`page` / `pageSize`（默认 200）
- **⚠️ 关键**：**不校验门店/渠道适用性**——「我有什么券」用它；「这家店能用什么券」要用 `query-store-coupons`

### `query-store-coupons`
- **用途**：**指定门店 + 订单类型**下可用的券
- **必传**：`storeCode`（纯数字）、`orderType`、`beType`

### `available-coupons`
- **用途**：可领但未领的券列表
- **入参**：无

### `auto-bind-coupons`
- **用途**：一键领取所有可领券 ⚠️ 写入
- **注意**：实测**领券回报 ≠ 可用**，需二次确认

### `query-my-account`
- **用途**：积分账户（含过期积分）
- **入参**：无

---

## 五、活动与营销（2）

### `campaign-calendar`
- **用途**：当月营销活动日历（进行中 / 往期 / 未来）
- **可选**：`specifiedDate`（传则返回该日前后各一个有活动的日子）

### `query-promotions`
- **用途**：促销规则（满减 / 满折）原始数据
- **限制**：**仅企业团餐（beType=6）**可用
- **返回**：`promotionId` / `promotionType`（31 满额减、33 订单折扣）/ `ruleDetail` / `products`
- **注意**：工具**不做最优推荐**，由模型自行解读规则

---

## 六、积分商城（5）

### `mall-points-products`
- **用途**：可兑换商品列表
- **可选**：`catRuleIds` 类目筛选（`1>4` 商品券、`2` 实物、`2>8` 周边、`2>9` 礼品卡、`1>6>20` 生日派对…）

### `mall-product-detail`
- **用途**：商品详情（返回全部 SKU，需选 SKU 才能下单）
- **必传**：`spuId`

### `mall-create-order`
- **用途**：积分兑换下单 ⚠️ 写入（仅 `shopId=2`）
- **必传**：`skuId`、`spuCategory`（1 虚拟 / 2 实物）；`spuCategory=2` 时需 `addressId`
- **注意**：**多商品必须分别下单**，且要排队等前一单响应成功；派对类走 `party-order-create`

### `mall-order-list` / `mall-order-detail`
- **用途**：商城订单列表 / 详情
- **入参**：`mall-order-list` 可选 `lastId` / `size`（≤10）；`mall-order-detail` 必传 `orderId`

---

## 七、派对与活动预约（5）

适用于：生日类派对 / 主题类派对 / 麦麦体验营 / 品鉴会 / 读书会 / 积分兑换活动（仅 `shopId=5`）

调用链**必须按顺序**，每步等用户选择：

```
query-party-city          → 哪些城市
      ↓（拿 code / 经纬度）
query-party-store         → 该城市哪些门店
      ↓（拿 storeCode）
query-party-store-date    → 该门店哪些日期可约
      ↓（拿 dateStr）
query-party-store-session → 当天有哪些场次（时间 / 余位 / 价格）
      ↓
party-order-create        → 下单 ⚠️ 写入（partyType：1 包场 / 2 拼团）
```

> 每个工具都要求先确定 `spuId`（来自 `mall-points-products` 或 `mall-product-detail`）。

---

## 八、积分抽奖（3）

### `query-lottery-info`
- **用途**：抽奖活动信息（奖品、单次消耗、剩余次数、可用积分）
- **重点字段**：`drawDecision.resourceEligible`（能否参与）、`drawDecision.nextConsumption`（本次实际扣减）

### `draw-lottery`
- **用途**：执行一次抽奖 ⚠️ 写入（消耗积分/次数）
- **硬约束**：必须先向用户展示 `nextConsumption` 并获**明确确认**；`resourceEligible=false` 不得调用；**严禁试抽/连抽**

### `query-my-prizes`
- **用途**：我的奖品（可用 / 已用 / 过期 / 已领 / 失效）
- **入参**：`pageNum` / `pageSize`（≤50）

---

## 九、工具（1）

### `now-time-info`
- **用途**：服务器当前时间（时间戳 / 格式化时间 / 时区 / UTC）
- **场景**：需要指定日期查活动日历、判断早餐时段等

---

## 附：本项目用到的子集（13 个）

`list-nutrition-foods`、`query-meals`、`calculate-price`、`query-meal-detail`、
`query-nearby-stores`、`delivery-query-stores`、`delivery-query-addresses`、
`create-order`、`query-order`、`auto-bind-coupons`、`query-my-coupons`、
`query-store-coupons`、`now-time-info`

> 详细实测要点（踩过的坑、参数传递规则、编码差异）见 [`mcp-tools.md`](mcp-tools.md)。
