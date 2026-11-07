"""Explicit locations, tested backends and bounded CalcLens worker connections."""
from __future__ import annotations

from weakref import WeakSet

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QWidget,
)

from .compute_devices import probe_devices
from .compute_server import RemoteCancellation, RemoteComputeConfig, remote_capabilities


def format_execution(run, language):
    if not run:
        return ""
    ko = language == "ko"
    actual = run.get("worker_effective_device") or run.get("effective_device", "—")
    location = ("원격" if ko else "Worker") if run.get("effective_device") == "remote" else ("로컬" if ko else "Local")
    requested = run.get("requested_worker_device") if run.get("effective_device") == "remote" else run.get("requested_device")
    parity = run.get("parity", {})
    parity_text = ("통과" if ko else "passed") if parity.get("passed") else ("미확인" if ko else "unverified")
    text = [
        f"{location} · {requested or '—'} → {actual} · {run.get('device_name', '')}",
        f"{run.get('precision', '—')} · {run.get('elapsed_seconds', 0):.4f} s · CPU float64 {parity_text}",
    ]
    reasons = list(run.get("fallback_reasons") or [])
    reasons.extend((run.get("worker_execution") or {}).get("fallback_reasons") or [])
    if reasons:
        text.append(("대체 실행 사유 · " if ko else "Fallback reasons · ") + " / ".join(dict.fromkeys(reasons)))
    return "\n".join(text)


def _device_choices(t, desired):
    combo = QComboBox()
    for key, label in [("auto", t("자동", "Auto")), ("cpu", "CPU"), ("metal", "Apple Metal"), ("cuda", "NVIDIA CUDA")]:
        combo.addItem(label, key)
    combo.setCurrentIndex(combo.findData(desired))
    return combo


def _update_availability(combo, rows):
    for row in rows:
        idx = combo.findData(row["id"])
        if idx < 0:
            continue
        item = combo.model().item(idx)
        item.setEnabled(bool(row["available"]))
        item.setToolTip(str(row.get("device_name") or row.get("reason") or "—"))


def _rows_text(rows):
    return "\n".join(f"{r['id']} · {r.get('reason') or r.get('device_name') or '—'}" for r in rows)


class DeviceControls:
    def __init__(self, panel, layout):
        self.panel = panel
        self.window = panel.window
        self.settings = self.window.preferences
        self.t = t = panel.t
        self.remote_probe = None
        self.running_requests = WeakSet()
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        layout.addLayout(form)
        self.location = QComboBox()
        self.location.addItem(t("이 컴퓨터", "This computer"), "local")
        self.location.addItem(t("원격 CalcLens 워커", "Remote CalcLens worker"), "remote")
        form.addRow(t("실행 위치", "Run on"), self.location)
        self.device = _device_choices(t, self.settings.get("local_device"))
        form.addRow(t("로컬 계산 장치", "Local device"), self.device)
        self.device.currentIndexChanged.connect(lambda: self.settings.set("local_device", self.device.currentData()))
        self.remote_box = QWidget()
        remote = QFormLayout(self.remote_box)
        remote.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        remote.setContentsMargins(0, 0, 0, 0)
        self.url, self.token, self.ca_file = QLineEdit(), QLineEdit(), QLineEdit()
        self.url.setPlaceholderText("https://host:8768")
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        self.ca_file.setPlaceholderText(t("선택 사항", "Optional"))
        self.timeout = QSpinBox()
        self.timeout.setRange(1, 120)
        self.timeout.setValue(45)
        self.timeout.setSuffix(" s")
        self.worker_device = _device_choices(t, self.settings.get("worker_device"))
        self.worker_device.currentIndexChanged.connect(lambda: self.settings.set("worker_device", self.worker_device.currentData()))
        remote.addRow("URL", self.url)
        remote.addRow(t("접속 토큰", "Token"), self.token)
        remote.addRow(t("CA 인증서", "CA file"), self.ca_file)
        remote.addRow(t("제한 시간", "Timeout"), self.timeout)
        remote.addRow(t("워커 장치", "Worker device"), self.worker_device)
        hint = QLabel(t("CalcLens 워커의 주소를 입력하세요. Gaussian SSH 서버나 작업 큐에 연결하는 기능은 없습니다.",
                        "Enter a CalcLens worker endpoint. Gaussian SSH and batch queues use a different protocol."))
        hint.setWordWrap(True)
        remote.addRow(hint)
        self.connect_button = QPushButton(t("워커 연결 확인", "Test worker connection"))
        self.connect_button.clicked.connect(lambda: panel._safe(self.check_remote))
        remote.addRow(self.connect_button)
        layout.addWidget(self.remote_box)
        self.probe_info = QLabel()
        self.probe_info.setWordWrap(True)
        self.probe_info.setTextFormat(Qt.TextFormat.PlainText)
        self.probe_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.probe_info)
        self.cancel_probe_button = QPushButton(t("장치 확인 취소", "Cancel device check"))
        self.cancel_probe_button.hide()
        self.cancel_probe_button.clicked.connect(self.cancel_probe)
        layout.addWidget(self.cancel_probe_button)
        self.location.currentIndexChanged.connect(self._location_changed)
        # New endpoints and credentials require a new explicit connection test.
        for field in (self.url, self.token, self.ca_file):
            field.textChanged.connect(self._clear_worker_probe)
        self._location_changed()
        self._availability(self.device, self.window.local_devices)
        self._availability(self.worker_device, [])

    def _availability(self, combo, records):
        if records:
            _update_availability(combo, records)
            return
        for key in ("auto", "cpu", "metal", "cuda"):
            item = combo.model().item(combo.findData(key))
            known = key in ("auto", "cpu")
            item.setEnabled(known)
            item.setToolTip("" if known else self.t("장치 확인 후 선택할 수 있습니다.", "Test availability to enable this device."))

    def ensure_local_probe(self):
        if self.window.local_devices:
            self._availability(self.device, self.window.local_devices)
        elif not any(job.key == "device-probe" for job, _, _ in self.window._jobs.values()):
            self.check_local()

    def _location_changed(self):
        remote = self.location.currentData() == "remote"
        self.remote_box.setVisible(remote)
        self.device.setEnabled(not remote)
        self.cancel_probe()
        self.probe_info.clear()

    def _clear_worker_probe(self):
        self.cancel_probe()
        self._availability(self.worker_device, [])
        self.probe_info.clear()

    def cancel_probe(self):
        if self.remote_probe:
            self.remote_probe.cancel()
        self.remote_probe = None
        self.window.cancel_job("device-probe")
        self.cancel_probe_button.hide()
        self.probe_info.setText(self.t("장치 확인을 취소했습니다.", "Device check cancelled."))

    def _probe(self, fn, show):
        self.cancel_probe()
        self.probe_info.setText(self.t("장치 확인 중…", "Testing devices…"))
        self.cancel_probe_button.show()

        def done(result):
            self.remote_probe = None
            self.cancel_probe_button.hide()
            show(result)

        def failed(error):
            self.remote_probe = None
            self.cancel_probe_button.hide()
            self.probe_info.setText(str(error))
        self.window.submit(fn, done, key="device-probe", on_error=failed)

    def check_local(self):
        def show(rows):
            self.window.local_devices = rows
            _update_availability(self.device, rows)
            self.probe_info.setText(_rows_text(rows))
        self._probe(probe_devices, show)

    def _config(self, cancel):
        if self.location.currentData() != "remote":
            raise ValueError(self.t("먼저 원격 워커를 선택하세요.", "Select the remote worker first."))
        return RemoteComputeConfig(self.url.text().strip(), self.token.text(), self.worker_device.currentData(),
                                   self.timeout.value(), self.ca_file.text().strip() or None, cancel)

    def check_remote(self):
        cancel = RemoteCancellation()
        config = self._config(cancel)
        def show(result):
            _update_availability(self.worker_device, result["devices"])
            self.probe_info.setText(self.t("워커 장치 정책", "Worker policy") + f" · {result['policy']}\n" + _rows_text(result["devices"]))
        self._probe(lambda: remote_capabilities(config), show)
        self.remote_probe = cancel

    def execution_choice(self):
        if self.location.currentData() == "local":
            item = self.device.model().item(self.device.currentIndex())
            if not item.isEnabled():
                raise ValueError(item.toolTip())
            return self.device.currentData(), None
        item = self.worker_device.model().item(self.worker_device.currentIndex())
        if not item.isEnabled():
            raise ValueError(item.toolTip())
        cancel = RemoteCancellation()
        config = self._config(cancel)
        if not config.url or not config.token:
            raise ValueError(self.t("워커 주소와 토큰을 입력하세요.", "Enter the worker URL and token."))
        if QMessageBox.question(self.panel, self.t("원격 계산", "Remote computation"),
                self.t("이 워커에 이번 계산의 수치 배열을 전송할까요?", "Send this calculation's numeric arrays to the worker?")
                + "\n" + config.url, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return None
        self.running_requests.add(cancel)
        return "remote", config

    def cancel_remote_calculations(self):
        for request in list(self.running_requests):
            request.cancel()

    def session_state(self):
        # Only for a same-window language change. Never serialized to disk.
        return (self.location.currentData(), self.url.text(), self.token.text(), self.ca_file.text(), self.timeout.value())

    def restore_session(self, state):
        loc, url, token, ca, timeout = state
        self.location.setCurrentIndex(self.location.findData(loc))
        self.url.setText(url)
        self.token.setText(token)
        self.ca_file.setText(ca)
        self.timeout.setValue(timeout)
        if self.window.local_devices:
            _update_availability(self.device, self.window.local_devices)
