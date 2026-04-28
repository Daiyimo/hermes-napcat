"""
NapCat platform adapter constants.

OneBot 11 protocol constants for NapCat (QQ client via OneBot 11).
"""

# ---------------------------------------------------------------------------
# Message limits
# ---------------------------------------------------------------------------
MAX_MESSAGE_LENGTH = 4500  # QQ practical limit per message

# ---------------------------------------------------------------------------
# WebSocket configuration
# ---------------------------------------------------------------------------
WS_CONNECT_TIMEOUT = 10  # seconds
WS_PING_INTERVAL = 20  # seconds — client-side keepalive
WS_PING_TIMEOUT = 10  # seconds
WS_CLOSE_TIMEOUT = 5  # seconds

# Heartbeat (from NapCat server, default 30 000 ms)
HEARTBEAT_INTERVAL = 30  # seconds

# ---------------------------------------------------------------------------
# Reconnection strategy (exponential backoff with jitter)
# ---------------------------------------------------------------------------
RECONNECT_BACKOFF_BASE = 2.0  # seconds
RECONNECT_MAX_ATTEMPTS = 100
RECONNECT_MAX_BACKOFF = 60.0  # seconds — cap per attempt
RECONNECT_JITTER = 0.5  # +-50 % jitter

# ---------------------------------------------------------------------------
# HTTP API configuration
# ---------------------------------------------------------------------------
API_TIMEOUT = 15  # seconds — general API calls
MEDIA_DOWNLOAD_TIMEOUT = 60  # seconds — downloading images / voice / files
MEDIA_UPLOAD_TIMEOUT = 60  # seconds

# ---------------------------------------------------------------------------
# Message deduplication
# ---------------------------------------------------------------------------
DEDUP_WINDOW_SECONDS = 5
DEDUP_MAX_SIZE = 1000

# ---------------------------------------------------------------------------
# OneBot 11 post_type values
# ---------------------------------------------------------------------------
POST_TYPE_MESSAGE = "message"
POST_TYPE_MESSAGE_SENT = "message_sent"
POST_TYPE_NOTICE = "notice"
POST_TYPE_REQUEST = "request"
POST_TYPE_META_EVENT = "meta_event"

# ---------------------------------------------------------------------------
# OneBot 11 message_type values
# ---------------------------------------------------------------------------
MSG_TYPE_PRIVATE = "private"
MSG_TYPE_GROUP = "group"

# ---------------------------------------------------------------------------
# OneBot 11 meta_event sub_type values
# ---------------------------------------------------------------------------
META_EVENT_LIFECYCLE = "lifecycle"
META_EVENT_HEARTBEAT = "heartbeat"

# ---------------------------------------------------------------------------
# OneBot 11 message segment types (CQ message array format)
# ---------------------------------------------------------------------------
SEG_TEXT = "text"
SEG_IMAGE = "image"
SEG_RECORD = "record"  # voice / audio
SEG_VIDEO = "video"
SEG_FILE = "file"
SEG_AT = "at"
SEG_REPLY = "reply"
SEG_FACE = "face"  # QQ built-in emoji
SEG_FORWARD = "forward"
SEG_JSON = "json"
SEG_XML = "xml"
SEG_POKE = "poke"
SEG_MARKDOWN = "markdown"

# ---------------------------------------------------------------------------
# NapCat API endpoints (HTTP POST)
# ---------------------------------------------------------------------------
API_SEND_MSG = "/send_msg"
API_SEND_PRIVATE_MSG = "/send_private_msg"
API_SEND_GROUP_MSG = "/send_group_msg"
API_DELETE_MSG = "/delete_msg"
API_GET_MSG = "/get_msg"

API_GET_LOGIN_INFO = "/get_login_info"
API_GET_STRANGER_INFO = "/get_stranger_info"
API_GET_FRIEND_LIST = "/get_friend_list"

API_GET_GROUP_INFO = "/get_group_info"
API_GET_GROUP_LIST = "/get_group_list"
API_GET_GROUP_MEMBER_INFO = "/get_group_member_info"
API_GET_GROUP_MEMBER_LIST = "/get_group_member_list"

API_SET_GROUP_KICK = "/set_group_kick"
API_SET_GROUP_BAN = "/set_group_ban"
API_SET_GROUP_WHOLE_BAN = "/set_group_whole_ban"
API_SET_GROUP_ADMIN = "/set_group_admin"

API_GET_IMAGE = "/get_image"
API_GET_RECORD = "/get_record"
API_GET_FILE = "/get_file"

API_GET_STATUS = "/get_status"
API_GET_VERSION_INFO = "/get_version_info"

API_GET_FORWARD_MSG = "/get_forward_msg"
API_SET_MSG_EMOJI_LIKE = "/set_msg_emoji_like"
API_MARK_GROUP_MSG_AS_READ = "/mark_group_msg_as_read"
API_MARK_PRIVATE_MSG_AS_READ = "/mark_private_msg_as_read"
API_GET_GROUP_MSG_HISTORY = "/get_group_msg_history"

# ---------------------------------------------------------------------------
# Response status values
# ---------------------------------------------------------------------------
RESP_STATUS_OK = "ok"
RESP_STATUS_ASYNC = "async"
RESP_STATUS_FAILED = "failed"
RESP_RETCODE_OK = 0
