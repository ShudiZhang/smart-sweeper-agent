"""
对话历史持久化 — 基于 Chroma 向量数据库
========================================
- 存储：每条消息作为一个 Document，embedding 用于语义检索
- 检索：按 session_id + index 排序，还原完整对话顺序
- 去重：同一会话重用同一 session_id，避免重复存储
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from langchain_chroma import Chroma
from langchain_core.documents import Document

from model.factory import embed_model
from utils.config_handler import chroma_conf
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class ConversationStore:
    """基于 Chroma 的对话持久化存储

    每个会话有唯一 session_id，消息按 index 有序存储。
    同时利用 Chroma 的 embedding 能力支持跨会话语义检索。
    """

    COLLECTION_NAME = "conversation_history"

    def __init__(self):
        persist_dir = get_abs_path(chroma_conf.persist_directory)
        self._store = Chroma(
            collection_name=self.COLLECTION_NAME,
            embedding_function=embed_model,
            persist_directory=persist_dir,
        )
        logger.info(
            f"[ConversationStore] 初始化完成，collection={self.COLLECTION_NAME}"
        )

    # ---- 写入 ----

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_token: str = "",
        index: int | None = None,
    ) -> str:
        """添加一条消息到会话历史

        Args:
            session_id: 会话 ID（同一会话保持不变）
            role: "user" 或 "assistant"
            content: 消息内容
            user_token: 用户标识，用于多用户隔离
            index: 消息序号，不传则自动计算

        Returns:
            消息的唯一 ID
        """
        if index is None:
            index = self._get_next_index(session_id, user_token)

        timestamp = time.time()
        msg_id = f"{session_id}_{index}"

        doc = Document(
            page_content=content,
            metadata={
                "session_id": session_id,
                "user_token": user_token,
                "role": role,
                "index": index,
                "timestamp": timestamp,
                "msg_id": msg_id,
                "deleted": False,
            },
        )

        # 删除同 ID 旧消息（幂等写入）
        try:
            existing = self._store.get(ids=[msg_id])
            if existing and existing["ids"]:
                self._store.delete(ids=[msg_id])
        except Exception:
            pass

        self._store.add_documents([doc], ids=[msg_id])
        return msg_id

    def add_conversation_turn(
        self,
        session_id: str,
        user_msg: str,
        assistant_msg: str,
        user_token: str = "",
    ) -> tuple[str, str]:
        """添加一轮完整对话（用户 + 助手），自动维护 index"""
        user_index = self._get_next_index(session_id, user_token)
        user_id = self.add_message(
            session_id, "user", user_msg, user_token=user_token, index=user_index
        )
        assistant_id = self.add_message(
            session_id,
            "assistant",
            assistant_msg,
            user_token=user_token,
            index=user_index + 1,
        )
        return user_id, assistant_id

    # ---- 读取 ----

    def get_session_history(
        self, session_id: str, user_token: str = "", max_turns: int = 20
    ) -> list[dict]:
        """获取指定会话的完整历史（按 index 升序），受 user_token 隔离

        Args:
            session_id: 会话 ID
            user_token: 用户标识，传空则不过滤（仅用于迁移兼容）
            max_turns: 最大返回轮数（每轮 = user + assistant 两条）

        Returns:
            [{"role": "user", "content": "..."}, ...]
        """
        where = {"session_id": session_id}
        results = self._store.get(where=where)
        results = self._filter_by_user_token(results, user_token)

        if not results or not results["ids"]:
            return []

        # 按 index 排序
        messages = []
        for i in range(len(results["ids"])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            if meta.get("deleted"):
                continue  # 软删除：过滤已标记删除的消息
            doc = results["documents"][i] if results.get("documents") else ""
            messages.append(
                {
                    "role": meta.get("role", "user"),
                    "content": doc,
                    "index": meta.get("index", 0),
                    "timestamp": meta.get("timestamp", 0),
                }
            )

        messages.sort(key=lambda m: m["index"])

        # 限制最大轮数（取最后 N 轮）
        max_msgs = max_turns * 2
        if len(messages) > max_msgs:
            messages = messages[-max_msgs:]

        # 只返回 role + content，与 Streamlit session_state 格式对齐
        return [{"role": m["role"], "content": m["content"]} for m in messages]

    def search_similar_conversations(self, query: str, k: int = 3) -> list[dict]:
        """语义搜索：跨会话检索与当前问题相似的历史对话

        Args:
            query: 搜索查询
            k: 返回条数

        Returns:
            [{"content": "...", "role": "...", "session_id": "..."}, ...]
        """
        docs = self._store.similarity_search(
            query, k=k * 2
        )  # 多取一些，过滤后保留 k 条
        results = []
        for doc in docs:
            if doc.metadata.get("deleted"):
                continue  # 软删除：跳过
            results.append(
                {
                    "content": doc.page_content,
                    "role": doc.metadata.get("role", ""),
                    "session_id": doc.metadata.get("session_id", ""),
                }
            )
        return results

    # ---- 删除 ----

    def delete_session(self, session_id: str, user_token: str = "") -> int:
        """软删除：标记指定会话的所有消息为 deleted=True，数据保留可恢复"""
        results = self._store.get(where={"session_id": session_id})
        results = self._filter_by_user_token(results, user_token)
        if not results or not results["ids"]:
            return 0

        count = 0
        deleted_at = time.time()
        for i in range(len(results["ids"])):
            meta = dict(results["metadatas"][i]) if results.get("metadatas") else {}
            if meta.get("deleted"):
                continue  # 已软删除，跳过
            doc_content = results["documents"][i] if results.get("documents") else ""
            doc_id = results["ids"][i]
            # 标记删除
            meta["deleted"] = True
            meta["deleted_at"] = deleted_at
            # Chroma 不支持原地更新 metadata，需删旧写新
            self._store.delete(ids=[doc_id])
            self._store.add_documents(
                [Document(page_content=doc_content, metadata=meta)],
                ids=[doc_id],
            )
            count += 1

        logger.info(f"[ConversationStore] 软删除会话 {session_id}，{count} 条消息")
        return count

    def hard_delete_session(self, session_id: str, user_token: str = "") -> int:
        """物理删除：彻底从数据库移除（不可恢复）"""
        results = self._store.get(where={"session_id": session_id})
        results = self._filter_by_user_token(results, user_token)
        if results and results["ids"]:
            self._store.delete(ids=results["ids"])
            count = len(results["ids"])
            logger.info(
                f"[ConversationStore] 物理删除会话 {session_id}，{count} 条消息"
            )
            return count
        return 0

    # ---- 工具方法 ----

    def get_existing_user_token(self) -> str:
        """获取数据库中已存在的 user_token（用于浏览器刷新后恢复身份）"""
        results = self._store.get(limit=5, include=["metadatas"])
        ids = results.get("ids") or []
        metas = results.get("metadatas") or []
        for i in range(len(ids)):
            token = metas[i].get("user_token", "") if i < len(metas) else ""
            if token:
                logger.info(f"[ConversationStore] 恢复已有 user_token: {token[:8]}...")
                return token
        return ""

    @staticmethod
    def _filter_by_user_token(results: dict, user_token: str) -> dict:
        """Python 侧过滤 Chroma 结果（避免 $and 语法兼容问题）"""
        if not user_token or not results or not results.get("ids"):
            return results
        indices = [
            i
            for i in range(len(results["ids"]))
            if (results.get("metadatas") or [{}])[i].get("user_token") == user_token
        ]
        return {
            "ids": [results["ids"][i] for i in indices],
            "metadatas": (
                [results["metadatas"][i] for i in indices]
                if results.get("metadatas")
                else None
            ),
            "documents": (
                [results["documents"][i] for i in indices]
                if results.get("documents")
                else None
            ),
        }

    def _get_next_index(self, session_id: str, user_token: str = "") -> int:
        """获取会话的下一个消息序号（排除已软删除的消息）"""
        results = self._store.get(where={"session_id": session_id})
        results = self._filter_by_user_token(results, user_token)
        if not results or not results["ids"]:
            return 0
        max_idx = max(
            (
                m.get("index", 0)
                for m in (results.get("metadatas") or [])
                if not m.get("deleted")  # 排除软删除的消息
            ),
            default=-1,
        )
        return max_idx + 1

    def list_sessions(self, user_token: str = "") -> list[dict]:
        """列出当前用户的所有会话（去重），受 user_token 隔离"""
        if user_token:
            results = self._store.get(where={"user_token": user_token})
        else:
            results = self._store.get()
        if not results or not results["ids"]:
            return []

        sessions: dict[str, dict] = {}
        for i in range(len(results["ids"])):
            meta = results["metadatas"][i] if results.get("metadatas") else {}
            if meta.get("deleted"):
                continue  # 软删除：跳过
            sid = meta.get("session_id", "")
            if sid and sid not in sessions:
                sessions[sid] = {
                    "session_id": sid,
                    "message_count": 0,
                    "last_active": meta.get("timestamp", 0),
                }
            if sid in sessions:
                sessions[sid]["message_count"] += 1
                sessions[sid]["last_active"] = max(
                    sessions[sid]["last_active"], meta.get("timestamp", 0)
                )

        return sorted(
            sessions.values(),
            key=lambda s: s["last_active"],
            reverse=True,
        )


# ============================================================
# 全局单例
# ============================================================

_conversation_store: Optional[ConversationStore] = None


def get_conversation_store() -> ConversationStore:
    """获取 ConversationStore 全局单例"""
    global _conversation_store
    if _conversation_store is None:
        _conversation_store = ConversationStore()
    return _conversation_store


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    store = ConversationStore()

    # 写入测试
    sid = str(uuid.uuid4())[:8]
    print(f"会话 ID: {sid}")

    store.add_message(sid, "user", "我的机器人不工作了怎么办")
    store.add_message(sid, "assistant", "请先检查电源是否连接正常")
    store.add_message(sid, "user", "电源正常但还是不动")
    store.add_message(sid, "assistant", "请检查驱动轮是否被毛发缠绕")

    # 读取测试
    history = store.get_session_history(sid)
    print(f"\n检索到 {len(history)} 条消息：")
    for msg in history:
        print(f"  [{msg['role']}] {msg['content'][:50]}")

    # 语义搜索测试
    print("\n语义搜索 '机器人不动'：")
    results = store.search_similar_conversations("机器人不动")
    for r in results:
        print(f"  [{r['role']}] {r['content'][:50]}")

    # 清理
    store.delete_session(sid)
    print("\n✅ ConversationStore 测试通过")
