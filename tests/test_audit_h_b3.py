"""Architecture step 4: typed settings layer (widget settings TypedDicts generated from defaults, typed widget
"wcfg"), every function of adapter / process / userfile packages annotated"""

import ast
import importlib
import importlib.util
import inspect
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import get_args

import pytest

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "neopedal"
GENERATED = PACKAGE / "template" / "widget_config_types.py"


def load_generator():
    """tools/gen_widget_config_types.py as module (tools is not a package)"""
    spec = importlib.util.spec_from_file_location("gen_widget_config_types", ROOT / "tools" / "gen_widget_config_types.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return load_generator()


def test_generated_widget_config_types_up_to_date(generator):
    """New or changed widget option: run python tools/gen_widget_config_types.py"""
    committed = GENERATED.read_bytes().decode("utf-8")
    assert "\r\n" not in committed  # LF
    assert committed == generator.render(), "run python tools/gen_widget_config_types.py"


def test_generation_deterministic(generator):
    assert generator.render() == generator.render()


def test_every_widget_typed_with_its_options():
    from neopedal.template.setting_widget import WIDGET_DEFAULT
    from neopedal.template.widget import WIDGET_DISPLAY_ORDER
    from neopedal.template.widget_config_types import WIDGET_CONFIG_TYPES, WidgetConfig

    assert tuple(WIDGET_CONFIG_TYPES) == WIDGET_DISPLAY_ORDER
    for name, config in WIDGET_CONFIG_TYPES.items():
        assert set(config.__annotations__) | set(WidgetConfig.__annotations__) >= set(WIDGET_DEFAULT[name])
        assert set(config.__required_keys__) == set(WIDGET_DEFAULT[name]), name


def test_types_follow_validation(generator):
    """Types are what validation keeps: bool & integer keys keep their type, other numbers any finite number,
    choices a Literal of valid values"""
    from neopedal import regex_pattern as rxp
    from neopedal.template.widget_config_types import (
        AccelerationConfig,
        BlackBoxConfig,
        DisplayProfileChoice,
        FontWeightChoice,
        VisibilityContextChoice,
        WidgetConfig,
    )

    hints = AccelerationConfig.__annotations__
    assert hints["font_size"] is int  # CFG_INTEGER
    assert hints["bar_padding"] is float  # numeric: int or float accepted
    assert hints["enable_auto_font_offset"] is bool
    assert hints["font_name"] is str
    assert hints["font_weight"] == FontWeightChoice
    assert get_args(FontWeightChoice) == tuple(rxp.FONT_WEIGHT_MAP)
    assert get_args(VisibilityContextChoice) == tuple(rxp.CHOICE_COMMON["^visibility_context$"])
    assert WidgetConfig.__annotations__["visibility_context"] == VisibilityContextChoice
    assert BlackBoxConfig.__annotations__["display_profile"] == DisplayProfileChoice
    assert get_args(DisplayProfileChoice) == tuple(rxp.CHOICE_COMMON["^display_profile$"])
    # Language list is extended by language packs at runtime: never a Literal
    assert generator.choice_list("language", "choice_common") is None


def test_default_validation_mismatch_rejected(generator):
    """A default the validator would replace (wrong type, invalid choice) stops generation"""
    aliases: dict = {}
    with pytest.raises(RuntimeError, match="validation keeps bool"):
        generator.value_type("show_speed", "yes", aliases)
    with pytest.raises(RuntimeError, match="validation keeps int"):
        generator.value_type("font_size", 1.5, aliases)
    with pytest.raises(RuntimeError, match="not a valid choice"):
        generator.value_type("font_weight", "Heavy", aliases)
    assert generator.value_type("bar_padding", 2, aliases) == "float"  # int default of number option
    assert generator.value_type("speed_unit", "KPH", aliases) == "SpeedUnitChoice"


def widget_classes():
    from neopedal.template.widget_config_types import WIDGET_CONFIG_TYPES

    for name, config in WIDGET_CONFIG_TYPES.items():
        for package in ("neopedal.widget", "neopedal.widget._modern"):
            module = importlib.import_module(f"{package}.{name}")
            yield f"{package}.{name}", module.Realtime, config


def test_every_widget_class_annotates_its_setting():
    """Each widget class (classic & modern) declares wcfg with its TypedDict (annotation only)"""
    from neopedal.template.widget_config_types import WIDGET_CONFIG_TYPES

    count = 0
    for path, klass, config in widget_classes():
        annotation = inspect.get_annotations(klass).get("wcfg")  # own annotations (str if postponed)
        if isinstance(annotation, str):
            assert config.__name__ in annotation.split(" | "), path
        else:
            assert annotation is config or config in get_args(annotation), path
        assert "wcfg" not in klass.__dict__, path  # no class attribute: annotation only
        count += 1
    assert count == 2 * len(WIDGET_CONFIG_TYPES)


def test_base_widget_setting_annotation_only():
    from neopedal.template.widget_config_types import WidgetConfig
    from neopedal.widget._base import Base

    assert inspect.get_annotations(Base)["wcfg"] in (WidgetConfig, "WidgetConfig")
    assert "wcfg" not in Base.__dict__


def test_widget_setting_unchanged_at_runtime():
    """Style overrides still a dict passing writes to user setting (typing changed annotations only)"""
    from neopedal.widget._style import StyledConfig

    source = {"position_x": 1, "font_size": 15}
    styled = StyledConfig(source, {"font_size": 20})
    styled["position_x"] = 5
    assert source == {"position_x": 5, "font_size": 15}
    assert type(styled) is StyledConfig


def test_plugin_setting_typed():
    from neopedal.plugin_loader import PLUGIN_BASE_DEFAULT
    from neopedal.template.widget_config_types import PluginConfig

    assert set(PluginConfig.__required_keys__) == {*PLUGIN_BASE_DEFAULT, "visibility_context", "stream_visibility"}


def test_mypy_overrides_configured():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"neopedal.adapter.*", "neopedal.process.*", "neopedal.userfile.*"' in text
    assert "disallow_untyped_defs = true" in text
    assert 'disable_error_code = ["literal-required"]' in text


@pytest.mark.parametrize("package", ["adapter", "process", "userfile"])
def test_every_function_annotated(package):
    """Same rule as mypy disallow_untyped_defs: parameters (self & cls excepted) and return annotated
    (__init__ with an annotated parameter: return None implied)"""
    missing = []
    for path in sorted((PACKAGE / package).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            args = node.args
            params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            untyped = [a.arg for a in params if a.annotation is None and a.arg not in ("self", "cls")]
            untyped += [a.arg for a in (args.vararg, args.kwarg) if a is not None and a.annotation is None]
            implied = node.name == "__init__" and len(params) > 1 and not untyped
            if (node.returns is None and not implied) or untyped:
                missing.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.name}")
    assert not missing, missing


def test_annotated_modules_import():
    """Annotations evaluated at import (modules without postponed annotations) refer to existing names"""
    for name in ("neopedal.userfile.custom_image", "neopedal.process.garage", "neopedal.userfile.layout_profile",
                 "neopedal.userfile.track_map", "neopedal.userfile.telemetry_lap"):
        assert isinstance(importlib.import_module(name), types.ModuleType)


def test_garage_setup_generator_unchanged():
    """Setup export generator still ends early without lines (annotation only change)"""
    from neopedal.process.garage import lmu_car_setup_json_to_svm

    assert tuple(lmu_car_setup_json_to_svm([], {})) == ()  # type: ignore[arg-type]


def test_setting_types_not_loaded_at_runtime():
    """Typed settings are for type checking only: widgets never import the generated module (no memory cost)"""
    code = (
        "import importlib, pkgutil, sys\n"
        "import neopedal.plugin_loader, neopedal.widget as w, neopedal.widget._modern as m, neopedal.widget._black_box as b\n"
        "for pkg in (w, m, b):\n"
        "    for info in pkgutil.iter_modules(pkg.__path__):\n"
        "        importlib.import_module(pkg.__name__ + '.' + info.name)\n"
        "print('neopedal.template.widget_config_types' in sys.modules)\n"
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"
