---
title: Unit Test with Mockito
date: 2025-03-01 17:10:31 +0800
categories: [Test]
tags: [Java, Mockito, Unit Test, Spring]
description: 自己平时写单元测试时使用到的一些 Mockito 案例
---

# Unit Test with Mockito

Tags: ItTest, Mock, MockStatic, Spring Event, UT, 未发布
备注: should be a blog in my Github blog project in some time

- `when … thenReturn …` 当执行某些方法时返回 mock 数据。
    
    ```java
    // userService should be annotated with @Mock
    when(userService).thenReturn(some_mock_value);
    ```
    
- `when … thenReturn …` 可以链式 thenReturn 多个 mock 值用于指定方法多次调用时返回不同的值。
    
    ```java
    @Test
    @DisplayName("每日分配上限测试-轮流分配+中间员工无分配权限")
    void test_daily_limit_with_middle_limit_0_should_ok() {
        when(mongoTemplate.find(any(), eq(ClueAutomaticAllot.class))).thenReturn(mockAllots);
        when(mongoTemplate.updateFirst(any(), any(), eq(defaultColl))).thenReturn(mockResult());
        when(clueAutomaticAllotRepo.saveAll(mockAllots)).thenReturn(null);
        when(userService.findAllByUserIdsIn(anyList()))
                .thenReturn(mockUserAllOnDuty(allotUserIds))
                .thenReturn(mockUserAllOnDuty(List.of("627a29d4b3e8940001ae07b0")))
                .thenReturn(mockUserAllOnDuty(List.of("627a29d4b3e8940001ae07b0")));
        when(mongoTemplate.aggregate(any(Aggregation.class), eq(defaultColl), eq(UserAllotData.class)))
                .thenReturn(mockAggResultEmpty())
                .thenReturn(mockAggResultWithLimit_1())
                .thenReturn(mockAggResultWithLimit_2());
    
        // 第一次分配给用户1
        clueAutomaticAllotService.autoAllot(mockInsertTask(List.of(matchPoolAndChannel_1())));
        assertEquals("61c877b13222fa00011c91bb", mockAllots.get(1).getLastAllotUser());
        // 第二次分配给用户3
        clueAutomaticAllotService.autoAllot(mockInsertTask(List.of(matchPoolAndChannel_1())));
        assertEquals("627a29d4b3e8940001ae07b0", mockAllots.get(1).getLastAllotUser());
        // 第三次分配给用户3
        clueAutomaticAllotService.autoAllot(mockInsertTask(List.of(matchPoolAndChannel_1())));
        assertEquals("627a29d4b3e8940001ae07b0", mockAllots.get(1).getLastAllotUser());
    
        // 相应的 event 事件代码逻辑应该执行了三次
        verify(opLogService, times(3)).publishOplog(any(OpLog.class));
        verify(eventPublisher, times(3)).publishEvent(any(ReclaimTaskEvent.class));
    }
    ```
    
- `thenAnswer()` 根据方法参数动态灵活的返回数据。
    
    ```java
    @ExtendWith(MockitoExtension.class)
    class PersonServiceTest {
    
        @Mock
        PersonRepository repository;
    
        @InjectMocks
        PersonService service;
    
        List<Person> people = List.of(
                new Person("1", "jack", 15),
                new Person("2", "jacsk", 16),
                new Person("3", "jackie", 17)
        );
    
        @Test
        void saveAllPeople() {
            when(repository.save(any(Person.class))) // mock save 操作
                    .thenAnswer(invocation -> invocation.getArgument(0)); // 返回传入的参数
            var ids = service.savePeople(people);
            assertThat(ids).hasSize(3); // 验证保存了 3 个对象
        }
    }
    ```
    
- `doNothing()`.when(mock).method(any(Argument.class))  **适用 void 方法**
    
    ```java
    doNothing().when(eventPublisher).publishEvent(any(ReclaimTaskEvent.class));
    ```
    
- `mockStatic`  静态方法 mock
    - 前提：在 `resources` 文件夹下创建 `mockito-extensions` 文件夹，创建 
    `org.mockito.plugins.MockMaker` 文件，内容为：`mock-maker-inline`
    - single static method
        
        ```java
        try (MockStatic<StaticClass> staticClass = Mockito.mockStatic(StaticClass.class)) {
            staticClass.when(StaticClsss::staticMethod).thenReturn(some_mock_value);
        }
        ```
        
    - nested static methods
        - nested try blocks with Mockito mockStatic statement！
        
        ```java
        try (MockedStatic<ServletUtil> servletUtilMockedStatic = Mockito.mockStatic(ServletUtil.class)) {
            try (MockedStatic<ContextUtil> contextUtilMockedStatic = Mockito.mockStatic(ContextUtil.class)) {
                contextUtilMockedStatic.when(ContextUtil::getServletRequest).thenReturn(null);
                contextUtilMockedStatic.when(ContextUtil::currentCusColl).thenReturn(cusColl);
                servletUtilMockedStatic.when(() -> ServletUtil.getClientIP(null)).thenReturn("0.0.0.0");
                ModifyResult result = customerService.pickUp(List.of(notDistributedOne));
                assertEquals(1, result.getSuccessCount());
                assertEquals(0, result.getFailedCount());
                // 更新后数据校验
                LinkedHashMap updated = findOne(notDistributedOne);
                assertEquals("已分配", updated.get("分配状态"));
                assertEquals(user.getId(), updated.get("followUser"));
                assertEquals(user.getName(), updated.get("跟进人"));
                assertEquals(user.getName(), updated.get("最近操作人"));
                assertEquals(1, updated.get("领取次数"));
            }
        }
        ```
        
- 验证方法执行次数 `verify + times`
    
    ```java
    // 校验发布事件次数
    verify(eventPublisher, times(1)).publishEvent(any(ReclaimTaskEvent.class));
    verify(eventPublisher, times(1)).publishEvent(any(OpLog.class));
    ```
    
- 验证方法执行顺序 `inOrder`
    
    ```java
    // verify the methods are called once, in the right order
    InOrder inOrder = inOrder(repository, translationService);
    inOrder.verify(repository).findById(anyInt());
    inOrder.verify(translationService).translate(anyString(), eq("en"), eq("en"));
    ```
    
- `spy()` 用于部分 mock
    
    1. You can intercept method calls to the dependencies for later verification.
    2. You can mock some methods in the dependencies rather than all of them. This is called a *partial mock*.
    
    ```java
    @Test
    void spyOnRepository() {
        // Spy on the in-memory repository
    		PersonRepository personRepo = spy(new InMemoryPersonRepository()); 
    		PersonService personService = new PersonService(personRepo);
    		personService.savePeople(people.toArray(Person[]::new)); assertThat(personRepo.findAll()).isEqualTo(people);
        // Verify the method calls on the spy
        verify(personRepo, times(people.size())).save(any(Person.class));
    }
    ```
    
- 方法入参校验 ArgumentMatcher
    1. 基本类型系列：**anyByte**, **anyShort**, **anyInt**, **anyLong**, **anyFloat**, **anyDouble**, **anyChar**, and **anyBoolean**.
    2. 集合类型系列：**anyCollection**, **anyList**, **anySet**, and **anyMap**
    3. 字符串系列：**anyString**, **startsWith**, **endsWith**, and the two overloads of matches, one that takes a regular expression as a string and the other a Pattern.
    4. null 检查：**isNull** and **isNotNull** (and its companion, **notNull**, which is just an alias), and n**ullable(Class)**, which matches either null or a given type.
    5. 等值判断：**eq()**
- 自定义方法入参校验器
    1. 实现 `ArgumentMatcher<T>`
    2. `argThat()` + lambda Predicate
    
    ⚠️ 如果是基本类型参数需要对应使用 **byteThat**, **shortThat**, **charThat**, **intThat**, **longThat**, **floatThat**, **doubleThat**, and **booleanThat**. 此举可避免因为装拆箱问题引起的 NPE 问题。
    
    ```java
    when(userRepo.findById(argThat(id -> id.startsWith("user")))).thenReturn(Optional.of(user));
    ```
    
- [Spring Boot Application Event Test](https://rieckpil.de/record-spring-events-when-testing-spring-boot-applications/)
- [@DataMongoTest with testcontainers](https://rieckpil.de/mongodb-testcontainers-setup-for-datamongotest/)
- BDDMockito given/when/then 写法：
    
    ```java
    @Test
    public void findMaxId_BDD() {
        given(repository.findAll()).willReturn(people);
        assertThat(service.getHighestId()).isEqualTo(14);
        then(repository).should().findAll();
    }
    ```
    
- Mock send spring event and consume spring event
    - 针对 `ApplicationEvent` 事件可以断言单个方法内发送了几次 event.
        
        ```java
        // 校验发布事件次数
        verify(eventPublisher, times(1)).publishEvent(any(ReclaimTaskEvent.class));
        verify(eventPublisher, times(1)).publishEvent(any(OpLog.class));
        ```
        
- How to assert a rest api with MockMvc
    
    ```java
    MvcResult result = mockMvc.perform(post("/api/users").header("Authorization", base64ForTestUser).contentType(MediaType.APPLICATION_JSON)
                .content("{\"userName\":\"testUserDetails\",\"firstName\":\"xxx\",\"lastName\":\"xxx\",\"password\":\"xxx\"}"))
                .andDo(MockMvcResultHandlers.print())
                .andExpect(status().isBadRequest())
    						.andExpect(jsonPath("data.total").value(5))
    						// 对于 json 数组的中元素字段进行断言
    						.andExpect(jsonPath("data.content.[0].createUser").value("62c7ec65baaca09ad14dbd9f"))
    						// todo 也会有中文乱码问题
    						.andExpect(content().string(Matchers.containsString("expected string")))
                .andReturn();
    
    // 指定编码防止中文乱码
    String content = result.getResponse().getContentAsString(StandardCharsets.UTF_8);
    // do what you want, usually do some assertions
    ```
    

[Mock, Stub, Spy](https://www.notion.so/Mock-Stub-Spy-5a0abffb89f240c381b2f616ded41441?pvs=21)