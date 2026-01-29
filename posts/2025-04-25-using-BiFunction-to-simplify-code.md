---
title: 使用 BiFunction 简化重复代码
date: 2025-04-25 13:30:30 +0800
categories: [Java]
tags: [Java, 函数事编程]
description: 第一次在代码里使用 BiFunction 来做重构简化代码，做个记录
---


Java 8 函数式编程的语言特性发布这么久，在平时的业务代码里用的做多的还是 Stream 相关的 API，比如 `map`, `filter`, `flatMap` 等，其他函数类方法用的最多的就是 `Function<T, R>`，`Consumer<T>` 和 `Supplier<T>` 等，可以用它们来作为通用参数，能够减少很多的相似代码，比如下面的代码：
```java
public static <T> Long sumLong(Function<T, Long> mapper, final List<T> list) {
	if (CollUtil.isEmpty(list)) return 0L;
	return list.stream().map(mapper).reduce(0L, Long::sum);
}
```

在计算某个列表的某个字段和时，使用这个方法就很方便。但是 `Function<T, R>` 只能接收一个参数，当需要接收两个参数时，就可以考虑使用 `BiFunction` 了。 `BiFunction` 是一个函数式接口，它接收两个参数，返回一个结果，它还有一个 `andThen(Function<? super R, ? extends V> after)` 方法，用于处理 apply 方法处理后的结果再处理。下面是它的定义：

```java
/**
 * Represents a function that accepts two arguments and produces a result.
 * This is the two-arity specialization of {@link Function}.
 *
 * <p>This is a <a href="package-summary.html">functional interface</a>
 * whose functional method is {@link #apply(Object, Object)}.
 *
 * @param <T> the type of the first argument to the function
 * @param <U> the type of the second argument to the function
 * @param <R> the type of the result of the function
 *
 * @see Function
 * @since 1.8
 */
@FunctionalInterface
public interface BiFunction<T, U, R> {

    /**
     * Applies this function to the given arguments.
     *
     * @param t the first function argument
     * @param u the second function argument
     * @return the function result
     */
    R apply(T t, U u);

    /**
     * Returns a composed function that first applies this function to
     * its input, and then applies the {@code after} function to the result.
     * If evaluation of either function throws an exception, it is relayed to
     * the caller of the composed function.
     *
     * @param <V> the type of output of the {@code after} function, and of the
     *           composed function
     * @param after the function to apply after this function is applied
     * @return a composed function that first applies this function and then
     * applies the {@code after} function
     * @throws NullPointerException if after is null
     */
    default <V> BiFunction<T, U, V> andThen(Function<? super R, ? extends V> after) {
        Objects.requireNonNull(after);
        return (T t, U u) -> after.apply(apply(t, u));
    }
}
```

之前有块业务代码的逻辑是拉取不同日期的巨量广告平台的流水和投放数据，除了数据结构和接口地址不一样以外，其他逻辑都一样，这种情况(需要根据自己的业务情况和方法参数等综合考量)就很适合使用 `BiFunction` 来简化代码，于是就有了下面的代码：
```java
/**
 * 
 * @param base 第三方接口返回的基本数据结构，包含错误码/失败信息等
 * @param pair 包含账号信息和日期信息等，用于再次调用接口
 * @param info 包含 access_token 信息，用于再次调用接口
 * @param dataFetcher 调用接口函数
 * @param dateF 业务用时间提取函数
 * @param advertiserF 业务用id提取函数
 * @param clazz 类型，主要记录日志信息，区分不同业务场景
 * @param coll 集合名称，业务用
 * @param <T> 不同业务场景的返回对象
 */
private <T> void  handleFailed(BaseDataResponse<?> base, Pair<AdvertiserAccountDetail, String> pair, AuthInfo info,
                            BiFunction<AuthInfo, Pair<AdvertiserAccountDetail, String>, List<T>> dataFetcher,
                            Function<T, String> dateF, Function<T, Long> advertiserF, Class<T> clazz, String coll) {
    var simpleName = clazz.getSimpleName();
    var name = pair.getFirst().getName();
    log.error("OceanEngine:{}:[{}:{}]获取广告主[{}]日[{}]数据失败，原因：[{}]:[{}]",
            simpleName, info.getAdPlatform(), info.getAccountName(),
            name, pair.getSecond(), base.getCode(), base.getMessage());
    if (base.oceanTooManyReq()) {
        var random = RandomUtil.randomInt(300, 600);
        CompletableFuture.delayedExecutor(random, TimeUnit.SECONDS).execute(() -> {
            var flows = dataFetcher.apply(info, pair);
            if (CollUtil.isEmpty(flows)) return;
            BulkOperations operations = mongoTemplate.bulkOps(BulkOperations.BulkMode.UNORDERED, coll);
            flows.forEach(f -> {
                var query = query(Criteria.where("date").is(dateF.apply(f))
                        .and("advertiserId").is(advertiserF.apply(f)));
                Update update = MongoDBUtils.updateBuilder(f);
                operations.upsert(query, update);
            });
            var result = operations.execute();
            int size = result.getUpserts().size();
            log.info("OceanEngine:{}:随机[5-6分钟内]补偿任务，结果:[{}]:[{}]", simpleName, name, size);
        });
    }
}

// 调用1
handleFailed(base, pair, authInfo, this::getDailyReportList, OceanEngineDailyReport::getDate,
					OceanEngineDailyReport::getAdvertiserId, OceanEngineDailyReport.class,
					getDailyReportCollection());

// 调用1的函数实际方法
private List<OceanEngineDailyReport> getDailyReportList(AuthInfo authInfo, Pair<AdvertiserAccountDetail, String> pair) {
    //...
}

// 调用2
handleFailed(base, pair, authInfo, this::getDailyCashFlowList, OceanEngineDailyCashFlow::getDate,
					OceanEngineDailyCashFlow::getAdvertiserId, OceanEngineDailyCashFlow.class,
					getDailyCashFlowCollection());

// 调用2的函数实际方法                                   
private List<OceanEngineDailyCashFlow> getDailyCashFlowList(AuthInfo authInfo, Pair<AdvertiserAccountDetail, String> pair) {
    // ...
}
```
其实代码里还有很多这样可以重构简化的地方，`BiFunction` 确实是一个好用的工具，但是如果结合 `andThen` 方法高强度使用再加上业务复杂的话，可能也会有使代码可读性变差的风险。