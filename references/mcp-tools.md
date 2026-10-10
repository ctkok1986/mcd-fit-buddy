# 麦当劳中国 MCP Server · 减脂搭子常用工具速查

> 接口地址：`https://mcp.mcd.cn`（streamablehttp）
> 接入方式见 [`MCP_INTEGRATION.md`](../MCP_INTEGRATION.md)

---

## 一、配餐模块核心工具

### 1. `list-nutrition-foods` — 营养数据地基

**无入参**，一次性返回全量营养表。本项目据此生成 `data/nutrition.csv`（158 项）。

| 字段 | 含义 |
|---|---|
| `productName` | 餐品名称 |
| `energyKj` | 能量（千焦） |
| `energyKcal` | **能量（千卡）** |
| `protein` | 蛋白质（g） |
| `fat` | 脂肪（g） |
| `carbohydrate` | 碳水化合物（g） |
| `sodium` | **钠（mg）** |
| `calcium` | 钙（mg） |

> ⚠️ 数据表用 `\n` 分隔的类 CSV 字符串返回，需自行解析。
> 部分行含中文描述（如 `能量约清水1杯`），解析时需容错。

### 2. `query-meals` — 门店真实菜单

必传：`storeCode` / `orderType` / `beType`

返回：
- `categories[]` —— 分类与餐品 `code`
- `meals{}` —— 餐品详情映射：`name` / `currentPrice` / `originalPrice` / `canWithOrder`

> `storeCode` 与 `list-nutrition-foods` 的餐品名**并非一一对应**，需按名称匹配后取 `productCode`。

### 3. `calculate-price` — 真实计价

用于验证配餐方案**真实可下单**并算出实付金额。

| 字段（单位：分） | 含义 |
|---|---|
| `originalPrice` | 原价 |
| `price` | 现价 |
| `discount` | 优惠金额 |
| `takeWayList[]` | 取餐方式（`eat-in` 堂食 / `locker-in` 外带），下单必传 |

---

## 二、领券与活动工具

| 工具 | 用途 | 写入？ |
|---|---|---|
| `auto-bind-coupons` | 一键领取全部可领券 | ⚠️ 是 |
| `query-my-coupons` | 券仓全量 + `tradeDateTime` 有效期 | 否 |
| `available-coupons` | 可领未领的券 | 否 |
| `campaign-calendar` | 当月活动日历 | 否 |
| `query-my-account` | 积分账户（含 `expiredPoint`） | 否 |
| `query-store-coupons` | 指定门店可用券 | 否 |

### `tradeDateTime` 的三种形态

```
形态 A｜纯日期段     2026-10-10 00:00-2026-10-16 23:59
形态 B｜日期段+日窗  2026-10-05 00:00-2026-10-11 23:59 10:00-22:00
形态 C｜单日窄窗     2026-10-12 05:00-2026-10-12 10:29 周一 05:00-10:29
```

> 形态 C 最危险：**只在当天 5.5 小时内可用**。实测一份 15 张券的样本中占比 73%。

---

## 四、下单比价模块工具

| 工具 | 用途 | 写入？ |
|---|---|---|
| `delivery-query-addresses` | 配送地址列表，取 `addressId` | 否 |
| `delivery-query-stores` | 按 `addressId` 查可配送门店，取 `beCode` | 否 |
| `create-order` | 创建订单 | ⚠️ 是 |

### `calculate-price` 外送场景返回的额外字段

| 字段（单位：分） | 含义 |
|---|---|
| `productOriginalPrice` | 商品原价小计 |
| `productPrice` | 商品现价小计 |
| `deliveryPrice` | **运费** |
| `packingPrice` | **打包费** |
| `originalPrice` | 含运费打包费的总原价 |
| `price` | **最终实付** |

> 外送返回的 `productList` 里还会出现一条 `打包服务费`（如 `920174`），
> 其 `quantity` 为打包费的分值（19 表示 1.9 元），`subtotal` 为 0，统计时勿重复计入。

---

## 五、参数传递规则（易错点）

| 场景 | beType | orderType | beCode |
|---|---|---|---|
| 到店自取 | 1 | 1 | 不传 |
| 得来速 DT | 5 | 1 | 必传 |
| 麦乐送 | 2 | 2 | 必传 |
| 企业团餐 | 6 | 2 | 必传 |

- `storeCode` 必须为**纯数字**
- `beCode` 只能由门店查询接口返回，**不可编造**
- 价格单位是**分**，展示前 ÷100
- `couponId` 与 `couponCode` 必须**配对**传递

---

## 四、（续）实测要点（踩过的坑 · 下单部分）

7. **自提与外送是两套商品编码，且无映射规则**
   - 双层吉士汉堡：自提 `1120` / 外送 `901120`
   - 中薯条：自提 `4810` / 外送 `501205`
   - 不素之霸双层牛堡：自提 `4648` / 外送 `900138`（**不是 9+补零**）
   → 必须按商品名在两个渠道菜单中分别查 `productCode`

8. **外送商品单价普遍高于自提**
   - 双层吉士汉堡 ¥23.00 → ¥25.00
   - 中薯条 ¥14.00 → ¥15.50
   → 比价时不能假设"同款同价"

9. **`calculate-price` 会静默丢弃渠道不可售商品**
   - 请求 3 件走外送，返回 `success: true` 但 `productList` 只剩 1 件
   → **必须逐项比对 `productList` 与请求清单**

10. **券的渠道适用性必须实测，不能看标签**
    - 9.9 元冰美式券标签含「外送专用」，但外送编码计价返回 `600012 促销规则不支持该商品`
    → 券绑定的是自提编码

11. **`takeWayCode` 因门店而异**
    - 门店 1410143 返回 `eat-in` / `locker-in`
    - 门店 1410509 返回 `eat-in` / `take-in-store`
    → 必须从 `calculate-price` 返回的 `takeWayList` 中取，**严禁硬编码**

12. **外送附加费由接口返回，勿自行估算**
    - 实测：运费 ¥6.00 + 打包费 ¥1.90
    → 直接从 `deliveryPrice` / `packingPrice` 读取

---

## 六、实测要点（踩过的坑 · 券与账户部分）

1. **营养表与门店菜单是两套编码**：营养表无 `productCode`，需按名称匹配门店菜单。
2. **营养表有重复行**：如「小杯玉米杯」「纯牛奶（盒装）」各出现两次，去重后再用。
3. **`calculate-price` 的错误码 `600012`** 表示"当前优惠券不可用"，排查方向：
   商品不匹配 / 门店不支持 / 取餐方式不符 / 时段未到。
4. **券可用性随时段变化**：同一门店同一账户，早间与午后查询返回的可用券数量不同。
5. **领券回报 ≠ 券可用**：实测 `auto-bind-coupons` 报告成功 3 张，但其中 1 张
   未出现在券列表中，且计价返回 `600012`。需二次确认。
6. **门店营业时段影响可用性**：早餐券需门店在早餐时段营业。
