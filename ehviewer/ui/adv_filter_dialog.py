# -*- coding: utf-8 -*-
"""高级筛选对话框（对应 Android 版 FilterActivity / AdvanceSearchTable）"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QGridLayout

from qfluentwidgets import (SubtitleLabel, CheckBox, PrimaryPushButton, PushButton,
                            SpinBox, CaptionLabel, BodyLabel, Slider, ComboBox, InfoBar,
                            InfoBarPosition, CardWidget, StrongBodyLabel)

from .. import constants as C


class AdvFilterDialog(QDialog):
    """高级筛选：标题/标签/描述/上传者/文件/图片/种子/语言/页数/最低评分"""

    def __init__(self, state, parent=None):
        super(AdvFilterDialog, self).__init__(parent)
        self.setWindowTitle("高级筛选")
        self.setFixedWidth(460)
        self._state = dict(state)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)
        lay.addWidget(SubtitleLabel("高级筛选"))

        card = CardWidget(self)
        g = QGridLayout(card)
        g.setContentsMargins(16, 12, 16, 12)
        g.setSpacing(8)

        adv = self._state.get("advance_search", C.DEFAULT_ADVANCE)
        self.cb_name = CheckBox("标题", card)
        self.cb_name.setChecked(bool(adv & C.SNAME))
        self.cb_tags = CheckBox("标签", card)
        self.cb_tags.setChecked(bool(adv & C.STAGS))
        self.cb_desc = CheckBox("描述", card)
        self.cb_desc.setChecked(bool(adv & C.SDESC))
        self.cb_torr = CheckBox("种子", card)
        self.cb_torr.setChecked(bool(adv & C.STORR))
        self.cb_uploader = CheckBox("上传者", card)
        self.cb_uploader.setChecked(bool(adv & C.SFU))
        self.cb_file = CheckBox("文件名", card)
        self.cb_file.setChecked(bool(adv & C.SFT))
        g.addWidget(self.cb_name, 0, 0)
        g.addWidget(self.cb_tags, 0, 1)
        g.addWidget(self.cb_desc, 0, 2)
        g.addWidget(self.cb_torr, 1, 0)
        g.addWidget(self.cb_uploader, 1, 1)
        g.addWidget(self.cb_file, 1, 2)
        lay.addWidget(card)

        # 最低评分
        rate_card = CardWidget(self)
        rl = QHBoxLayout(rate_card)
        rl.setContentsMargins(16, 10, 16, 10)
        rl.addWidget(BodyLabel("最低评分"))
        self.rate_combo = ComboBox(rate_card)
        for i in range(1, 6):
            self.rate_combo.addItem("%d 星及以上" % i, userData=i)
        self.rate_combo.addItem("不限", userData=-1)
        self.rate_combo.setCurrentIndex(4)  # 默认不限
        mr = self._state.get("min_rating", -1)
        idx = self.rate_combo.findData(mr)
        if idx >= 0:
            self.rate_combo.setCurrentIndex(idx)
        rl.addStretch(1)
        rl.addWidget(self.rate_combo)
        lay.addWidget(rate_card)

        # 页数范围
        page_card = CardWidget(self)
        pl = QHBoxLayout(page_card)
        pl.setContentsMargins(16, 10, 16, 10)
        pl.addWidget(BodyLabel("页数范围"))
        self.page_from = SpinBox(page_card)
        self.page_from.setRange(0, 10000)
        self.page_from.setValue(max(0, self._state.get("page_from", -1)))
        self.page_to = SpinBox(page_card)
        self.page_to.setRange(0, 10000)
        self.page_to.setValue(max(0, self._state.get("page_to", -1)))
        pl.addStretch(1)
        pl.addWidget(BodyLabel("从"))
        pl.addWidget(self.page_from)
        pl.addWidget(BodyLabel("到"))
        pl.addWidget(self.page_to)
        lay.addWidget(page_card)

        btn_row = QHBoxLayout()
        reset = PushButton("重置", self)
        reset.clicked.connect(self._reset)
        ok = PrimaryPushButton("应用", self)
        ok.clicked.connect(self.accept)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btn_row.addWidget(reset)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

    def _reset(self):
        self.cb_name.setChecked(True)
        self.cb_tags.setChecked(True)
        for cb in (self.cb_desc, self.cb_torr, self.cb_uploader, self.cb_file):
            cb.setChecked(False)
        self.rate_combo.setCurrentIndex(self.rate_combo.findData(-1))
        self.page_from.setValue(0)
        self.page_to.setValue(0)
        self._state = {}

    def result_state(self):
        adv = 0
        if self.cb_name.isChecked(): adv |= C.SNAME
        if self.cb_tags.isChecked(): adv |= C.STAGS
        if self.cb_desc.isChecked(): adv |= C.SDESC
        if self.cb_torr.isChecked(): adv |= C.STORR
        if self.cb_uploader.isChecked(): adv |= C.SFU
        if self.cb_file.isChecked(): adv |= C.SFT
        st = {"advance_search": adv if adv else -1,
              "min_rating": self.rate_combo.currentData(),
              "page_from": self.page_from.value() or -1,
              "page_to": self.page_to.value() or -1}
        return st
