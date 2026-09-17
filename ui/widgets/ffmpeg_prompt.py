# -*- coding: utf-8 -*-
"""缺少 ffmpeg 时的按需提示与一键安装
============================================

**为什么不随包内置**：全项目只有一处用 ffmpeg（本地视频抽首帧当封面），
没有它程序照常跑，只是视频没封面；而完整构建 150~170 MB 会让安装包从
87 MB 涨到 140 MB+。所以改成"第一次真的需要时问用户"。

弹窗给用户的选项（对应用户的明确要求）：

* **立即下载** —— 自动下载到 `{下载根}/ffmpeg-download/`，自动解压，
  成功后**打开所在文件夹**给用户看，并把路径绑定进程序（写进配置 `ffmpeg_path`）。
* **手动指定…** —— 自己已经下好/装好了：可以选 `ffmpeg.exe`，也可以选
  下载目录里的 `.zip`/`.7z`（会自动解压再绑定）。
* **稍后** —— 什么都不做。
* 勾选「**我已知晓，下次不再显示**」再点确认 → 写入 `ffmpeg_prompt_dismissed`，
  以后不再打扰（``find_ffmpeg()`` 仍会继续自动查找 PATH 等位置）。

入口是 ``maybe_prompt_ffmpeg(parent)``；页面第一次真的需要视频封面时调它即可。
下载在工作线程里跑，主线程只更新进度条 —— 见 AGENTS.md §4.4。
"""
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFileDialog, QWidget
from qfluentwidgets import (BodyLabel, CaptionLabel, CheckBox, FluentIcon as FIF,
                            InfoBar, InfoBarPosition, MessageBoxBase, ProgressBar,
                            PushButton, SubtitleLabel)

from core.config import config as CFG
from core.logger import logger
from services import ffmpeg_installer as FI
from services import file_library as FL

#: 取消后未能在 5 秒内退出的下载线程先寄存在这里，等它自己 finished 再摘掉。
#: 目的是**保住 Python 引用**，避免 QThread 在运行时被 GC → 进程级 abort。
#: （与 core/thread_guard.py 的思路一致：宁可多留一会儿，也不让线程被提前销毁。）
_ORPHANED = []


# ═══════════════════════ 下载线程 ═══════════════════════

class FfmpegDownloadWorker(QThread):
    """下载 + 解压 + 绑定 ffmpeg。

    所有磁盘/网络操作都在这个线程里；主线程只收信号刷进度条。
    **失败也必须发信号**（AGENTS.md §4.4 第 6 条），否则界面会永久卡在"下载中"。
    """
    progress = pyqtSignal(int, int)      # (已下载字节, 总字节；0 表示未知)
    stage = pyqtSignal(str)              # 阶段文字
    ok = pyqtSignal(str)                 # 绑定成功的 ffmpeg 路径
    failed = pyqtSignal(str)             # 失败原因（已翻译成人话）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _cancelled(self) -> bool:
        return self._cancel or self.isInterruptionRequested()

    def run(self):
        try:
            self.stage.emit('正在下载 ffmpeg…')
            archive = FI.download_archive(
                progress_cb=lambda d, t: self.progress.emit(d, t),
                cancel_cb=self._cancelled)
            if self._cancelled():
                self.failed.emit('已取消下载')
                return
            self.stage.emit('正在解压…')
            exe = FI.install_from_archive(archive)
            FI.cleanup_archive()
            self.ok.emit(exe)
        except InterruptedError:
            self.failed.emit('已取消下载')
        except Exception as e:
            logger.error(f'[ffmpeg] 自动安装失败: {e}', exc_info=True)
            self.failed.emit(str(e))


# ═══════════════════════ 提示弹窗 ═══════════════════════

class FfmpegMissingDialog(MessageBoxBase):
    """「需要 ffmpeg 才能生成视频封面」—— 说明 + 三个选择 + 不再提示。"""

    def __init__(self, parent=None, reason: str = ''):
        super().__init__(parent)
        self.action = 'later'        # later / download / manual

        self.titleLabel = SubtitleLabel('需要 ffmpeg 才能生成视频封面', self)
        self.viewLayout.addWidget(self.titleLabel)

        body = (
            '检测到本地视频，但系统里没有找到 ffmpeg。\n\n'
            '程序只用它做一件事：**抽取视频第一帧当封面缩略图**。'
            '没有它不影响下载、播放和其他任何功能，只是这些视频会显示不出封面。'
        )
        self.bodyLabel = BodyLabel(body, self)
        self.bodyLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.bodyLabel)

        tip = (
            f'点「立即下载」会自动下载到：\n{FI.download_dir()}\n'
            f'下载后自动解压并自动绑定路径（{FI.disk_usage_hint()}）。\n'
            '也可以自己下载后在「设置 → 工具依赖」里填路径。'
        )
        self.tipLabel = CaptionLabel(tip, self)
        self.tipLabel.setWordWrap(True)
        self.tipLabel.setStyleSheet('color: #909399;')
        self.viewLayout.addWidget(self.tipLabel)

        if reason:
            self.errLabel = CaptionLabel(f'上次失败：{reason}', self)
            self.errLabel.setWordWrap(True)
            self.errLabel.setStyleSheet('color: #F56C6C;')
            self.viewLayout.addWidget(self.errLabel)

        self.dismissBox = CheckBox('我已知晓，下次不再显示', self)
        self.viewLayout.addWidget(self.dismissBox)

        self.yesButton.setText('立即下载')
        self.yesButton.setIcon(FIF.DOWNLOAD.icon())
        self.cancelButton.setText('稍后')

        # 第三个按钮：手动指定（插在「立即下载」和「稍后」之间）
        self.manualButton = PushButton('手动指定…', self.buttonGroup)
        self.manualButton.setIcon(FIF.FOLDER.icon())
        self.manualButton.clicked.connect(self._on_manual)
        self.buttonLayout.insertWidget(1, self.manualButton, 1, Qt.AlignVCenter)

        # 「立即下载」是默认动作：yesButton 走基类的 validate()→accept()。
        # 只有「稍后」/Esc/关闭才改写成 later —— 用重写 reject() 实现，
        # 比在 clicked 上再挂一个 lambda 可靠（不依赖信号槽先后顺序）。
        self.action = 'download'

    def reject(self):
        self.action = 'later'
        super().reject()

    def _on_manual(self):
        self.action = 'manual'
        self.accept()

    def was_dismissed(self) -> bool:
        return self.dismissBox.isChecked()

    def mark_dismissed(self):
        if self.dismissBox.isChecked():
            CFG['ffmpeg_prompt_dismissed'] = True
            logger.info('[ffmpeg] 用户勾选「下次不再显示」')


class FfmpegDownloadDialog(MessageBoxBase):
    """下载进度弹窗（模态）。结束后 ``succeeded`` / ``error`` 有结论。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.succeeded = False
        self.result_path = ''
        self.error = ''

        self.titleLabel = SubtitleLabel('正在安装 ffmpeg', self)
        self.viewLayout.addWidget(self.titleLabel)

        self.stageLabel = BodyLabel('准备中…', self)
        self.stageLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.stageLabel)

        self.bar = ProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.viewLayout.addWidget(self.bar)

        self.detailLabel = CaptionLabel('', self)
        self.detailLabel.setStyleSheet('color: #909399;')
        self.viewLayout.addWidget(self.detailLabel)

        self.yesButton.hide()
        self.cancelButton.setText('取消下载')

        self._worker = None

    def reject(self):
        # 关窗口 = 取消：任何 reject 路径（取消按钮 / Esc / 关闭）都先停线程，
        # 否则下载会在对话框消失后继续，甚至把已销毁的对象当 parent 用。
        self._stop_worker()
        super().reject()

    def _stop_worker(self):
        """取消并等待下载线程。

        ``wait`` 超时（正在等一个 60s 超时的 socket 读）时**不能就这么放手**：
        对话框随后会被 GC，而 worker 是它的子对象 —— 一起被销毁就是
        ``QThread: Destroyed while thread is still running`` 直接 abort。
        所以超时路径要：断开信号 → 脱离父子关系 → 塞进模块级列表保命，
        等它自己 ``finished`` 再从列表里摘掉。
        """
        w = self._worker
        if w is None or not w.isRunning():
            return
        w.cancel()
        if w.wait(5000):
            return
        logger.warning('[ffmpeg] 下载线程未在 5 秒内退出，已转为后台自行收尾')
        try:
            w.disconnect()
        except Exception:
            pass
        try:
            w.setParent(None)
        except Exception:
            pass
        _ORPHANED.append(w)
        w.finished.connect(lambda: _ORPHANED.remove(w) if w in _ORPHANED else None)

    # ── 生命周期 ──
    def start(self):
        self._worker = FfmpegDownloadWorker(self)
        self._worker.progress.connect(self._on_progress)
        self._worker.stage.connect(self.stageLabel.setText)
        self._worker.ok.connect(self._on_ok)
        self._worker.failed.connect(self._on_failed)
        # QThread 自带的 finished 信号：**线程真正结束**后才释放引用。
        # 不能在 _on_failed 里直接 self._worker = None —— 那时 run() 可能还没返回，
        # 丢掉最后一个 Python 引用会让 QThread 对象被 GC，撞上上面那个 abort。
        self._worker.finished.connect(self._on_thread_done)
        self._worker.start()

    def _on_thread_done(self):
        w = self._worker
        self._worker = None
        if w is not None:
            try:
                w.deleteLater()
            except Exception:
                pass

    def _on_progress(self, done, total):
        if total > 0:
            self.bar.setValue(min(99, int(done * 100 / total)))
            self.detailLabel.setText(
                f'{done / 1048576:.1f} MB / {total / 1048576:.1f} MB')
        else:
            self.detailLabel.setText(f'已下载 {done / 1048576:.1f} MB')

    def _on_ok(self, path):
        self.succeeded = True
        self.result_path = path
        self.bar.setValue(100)
        self.accept()

    def _on_failed(self, msg):
        # 线程马上就会结束；这里只记结论并关窗（reject 会 wait 一下确保它退干净）
        self.error = msg
        super().reject()


# ═══════════════════════ 对外流程 ═══════════════════════

def _need_dialog_parent(parent):
    """解析出一个**非 None** 的父控件。

    ⚠️ ``MaskDialogBase.__init__`` 会做 ``parent.width()`` / ``parent.height()``，
    传 None 会直接 AttributeError。所以这里必须兜住：
    页面 → 页面所在窗口 → 当前活动窗口 → 找不到就放弃弹窗（返回 None）。
    """
    w = None
    try:
        if parent is not None:
            w = parent.window()
    except Exception:
        w = None
    if w is None:
        try:
            w = QApplication.activeWindow()
        except Exception:
            w = None
    return w


def run_download_dialog(parent=None) -> str:
    """走一遍「下载 → 解压 → 绑定」，返回绑定好的路径；失败/取消返回空串。"""
    host = _need_dialog_parent(parent)
    if host is None:
        logger.warning('[ffmpeg] 找不到可用于弹窗的父窗口，跳过自动安装')
        return ''
    dlg = FfmpegDownloadDialog(host)
    dlg.start()
    dlg.exec()
    if dlg.succeeded and dlg.result_path:
        FI.open_folder(dlg.result_path)
        _info(parent, 'ffmpeg 安装完成',
              f'已绑定：{dlg.result_path}\n视频封面现在可以正常生成。')
        return dlg.result_path

    err = dlg.error or '下载未完成'
    logger.warning(f'[ffmpeg] 自动安装未成功: {err}')
    _info(parent, 'ffmpeg 自动安装失败',
          f'{err}\n\n可以自己下载后，在「设置 → 工具依赖」里选择 ffmpeg.exe；'
          f'或把压缩包放到 {FI.download_dir()} 再点「手动指定…」。',
          success=False)
    return ''


def _pick_and_bind(parent=None) -> str:
    """让用户挑 ffmpeg.exe 或压缩包，然后绑定。返回绑定路径或空串。"""
    path, _ = QFileDialog.getOpenFileName(
        parent, '选择 ffmpeg.exe 或 ffmpeg 压缩包',
        str(FI.download_dir()),
        'ffmpeg 可执行文件 (ffmpeg.exe);;压缩包 (*.zip *.7z);;所有文件 (*)')
    if not path:
        return ''
    try:
        if path.lower().endswith(('.zip', '.7z', '.xz', '.tar')):
            exe = FI.install_from_archive(path)
        else:
            exe = FI.install_from_exe(path)
    except Exception as e:
        logger.error(f'[ffmpeg] 手动绑定失败: {e}', exc_info=True)
        _info(parent, '绑定失败', str(e), success=False)
        return ''
    _info(parent, 'ffmpeg 绑定成功', f'已绑定：{exe}')
    return exe


def prompt_and_install(parent=None, reason: str = '') -> str:
    """缺 ffmpeg 时走完整询问流程；返回可用路径（空串表示用户选择稍后/失败）。

    ``reason`` 用于二次提示时显示上次失败原因。
    """
    while True:
        host = _need_dialog_parent(parent)
        if host is None:
            logger.warning('[ffmpeg] 找不到可用于弹窗的父窗口，跳过提示')
            return ''
        dlg = FfmpegMissingDialog(host, reason=reason)
        accepted = bool(dlg.exec())
        dlg.mark_dismissed()
        if not accepted or dlg.action == 'later':
            return ''
        if dlg.action == 'download':
            got = run_download_dialog(parent)
            if got:
                return got
            reason = '下载失败，可重试或手动指定'
            continue
        if dlg.action == 'manual':
            got = _pick_and_bind(host)
            if got:
                return got
            reason = '手动指定的文件不可用'
            continue
        return ''


def maybe_prompt_ffmpeg(parent=None) -> str:
    """给页面用的轻量入口：已可用/用户说过不再提示就直接返回，不打扰。"""
    try:
        found = FL.find_ffmpeg()
        if found:
            return found
        if CFG.get('ffmpeg_prompt_dismissed', False):
            return ''
        return prompt_and_install(parent)
    except Exception as e:
        # 提示流程本身绝不能把页面搞崩（AGENTS.md §7 第 1 条）
        logger.error(f'[ffmpeg] 提示流程异常: {e}', exc_info=True)
        return ''


def _info(parent, title, content, success=True):
    """InfoBar 提示（弹窗父控件必须可用，取不到就静默跳过 —— 提示失败不该影响主流程）。"""
    try:
        host = parent if parent is not None else _need_dialog_parent(None)
        if host is None:
            return
        fn = InfoBar.success if success else InfoBar.warning
        fn(title=title, content=content, orient=Qt.Horizontal,
           isClosable=True, position=InfoBarPosition.TOP_RIGHT,
           duration=6000, parent=host)
    except Exception:
        pass
