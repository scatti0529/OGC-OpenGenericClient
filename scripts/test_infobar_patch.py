# -*- coding: utf-8 -*-
"""
验证 InfoBar 动画补丁：修复
    QPropertyAnimation::updateState (pos, InfoBar, ): starting an animation without end value

测试场景：
1. 先使用 qfluentwidgets 原始 InfoBar 逻辑连续弹出多个 InfoBar（模拟推特解析/下载完成时场景）
   → 预期捕获到 "starting an animation without end value" 警告
2. 应用 main.py 中的补丁（InfoBarManager.add 补上 dropAni 的 start/end value）后再次连续弹出
   → 预期无该警告
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# ── Qt 平台插件路径修复（与 main.py 一致，中文路径下 QLibraryInfo 损坏）──
if sys.platform == 'win32':
    site_packages = os.path.join(BASE_DIR, '.venv', 'Lib', 'site-packages')
    plugin_dir = os.path.join(site_packages, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(plugin_dir, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', plugin_dir)

from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import QApplication


def install_warning_handler(captured):
    """安装 Qt 消息处理器，捕获 stderr 警告到 captured 列表"""
    from PyQt5.QtCore import qInstallMessageHandler, QtMsgType

    def handler(mode, context, message):
        captured.append(message)

    qInstallMessageHandler(handler)
    return handler


app = QApplication(sys.argv)

# 创建一个父窗口模拟 PlatformPage
from PyQt5.QtWidgets import QWidget
parent = QWidget()
parent.resize(800, 600)
parent.show()


def flush_events():
    """处理挂起事件，让动画/定时器运行"""
    for _ in range(20):
        app.processEvents()


def pop_infobars(count=3, parent_widget=None):
    """连续弹出 InfoBar，模拟解析/下载完成场景"""
    from qfluentwidgets import InfoBar, InfoBarPosition
    infobars = []
    for i in range(count):
        bar = InfoBar.success(
            title=f"测试 {i}",
            content=f"第 {i} 条提示",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=500,
            parent=parent_widget or parent,
        )
        infobars.append(bar)
        flush_events()
    return infobars


def capture_drop_ani_warning(manager, parent_widget, captured):
    """添加两个 InfoBar（第二个会创建 dropAni），直接 start() 该 dropAni 触发警告"""
    from qfluentwidgets import InfoBar, InfoBarPosition
    bars = []
    for i in range(2):
        bar = InfoBar(
            InfoBarIcon.SUCCESS,
            title=f"t{i}", content=f"c{i}",
            orient=Qt.Horizontal, isClosable=True, duration=500,
            position=InfoBarPosition.BOTTOM_RIGHT, parent=parent_widget,
        )
        manager.add(bar)
        bars.append(bar)
        flush_events()

    # 第2个 InfoBar 有 dropAni（因为 add 时 infoBars[p] 非空）
    drop_ani = bars[1].property('dropAni')
    if drop_ani is not None:
        drop_ani.start()
        flush_events()
    return bars, drop_ani


from qfluentwidgets.components.widgets.info_bar import (
    InfoBarManager, InfoBarIcon, InfoBarPosition,
)

# ════════════════════════════════
# 阶段1：补丁前（原始 qfluentwidgets）
# ════════════════════════════════
print("═══ [阶段1] 补丁前：dropAni 缺少 end value ═══")
warnings_before = []
install_warning_handler(warnings_before)
manager = InfoBarManager.make(InfoBarPosition.BOTTOM_RIGHT)
bars1, drop1 = capture_drop_ani_warning(manager, parent, warnings_before)

end_value_warns_before = [
    w for w in warnings_before
    if 'starting an animation without end value' in w
]
print(f"  dropAni 存在: {drop1 is not None}")
print(f"  dropAni endValue: {drop1.endValue() if drop1 else None}")
print(f"  捕获到 {len(end_value_warns_before)} 条 'without end value' 警告")
for w in end_value_warns_before[:3]:
    print(f"    ⚠ {w}")

# 清理
for b in bars1:
    try:
        b.close()
    except Exception:
        pass
flush_events()
from PyQt5.QtCore import qInstallMessageHandler
qInstallMessageHandler(None)
print()

# ════════════════════════════════
# 阶段2：补丁后（main.py 中的补丁逻辑）
# ════════════════════════════════
print("═══ [阶段2] 补丁后：dropAni 已补上 end value ═══")
from PyQt5.QtCore import QPropertyAnimation, QParallelAnimationGroup


def _patched_add(self, infoBar):
    """与原始 add 逻辑一致，仅修复 dropAni 缺少 start/end value 的问题"""
    p = infoBar.parent()
    if not p:
        return

    if p not in self.infoBars:
        p.installEventFilter(self)
        self.infoBars[p] = []
        self.aniGroups[p] = QParallelAnimationGroup(self)

    if infoBar in self.infoBars[p]:
        return

    # add drop animation（补上 start/end value 避免 without end value 警告）
    if self.infoBars[p]:
        dropAni = QPropertyAnimation(infoBar, b'pos')
        dropAni.setDuration(200)
        dropAni.setStartValue(infoBar.pos())
        dropAni.setEndValue(infoBar.pos())

        self.aniGroups[p].addAnimation(dropAni)
        self.dropAnis.append(dropAni)

        infoBar.setProperty('dropAni', dropAni)

    # add slide animation
    self.infoBars[p].append(infoBar)
    slideAni = self._createSlideAni(infoBar)
    self.slideAnis.append(slideAni)

    infoBar.setProperty('slideAni', slideAni)
    infoBar.closedSignal.connect(lambda: self.remove(infoBar))

    slideAni.start()


InfoBarManager.add = _patched_add

warnings_after = []
install_warning_handler(warnings_after)
manager2 = InfoBarManager.make(InfoBarPosition.BOTTOM_RIGHT)
bars2, drop2 = capture_drop_ani_warning(manager2, parent, warnings_after)

end_value_warns_after = [
    w for w in warnings_after
    if 'starting an animation without end value' in w
]
print(f"  dropAni 存在: {drop2 is not None}")
print(f"  dropAni endValue: {drop2.endValue() if drop2 else None}")
print(f"  捕获到 {len(end_value_warns_after)} 条 'without end value' 警告")

# 清理
for b in bars2:
    try:
        b.close()
    except Exception:
        pass
flush_events()
qInstallMessageHandler(None)
print()

# ════════════════════════════════
# 结果判定
# ════════════════════════════════
drop_has_end_before = drop1 is not None and drop1.endValue() is None
drop_has_end_after = drop2 is not None and drop2.endValue() is not None

if drop_has_end_before and drop_has_end_after and not end_value_warns_after:
    print("✅ 补丁验证通过：补丁前 dropAni 无 end value（触发警告），补丁后已补上且无警告")
elif end_value_warns_before and not end_value_warns_after:
    print("✅ 补丁验证通过：补丁前有警告，补丁后无警告")
else:
    print("⚠ 验证结果：")
    print(f"  [补丁前] dropAni 无 end value: {drop_has_end_before}，警告数: {len(end_value_warns_before)}")
    print(f"  [补丁后] dropAni 有 end value: {drop_has_end_after}，警告数: {len(end_value_warns_after)}")

print(f"\n[总结] 补丁前警告数: {len(end_value_warns_before)}，补丁后警告数: {len(end_value_warns_after)}")
