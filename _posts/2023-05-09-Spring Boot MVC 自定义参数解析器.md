---
title: Spring Boot MVC 自定义参数解析器
date: 2023-05-09 13:30:30 +0800
categories: [技术, Java]
tags: [Spring,Java,Spring Web MVC]     # TAG names should always be lowercase
description: 使用 Spring Boot MVC 自定义参数解析器解析负责业务自定义参数
---



## 背景

- `遗留系统`：

```shell
遗留接口系统为 Golang + Gin + MongoDB 实现, MongoDB collection 的 field 字段为中文名而且不固定(可以通过 excel 文件自定义表头的形式添加), 查询参数是直接传的中文形式, 而且传参不固定(query参数的 key 和 value 都不固定)，如：/api/v1/customers?姓名=张三&录入时间=2022-09-01 00:00:00&录入时间=2022-09-02 23:59:59
```

- `问题`：

```shell
go 工程师离职, 后端只有 java 工程师的情况下，将此接口改用 java 重写一遍，但传参方式不变(query key 还是为中文)
```

## 实现



### 可选方案

- **方案一**：不用 java 改写，java 工程师维护 golang 项目
  - 优点：代码改动最小，出现 bug 的概率也最小
  - 缺点：需要花时间学习 go 语言和相关项目
- **方案二**：获取 HttpServletRequset 对象, 在相应的接口入口层进行参数处理
  - 优点：能够获取到所有参数，快速实现功能
  - 缺点：针对特定接口实现，不利于代码扩展
- **方案三**：自定义 MVC 层参数解析器解析请求参数并绑定
  - 优点：能够抽取此类需求的公共参数,结合反射和注解机制利于相似需求的扩展
  - 缺点：相对于方案二性能可能会差一点。
    - 涉及到反射处理

### 方案三实现

- MVC 方法参数处理器接口 **HandlerMethodArgumentResolver**

```java
public interface HandlerMethodArgumentResolver {

	/**
	 * 此解析器是否支持该方法参数的解析
	 */
	boolean supportsParameter(MethodParameter parameter);

	/**
	 * 将拿到的原始数据解析成想要的参数对象
	 * A {@link ModelAndViewContainer} provides access to the model for the
	 * request. A {@link WebDataBinderFactory} provides a way to create
	 * a {@link WebDataBinder} instance when needed for data binding and
	 * type conversion purposes.
	 * @param parameter the method parameter to resolve. This parameter must
	 * have previously been passed to {@link #supportsParameter} which must
	 * have returned {@code true}.
	 * @param mavContainer the ModelAndViewContainer for the current request
	 * @param webRequest the current request
	 * @param binderFactory a factory for creating {@link WebDataBinder} instances
	 * @return the resolved argument value, or {@code null} if not resolvable
	 * @throws Exception in case of errors with the preparation of argument values
	 */
	@Nullable
	Object resolveArgument(MethodParameter parameter, @Nullable ModelAndViewContainer mavContainer,
			NativeWebRequest webRequest, @Nullable WebDataBinderFactory binderFactory) throws Exception;

}

```

- 实现自定义方法参数处理器

```java
@Slf4j
public class ZhFieldRequestResolver implements HandlerMethodArgumentResolver {

    @Override
    public boolean supportsParameter(MethodParameter parameter) {
        // 有 ZhBindConvertor 注解的参数才进行解析转换
        return parameter.hasParameterAnnotation(ZhBindConvertor.class);
    }

    @Override
    public Object resolveArgument(MethodParameter parameter, ModelAndViewContainer mavContainer,
                                  NativeWebRequest webRequest, WebDataBinderFactory binderFactory) throws Exception {
        HttpServletRequest request = webRequest.getNativeRequest(HttpServletRequest.class);
        assert request != null;
        // 获取参数类型，根据参数类型反射创建类型实例
        Class<?> resultType = parameter.getParameterType();
        return buildResultObject(resultType, request);
    }

    private Object buildResultObject(Class<?> resultType, HttpServletRequest request) throws InvocationTargetException,
            NoSuchMethodException, InstantiationException, IllegalAccessException, IOException {
        String method = request.getMethod();
        // 根据不同的 http 方法，使用不同的参数构建模式
        return switch (method) {
            case "POST" -> buildResultObjectForPost(resultType, request);
            case "GET" -> buildResultObjectForGet(resultType, request);
            default -> throw new IllegalStateException("不支持的 http 方法类型: " + method);
        };
    }

    /**
     * GET 方法直接通过 {@link ServletRequest#getParameterMap()} 方法获取请求参数
     */
    private Object buildResultObjectForGet(Class<?> resultType, HttpServletRequest request) throws NoSuchMethodException,
            InvocationTargetException, InstantiationException, IllegalAccessException {
        Map<String, String[]> parameterMap = request.getParameterMap();
        Map<String, List<String>> pMap = new HashMap<>();
        parameterMap.forEach((k, v) -> pMap.put(k, List.of(v)));
        Field[] fields = resultType.getDeclaredFields();
        Class<?> superclass = resultType.getSuperclass();
        Field[] superFields = null;
        if (!superclass.equals(Object.class)) {
            superFields = superclass.getDeclaredFields();
        }
        // 反射实例化参数对象        
        Object instance = resultType.getDeclaredConstructor(null).newInstance(null);
        // 填充对象字段信息        
        setFieldsForGet(fields, instance, parameterMap, pMap);
        if (superFields != null) {
            setFieldsForGet(superFields, instance, parameterMap, pMap);
        }
        return instance;
    }

    /**
     * 通过 field type 来设置对应的字段值
     * https://docs.oracle.com/javase/tutorial/reflect/member/fieldTypes.html
     */
    private void setFieldsForGet(Field[] fields, Object instance, Map<String, String[]> parameterMap, Map<String,
            List<String>> pMap) throws IllegalAccessException {
        for (Field f : fields) {
            f.setAccessible(true);
            String typeName = f.getGenericType().getTypeName();
            ZhBindAlias bindAlias = f.getAnnotation(ZhBindAlias.class);
            if (Objects.nonNull(bindAlias)) {
                String name = bindAlias.value();
                int index = bindAlias.index();
                String[] values = parameterMap.get(name);
                if (values != null && values.length > 0) {
                    Object convertValue = FieldTypeConvertor.FieldType.of(typeName).convert(values, index);
                    f.set(instance, convertValue);
                }
                pMap.remove(name);
                if ("extras".equals(f.getName()) && !pMap.isEmpty()) {
                    f.set(instance, pMap);
                }
            } else {
                String[] values = parameterMap.get(f.getName());
                if (values != null && values.length > 0) {
                    Object convertValue = FieldTypeConvertor.FieldType.of(typeName).convertFirst(values);
                    f.set(instance, convertValue);
                }
                pMap.remove(f.getName());
            }
        }
    }

    /**
     * POST 方法通过获取请求体 json 字符串转请求对象的方式获取参数信息
     */
    private Object buildResultObjectForPost(Class<?> resultType, HttpServletRequest request) throws NoSuchMethodException,
            InvocationTargetException, InstantiationException, IllegalAccessException, IOException {
        // 验证 header 的 Content-Type 为 application/json 才能进行后续操作
        String contentTypeHeader = request.getHeader(HttpHeaders.CONTENT_TYPE);
        if (StringUtils.isBlank(contentTypeHeader) || !contentTypeHeader.equals(MediaType.APPLICATION_JSON_VALUE)) {
            throw new IllegalStateException("请设置 Content-Type 值为 application/json");
        }
        Field[] fields = resultType.getDeclaredFields();
        Class<?> superclass = resultType.getSuperclass();
        Field[] superFields = null;
        if (!superclass.equals(Object.class)) {
            superFields = superclass.getDeclaredFields();
        }
        Object instance = resultType.getDeclaredConstructor(null).newInstance(null);
        StringBuilder sb = new StringBuilder();
        try (BufferedReader reader = request.getReader()) {
            String line = reader.readLine();
            while (StringUtils.isNotBlank(line)) {
                sb.append(line);
                line = reader.readLine();
            }
            log.info("uri:{},请求体参数:{}", request.getRequestURI(), sb);
            JSONObject body = JSON.parseObject(sb.toString());
            setFields(fields, body, instance);
            setFields(superFields, body, instance);
        }
        return instance;
    }

    private void setFields(Field[] fields, JSONObject source, Object target) throws IllegalAccessException {
        if (Objects.isNull(fields) || fields.length == 0) return;
        for (Field f : fields) {
            f.setAccessible(true);
            String fName = f.getName();
            String typeName = f.getGenericType().getTypeName();
            ZhBindAlias bindAlias = f.getAnnotation(ZhBindAlias.class);
            if (Objects.nonNull(bindAlias)) {
                String name = bindAlias.value();
                int index = bindAlias.index();
                Object o = source.get(name);
                if ("extras".equals(fName)) {
                    f.set(target, jsonObjectToMap(source));
                }
                if (Objects.isNull(o)) continue;
                Object convertValue = FieldTypeConvertor.FieldType.of(typeName).convertJsonObject(o, index, name);
                f.set(target, convertValue);
                source.remove(name);
            } else {
                Object o = source.get(fName);
                if (Objects.isNull(o)) continue;
                Object convertValue = FieldTypeConvertor.FieldType.of(typeName).convertJsonObject(o, 0, fName);
                f.set(target, convertValue);
                source.remove(fName);
            }
        }
    }

    private Map<String, List<String>> jsonObjectToMap(JSONObject object) {
        TypeReference<List<String>> type = new TypeReference<>(){};
        Map<String, List<String>> value = new HashMap<>();
        object.forEach((k, v) -> {
            List<String> list = JSON.parseObject(v.toString(), type);
            value.put(k, list);
        });
        return value;
    }
}
```

- 配置 **WebMvcConfigurer** 使自定义参数解析器生效

```java
@Configuration
public class WebConfig implements WebMvcConfigurer {

    @Override
    public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
        resolvers.add(new ZhFieldRequestResolver());
    }
}
```

- 自定义注解用于标注解析后的参数接收类

```java
/**
 * 中文请求参数转换,请求实体字段配合 {@link ZhBindAlias} 使用
 * 实现原理：自定义实现 mvc 参数转换器 {@link org.springframework.web.method.support.HandlerMethodArgumentResolver}
 */
@Documented
@Target(ElementType.PARAMETER)
@Retention(RetentionPolicy.RUNTIME)
public @interface ZhBindConvertor {

    boolean required() default true;
}

@Target(ElementType.FIELD)
@Retention(RetentionPolicy.RUNTIME)
public @interface ZhBindAlias {
    /** 字段的中文别名 */
    String value();

    /** 同名的情况下绑定到第几个参数 */
    int index() default 0;

    /** 是否默认添加到 query 条件构建中 */
    boolean includeQuery() default true;
}
```

- 抽取公用查询参数类

```java
/**
 * 公共查询参数
 */
@Data
public abstract class ZhSearchReq {

    @ZhBindAlias("录入时间")
    private String startTime;

    @ZhBindAlias(value = "录入时间", index = 1)
    private String endTime;

    /** 自定义查询字段(对应变化的部分) */
    @ZhBindAlias(value = "extra", includeQuery = false)
    private Map<String, List<String>> extras;

    /**
     * 排序字段, json 字符串，示例：
     * {“录入时间”: "ascend", "分配时间": "descend"}
     * 按录入时间升序，分配时间降序排列，默认升序
     */
    private String sorter;

    @Min(1)
    @ZhBindAlias(value = "current", includeQuery = false)
    private Integer current = 1;

    @Min(1)
    @ZhBindAlias(value = "pageSize", includeQuery = false)
    private Integer pageSize = 50;

    /** 默认按录入时间降序排列 */
    private Sort defaultSort() {
        return Sort.by("录入时间").descending();
    }

    /**
     * 获取子类字段的值,子类需要有 getter 方法
     * @deprecated
     */
    private void filedCriteriaForSubClass(Criteria criteria, Field f) {
        Method[] methods = this.getClass().getDeclaredMethods();
        String name = f.getName();
        Stream.of(methods)
                .filter(m -> m.getName().startsWith("get") && m.getName().toLowerCase().contains(name.toLowerCase()))
                .findAny()
                .ifPresent(m -> {
                    try {
                        Object value = m.invoke(this, null);
                        // filedCriteria(criteria, f, value);
                    } catch (IllegalAccessException e) {
                        e.printStackTrace();
                    } catch (InvocationTargetException e) {
                        e.printStackTrace();
                    }
                });
    }

    public Sort sort() {
        String sorter = getSorter();
        if (StringUtils.isEmpty(sorter)) return defaultSort();
        HashMap sorterMap = JSONObject.parseObject(sorter, HashMap.class);
        if (sorterMap.isEmpty()) return defaultSort();
        List<Sort.Order> orders = new ArrayList<>(sorterMap.size());
        sorterMap.forEach((k, v) -> {
            Sort.Order order;
            if (v.equals("descend")) {
                order = Sort.Order.desc(k.toString());
            } else {
                order = Sort.Order.asc(k.toString());
            }
            orders.add(order);
        });
        if (orders.isEmpty()) return defaultSort();
        return Sort.by(orders);
    }

    /**
     * 由于数据库选型原因，与 MongoDB 查询条件强绑定
     */
    public Criteria getQueryCriteria() {
        Criteria criteria = new Criteria();
        Class<? extends ZhSearchReq> reqClass = this.getClass();
        Class<?> superclass = reqClass.getSuperclass();
        Field[] superFields = new Field[0];
        if (!superclass.equals(Object.class)) {
            superFields = superclass.getDeclaredFields();
        }
        Field[] fields = reqClass.getDeclaredFields();
        Arrays.stream(fields).forEach(f -> filedCriteria(criteria, f));
        Arrays.stream(superFields).forEach(f -> filedCriteria(criteria, f));
        if (StringUtils.isNotBlank(getStartTime()) && StringUtils.isNotBlank(getEndTime())) {
            criteria.and("录入时间").gte(getStartTime()).lte(getEndTime());
        }
        // 对于动态参数的处理
        if (MapUtil.isNotEmpty(extras)) {
            extras.forEach((k, v) -> {
                if (CollUtil.isNotEmpty(v)) {
                    // warning 与具体业务逻辑相关,可以前端确定公用的处理模型
                    if (!v.contains("全选")) {
                        if (v.size() == 1) {
                            // 根据业务逻辑确定单值的查询定义
                            criteria.and(k).is(v.get(0));
                        } else {
                            // 根据业务逻辑确定多值的查询定义
                            criteria.and(k).in(v);
                        }
                    }
                }
            });
        }
        return criteria;
    }

    /**
     * 对于单个查询参数的处理
     */
    protected void filedCriteria(Criteria criteria, Field f) {
        String fName = f.getName();
        if ("sorter".equals(fName)) return;
        String typeName = f.getGenericType().getTypeName();
        ZhBindAlias alias = f.getAnnotation(ZhBindAlias.class);
        Object value = null;
        try {
            f.setAccessible(true);
            value = f.get(this);
        } catch (IllegalAccessException e) {
            // 内部调用，不会有问题
            e.printStackTrace();
        }
        if (Objects.isNull(value)) return;
        if (Objects.nonNull(alias)) {
            if (!alias.includeQuery()) return;
            String where = alias.value();
            if ("java.lang.String".equals(typeName) && !where.contains("时间")) {
                // 单值采用前缀匹配查询
                criteria.and(where).regex("^" + value);
            } else if ("java.util.List<java.lang.String>".equals(typeName) && !where.contains("时间")) {
                List<String> values = (List<String>) value;
                if (!values.contains("全选")) {
                    // 多值采用 $in 查询
                    criteria.and(where).in(values);
                }
            }
        } else {
            // 等值查询
            criteria.and(fName).is(value);
        }
    }
}
```

- 扩展查询参数类

```java
@Data
public class CustomerSearchReq extends ZhSearchReq {

    @ZhBindAlias("跟进状态")
    private List<String> followState;

    @ZhBindAlias("手机号")
    private String mobile;

    @ZhBindAlias("姓名")
    private String name;
}
```

- 使用

```java
@GetMapping()
@Operation(summary = "线索列表")
public R<PageResult<LinkedHashMap>> searchPage(@ZhBindConvertor CustomerSearchReq searchReq) {
    return R.ok(customerSearchService.search(searchReq));
}
```

- 重构质量保证-测试用例
  - 只写了集成测试用例，保证基本的全流程准确性

## 总结

### 涉及知识点

- Spring
  - SpringMVC 参数绑定流程及自定义参数解析器实现
    - GET 类型请求参数解析
    - POST 类型请求参数解析
  - 自定义参数解析器如何配置生效
- 反射:
  - 根据类型实例化对象
  - 字段信息获取与对象字段设置
  - 字段类型信息获取和区分各种不同类型
  - 父类字段信息获取以及子类字段信息如何获取
  - 对象示例方法信息获取和方法执行
- 自定义注解的使用
- 测试用例
  - 使用了 testcontainers + docker mongodb + mockmvc 编写集成测试用例
  - json 文件 + MongoTemplate#insert 完成测试前数据准备
  - MongoTemplate#dropCollection 完成测试后数据清理
  - MockMvc 对于响应数据的各种准确性断言

### 遇到的问题

- 父类方法反射获取子类字段的取值(子类实例调用时)
  - 解决：忘记了 **f.setAccessible(true)**;
  - 没有 f.setAccessible(true) 的时候也可以使用调用反射方法 getter + field name 的方式获取值，但很不 clean 也会有更大性能开销？[benchmark](https://github.com/Xuguozong/custom_mvc_method_argument_resolver/blob/main/src/test/java/com/example/benchmark/ReflectFieldGetVSGetterMethodInvoke.java)

- spring doc openapi 参数转换器问题
  - 通过 WebMvcConfigurer#addArgumentResolvers 解决


### 存在的问题及可以继续改进的地方

- 公用查询参数类只支持一层继承体系类的处理，可以根据业务实际需要做支持处理或做规范
- 公用查询参数类获取 query 条件的方法与数据库类型以及业务强绑定，可以在这一层根据实际需求再做一层抽象
- 由于业务逻辑简单，没有做单元测试，只做了集成测试
- 反射获取字段信息时没有做缓存，可以 [benchmark](https://github.com/Xuguozong/custom_mvc_method_argument_resolver/blob/main/src/test/java/com/example/benchmark/ReflectGetFieldsUsingCacheOrNot.java) 下看看对于应用的性能提升





## 参考及示例代码

代码：

[custom_mvc_method_argument_resolver](https://github.com/Xuguozong/custom_mvc_method_argument_resolver)

参考：

[Spring From the Trenches: Creating a Custom HandlerMethodArgumentResolver](https://www.petrikainulainen.net/programming/spring-framework/spring-from-the-trenches-creating-a-custom-handlermethodargumentresolver/)

[mvc-ann-methods](https://docs.spring.io/spring-framework/docs/current/reference/html/web.html#mvc-ann-methods)

[oracle-reflect-fieldTypes](https://docs.oracle.com/javase/tutorial/reflect/member/fieldTypes.html)

<!-- ##{"timestamp":1683634903}## -->