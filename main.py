import asyncio
import html
import inspect
import json
import os
from datetime import datetime
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class QQToolsPlugin(Star):
    """仅支持 aiocqhttp / OneBot v11 的 QQ Agent 工具集。"""

    # ----- call_action 动作分类 -----
    MESSAGE_ACTIONS = {
        "send_group_msg", "send_msg", "send_group_forward_msg", "send_like",
        "send_group_sign", "friend_poke",
    }
    GROUP_WRITE_ACTIONS = {
        "set_group_kick", "set_group_ban", "set_group_whole_ban",
        "set_group_admin", "set_group_card", "set_group_special_title",
        "set_group_name", "set_group_leave", "set_group_add_request",
        "set_group_portrait", "set_anonymous_ban", "send_group_sign",
        "upload_group_file", "delete_group_file", "create_group_file_folder",
        "delete_group_folder", "set_essence_msg", "delete_essence_msg",
        "_send_group_notice",
    }
    ACCOUNT_WRITE_ACTIONS = {"set_qq_profile", "set_online_status"}
    DESTRUCTIVE_ACTIONS = {
        "set_group_kick", "set_group_ban", "set_group_whole_ban",
        "set_group_admin", "set_group_leave", "delete_msg",
        "delete_group_file", "delete_group_folder", "delete_essence_msg",
        "delete_friend", "delete_unidirectional_friend", "set_anonymous_ban",
    }
    SENSITIVE_ACTIONS = {"get_cookies", "get_csrf_token", "get_credentials"}
    INFO_ACTIONS = {
        "get_login_info", "get_online_clients", "get_version_info", "get_status",
        "get_msg", "get_group_system_msg", "get_group_ignore_add_request",
        "get_group_list", "get_group_info", "get_group_member_list",
        "get_group_member_info", "get_stranger_info", "get_friend_list",
        "get_group_honor_info", "get_group_at_all_remain",
        "get_group_msg_history", "get_recent_contacts",
        "get_unidirectional_friend_list", "get_friend_msg_history",
        "get_group_file_system_info", "get_group_root_files",
        "get_group_files_by_folder", "get_essence_msg_list",
        "_get_group_notice", "can_send_image", "can_send_record",
        "get_image", "get_record", "get_forward_msg",
    }
    GROUP_ACTIONS = {
        "set_group_kick", "set_group_ban", "set_group_whole_ban",
        "set_group_admin", "set_group_card", "set_group_special_title",
        "set_group_name", "set_group_leave", "set_group_portrait",
        "set_anonymous_ban", "send_group_sign", "send_group_msg",
        "send_group_forward_msg", "get_group_info", "get_group_member_list",
        "get_group_member_info", "get_group_honor_info",
        "get_group_at_all_remain", "get_group_msg_history",
        "_get_group_notice", "upload_group_file",
        "get_group_file_system_info", "get_group_root_files",
        "delete_group_file", "get_group_files_by_folder",
        "create_group_file_folder", "delete_group_folder",
        "get_essence_msg_list", "_send_group_notice",
    }
    ONEBOT_STATUS_MAP = {"online": 0, "leave": 1, "busy": 2, "dont_disturb": 3,
        "invisible": 4, "listening": 5, "qme": 6, "constellation": 7,
        "weather": 8, "meet_spring": 9, "tianxuan": 10, "step": 11,
    }
    ONEBOT_STATUS_ALIAS = {
        "在线": 0, "离开": 1, "忙碌": 2, "勿扰": 3, "请勿打扰": 3,
        "隐身": 4, "听歌": 5, "我的电量": 6, "星座": 7, "天气": 8,
        "遇见春天": 9, "天选": 10, "步数": 11,
    }
    CONFIG_DEFAULTS = {
        "enable_group_manage": True,
        "enable_message": True,
        "enable_info": True,
        "enable_sensitive_account": False,
        "enable_admin_check": True,
        "allow_admin_cross_group": False,
    }
    MAX_FORWARD_NODES = 30
    MAX_FORWARD_TEXT = 4000

    def __init__(
        self, context: Context, config: AstrBotConfig | dict | None = None
    ):
        super().__init__(context)
        self.config = config or {}

    # -------------------- 通用辅助 --------------------
    @staticmethod
    def _ok(action: str, detail: str = "") -> str:
        message = f"[QQ工具] {action}成功" + (f" | {detail}" if detail else "")
        logger.info(message)
        return message

    @staticmethod
    def _fail(action: str, reason: str = "") -> str:
        message = f"[QQ工具] {action}失败" + (f" | {reason}" if reason else "")
        logger.warning(message)
        return message

    def _enabled(self, key: str) -> bool:
        default = self.CONFIG_DEFAULTS.get(key, False)
        value = self.config.get(key, default)
        return value if isinstance(value, bool) else default

    def _admins(self) -> set[str]:
        """兼容当前 template_list、旧字典列表和纯 QQ 号列表。"""
        raw = self.config.get("admin_list", [])
        if not isinstance(raw, list):
            return set()
        admins: set[str] = set()
        for item in raw:
            value = item.get("qq", "") if isinstance(item, dict) else item
            text = str(value or "").strip()
            if text.isdigit() and int(text) > 0:
                admins.add(text)
        return admins

    @staticmethod
    def _positive_int(value: Any) -> int | None:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError, OverflowError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _strict_bool(value: Any) -> bool | None:
        """严格解析布尔值。失败关闭：无法识别时返回 None，由调用方拒绝。"""
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if normalized in {"true", "1", "yes", "on", "是", "开启", "y", "t"}:
            return True
        if normalized in {"false", "0", "no", "off", "否", "关闭", "n", "f"}:
            return False
        return None

    def _gid(self, event: AstrMessageEvent, group_id: Any = None) -> int | None:
        value = group_id if group_id not in (None, "") else event.get_group_id()
        return self._positive_int(value)

    @staticmethod
    def _ts(timestamp: Any) -> str:
        try:
            return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            return str(timestamp)

    @staticmethod
    def _data(response: Any) -> Any:
        """从 OneBot 响应中提取 data 字段。仅当同时存在 data 与状态字段时剥离。"""
        if not isinstance(response, dict):
            return response
        if "data" in response and (
            "status" in response or "retcode" in response or "wording" in response
        ):
            return response.get("data")
        return response

    async def _bot(self, event: AstrMessageEvent):
        platform = self.context.get_platform_inst(event.get_platform_id())
        if platform is None:
            return None
        meta = getattr(platform, "meta", None)
        try:
            platform_name = getattr(meta(), "name", "") if callable(meta) else ""
        except Exception:
            platform_name = ""
        if platform_name and platform_name != "aiocqhttp":
            return None
        get_client = getattr(platform, "get_client", None)
        client = get_client() if callable(get_client) else None
        if inspect.isawaitable(client):
            client = await client
        return client or getattr(platform, "bot", None)

    # -------------------- 权限 --------------------
    def _authorize(
        self, event: AstrMessageEvent, action: str, params: dict[str, Any]
    ) -> str | None:
        sender = str(event.get_sender_id() or "").strip()
        current_gid = self._positive_int(event.get_group_id())
        admins = self._admins()
        is_admin = bool(sender) and sender in admins

        if action in self.SENSITIVE_ACTIONS:
            if not self._enabled("enable_sensitive_account"):
                return "敏感账号凭证功能未启用"
            if current_gid is not None:
                return "账号凭证只能在私聊中读取"
            if not is_admin:
                return "账号凭证仅允许 admin_list 管理员读取"

        needs_admin = (
            action in self.MESSAGE_ACTIONS
            or action in self.GROUP_WRITE_ACTIONS
            or action in self.ACCOUNT_WRITE_ACTIONS
            or action in self.DESTRUCTIVE_ACTIONS
        )
        if needs_admin and not is_admin:
            return "该操作仅允许 admin_list 管理员执行"

        if self._enabled("enable_admin_check") and not is_admin:
            return "管理员验证已启用，仅 admin_list 成员可使用 QQ 工具"

        target_gid = self._positive_int(params.get("group_id"))
        if action in self.GROUP_ACTIONS:
            if target_gid is None:
                return "缺少有效的 group_id"
            if current_gid is None and not is_admin:
                return "私聊中禁止操作群功能"
            if current_gid and target_gid != current_gid:
                if not is_admin or not self._enabled("allow_admin_cross_group"):
                    return "禁止跨群操作；目标群必须是当前群"
        return None

    # -------------------- OneBot 调用 --------------------
    async def _call(self, event: AstrMessageEvent, action: str, **params):
        sender = str(event.get_sender_id() or "").strip()
        current_gid = event.get_group_id()
        context = f"群{current_gid}" if current_gid else "私聊"
        logger.info(
            f"[QQTools] 动作={action} 调用者={sender or '未知'} "
            f"上下文={context} 参数={list(params)}"
        )

        if action in self.MESSAGE_ACTIONS and not self._enabled("enable_message"):
            return None, "消息与互动功能未启用"
        if action in self.GROUP_WRITE_ACTIONS and not self._enabled("enable_group_manage"):
            return None, "群管理功能未启用"
        if action in self.INFO_ACTIONS and not self._enabled("enable_info"):
            return None, "信息查询功能未启用"

        error = self._authorize(event, action, params)
        if error:
            return None, error

        try:
            bot = await self._bot(event)
            if bot is None:
                return None, "未找到 aiocqhttp 平台连接"
            call_action = getattr(bot, "call_action", None)
            if not callable(call_action):
                return None, "当前平台客户端不支持 call_action"
            raw = await call_action(action, **params)
            if isinstance(raw, dict) and ("status" in raw or "retcode" in raw):
                status = str(raw.get("status", "")).lower()
                retcode = raw.get("retcode")
                try:
                    retcode_num: int | None = int(retcode) if retcode is not None else None
                except (TypeError, ValueError, OverflowError):
                    retcode_num = None
                ok_status = status in {"ok", "async"} and retcode_num in (None, 0, 1)
                if status == "failed" or (retcode_num is not None and not ok_status):
                    reason = (
                        raw.get("msg")
                        or raw.get("message")
                        or raw.get("wording")
                        or f"错误码={retcode}"
                    )
                    return None, f"QQ 协议端拒绝：{reason}"
            return raw, None
        except asyncio.TimeoutError:
            return None, "请求超时，协议端未响应"
        except ConnectionError:
            return None, "无法连接到协议端"
        except Exception as exc:
            logger.exception(f"[QQTools] {action} 调用异常")
            return None, f"调用异常：{type(exc).__name__}: {str(exc)[:160]}"

    @staticmethod
    def _dump(payload: Any) -> str:
        try:
            return json.dumps(payload, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(payload)

    # ===================================================
    # =================== 账号管理 =======================
    # ===================================================

    @filter.llm_tool(name="get_login_info")
    async def get_login_info(self, event: AstrMessageEvent):
        """获取当前登录账号的信息，包括QQ号和昵称。 危险等级: 低。"""
        r, e = await self._call(event, "get_login_info")
        if e:
            yield event.plain_result(self._fail("获取登录信息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取登录信息")

    @filter.llm_tool(name="set_qq_profile")
    async def set_qq_profile(
        self,
        event: AstrMessageEvent,
        nickname: str,
        personal_note: str = "",
        company: str = "",
        email: str = "",
        college: str = "",
    ):
        """设置 Bot 的 QQ 个人资料。需要填什么就填什么，不需要的留空。
        Args:
            nickname(string): 新昵称（必填）
            personal_note(string): 个性签名，留空不修改
            company(string): 公司，留空不修改
            email(string): 邮箱，留空不修改
            college(string): 大学，留空不修改
        危险等级: 中。
        """
        if not nickname or not nickname.strip():
            yield event.plain_result(self._fail("设置个人资料", "nickname 不能为空"))
            return
        r, e = await self._call(
            event,
            "set_qq_profile",
            nickname=nickname,
            personal_note=personal_note,
            company=company,
            email=email,
            college=college,
        )
        if e:
            yield event.plain_result(self._fail("设置个人资料", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("设置个人资料")

    @filter.llm_tool(name="get_online_clients")
    async def get_online_clients(self, event: AstrMessageEvent):
        """获取当前账号在线的客户端列表，可以知道 Bot 在哪些设备上登录。 危险等级: 低。"""
        r, e = await self._call(event, "get_online_clients")
        if e:
            yield event.plain_result(self._fail("获取在线客户端", e))
            return
        payload = self._data(r)
        if isinstance(payload, dict):
            clients = payload.get("clients", [])
        else:
            clients = payload
        yield event.plain_result(self._dump(clients))
        self._ok("获取在线客户端")

    @filter.llm_tool(name="set_online_status")
    async def set_online_status(self, event: AstrMessageEvent, status: str):
        """设置 Bot 的在线状态。
        Args:
            status(string): 可选值：online/在线、leave/离开、busy/忙碌、dont_disturb/勿扰、invisible/隐身、listening/听歌、qme/我的电量、constellation/星座、weather/天气、meet_spring/遇见春天、tianxuan/天选、step/步数
        危险等级: 中。
        """
        key = (status or "").strip().lower()
        if key in self.ONEBOT_STATUS_ALIAS:
            code = self.ONEBOT_STATUS_ALIAS[key]
        elif key in self.ONEBOT_STATUS_MAP:
            code = self.ONEBOT_STATUS_MAP[key]
        else:
            yield event.plain_result(self._fail("设置在线状态", f"不支持的状态：{status}"))
            return
        r, e = await self._call(event, "set_online_status", status=code)
        if e:
            yield event.plain_result(self._fail("设置在线状态", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"设置在线状态为{status}")

    @filter.llm_tool(name="get_cookies")
    async def get_cookies(self, event: AstrMessageEvent, domain: str = ""):
        """获取 Bot 账号的 Cookies。仅允许在私聊中、admin_list 管理员调用，且需启用 enable_sensitive_account。
        Args:
            domain(string): 需要获取 cookies 的域名，例如 qzone.qq.com
        危险等级: 危险（账号凭证）。
        """
        r, e = await self._call(event, "get_cookies", domain=domain)
        if e:
            yield event.plain_result(self._fail("获取Cookies", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取Cookies")

    @filter.llm_tool(name="get_csrf_token")
    async def get_csrf_token(self, event: AstrMessageEvent):
        """获取 Bot 账号的 CSRF Token。仅允许在私聊中、admin_list 管理员调用，且需启用 enable_sensitive_account。 危险等级: 危险（账号凭证）。"""
        r, e = await self._call(event, "get_csrf_token")
        if e:
            yield event.plain_result(self._fail("获取CSRF Token", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取CSRF Token")

    @filter.llm_tool(name="get_credentials")
    async def get_credentials(self, event: AstrMessageEvent):
        """获取 Bot 账号的完整凭证（cookies + csrf_token）。仅允许在私聊中、admin_list 管理员调用，且需启用 enable_sensitive_account。 危险等级: 危险（账号凭证）。"""
        r, e = await self._call(event, "get_credentials")
        if e:
            yield event.plain_result(self._fail("获取凭证", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取凭证")

    @filter.llm_tool(name="get_version_info")
    async def get_version_info(self, event: AstrMessageEvent):
        """获取 OneBot v11 协议端版本信息。 危险等级: 低。"""
        r, e = await self._call(event, "get_version_info")
        if e:
            yield event.plain_result(self._fail("获取版本", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取版本")

    @filter.llm_tool(name="get_status")
    async def get_status(self, event: AstrMessageEvent):
        """获取协议端运行状态，包括是否在线、运行时长。 危险等级: 低。"""
        r, e = await self._call(event, "get_status")
        if e:
            yield event.plain_result(self._fail("获取状态", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取状态")

    # ===================================================
    # =================== 消息发送 =======================
    # ===================================================

    @filter.llm_tool(name="send_group_msg")
    async def send_group_msg(self, event: AstrMessageEvent, group_id: str = "", message: str = ""):
        """向指定群发送消息。不传 group_id 则发到当前群。
        Args:
            group_id(string): 群号，留空=当前群聊
            message(string): 消息内容，1~4000 字符
        危险等级: 中。
        """
        if not isinstance(message, str) or not message.strip():
            yield event.plain_result(self._fail("发送群消息", "message 不能为空"))
            return
        if len(message) > self.MAX_FORWARD_TEXT:
            yield event.plain_result(self._fail("发送群消息", f"message 不能超过 {self.MAX_FORWARD_TEXT} 字符"))
            return
        gid = self._gid(event, group_id)
        if gid is None:
            yield event.plain_result(self._fail("发送群消息", "缺少有效的 group_id"))
            return
        r, e = await self._call(event, "send_group_msg", group_id=gid, message=message)
        if e:
            yield event.plain_result(self._fail("发送群消息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"发送群消息 群{gid}")

    @filter.llm_tool(name="send_private_msg")
    async def send_private_msg(
        self, event: AstrMessageEvent, user_id: str, message: str, group_id: str = ""
    ):
        """向指定用户发送私聊消息，可附带 group_id 走临时会话。
        Args:
            user_id(string): 目标用户QQ号（必填）
            message(string): 消息内容，1~4000 字符
            group_id(string): 可选，通过群聊发起临时会话时填写群号
        危险等级: 中。
        """
        uid = self._positive_int(user_id)
        if uid is None:
            yield event.plain_result(self._fail("发送私聊", "user_id 必须是正整数"))
            return
        if not isinstance(message, str) or not message.strip():
            yield event.plain_result(self._fail("发送私聊", "message 不能为空"))
            return
        if len(message) > self.MAX_FORWARD_TEXT:
            yield event.plain_result(self._fail("发送私聊", f"message 不能超过 {self.MAX_FORWARD_TEXT} 字符"))
            return
        params: dict[str, Any] = {"user_id": uid, "message": message}
        if group_id not in (None, ""):
            gid = self._positive_int(group_id)
            if gid is None:
                yield event.plain_result(self._fail("发送私聊", "group_id 必须是正整数"))
                return
            params["group_id"] = gid
        r, e = await self._call(event, "send_msg", message_type="private", **params)
        if e:
            yield event.plain_result(self._fail("发送私聊", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"发送私聊 用户{uid}")

    @filter.llm_tool(name="send_group_forward_msg")
    async def send_group_forward_msg(
        self, event: AstrMessageEvent, group_id: str, messages: str
    ):
        """发送合并转发消息。messages 是 JSON 字符串数组。
        Args:
            group_id(string): 群号（必填）
            messages(string): 节点 JSON 字符串，例：[{"type":"node","data":{"user_id":"xxx","nickname":"xxx","content":"xxx"}}]，节点数 1~30
        危险等级: 中。
        """
        gid = self._gid(event, group_id)
        if gid is None:
            yield event.plain_result(self._fail("发送合并转发", "group_id 必须是正整数"))
            return
        try:
            nodes = json.loads(messages)
        except (TypeError, ValueError) as exc:
            yield event.plain_result(self._fail("发送合并转发", f"messages 必须是合法 JSON：{exc}"))
            return
        if not isinstance(nodes, list) or not nodes:
            yield event.plain_result(self._fail("发送合并转发", "messages 必须是非空数组"))
            return
        if len(nodes) > self.MAX_FORWARD_NODES:
            yield event.plain_result(self._fail("发送合并转发", f"节点数不能超过 {self.MAX_FORWARD_NODES}"))
            return
        r, e = await self._call(
            event, "send_group_forward_msg", group_id=gid, messages=nodes
        )
        if e:
            yield event.plain_result(self._fail("发送合并转发", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"发送合并转发 群{gid}")

    @filter.llm_tool(name="send_like")
    async def send_like(self, event: AstrMessageEvent, user_id: str, times: str = "1"):
        """给指定用户点赞。
        Args:
            user_id(string): 目标QQ号（必填）
            times(string): 点赞次数，1~10，默认 1
        危险等级: 中。
        """
        uid = self._positive_int(user_id)
        if uid is None:
            yield event.plain_result(self._fail("点赞", "user_id 必须是正整数"))
            return
        try:
            times_int = int(str(times).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("点赞", "times 必须是整数"))
            return
        if not 1 <= times_int <= 10:
            yield event.plain_result(self._fail("点赞", "times 必须在 1 到 10 之间"))
            return
        r, e = await self._call(event, "send_like", user_id=uid, times=times_int)
        if e:
            yield event.plain_result(self._fail("点赞", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"点赞 用户{uid} x{times_int}")

    @filter.llm_tool(name="get_msg")
    async def get_msg(self, event: AstrMessageEvent, message_id: str):
        """获取指定消息 ID 的详细内容。
        Args:
            message_id(string): 消息ID（必填）
        危险等级: 低。
        """
        mid = self._positive_int(message_id)
        if mid is None:
            yield event.plain_result(self._fail("获取消息", "message_id 必须是正整数"))
            return
        r, e = await self._call(event, "get_msg", message_id=mid)
        if e:
            yield event.plain_result(self._fail("获取消息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取消息")

    # ===================================================
    # =================== 群管理 =========================
    # ===================================================

    @filter.llm_tool(name="group_kick")
    async def group_kick(
        self, event: AstrMessageEvent, group_id: str, user_id: str, reject_add: str = "false"
    ):
        """踢出指定群成员。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            user_id(string): 用户QQ号（必填）
            reject_add(string): true/false，是否拒绝再加群，默认 false
        危险等级: 危险。
        """
        gid = self._positive_int(group_id)
        uid = self._positive_int(user_id)
        reject = self._strict_bool(reject_add)
        if gid is None or uid is None or reject is None:
            yield event.plain_result(self._fail("踢人", "group_id、user_id 必须为正整数，reject_add 必须为布尔值"))
            return
        r, e = await self._call(
            event, "set_group_kick", group_id=gid, user_id=uid, reject_add_request=reject
        )
        if e:
            yield event.plain_result(self._fail("踢人", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"踢人 群{gid} 用户{uid}")

    @filter.llm_tool(name="group_ban")
    async def group_ban(
        self, event: AstrMessageEvent, group_id: str, user_id: str, duration: str = "1800"
    ):
        """禁言或解除禁言。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            user_id(string): 用户QQ号（必填）
            duration(string): 禁言秒数，0=解除禁言，1~2592000，默认 1800
        危险等级: 危险。
        """
        gid = self._positive_int(group_id)
        uid = self._positive_int(user_id)
        try:
            duration_int = int(str(duration).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("禁言", "duration 必须是整数"))
            return
        if gid is None or uid is None or duration_int < 0 or duration_int > 2_592_000:
            yield event.plain_result(self._fail("禁言", "group_id、user_id 必须为正整数，duration 必须在 0~2592000 之间"))
            return
        r, e = await self._call(
            event, "set_group_ban", group_id=gid, user_id=uid, duration=duration_int
        )
        if e:
            yield event.plain_result(self._fail("禁言", e))
            return
        action = "解除禁言" if duration_int == 0 else f"禁言{duration_int}秒"
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"{action} 群{gid} 用户{uid}")

    @filter.llm_tool(name="group_whole_ban")
    async def group_whole_ban(
        self, event: AstrMessageEvent, group_id: str, enable: str = "true"
    ):
        """开启或关闭全员禁言。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            enable(string): true/false，默认 true
        危险等级: 危险。
        """
        gid = self._positive_int(group_id)
        flag = self._strict_bool(enable)
        if gid is None or flag is None:
            yield event.plain_result(self._fail("全员禁言", "group_id 必须为正整数，enable 必须为布尔值"))
            return
        r, e = await self._call(
            event, "set_group_whole_ban", group_id=gid, enable=flag
        )
        if e:
            yield event.plain_result(self._fail("全员禁言", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"{'开启' if flag else '关闭'}全员禁言 群{gid}")

    @filter.llm_tool(name="group_set_admin")
    async def group_set_admin(
        self, event: AstrMessageEvent, group_id: str, user_id: str, enable: str = "true"
    ):
        """设置或取消群管理员。Bot 需要群主权限。
        Args:
            group_id(string): 群号（必填）
            user_id(string): 用户QQ号（必填）
            enable(string): true=设置，false=取消，默认 true
        危险等级: 危险。
        """
        gid = self._positive_int(group_id)
        uid = self._positive_int(user_id)
        flag = self._strict_bool(enable)
        if gid is None or uid is None or flag is None:
            yield event.plain_result(self._fail("设置管理员", "group_id、user_id 必须为正整数，enable 必须为布尔值"))
            return
        r, e = await self._call(
            event, "set_group_admin", group_id=gid, user_id=uid, enable=flag
        )
        if e:
            yield event.plain_result(self._fail("设置管理员", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"{'设置' if flag else '取消'}管理员 群{gid} 用户{uid}")

    @filter.llm_tool(name="group_set_card")
    async def group_set_card(
        self, event: AstrMessageEvent, group_id: str, user_id: str, card: str = ""
    ):
        """设置群成员名片（群昵称），留空=清除。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            user_id(string): 用户QQ号（必填）
            card(string): 新名片内容，留空清除
        危险等级: 中。
        """
        gid = self._positive_int(group_id)
        uid = self._positive_int(user_id)
        if gid is None or uid is None:
            yield event.plain_result(self._fail("设置名片", "group_id、user_id 必须为正整数"))
            return
        r, e = await self._call(
            event, "set_group_card", group_id=gid, user_id=uid, card=card or ""
        )
        if e:
            yield event.plain_result(self._fail("设置名片", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"{'清除名片' if not card else '设置名片'} 群{gid} 用户{uid}")

    @filter.llm_tool(name="group_set_title")
    async def group_set_title(
        self, event: AstrMessageEvent, group_id: str, user_id: str, title: str = ""
    ):
        """设置群成员专属头衔，留空=清除。Bot 需要群主权限。
        Args:
            group_id(string): 群号（必填）
            user_id(string): 用户QQ号（必填）
            title(string): 头衔内容，留空清除
        危险等级: 中。
        """
        gid = self._positive_int(group_id)
        uid = self._positive_int(user_id)
        if gid is None or uid is None:
            yield event.plain_result(self._fail("设置头衔", "group_id、user_id 必须为正整数"))
            return
        r, e = await self._call(
            event, "set_group_special_title", group_id=gid, user_id=uid, special_title=title or ""
        )
        if e:
            yield event.plain_result(self._fail("设置头衔", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"{'清除头衔' if not title else '设置头衔'} 群{gid} 用户{uid}")

    @filter.llm_tool(name="group_set_name")
    async def group_set_name(
        self, event: AstrMessageEvent, group_id: str, group_name: str
    ):
        """修改群名称。Bot 需要群主或管理员权限。
        Args:
            group_id(string): 群号（必填）
            group_name(string): 新群名（必填）
        危险等级: 高。
        """
        gid = self._positive_int(group_id)
        if gid is None or not group_name or not group_name.strip():
            yield event.plain_result(self._fail("修改群名", "group_id 必须为正整数，group_name 不能为空"))
            return
        r, e = await self._call(
            event, "set_group_name", group_id=gid, group_name=group_name
        )
        if e:
            yield event.plain_result(self._fail("修改群名", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"群名改为'{group_name}' 群{gid}")

    @filter.llm_tool(name="group_leave")
    async def group_leave(self, event: AstrMessageEvent, group_id: str):
        """Bot 主动退出指定群。
        Args:
            group_id(string): 群号（必填）
        危险等级: 危险。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("退群", "group_id 必须为正整数"))
            return
        r, e = await self._call(event, "set_group_leave", group_id=gid)
        if e:
            yield event.plain_result(self._fail("退群", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"已退出群{gid}")

    @filter.llm_tool(name="set_group_add_request")
    async def set_group_add_request(
        self,
        event: AstrMessageEvent,
        flag: str,
        approve: str,
        sub_type: str = "add",
        reason: str = "",
    ):
        """处理加群请求。flag/approve 从加群通知事件获取。
        Args:
            flag(string): 加群请求 flag（必填）
            approve(string): true/false，是否同意
            sub_type(string): add=用户申请加群, invite=被邀请入群，默认 add
            reason(string): 拒绝理由，仅拒绝时生效
        危险等级: 高。
        """
        if not flag or not flag.strip():
            yield event.plain_result(self._fail("处理加群请求", "flag 不能为空"))
            return
        approve_flag = self._strict_bool(approve)
        if approve_flag is None:
            yield event.plain_result(self._fail("处理加群请求", "approve 必须为 true/false"))
            return
        if sub_type not in {"add", "invite"}:
            yield event.plain_result(self._fail("处理加群请求", "sub_type 只能是 add 或 invite"))
            return
        r, e = await self._call(
            event,
            "set_group_add_request",
            flag=flag,
            sub_type=sub_type,
            approve=approve_flag,
            reason=reason or "",
        )
        if e:
            yield event.plain_result(self._fail("处理加群请求", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("同意加群请求" if approve_flag else "拒绝加群请求")

    @filter.llm_tool(name="set_group_portrait")
    async def set_group_portrait(
        self, event: AstrMessageEvent, group_id: str, file: str
    ):
        """设置群头像。Bot 需要群主权限。file 可以是 http(s) URL、file:// URI、base64:// 或绝对路径。
        Args:
            group_id(string): 群号（必填）
            file(string): 图片资源（必填）
        危险等级: 高。
        """
        gid = self._positive_int(group_id)
        if gid is None or not file or not file.strip():
            yield event.plain_result(self._fail("设置群头像", "group_id 必须为正整数，file 不能为空"))
            return
        r, e = await self._call(event, "set_group_portrait", group_id=gid, file=file)
        if e:
            yield event.plain_result(self._fail("设置群头像", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"设置群头像 群{gid}")

    @filter.llm_tool(name="set_anonymous_ban")
    async def set_anonymous_ban(
        self, event: AstrMessageEvent, group_id: str, flag: str, duration: str = "1800"
    ):
        """禁言群里的匿名用户。flag 从匿名消息事件获取。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            flag(string): 匿名消息 flag（必填）
            duration(string): 禁言秒数，0=解除，1~2592000，默认 1800
        危险等级: 危险。
        """
        gid = self._positive_int(group_id)
        if gid is None or not flag or not flag.strip():
            yield event.plain_result(self._fail("匿名禁言", "group_id 必须为正整数，flag 不能为空"))
            return
        try:
            duration_int = int(str(duration).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("匿名禁言", "duration 必须是整数"))
            return
        if duration_int < 0 or duration_int > 2_592_000:
            yield event.plain_result(self._fail("匿名禁言", "duration 必须在 0~2592000 之间"))
            return
        r, e = await self._call(
            event, "set_anonymous_ban", group_id=gid, flag=flag, duration=duration_int
        )
        if e:
            yield event.plain_result(self._fail("匿名禁言", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"{'解除匿名禁言' if duration_int == 0 else f'匿名禁言{duration_int}秒'} 群{gid}")

    @filter.llm_tool(name="send_group_sign")
    async def send_group_sign(self, event: AstrMessageEvent, group_id: str):
        """在指定群签到。
        Args:
            group_id(string): 群号（必填）
        危险等级: 中。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("群签到", "group_id 必须为正整数"))
            return
        r, e = await self._call(event, "send_group_sign", group_id=gid)
        if e:
            yield event.plain_result(self._fail("群签到", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"群签到 群{gid}")

    # ===================================================
    # =================== 消息管理 =======================
    # ===================================================

    @filter.llm_tool(name="delete_msg")
    async def delete_msg(self, event: AstrMessageEvent, message_id: str):
        """撤回指定消息。Bot 需要管理员权限。
        Args:
            message_id(string): 消息ID（必填）
        危险等级: 危险。
        """
        mid = self._positive_int(message_id)
        if mid is None:
            yield event.plain_result(self._fail("撤回消息", "message_id 必须为正整数"))
            return
        r, e = await self._call(event, "delete_msg", message_id=mid)
        if e:
            yield event.plain_result(self._fail("撤回消息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"撤回消息 {mid}")

    @filter.llm_tool(name="mark_msg_as_read")
    async def mark_msg_as_read(
        self, event: AstrMessageEvent, user_id: str = "", group_id: str = ""
    ):
        """标记消息为已读。需至少传入 user_id 或 group_id 之一。
        Args:
            user_id(string): 私聊发送者 QQ号
            group_id(string): 群号
        危险等级: 中。
        """
        params: dict[str, Any] = {}
        if user_id not in (None, ""):
            uid = self._positive_int(user_id)
            if uid is None:
                yield event.plain_result(self._fail("标记已读", "user_id 必须为正整数"))
                return
            params["user_id"] = uid
        if group_id not in (None, ""):
            gid = self._positive_int(group_id)
            if gid is None:
                yield event.plain_result(self._fail("标记已读", "group_id 必须为正整数"))
                return
            params["group_id"] = gid
        if not params:
            yield event.plain_result(self._fail("标记已读", "user_id 与 group_id 至少需要传入一个"))
            return
        r, e = await self._call(event, "mark_msg_as_read", **params)
        if e:
            yield event.plain_result(self._fail("标记已读", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("标记已读")

    @filter.llm_tool(name="get_group_system_msg")
    async def get_group_system_msg(self, event: AstrMessageEvent, group_id: str = ""):
        """获取群系统消息（加群请求、被邀请入群等）。留空获取全部。
        Args:
            group_id(string): 群号，留空获取全部
        危险等级: 低。
        """
        params: dict[str, Any] = {}
        if group_id not in (None, ""):
            gid = self._positive_int(group_id)
            if gid is None:
                yield event.plain_result(self._fail("获取系统消息", "group_id 必须为正整数"))
                return
            params["group_id"] = gid
        r, e = await self._call(event, "get_group_system_msg", **params)
        if e:
            yield event.plain_result(self._fail("获取系统消息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取系统消息")

    @filter.llm_tool(name="get_group_ignore_add_request")
    async def get_group_ignore_add_request(self, event: AstrMessageEvent):
        """获取被忽略的加群请求列表。 危险等级: 低。"""
        r, e = await self._call(event, "get_group_ignore_add_request")
        if e:
            yield event.plain_result(self._fail("获取忽略请求", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取忽略请求")

    # ===================================================
    # =================== 信息查询 =======================
    # ===================================================

    @filter.llm_tool(name="get_group_list")
    async def get_group_list(self, event: AstrMessageEvent):
        """获取 Bot 加入的所有群列表。 危险等级: 低。"""
        r, e = await self._call(event, "get_group_list")
        if e:
            yield event.plain_result(self._fail("获取群列表", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取群列表")

    @filter.llm_tool(name="get_group_info")
    async def get_group_info(self, event: AstrMessageEvent, group_id: str = ""):
        """获取群的详细信息。不传 group_id 则使用当前群。
        Args:
            group_id(string): 群号，留空=当前群聊
        危险等级: 低。
        """
        gid = self._gid(event, group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取群信息", "缺少有效的 group_id"))
            return
        r, e = await self._call(event, "get_group_info", group_id=gid)
        if e:
            yield event.plain_result(self._fail("获取群信息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取群信息 群{gid}")

    @filter.llm_tool(name="get_group_member_list")
    async def get_group_member_list(self, event: AstrMessageEvent, group_id: str = ""):
        """获取群成员列表。不传 group_id 则使用当前群。
        Args:
            group_id(string): 群号，留空=当前群聊
        危险等级: 低。
        """
        gid = self._gid(event, group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取成员列表", "缺少有效的 group_id"))
            return
        r, e = await self._call(event, "get_group_member_list", group_id=gid)
        if e:
            yield event.plain_result(self._fail("获取成员列表", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取成员列表 群{gid}")

    @filter.llm_tool(name="get_group_member_info")
    async def get_group_member_info(
        self, event: AstrMessageEvent, group_id: str, user_id: str
    ):
        """获取指定群成员的详细信息。
        Args:
            group_id(string): 群号（必填）
            user_id(string): 用户QQ号（必填）
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        uid = self._positive_int(user_id)
        if gid is None or uid is None:
            yield event.plain_result(self._fail("获取成员信息", "group_id、user_id 必须为正整数"))
            return
        r, e = await self._call(
            event, "get_group_member_info", group_id=gid, user_id=uid, no_cache=True
        )
        if e:
            yield event.plain_result(self._fail("获取成员信息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取成员信息 群{gid} 用户{uid}")

    @filter.llm_tool(name="get_stranger_info")
    async def get_stranger_info(self, event: AstrMessageEvent, user_id: str):
        """获取陌生人 QQ 信息。
        Args:
            user_id(string): 用户QQ号（必填）
        危险等级: 低。
        """
        uid = self._positive_int(user_id)
        if uid is None:
            yield event.plain_result(self._fail("获取用户信息", "user_id 必须为正整数"))
            return
        r, e = await self._call(event, "get_stranger_info", user_id=uid, no_cache=True)
        if e:
            yield event.plain_result(self._fail("获取用户信息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取用户信息 用户{uid}")

    @filter.llm_tool(name="get_friend_list")
    async def get_friend_list(self, event: AstrMessageEvent):
        """获取 Bot 的好友列表。 危险等级: 低。"""
        r, e = await self._call(event, "get_friend_list")
        if e:
            yield event.plain_result(self._fail("获取好友列表", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取好友列表")

    @filter.llm_tool(name="get_group_honor_info")
    async def get_group_honor_info(
        self, event: AstrMessageEvent, group_id: str, honor_type: str = "all"
    ):
        """获取群荣誉信息。
        Args:
            group_id(string): 群号（必填）
            honor_type(string): talkative/performer/legend/strong_newbie/emotion/all
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取群荣誉", "group_id 必须为正整数"))
            return
        r, e = await self._call(
            event, "get_group_honor_info", group_id=gid, type=honor_type
        )
        if e:
            yield event.plain_result(self._fail("获取群荣誉", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取群荣誉 群{gid}")

    @filter.llm_tool(name="get_group_at_all_remain")
    async def get_group_at_all_remain(self, event: AstrMessageEvent, group_id: str):
        """获取群内 @全体成员 的剩余次数。
        Args:
            group_id(string): 群号（必填）
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取@全体次数", "group_id 必须为正整数"))
            return
        r, e = await self._call(event, "get_group_at_all_remain", group_id=gid)
        if e:
            yield event.plain_result(self._fail("获取@全体次数", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取@全体次数 群{gid}")

    @filter.llm_tool(name="get_group_msg_history")
    async def get_group_msg_history(
        self, event: AstrMessageEvent, group_id: str, message_seq: str = "0", count: str = "20"
    ):
        """获取群消息历史记录。
        Args:
            group_id(string): 群号（必填）
            message_seq(string): 起始消息序号（默认 0）
            count(string): 拉取条数，1~50，默认 20
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取消息历史", "group_id 必须为正整数"))
            return
        try:
            seq_int = int(str(message_seq).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("获取消息历史", "message_seq 必须是整数"))
            return
        try:
            count_int = int(str(count).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("获取消息历史", "count 必须是整数"))
            return
        if count_int < 1 or count_int > 50:
            yield event.plain_result(self._fail("获取消息历史", "count 必须在 1~50 之间"))
            return
        r, e = await self._call(
            event, "get_group_msg_history", group_id=gid, message_seq=seq_int, count=count_int
        )
        if e:
            yield event.plain_result(self._fail("获取消息历史", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取消息历史 群{gid}")

    @filter.llm_tool(name="get_recent_contacts")
    async def get_recent_contacts(self, event: AstrMessageEvent):
        """获取 Bot 最近联系人列表。 危险等级: 低。"""
        r, e = await self._call(event, "get_recent_contacts")
        if e:
            yield event.plain_result(self._fail("获取最近联系人", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取最近联系人")

    @filter.llm_tool(name="get_unidirectional_friend_list")
    async def get_unidirectional_friend_list(self, event: AstrMessageEvent):
        """获取单向好友列表（对方删了你但你还没删他）。 危险等级: 低。"""
        r, e = await self._call(event, "get_unidirectional_friend_list")
        if e:
            yield event.plain_result(self._fail("获取单向好友", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取单向好友")

    @filter.llm_tool(name="get_friend_msg_history")
    async def get_friend_msg_history(
        self, event: AstrMessageEvent, user_id: str, message_seq: str = "0", count: str = "20"
    ):
        """获取与指定好友的聊天历史记录。
        Args:
            user_id(string): 好友QQ号（必填）
            message_seq(string): 起始消息序号，默认 0
            count(string): 拉取条数，1~50，默认 20
        危险等级: 低。
        """
        uid = self._positive_int(user_id)
        if uid is None:
            yield event.plain_result(self._fail("获取好友消息历史", "user_id 必须为正整数"))
            return
        try:
            seq_int = int(str(message_seq).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("获取好友消息历史", "message_seq 必须是整数"))
            return
        try:
            count_int = int(str(count).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("获取好友消息历史", "count 必须是整数"))
            return
        if count_int < 1 or count_int > 50:
            yield event.plain_result(self._fail("获取好友消息历史", "count 必须在 1~50 之间"))
            return
        r, e = await self._call(
            event, "get_friend_msg_history", user_id=uid, message_seq=seq_int, count=count_int
        )
        if e:
            yield event.plain_result(self._fail("获取好友消息历史", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取好友消息历史")

    # ===================================================
    # =================== 文件管理 =======================
    # ===================================================

    @filter.llm_tool(name="upload_group_file")
    async def upload_group_file(
        self,
        event: AstrMessageEvent,
        group_id: str,
        file_path: str,
        name: str = "",
        folder: str = "",
    ):
        """上传文件到群文件。file_path 优先使用 http(s) URL 或 file:// 绝对路径；绝对路径需与协议端共享文件系统。
        Args:
            group_id(string): 群号（必填）
            file_path(string): 本地文件路径、http(s) URL 或 file:// URI（必填）
            name(string): 上传后显示的文件名，留空按 file_path 推断
            folder(string): 目标文件夹 ID，留空=根目录
        危险等级: 中。
        """
        gid = self._positive_int(group_id)
        if gid is None or not file_path or not file_path.strip():
            yield event.plain_result(self._fail("上传群文件", "group_id 必须为正整数，file_path 不能为空"))
            return
        if not name or not name.strip():
            name = os.path.basename(file_path.replace("\\", "/"))
        params: dict[str, Any] = {"group_id": gid, "file": file_path, "name": name}
        if folder not in (None, ""):
            params["folder"] = folder
        r, e = await self._call(event, "upload_group_file", **params)
        if e:
            yield event.plain_result(self._fail("上传群文件", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"上传群文件 群{gid}")

    @filter.llm_tool(name="get_group_file_system_info")
    async def get_group_file_system_info(self, event: AstrMessageEvent, group_id: str):
        """获取群文件系统信息（总空间、已用空间等）。
        Args:
            group_id(string): 群号（必填）
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取文件系统", "group_id 必须为正整数"))
            return
        r, e = await self._call(event, "get_group_file_system_info", group_id=gid)
        if e:
            yield event.plain_result(self._fail("获取文件系统", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取文件系统 群{gid}")

    @filter.llm_tool(name="get_group_root_files")
    async def get_group_root_files(self, event: AstrMessageEvent, group_id: str):
        """获取群文件根目录列表。
        Args:
            group_id(string): 群号（必填）
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取群文件", "group_id 必须为正整数"))
            return
        r, e = await self._call(event, "get_group_root_files", group_id=gid)
        if e:
            yield event.plain_result(self._fail("获取群文件", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取群文件 群{gid}")

    @filter.llm_tool(name="delete_group_file")
    async def delete_group_file(
        self, event: AstrMessageEvent, group_id: str, file_id: str
    ):
        """删除群文件。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            file_id(string): 文件ID（必填）
        危险等级: 危险。
        """
        gid = self._positive_int(group_id)
        if gid is None or not file_id or not file_id.strip():
            yield event.plain_result(self._fail("删除群文件", "group_id 必须为正整数，file_id 不能为空"))
            return
        r, e = await self._call(
            event, "delete_group_file", group_id=gid, file_id=file_id
        )
        if e:
            yield event.plain_result(self._fail("删除群文件", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"删除群文件 群{gid}")

    @filter.llm_tool(name="get_group_files_by_folder")
    async def get_group_files_by_folder(
        self, event: AstrMessageEvent, group_id: str, folder_id: str = ""
    ):
        """获取群文件指定文件夹内的列表。folder_id 留空=根目录。
        Args:
            group_id(string): 群号（必填）
            folder_id(string): 文件夹 ID，留空=根目录
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取文件夹文件", "group_id 必须为正整数"))
            return
        params: dict[str, Any] = {"group_id": gid}
        if folder_id not in (None, ""):
            params["folder_id"] = folder_id
        r, e = await self._call(event, "get_group_files_by_folder", **params)
        if e:
            yield event.plain_result(self._fail("获取文件夹文件", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取文件夹文件 群{gid}")

    @filter.llm_tool(name="create_group_file_folder")
    async def create_group_file_folder(
        self, event: AstrMessageEvent, group_id: str, folder_name: str, parent_folder: str = ""
    ):
        """在群文件创建文件夹。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            folder_name(string): 文件夹名称（必填）
            parent_folder(string): 父文件夹 ID，留空=根目录
        危险等级: 高。
        """
        gid = self._positive_int(group_id)
        if gid is None or not folder_name or not folder_name.strip():
            yield event.plain_result(self._fail("创建文件夹", "group_id 必须为正整数，folder_name 不能为空"))
            return
        params: dict[str, Any] = {"group_id": gid, "name": folder_name}
        if parent_folder not in (None, ""):
            params["parent_id"] = parent_folder
        r, e = await self._call(event, "create_group_file_folder", **params)
        if e:
            yield event.plain_result(self._fail("创建文件夹", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"创建文件夹 群{gid}")

    @filter.llm_tool(name="delete_group_folder")
    async def delete_group_folder(
        self, event: AstrMessageEvent, group_id: str, folder_id: str
    ):
        """删除群文件夹。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            folder_id(string): 文件夹ID（必填）
        危险等级: 高。
        """
        gid = self._positive_int(group_id)
        if gid is None or not folder_id or not folder_id.strip():
            yield event.plain_result(self._fail("删除文件夹", "group_id 必须为正整数，folder_id 不能为空"))
            return
        r, e = await self._call(
            event, "delete_group_folder", group_id=gid, folder_id=folder_id
        )
        if e:
            yield event.plain_result(self._fail("删除文件夹", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"删除文件夹 群{gid}")

    @filter.llm_tool(name="download_file")
    async def download_file(
        self, event: AstrMessageEvent, url: str, thread_count: str = "3"
    ):
        """通过协议端下载文件到 Bot 本地。
        Args:
            url(string): 文件下载链接（必填）
            thread_count(string): 下载线程数，1~16，默认 3
        危险等级: 中。
        """
        if not url or not url.strip():
            yield event.plain_result(self._fail("下载文件", "url 不能为空"))
            return
        try:
            threads = int(str(thread_count).strip())
        except (TypeError, ValueError, OverflowError):
            yield event.plain_result(self._fail("下载文件", "thread_count 必须是整数"))
            return
        if not 1 <= threads <= 16:
            yield event.plain_result(self._fail("下载文件", "thread_count 必须在 1~16 之间"))
            return
        r, e = await self._call(event, "download_file", url=url, thread_count=threads)
        if e:
            yield event.plain_result(self._fail("下载文件", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("下载文件")

    # ===================================================
    # =================== 精华与公告 ====================
    # ===================================================

    @filter.llm_tool(name="set_essence_msg")
    async def set_essence_msg(self, event: AstrMessageEvent, message_id: str):
        """将指定消息设为群精华。Bot 需要管理员权限。
        Args:
            message_id(string): 消息ID（必填）
        危险等级: 中。
        """
        mid = self._positive_int(message_id)
        if mid is None:
            yield event.plain_result(self._fail("设置精华", "message_id 必须为正整数"))
            return
        r, e = await self._call(event, "set_essence_msg", message_id=mid)
        if e:
            yield event.plain_result(self._fail("设置精华", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"设置精华 {mid}")

    @filter.llm_tool(name="get_essence_msg_list")
    async def get_essence_msg_list(self, event: AstrMessageEvent, group_id: str):
        """获取群精华消息列表。
        Args:
            group_id(string): 群号（必填）
        危险等级: 低。
        """
        gid = self._positive_int(group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取精华消息", "group_id 必须为正整数"))
            return
        r, e = await self._call(event, "get_essence_msg_list", group_id=gid)
        if e:
            yield event.plain_result(self._fail("获取精华消息", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取精华消息 群{gid}")

    @filter.llm_tool(name="delete_essence_msg")
    async def delete_essence_msg(self, event: AstrMessageEvent, message_id: str):
        """移除群精华。Bot 需要管理员权限。
        Args:
            message_id(string): 消息ID（必填）
        危险等级: 危险。
        """
        mid = self._positive_int(message_id)
        if mid is None:
            yield event.plain_result(self._fail("移除精华", "message_id 必须为正整数"))
            return
        r, e = await self._call(event, "delete_essence_msg", message_id=mid)
        if e:
            yield event.plain_result(self._fail("移除精华", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"移除精华 {mid}")

    @filter.llm_tool(name="send_group_notice")
    async def send_group_notice(
        self, event: AstrMessageEvent, group_id: str, title: str, content: str
    ):
        """发布群公告。Bot 需要管理员权限。
        Args:
            group_id(string): 群号（必填）
            title(string): 公告标题（必填）
            content(string): 公告内容（必填）
        危险等级: 高。
        """
        gid = self._positive_int(group_id)
        if gid is None or not title or not title.strip() or not content or not content.strip():
            yield event.plain_result(self._fail("发布群公告", "group_id 必须为正整数，title 和 content 不能为空"))
            return
        r, e = await self._call(
            event, "_send_group_notice", group_id=gid, title=title, content=content
        )
        if e:
            yield event.plain_result(self._fail("发布群公告", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"发布群公告 群{gid}")

    @filter.llm_tool(name="get_group_notice")
    async def get_group_notice(self, event: AstrMessageEvent, group_id: str = ""):
        """获取群公告列表。不传 group_id 则使用当前群。只返回标题列表与发布时间，不输出完整正文。
        Args:
            group_id(string): 群号，留空=当前群聊
        危险等级: 低。
        """
        gid = self._gid(event, group_id)
        if gid is None:
            yield event.plain_result(self._fail("获取群公告", "缺少有效的 group_id"))
            return
        r, e = await self._call(event, "_get_group_notice", group_id=gid)
        if e:
            yield event.plain_result(self._fail("获取群公告", e))
            return
        data = self._data(r)
        notices: list[dict[str, Any]] = []
        if isinstance(data, list):
            notices = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            for key in ("notices", "items", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    notices = [item for item in value if isinstance(item, dict)]
                    break
        if not notices:
            yield event.plain_result(self._ok(f"获取群公告 群{gid}", "0 条"))
            return
        lines: list[str] = []
        for item in notices[:20]:
            msg_raw = item.get("msg") or item.get("content") or item.get("text") or ""
            pub = item.get("publish_time") or item.get("time") or item.get("sender_time")
            if isinstance(msg_raw, dict):
                title = str(msg_raw.get("title") or msg_raw.get("subject") or "公告")
            else:
                title = str(item.get("title") or item.get("subject") or "公告")
            time_text = f" [{self._ts(pub)}]" if pub else ""
            lines.append(f"- {title}{time_text}")
        text = f"群{gid}公告共 {len(notices)} 条，仅返回标题：\n" + "\n".join(lines)
        yield event.plain_result(text)
        self._ok(f"获取群公告 群{gid} {len(notices)} 条")

    # ===================================================
    # =================== 好友互动 =======================
    # ===================================================

    @filter.llm_tool(name="friend_poke")
    async def friend_poke(self, event: AstrMessageEvent, user_id: str):
        """戳一戳好友。
        Args:
            user_id(string): 好友QQ号（必填）
        危险等级: 中。
        """
        uid = self._positive_int(user_id)
        if uid is None:
            yield event.plain_result(self._fail("戳一戳", "user_id 必须为正整数"))
            return
        r, e = await self._call(event, "friend_poke", user_id=uid)
        if e:
            yield event.plain_result(self._fail("戳一戳", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"戳一戳 用户{uid}")

    @filter.llm_tool(name="delete_friend")
    async def delete_friend(self, event: AstrMessageEvent, user_id: str):
        """删除指定好友。
        Args:
            user_id(string): 好友QQ号（必填）
        危险等级: 危险。
        """
        uid = self._positive_int(user_id)
        if uid is None:
            yield event.plain_result(self._fail("删除好友", "user_id 必须为正整数"))
            return
        r, e = await self._call(event, "delete_friend", user_id=uid)
        if e:
            yield event.plain_result(self._fail("删除好友", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"删除好友 {uid}")

    @filter.llm_tool(name="delete_unidirectional_friend")
    async def delete_unidirectional_friend(
        self, event: AstrMessageEvent, user_id: str
    ):
        """删除单向好友。
        Args:
            user_id(string): 对方QQ号（必填）
        危险等级: 危险。
        """
        uid = self._positive_int(user_id)
        if uid is None:
            yield event.plain_result(self._fail("删除单向好友", "user_id 必须为正整数"))
            return
        r, e = await self._call(event, "delete_unidirectional_friend", user_id=uid)
        if e:
            yield event.plain_result(self._fail("删除单向好友", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"删除单向好友 {uid}")

    @filter.llm_tool(name="ocr_image")
    async def ocr_image(self, event: AstrMessageEvent, image: str):
        """对图片进行 OCR 文字识别。
        Args:
            image(string): http(s) URL、file:// URI 或 base64:// 字符串（必填）
        危险等级: 中。
        """
        if not image or not image.strip():
            yield event.plain_result(self._fail("OCR识别", "image 不能为空"))
            return
        r, e = await self._call(event, "ocr_image", image=image)
        if e:
            yield event.plain_result(self._fail("OCR识别", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("OCR识别")

    @filter.llm_tool(name="can_send_image")
    async def can_send_image(self, event: AstrMessageEvent):
        """检查 Bot 当前是否可以发送图片。 危险等级: 低。"""
        r, e = await self._call(event, "can_send_image")
        if e:
            yield event.plain_result(self._fail("检查发图权限", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("检查发图权限")

    @filter.llm_tool(name="can_send_record")
    async def can_send_record(self, event: AstrMessageEvent):
        """检查 Bot 当前是否可以发送语音。 危险等级: 低。"""
        r, e = await self._call(event, "can_send_record")
        if e:
            yield event.plain_result(self._fail("检查发语音权限", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("检查发语音权限")

    @filter.llm_tool(name="get_image")
    async def get_image(self, event: AstrMessageEvent, file: str):
        """获取指定图片的下载链接。
        Args:
            file(string): 图片文件名或 file_id（必填）
        危险等级: 低。
        """
        if not file or not file.strip():
            yield event.plain_result(self._fail("获取图片", "file 不能为空"))
            return
        r, e = await self._call(event, "get_image", file=file)
        if e:
            yield event.plain_result(self._fail("获取图片", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取图片")

    @filter.llm_tool(name="get_record")
    async def get_record(
        self, event: AstrMessageEvent, file: str, out_format: str = ""
    ):
        """获取语音消息的下载链接或转码数据。
        Args:
            file(string): 语音文件名或 file_id（必填）
            out_format(string): 输出格式，如 mp3、amr、wav
        危险等级: 低。
        """
        if not file or not file.strip():
            yield event.plain_result(self._fail("获取语音", "file 不能为空"))
            return
        params: dict[str, Any] = {"file": file}
        if out_format not in (None, ""):
            params["out_format"] = out_format
        r, e = await self._call(event, "get_record", **params)
        if e:
            yield event.plain_result(self._fail("获取语音", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok("获取语音")

    @filter.llm_tool(name="get_forward_msg")
    async def get_forward_msg(self, event: AstrMessageEvent, message_id: str):
        """获取合并转发消息的详细内容。
        Args:
            message_id(string): 合并转发消息ID（必填）
        危险等级: 低。
        """
        mid = self._positive_int(message_id)
        if mid is None:
            yield event.plain_result(self._fail("获取合并转发", "message_id 必须为正整数"))
            return
        r, e = await self._call(event, "get_forward_msg", message_id=mid)
        if e:
            yield event.plain_result(self._fail("获取合并转发", e))
            return
        yield event.plain_result(self._dump(self._data(r)))
        self._ok(f"获取合并转发 {mid}")
