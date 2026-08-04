# coding:utf-8
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QEvent
from PyQt5.QtGui import QDesktopServices, QPainter, QPen, QColor
from PyQt5.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame, QCompleter, QSizePolicy
import os
from qfluentwidgets import (ScrollArea, PushButton, ToolButton, FluentIcon,
                            isDarkTheme, IconWidget, Theme, ToolTipFilter, TitleLabel, CaptionLabel,
                            StrongBodyLabel, BodyLabel, toggleTheme, ImageLabel, SearchLineEdit)
from ui.widgets.common import cfg, FEEDBACK_URL, HELP_URL, EXAMPLE_URL
from ui.widgets.common import Icon
from ui.widgets.common import StyleSheet
from ui.widgets.common import signalBus


class SeparatorWidget(QWidget):
    """ Seperator widget """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedSize(6, 16)

    def paintEvent(self, e):
        painter = QPainter(self)
        pen = QPen(1)
        pen.setCosmetic(True)
        c = QColor(255, 255, 255, 21) if isDarkTheme() else QColor(0, 0, 0, 15)
        pen.setColor(c)
        painter.setPen(pen)

        x = self.width() // 2
        painter.drawLine(x, 0, x, self.height())


class ToolBar(QWidget):
    """ Tool bar """

    searchSignal = pyqtSignal(str)  # 新增信号

    def __init__(self, title, subtitle, search, music, parent=None):
        super().__init__(parent=parent)
        
        self.search = search
        self.music = music
        
        self.titleLabel = TitleLabel(title, self)
        self.subtitleLabel = CaptionLabel(subtitle, self)
        if self.search:
            # self.hBoxLayout = QHBoxLayout(self)
            self.lineEdit = SearchLineEdit(self)
            self.lineEdit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            # self.button = PushButton('Search', self)
            
        elif self.music:
            self.documentButton = PushButton(
                self.tr('Documentation'), self, FluentIcon.DOCUMENT)
            self.sourceButton = PushButton(self.tr('Source'), self, FluentIcon.GITHUB)
            self.themeButton = ToolButton(FluentIcon.CONSTRACT, self)
            self.separator = SeparatorWidget(self)
            self.supportButton = ToolButton(FluentIcon.HEADPHONES, self)
            self.feedbackButton = ToolButton(FluentIcon.FEEDBACK, self)
            
        else:
            self.documentButton = PushButton(
                self.tr('Documentation'), self, FluentIcon.DOCUMENT)
            self.sourceButton = PushButton(self.tr('Source'), self, FluentIcon.GITHUB)
            self.themeButton = ToolButton(FluentIcon.CONSTRACT, self)
            self.separator = SeparatorWidget(self)
            self.supportButton = ToolButton(FluentIcon.HEART, self)
            self.feedbackButton = ToolButton(FluentIcon.FEEDBACK, self)
        self.vBoxLayout = QVBoxLayout(self)
        self.buttonLayout = QHBoxLayout()

        self.__initWidget()

    def __initWidget(self):
        self.setFixedHeight(138)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(36, 36, 36, 12)
        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(4)
        self.vBoxLayout.addWidget(self.subtitleLabel)
        self.vBoxLayout.addSpacing(4)
        self.vBoxLayout.addLayout(self.buttonLayout, 1)
        self.vBoxLayout.setAlignment(Qt.AlignTop)
        if self.search:
            # add completer
            stands = [
                "Star Platinum", "Hierophant Green",
                "Made in Haven", "King Crimson",
                "Silver Chariot", "Crazy diamond",
                "Metallica", "Another One Bites The Dust",
                "Heaven's Door", "Killer Queen",
                "The Grateful Dead", "Stone Free",
                "The World", "Sticky Fingers",
                "Ozone Baby", "Love Love Deluxe",
                "Hermit Purple", "Gold Experience",
                "King Nothing", "Paper Moon King",
                "Scary Monster", "Mandom",
                "20th Century Boy", "Tusk Act 4",
                "Ball Breaker", "Sex Pistols",
                "D4C • Love Train", "Born This Way",
                "SOFT & WET", "Paisley Park",
                "Wonder of U", "Walking Heart",
                "Cream Starter", "November Rain",
                "Smooth Operators", "The Matte Kudasai"
            ]
            self.completer = QCompleter(stands, self.lineEdit)
            self.completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.completer.setMaxVisibleItems(10)
            self.lineEdit.setCompleter(self.completer)

            #self.resize(400, 400)
            self.buttonLayout.setAlignment(Qt.AlignCenter)
            self.buttonLayout.addWidget(self.lineEdit, 0, Qt.AlignCenter)
            # self.buttonLayout.addStretch(1)
            # self.buttonLayout.addWidget(self.button, 0, Qt.AlignCenter)
            self.lineEdit.setFixedWidth(700)
            self.lineEdit.setFixedHeight(33)
            self.lineEdit.setClearButtonEnabled(True)
            self.lineEdit.setPlaceholderText('Search stand')
            self.lineEdit.searchButton.clicked.connect(self.search_def)
            # self.button.clicked.connect(self.search_def)
            
        elif self.music:
            self.buttonLayout.setSpacing(4)
            self.buttonLayout.setContentsMargins(0, 0, 0, 0)
            self.buttonLayout.addWidget(self.documentButton, 0, Qt.AlignLeft)
            self.buttonLayout.addWidget(self.sourceButton, 0, Qt.AlignLeft)
            self.buttonLayout.addStretch(1)
            self.buttonLayout.addWidget(self.themeButton, 0, Qt.AlignRight)
            self.buttonLayout.addWidget(self.separator, 0, Qt.AlignRight)
            self.buttonLayout.addWidget(self.supportButton, 0, Qt.AlignRight)
            self.buttonLayout.addWidget(self.feedbackButton, 0, Qt.AlignRight)
            self.buttonLayout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            
            self.themeButton.installEventFilter(ToolTipFilter(self.themeButton))
            self.supportButton.installEventFilter(ToolTipFilter(self.supportButton))
            self.feedbackButton.installEventFilter(
                ToolTipFilter(self.feedbackButton))
            self.themeButton.setToolTip(self.tr('Toggle theme'))
            self.supportButton.setToolTip(self.tr('Support me'))
            self.feedbackButton.setToolTip(self.tr('Send feedback'))

            self.themeButton.clicked.connect(lambda: toggleTheme(True))
            self.supportButton.clicked.connect(signalBus.supportMusicSignal)
            self.documentButton.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
            self.sourceButton.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(EXAMPLE_URL)))
            self.feedbackButton.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
            
            
        else:
            self.buttonLayout.setSpacing(4)
            self.buttonLayout.setContentsMargins(0, 0, 0, 0)
            self.buttonLayout.addWidget(self.documentButton, 0, Qt.AlignLeft)
            self.buttonLayout.addWidget(self.sourceButton, 0, Qt.AlignLeft)
            self.buttonLayout.addStretch(1)
            self.buttonLayout.addWidget(self.themeButton, 0, Qt.AlignRight)
            self.buttonLayout.addWidget(self.separator, 0, Qt.AlignRight)
            self.buttonLayout.addWidget(self.supportButton, 0, Qt.AlignRight)
            self.buttonLayout.addWidget(self.feedbackButton, 0, Qt.AlignRight)
            self.buttonLayout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            
            self.themeButton.installEventFilter(ToolTipFilter(self.themeButton))
            self.supportButton.installEventFilter(ToolTipFilter(self.supportButton))
            self.feedbackButton.installEventFilter(
                ToolTipFilter(self.feedbackButton))
            self.themeButton.setToolTip(self.tr('Toggle theme'))
            self.supportButton.setToolTip(self.tr('Support me'))
            self.feedbackButton.setToolTip(self.tr('Send feedback'))

            self.themeButton.clicked.connect(lambda: toggleTheme(True))
            self.supportButton.clicked.connect(signalBus.supportSignal)
            self.documentButton.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(HELP_URL)))
            self.sourceButton.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(EXAMPLE_URL)))
            self.feedbackButton.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
        
        self.subtitleLabel.setTextColor(QColor(96, 96, 96), QColor(216, 216, 216))
    
    def search_def(self):
        text = self.lineEdit.text()
        self.searchSignal.emit(text)  # 发射信号
        # print(f'Searching for: {text}')


class ExampleCard(QWidget):
    """ Example card """

    def __init__(self, title, widget: QWidget, sourcePath, stretch=0, parent=None):
        super().__init__(parent=parent)
        self.widget = widget
        self.stretch = stretch

        self.titleLabel = StrongBodyLabel(title, self)
        self.card = QFrame(self)

        self.sourceWidget = QFrame(self.card)
        self.sourcePath = sourcePath
        self.sourcePathLabel = BodyLabel(
            self.tr('Source code'), self.sourceWidget)
        self.linkIcon = IconWidget(FluentIcon.LINK, self.sourceWidget)

        self.vBoxLayout = QVBoxLayout(self)
        self.cardLayout = QVBoxLayout(self.card)
        self.topLayout = QHBoxLayout()
        self.bottomLayout = QHBoxLayout(self.sourceWidget)

        self.__initWidget()

    def __initWidget(self):
        self.linkIcon.setFixedSize(16, 16)
        self.__initLayout()

        self.sourceWidget.setCursor(Qt.PointingHandCursor)
        self.sourceWidget.installEventFilter(self)

        self.card.setObjectName('card')
        self.sourceWidget.setObjectName('sourceWidget')

    def __initLayout(self):
        self.vBoxLayout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        self.cardLayout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        self.topLayout.setSizeConstraint(QHBoxLayout.SetMinimumSize)

        self.vBoxLayout.setSpacing(12)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.topLayout.setContentsMargins(12, 12, 12, 12)
        self.bottomLayout.setContentsMargins(18, 18, 18, 18)
        self.cardLayout.setContentsMargins(0, 0, 0, 0)

        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignTop)
        self.vBoxLayout.addWidget(self.card, 0, Qt.AlignTop)
        self.vBoxLayout.setAlignment(Qt.AlignTop)

        self.cardLayout.setSpacing(0)
        self.cardLayout.setAlignment(Qt.AlignTop)
        self.cardLayout.addLayout(self.topLayout, 0)
        self.cardLayout.addWidget(self.sourceWidget, 0, Qt.AlignBottom)

        self.widget.setParent(self.card)
        self.topLayout.addWidget(self.widget)
        if self.stretch == 0:
            self.topLayout.addStretch(1)

        self.widget.show()

        self.bottomLayout.addWidget(self.sourcePathLabel, 0, Qt.AlignLeft)
        self.bottomLayout.addStretch(1)
        self.bottomLayout.addWidget(self.linkIcon, 0, Qt.AlignRight)
        self.bottomLayout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    def eventFilter(self, obj, e):
        if obj is self.sourceWidget:
            if e.type() == QEvent.MouseButtonRelease:
                QDesktopServices.openUrl(QUrl(self.sourcePath))

        return super().eventFilter(obj, e)


class GalleryInterface(ScrollArea):
    """ Gallery interface """

    def __init__(self, title: str, subtitle: str, search = False, music = False, parent=None):
        """
        Parameters
        ----------
        title: str
            The title of gallery

        subtitle: str
            The subtitle of gallery

        parent: QWidget
            parent widget
        """
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.toolBar = ToolBar(title, subtitle, search, music, self)
        self.vBoxLayout = QVBoxLayout(self.view)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, self.toolBar.height(), 0, 0)
        self.setWidget(self.view)
        self.setWidgetResizable(True)

        self.vBoxLayout.setSpacing(30)
        self.vBoxLayout.setAlignment(Qt.AlignTop)
        self.vBoxLayout.setContentsMargins(36, 20, 36, 36)

        self.view.setObjectName('view')
        StyleSheet.GALLERY_INTERFACE.apply(self)

    def addExampleCard(self, title, widget, sourcePath: str, stretch=0):
        card = ExampleCard(title, widget, sourcePath, stretch, self.view)
        self.vBoxLayout.addWidget(card, 0, Qt.AlignTop)
        return card

    def scrollToCard(self, index: int):
        """ scroll to example card """
        w = self.vBoxLayout.itemAt(index).widget()
        self.verticalScrollBar().setValue(w.y())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.toolBar.resize(self.width(), self.toolBar.height())
