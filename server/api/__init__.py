from __future__ import annotations

from . import assets, attendance, device_v1, devices, frame, layouts, mock, modules, scenes, workspace

BLUEPRINTS = [
    devices.bp,
    layouts.bp,
    modules.bp,
    scenes.bp,
    frame.bp,
    mock.bp,
    assets.bp,
    attendance.bp,
    workspace.bp,
    device_v1.bp,
]
