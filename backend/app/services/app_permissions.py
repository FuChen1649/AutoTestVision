import re
from dataclasses import dataclass

SYSTEM_APP_PRIORITY = [
    "com.android.settings",
    "com.android.systemui",
    "com.android.launcher",
    "com.android.launcher3",
    "com.miui.home",
    "com.huawei.android.launcher",
    "com.oppo.launcher",
    "com.vivo.launcher",
    "com.android.contacts",
    "com.android.dialer",
    "com.android.mms",
    "com.android.camera",
    "com.android.camera2",
    "com.android.gallery3d",
    "com.google.android.apps.photos",
    "com.android.chrome",
    "com.android.vending",
    "com.google.android.gms",
    "com.android.packageinstaller",
    "com.android.permissioncontroller",
]

COMMON_APP_PRIORITY = [
    "com.tencent.mm",
    "com.tencent.mobileqq",
    "com.tencent.wework",
    "com.ss.android.ugc.aweme",
    "com.smile.gifmaker",
    "com.alibaba.android.rimet",
    "com.eg.android.AlipayGphone",
    "com.taobao.taobao",
    "com.jingdong.app.mall",
    "com.xunmeng.pinduoduo",
    "com.autonavi.minimap",
    "com.baidu.BaiduMap",
    "com.sina.weibo",
    "com.zhihu.android",
    "com.xingin.xhs",
    "com.netease.cloudmusic",
    "com.tencent.qqlive",
    "com.youku.phone",
    "com.baidu.searchbox",
    "com.MobileTicket",
    "com.unionpay",
    "com.dianping.v1",
    "com.sankuai.meituan",
    "com.achievo.vipshop",
    "com.tencent.news",
    "com.ss.android.article.news",
    "com.larus.nova",
]

KNOWN_APP_LABELS = {
    "com.android.settings": "系统设置",
    "com.android.systemui": "系统界面",
    "com.android.contacts": "联系人",
    "com.android.dialer": "电话",
    "com.android.mms": "短信",
    "com.android.camera": "相机",
    "com.android.camera2": "相机",
    "com.android.gallery3d": "相册",
    "com.android.chrome": "Chrome",
    "com.android.vending": "应用商店",
    "com.tencent.mm": "微信",
    "com.tencent.mobileqq": "QQ",
    "com.tencent.wework": "企业微信",
    "com.ss.android.ugc.aweme": "抖音",
    "com.smile.gifmaker": "快手",
    "com.alibaba.android.rimet": "钉钉",
    "com.eg.android.AlipayGphone": "支付宝",
    "com.taobao.taobao": "淘宝",
    "com.jingdong.app.mall": "京东",
    "com.xunmeng.pinduoduo": "拼多多",
    "com.autonavi.minimap": "高德地图",
    "com.baidu.BaiduMap": "百度地图",
    "com.sina.weibo": "微博",
    "com.zhihu.android": "知乎",
    "com.xingin.xhs": "小红书",
    "com.netease.cloudmusic": "网易云音乐",
    "com.tencent.qqlive": "腾讯视频",
    "com.youku.phone": "优酷",
    "com.baidu.searchbox": "百度",
    "com.MobileTicket": "铁路12306",
    "com.unionpay": "云闪付",
    "com.dianping.v1": "大众点评",
    "com.sankuai.meituan": "美团",
    "com.larus.nova": "豆包",
}

PERMISSION_LABELS = {
    "android.permission.CAMERA": "相机",
    "android.permission.RECORD_AUDIO": "麦克风",
    "android.permission.ACCESS_FINE_LOCATION": "精确位置",
    "android.permission.ACCESS_COARSE_LOCATION": "大致位置",
    "android.permission.ACCESS_BACKGROUND_LOCATION": "后台位置",
    "android.permission.READ_CONTACTS": "读取联系人",
    "android.permission.WRITE_CONTACTS": "写入联系人",
    "android.permission.READ_CALL_LOG": "读取通话记录",
    "android.permission.WRITE_CALL_LOG": "写入通话记录",
    "android.permission.READ_PHONE_STATE": "读取手机状态",
    "android.permission.CALL_PHONE": "拨打电话",
    "android.permission.READ_SMS": "读取短信",
    "android.permission.RECEIVE_SMS": "接收短信",
    "android.permission.SEND_SMS": "发送短信",
    "android.permission.READ_EXTERNAL_STORAGE": "读取存储",
    "android.permission.WRITE_EXTERNAL_STORAGE": "写入存储",
    "android.permission.READ_MEDIA_IMAGES": "读取图片",
    "android.permission.READ_MEDIA_VIDEO": "读取视频",
    "android.permission.READ_MEDIA_AUDIO": "读取音频",
    "android.permission.POST_NOTIFICATIONS": "通知",
    "android.permission.BLUETOOTH_CONNECT": "蓝牙连接",
    "android.permission.BLUETOOTH_SCAN": "蓝牙扫描",
    "android.permission.NEARBY_WIFI_DEVICES": "附近 Wi-Fi 设备",
    "android.permission.BODY_SENSORS": "身体传感器",
    "android.permission.ACTIVITY_RECOGNITION": "活动识别",
    "android.permission.SYSTEM_ALERT_WINDOW": "悬浮窗",
    "android.permission.PACKAGE_USAGE_STATS": "使用情况访问",
    "android.permission.REQUEST_INSTALL_PACKAGES": "安装应用",
}


@dataclass
class ParsedPermission:
    name: str
    label: str
    granted: bool | None
    revocable: bool
    group: str


def package_label(package: str, dump_text: str = "") -> str:
    if package in KNOWN_APP_LABELS:
        return KNOWN_APP_LABELS[package]

    for pattern in (
        r"application-label:'([^']+)'",
        r'application-label:"([^"]+)"',
        r"application-label-zh-CN:'([^']+)'",
        r"nonLocalizedLabel=([^\s}]+)",
    ):
        match = re.search(pattern, dump_text)
        if match:
            return match.group(1)

    return package.rsplit(".", 1)[-1]


def permission_label(name: str) -> str:
    if name in PERMISSION_LABELS:
        return PERMISSION_LABELS[name]
    return name.removeprefix("android.permission.").replace("_", " ").lower()


def app_sort_key(package: str) -> tuple[int, int, str]:
    if package in SYSTEM_APP_PRIORITY:
        return (0, SYSTEM_APP_PRIORITY.index(package), package)
    if package in COMMON_APP_PRIORITY:
        return (1, COMMON_APP_PRIORITY.index(package), package)
    if package.startswith(("com.android.", "com.google.android.", "android.")):
        return (2, 0, package)
    return (3, 0, package)


def parse_package_permissions(dump_text: str) -> list[ParsedPermission]:
    requested: list[str] = []
    runtime: dict[str, bool] = {}
    install_granted: set[str] = set()
    section: str | None = None

    for raw_line in dump_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line == "requested permissions:":
            section = "requested"
            continue
        if line == "install permissions:":
            section = "install"
            continue
        if line.startswith("runtime permissions:"):
            section = "runtime"
            continue
        if line.startswith(("Package [", "User ", "AndroidManifest")):
            section = None
            continue

        if section == "requested":
            permission = line.split()[0]
            if permission.startswith(("android.permission.", "com.")):
                requested.append(permission)
            continue

        if section == "install":
            permission = line.split(":")[0].strip()
            if permission.startswith(("android.permission.", "com.")):
                install_granted.add(permission)
            continue

        if section == "runtime":
            match = re.match(r"(\S+):\s+granted=(true|false)", line)
            if match:
                runtime[match.group(1)] = match.group(2) == "true"

    permissions: list[ParsedPermission] = []
    seen: set[str] = set()

    for name in requested:
        if name in seen:
            continue
        seen.add(name)

        if name in runtime:
            granted = runtime[name]
            revocable = True
            group = "runtime"
        elif name in install_granted:
            granted = True
            revocable = False
            group = "install"
        else:
            granted = None
            revocable = False
            group = "unknown"

        permissions.append(
            ParsedPermission(
                name=name,
                label=permission_label(name),
                granted=granted,
                revocable=revocable,
                group=group,
            )
        )

    permissions.sort(key=lambda item: item.label)
    return permissions
