# Scripts

博客辅助脚本集合，用于管理阅读数据和跑步数据。

## 脚本列表

### add_book.py

通过 ISBN 查询书籍信息并添加到 `reading-data/books.json`。

**数据源**（按优先级）：
1. Google Books API（需要 `GOOGLE_BOOKS_API_KEY`）
2. Open Library API（免费，无需密钥）

**用法**：

```bash
# 添加到想读列表
python scripts/add_book.py add --isbn 9787532153626

# 标记为在读
python scripts/add_book.py add --isbn 9787532153626 --status reading

# 标记为已读并评分
python scripts/add_book.py add --isbn 9787532153626 --status finished --rating 5 --tags 写作 文学

# 指定起止日期
python scripts/add_book.py add --isbn 9787532153626 --status finished \
  --started-at 2026-01-01 --finished-at 2026-03-15 --rating 4 --notes "值得重读"

# 更新已有书籍：添加短评和评分
python scripts/add_book.py update --isbn 9787532153626 --notes "非常好的一本书" --rating 4

# 更新阅读状态和日期
python scripts/add_book.py update --isbn 9787532153626 --status finished --finished-at 2026-05-28

# 更新摘要
python scripts/add_book.py update --isbn 9787532153626 --description "一本关于写作的回忆录"
```

**add 子命令参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--isbn` | 是 | ISBN 编号（10 或 13 位） |
| `--status` | 否 | 阅读状态：`reading` / `finished` / `wishlist`（默认 `wishlist`） |
| `--tags` | 否 | 标签列表 |
| `--rating` | 否 | 评分 1-5 |
| `--notes` | 否 | 短评（可多次 update 追加，每条带日期） |
| `--started-at` | 否 | 开始阅读日期（YYYY-MM-DD） |
| `--finished-at` | 否 | 读完日期（YYYY-MM-DD） |

**update 子命令参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--isbn` | 是 | 要更新的书籍 ISBN |
| `--status` | 否 | 更新阅读状态 |
| `--rating` | 否 | 更新评分 1-5 |
| `--notes` | 否 | 追加一条笔记（带日期，不覆盖已有） |
| `--description` | 否 | 更新书籍摘要/简介 |
| `--started-at` | 否 | 更新开始阅读日期 |
| `--finished-at` | 否 | 更新读完日期 |
| `--tags` | 否 | 更新标签 |

脚本会自动下载封面到 `assets/img/reading/{isbn}.jpg`，重复 ISBN 会提示使用 `update` 子命令。

API 密钥通过环境变量 `GOOGLE_BOOKS_API_KEY` 或项目根目录 `.env` 文件提供。

### add_quote.py

添加阅读摘录/高亮到 `reading-data/quotes.json`。

**用法**：

```bash
# 通过 ISBN 自动关联书籍
python scripts/add_quote.py --content "写作是一种心灵感应" --book 9787532153626 --page 42

# 手动指定书名
python scripts/add_quote.py --content "金句内容" --book-title "书名" --book-author "作者"

# 指定日期（默认今天）
python scripts/add_quote.py --content "金句" --book 9787532153626 --highlighted-at 2026-05-20
```

**参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--content` | 是 | 摘录内容 |
| `--book` | 否 | ISBN，自动从 books.json 查找书名和作者 |
| `--book-title` | 否 | 手动指定书名（与 --book 二选一） |
| `--book-author` | 否 | 手动指定作者 |
| `--page` | 否 | 页码 |
| `--highlighted-at` | 否 | 标注日期（YYYY-MM-DD，默认今天） |

### add_body.py

添加体测记录（体重、体脂率）到 `running-data/body.json`。

**用法**：

```bash
# 记录今天的体重和体脂
python scripts/add_body.py 70.5 18.2

# 指定日期
python scripts/add_body.py 70.5 18.2 2026-05-20
```

同一日期重复添加会覆盖已有记录，数据按日期排序保存。

### sync_garmin.py

从 Garmin CN 同步跑步数据到 `running-data/activities.json`。

**用法**：

```bash
# 通过命令行参数
python scripts/sync_garmin.py --secret "<oauth_secret_string>"

# 通过环境变量
export GARMIN_SECRET="<oauth_secret_string>"
python scripts/sync_garmin.py
```

功能：
- 使用 `garth` 库连接 Garmin CN（`garmin.cn`）
- 支持增量同步：已存在数据时仅拉取最近的记录
- 按日期聚合同一天的多条跑步记录（距离、时长加权平均心率和步频）
- 记录字段包括：距离、时长、配速、心率、步频、VO2Max

**依赖**：`pip install garth`
