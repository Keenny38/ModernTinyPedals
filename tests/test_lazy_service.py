"""Lazy services: module imported at first attribute read only, target resolved once"""

import sys
import types
from types import SimpleNamespace

import pytest

from neopedal import lazy_service
from neopedal.lazy_service import LazyService, imported

MODULE = "neopedal._lazy_service_test_target"


def test_module_not_imported_until_attribute_read(monkeypatch):
    service = LazyService("_lazy_service_test_target", "target")
    assert service._module == MODULE
    assert not service.imported and not imported(service)
    module = types.ModuleType(MODULE)
    module.target = SimpleNamespace(value=3)
    monkeypatch.setitem(sys.modules, MODULE, module)
    assert service.imported  # imported by any other user counts
    assert service._target is None  # nothing resolved yet
    assert service.value == 3
    assert service._target is module.target


def test_target_resolved_once(monkeypatch):
    module = types.ModuleType(MODULE)
    module.target = SimpleNamespace(value=1)
    monkeypatch.setitem(sys.modules, MODULE, module)
    service = LazyService("_lazy_service_test_target", "target")
    assert service.value == 1
    module.target = SimpleNamespace(value=2)  # replaced in module later: proxy keeps first target
    assert service.value == 1
    module.target.value = 5
    assert service.value == 1


def test_attribute_errors_come_from_target(monkeypatch):
    module = types.ModuleType(MODULE)
    module.target = SimpleNamespace(value=1)
    monkeypatch.setitem(sys.modules, MODULE, module)
    service = LazyService("_lazy_service_test_target", "target")
    with pytest.raises(AttributeError):
        _ = service.missing
    assert not hasattr(service, "missing")


def test_missing_module_raises_on_use_only():
    service = LazyService("_lazy_service_no_such_module", "target")  # creating never imports
    assert not service.imported
    with pytest.raises(ModuleNotFoundError):
        _ = service.anything
    assert service._target is None and not service.imported


def test_target_attributes_of_missing_name(monkeypatch):
    monkeypatch.setitem(sys.modules, MODULE, types.ModuleType(MODULE))
    service = LazyService("_lazy_service_test_target", "absent")
    with pytest.raises(AttributeError):
        _ = service.value


def test_imported_of_replaced_service():
    assert imported(SimpleNamespace())  # service replaced by tests: always imported
    assert not imported(SimpleNamespace(imported=False))


def test_app_services_point_to_their_module():
    assert lazy_service.cmdserver._module == "neopedal.command_server"
    assert lazy_service.webdashboard._module == "neopedal.web_dashboard"
    assert lazy_service.streamoverlay._module == "neopedal.stream_overlay"
    assert lazy_service.update_checker._module == "neopedal.update"
    from neopedal import command_server

    assert lazy_service.cmdserver.imported
    assert lazy_service.cmdserver.enable == command_server.cmdserver.enable  # same server object
