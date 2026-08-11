# QQ 工具集

为 AI 提供的 QQ 全功能工具箱，AI 通过 Agent 自主调用工具获取信息、执行操作。所有数据返回给 AI 处理，AI 根据结果组织回复。

**仅支持 aiocqhttp / OneBot v11 协议端**。请确保 AstrBot 中至少配置了一个 `aiocqhttp` 平台。

## 重要安全说明

本插件默认开启**严格权限控制**，调用任何工具前请先阅读本节：

- 默认所有工具只允许 `admin_list` 中的 QQ 号调用（`enable_admin_check` 默认 `true`）。
- 群写操作（踢人、禁言、改名片、签到、群文件、精华、公告、撤回、加群审批等）必须由 `admin_list` 成员触发。
- 消息发送和互动（发消息、点赞、戳一戳、签到等）必须由 `admin_list` 成员触发。
- 敏感账号凭证（`get_cookies` / `get_csrf_token` / `get_credentials`）默认**完全关闭**，必须显式开启 `enable_sensitive_account`；即使开启，也只允许 `admin_list` 成员在**私聊**中调用。
- 默认**禁止跨群操作**：群成员通过 Agent 调工具时，`group_id` 必须等于当前群。`allow_admin_cross_group` 仅控制管理员私聊时是否允许跨群。
- 私聊中默认禁止调用依赖群上下文的工具。
- 所有危险、高危操作（踢人、禁言、退群、撤回、删好友、删文件、删文件夹、修改群名、群头像、加群审批、群公告）受上述权限开关双重保护。

## 功能分类

### 账号管理
| 工具 | 功能 | 等级 |
|------|------|------|
| `get_login_info` | 获取 Bot 的 QQ 号和昵称 | 低 |
| `set_qq_profile` | 设置昵称/签名/公司/邮箱/大学 | 中 |
| `get_online_clients` | 查看 Bot 在哪些设备登录 | 低 |
| `set_online_status` | 切换在线/离开/忙碌/勿扰/隐身/听歌等 | 中 |
| `get_cookies` | 获取账号 Cookies（**需 enable_sensitive_account**） | 危险 |
| `get_csrf_token` | 获取 CSRF Token（**需 enable_sensitive_account**） | 危险 |
| `get_credentials` | 获取 cookies+csrf_token（**需 enable_sensitive_account**） | 危险 |
| `get_version_info` | 查看协议端版本 | 低 |
| `get_status` | 查看运行状态 | 低 |

### 消息发送
| 工具 | 功能 | 等级 |
|------|------|------|
| `send_group_msg` | 发送群消息，不传 group_id 自动使用当前群 | 中 |
| `send_private_msg` | 发送私聊消息，可带 group_id 走临时会话 | 中 |
| `send_group_forward_msg` | 发送合并转发（聊天记录样式，节点 1~30） | 中 |
| `send_like` | 点赞用户，1~10 次 | 中 |
| `get_msg` | 根据消息 ID 获取消息详细内容 | 低 |

### 群管理
| 工具 | 功能 | 等级 |
|------|------|------|
| `group_kick` | 踢出群成员 | 危险 |
| `group_ban` | 禁言/解禁（0~30 天） | 危险 |
| `group_whole_ban` | 全员禁言开关 | 危险 |
| `group_set_admin` | 设置/取消管理员 | 危险 |
| `group_set_card` | 设置群名片，留空=清除 | 中 |
| `group_set_title` | 设置专属头衔 | 中 |
| `group_set_name` | 修改群名称 | 高 |
| `group_leave` | Bot 主动退群 | 危险 |
| `set_group_add_request` | 处理加群请求（add/invite） | 高 |
| `set_group_portrait` | 设置群头像 | 高 |
| `set_anonymous_ban` | 禁言匿名用户 | 危险 |
| `send_group_sign` | 群签到 | 中 |

### 消息管理
| 工具 | 功能 | 等级 |
|------|------|------|
| `delete_msg` | 撤回消息 | 危险 |
| `mark_msg_as_read` | 标记已读 | 中 |
| `get_group_system_msg` | 查看加群请求、邀请等 | 低 |
| `get_group_ignore_add_request` | 查看被忽略的加群请求 | 低 |

### 信息查询
| 工具 | 功能 | 等级 |
|------|------|------|
| `get_group_list` | Bot 加入的所有群列表 | 低 |
| `get_group_info` | 群详细信息 | 低 |
| `get_group_member_list` | 群成员列表 | 低 |
| `get_group_member_info` | 指定成员详细信息 | 低 |
| `get_stranger_info` | 陌生人信息 | 低 |
| `get_friend_list` | 好友列表 | 低 |
| `get_group_honor_info` | 群荣誉 | 低 |
| `get_group_at_all_remain` | @全体剩余次数 | 低 |
| `get_group_msg_history` | 群聊天记录（1~50 条） | 低 |
| `get_recent_contacts` | 最近联系人 | 低 |
| `get_unidirectional_friend_list` | 单向好友 | 低 |
| `get_friend_msg_history` | 私聊记录（1~50 条） | 低 |

### 文件管理
| 工具 | 功能 | 等级 |
|------|------|------|
| `upload_group_file` | 上传群文件 | 中 |
| `get_group_file_system_info` | 文件系统信息 | 低 |
| `get_group_root_files` | 根目录列表 | 低 |
| `delete_group_file` | 删除群文件 | 危险 |
| `get_group_files_by_folder` | 文件夹内列表 | 低 |
| `create_group_file_folder` | 创建文件夹 | 高 |
| `delete_group_folder` | 删除文件夹 | 高 |
| `download_file` | 下载文件到 Bot 本地 | 中 |

### 精华消息
| 工具 | 功能 | 等级 |
|------|------|------|
| `set_essence_msg` | 设为精华 | 中 |
| `get_essence_msg_list` | 精华列表 | 低 |
| `delete_essence_msg` | 移除精华 | 危险 |

### 群公告
| 工具 | 功能 | 等级 |
|------|------|------|
| `send_group_notice` | 发布群公告 | 高 |
| `get_group_notice` | 查看公告标题列表 | 低 |

### 好友互动
| 工具 | 功能 | 等级 |
|------|------|------|
| `friend_poke` | 戳一戳好友 | 中 |
| `delete_friend` | 删除好友 | 危险 |
| `delete_unidirectional_friend` | 删除单向好友 | 危险 |
| `ocr_image` | 图片文字识别 | 中 |

### 媒体
| 工具 | 功能 | 等级 |
|------|------|------|
| `can_send_image` | 检查能否发图 | 低 |
| `can_send_record` | 检查能否发语音 | 低 |
| `get_image` | 获取图片下载链接 | 低 |
| `get_record` | 获取语音下载链接 | 低 |
| `get_forward_msg` | 获取合并转发内容 | 低 |

## 配置面板

| 配置项 | 说明 | 默认 |
|--------|------|------|
| `enable_group_manage` | 启用群写操作 | 开 |
| `enable_message` | 启用消息与互动 | 开 |
| `enable_info` | 启用信息查询 | 开 |
| `enable_sensitive_account` | 启用账号凭证（强烈建议保持关闭） | **关** |
| `enable_admin_check` | 启用管理员验证 | 开 |
| `allow_admin_cross_group` | 允许管理员跨群操作 | 关 |
| `admin_list` | 管理员 QQ 号列表 | 空 |

## 危险等级说明

- **低**：纯查询只读，无副作用。
- **中**：少量副作用（发消息、改名片、签到等）。
- **高**：重要变更（修改群名、发公告、加群审批、修改群头像、创建/删除文件夹）。
- **危险**：不可逆操作（踢人、禁言、撤回、删好友、删文件、Bot 退群、删精华等）。

## 部署注意事项

- **协议端选择**：仅 `aiocqhttp` 平台可用；其他平台会被拒绝并提示「未找到 aiocqhttp 平台连接」。
- **本地文件路径**：`upload_group_file` 等使用本地路径时，需要 AstrBot 与协议端共享文件系统；推荐改用 http(s) URL 或 `file://` URI。
- **敏感凭证**：请勿在群聊中开启 `enable_sensitive_account`；即使开启，也仅私聊有效。

---

By 小星萤