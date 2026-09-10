# -*- coding: utf-8 -*-
"""标签翻译 + 自动换行回归测试（离屏，不联网）。"""
import os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
if sys.platform == 'win32':
    sp = os.path.join(BASE, '.venv', 'Lib', 'site-packages')
    pd = os.path.join(sp, 'PyQt5', 'Qt5', 'plugins')
    if os.path.isdir(os.path.join(pd, 'platforms')):
        os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH', pd)
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout
app = QApplication.instance() or QApplication(sys.argv)

from qfluentwidgets import CaptionLabel, FlowLayout

# 1) 翻译加载
from ehviewer.tag_translation import tag_translation, namespace_name
fail = []
def chk(name, cond, extra=''):
    print(('  [%s] %s %s' % ('PASS' if cond else 'FAIL', name, extra)))
    if not cond:
        fail.append(name)

chk('female:ahegao -> 阿黑颜', tag_translation('female', 'ahegao') == '阿黑颜',
    repr(tag_translation('female', 'ahegao')))
chk('female:blowjob -> 口交', tag_translation('female', 'blowjob') == '口交',
    repr(tag_translation('female', 'blowjob')))
chk('namespace female -> 女性', namespace_name('female') == '女性',
    repr(namespace_name('female')))
chk('无翻译标签返回空串', tag_translation('female', 'zz_not_exist_tag_123') == '')

# 2) _TagChip 显示 [中文]
import ehviewer.ui.detail_window as dw
chip = dw._TagChip('female', 'ahegao')
chk('chip 文本 ahegao[阿黑颜]', chip.text() == 'ahegao[阿黑颜]', repr(chip.text()))
chip2 = dw._TagChip('female', 'zz_no_tag')
chk('无翻译 chip 保持原文', chip2.text() == 'zz_no_tag', repr(chip2.text()))

# 超长译名（>20 字）截断路径不崩溃
_orig_tr = dw.tag_translation
dw.tag_translation = lambda ns, t: '超长译名' * 12   # 48 字
chip3 = dw._TagChip('female', 'long_tag')
dw.tag_translation = _orig_tr
chk('超长译名截断加省略号且不抛错',
    chip3.text() == 'long_tag[%s…]' % ('超长译名' * 5), repr(chip3.text()))

# 2.5) chip 字体 = 信息列 BodyLabel 字体
from qfluentwidgets import BodyLabel
probe = BodyLabel('')
chk('chip 字体大小与 BodyLabel 一致',
    chip.font().pointSizeF() == probe.font().pointSizeF() and
    chip.font().family() == probe.font().family(),
    'chip=%s/%s probe=%s/%s' % (chip.font().family(), chip.font().pointSizeF(),
                                probe.font().family(), probe.font().pointSizeF()))

# 3) 流式布局自动换行 + 不超宽（复刻详情页标签列的 HBox(caption)+Flow 结构）
tags = (['ahegao', 'blowjob', 'deepthroat', 'lolicon', 'paizuri', 'piledriver',
         'tentacle', 'double penetration', 'fellatio', 'sex', 'milf', 'schoolgirl uniform'] * 4)
w = QWidget()
w.setFixedWidth(560)   # 详情标签列常见可用宽度（>单 chip 最大宽度，验证换行与不超宽）
outer = QVBoxLayout(w)
row = QHBoxLayout()
row.setSpacing(6)
box = CaptionLabel('female:')
box.setFixedWidth(64)
row.addWidget(box, 0, Qt.AlignTop)
flow = FlowLayout(needAni=False)
flow.setSpacing(4)
for t in tags[:40]:
    flow.addWidget(dw._TagChip('female', t, w))
row.addLayout(flow, 1)
outer.addLayout(row)
outer.addStretch(1)
w.show()
app.processEvents()
app.processEvents()

ys = set()
over = []
for i in range(flow.count()):
    it = flow.itemAt(i)
    wid = it.widget()
    g = wid.geometry()
    ys.add(g.y())
    if g.x() + g.width() > w.width():
        over.append(wid.text())
print('  container=%d  chips=%d  lines=%d  overflow=%d' % (w.width(), flow.count(), len(ys), len(over)))
chk('标签自动换行（多行）', len(ys) >= 2, 'lines=%d' % len(ys))
chk('无标签超出容器宽度', not over, over[:5])
w.close()

if fail:
    print('TAG TEST FAILED:', fail)
    sys.exit(1)
print('标签翻译 + 自动换行测试全部通过')
