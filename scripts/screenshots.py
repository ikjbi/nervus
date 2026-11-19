"""Render screenshots of the editor for the documentation (docs/images/).

Run: QT_QPA_PLATFORM=offscreen uv run python scripts/screenshots.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QWidget

ROOT = Path(__file__).parent.parent
OUT = ROOT / "docs" / "images"


def masked_example():  # type: ignore[no-untyped-def]
    """A small model with a masked combustion-torque subsystem (for the mask screenshots)."""
    from nervus.blocks import Constant, Gain, Inport, Outport, Scope, Subsystem
    from nervus.core import Diagram, Variable

    md = Diagram("masked_example")
    inner = Diagram()
    air = inner.add(Inport(port=1), name="air_flow")
    gain = inner.add(Gain(gain="eta * Q_lhv / afr"), name="torque_gain")
    inner.chain(air, gain, inner.add(Outport(port=1), name="torque"))
    sub = Subsystem(system=inner)
    sub.mask.add(Variable("eta", 0.3, "Thermal efficiency", "-"))
    sub.mask.add(Variable("Q_lhv", 44e6, "Fuel heating value", "J/kg"))
    sub.mask.add(Variable("afr", 14.7, "Air-fuel ratio", "-"))
    sub.mask_icon = "Combustion\\ntorque"
    md.add(sub, name="combustion")
    md.chain(md.add(Constant(value=0.003), name="air"), sub, md.add(Scope(), name="scope"))
    return md, sub


def gated_example():  # type: ignore[no-untyped-def]
    """A subsystem with an enable and a rising-edge trigger input (for the docs)."""
    from nervus.blocks import Constant, Counter, Inport, Outport, Pulse, Scope, Subsystem
    from nervus.core import Diagram

    d = Diagram("gated_example")
    inner = Diagram()
    x = inner.add(Inport(port=1), name="tooth")
    cnt = inner.add(Counter(limit=1000, sample_time=0.001), name="count")
    inner.chain(x, cnt, inner.add(Outport(port=1), name="teeth"))
    sub = Subsystem(system=inner, enable_port=True, trigger="rising")
    d.add(sub, name="tooth_counter")
    d.connect(d.add(Constant(value=1.0), name="one"), (sub, 0))
    d.connect(d.add(Constant(value=1.0), name="engine_running"), (sub, 1))
    d.connect(d.add(Pulse(period=0.01, sample_time=0.001), name="crank_sensor"), (sub, 2))
    d.connect(sub, d.add(Scope(), name="scope"))
    return d


def tasks_example():  # type: ignore[no-untyped-def]
    """An ECU with a 10 ms and a 100 ms task (atomic subsystems with their own sample time)."""
    from nervus.blocks import DiscretePID, Inport, MovingAverage, Outport, Scope, Sine, Subsystem, Sum
    from nervus.core import Diagram

    d = Diagram("tasks_example")
    fast = Diagram()
    rpm = fast.add(Inport(port=1), name="rpm")
    target = fast.add(Inport(port=2), name="target")
    err = fast.add(Sum(signs="-+"), name="error")
    fast.connect(rpm, err.in_port(0))
    fast.connect(target, err.in_port(1))
    fast.chain(
        err,
        fast.add(DiscretePID(P=0.04, I=0.03, sample_time=-1), name="idle_pi"),
        fast.add(Outport(port=1), name="throttle"),
    )
    slow = Diagram()
    temp = slow.add(Inport(port=1), name="coolant_temp")
    slow.chain(
        temp,
        slow.add(MovingAverage(length=10, sample_time=-1), name="filter"),
        slow.add(Outport(port=1), name="temp_filtered"),
    )
    t10 = d.add(Subsystem(system=fast, sample_time=0.01), name="task_10ms")
    t100 = d.add(Subsystem(system=slow, sample_time=0.1), name="task_100ms")
    d.connect(d.add(Sine(amplitude=20.0, bias=800.0), name="engine_rpm"), (t10, 0))
    d.connect(d.add(Sine(amplitude=0.0, bias=800.0), name="target_rpm"), (t10, 1))
    d.chain(d.add(Sine(amplitude=2.0, bias=90.0), name="coolant_sensor"), t100)
    d.connect(t10, d.add(Scope(), name="throttle_cmd"))
    d.connect(t100, d.add(Scope(), name="coolant"))
    for name, (x, y) in {
        "engine_rpm": (0, 0),
        "target_rpm": (0, 110),
        "task_10ms": (200, 40),
        "throttle_cmd": (520, 40),
        "coolant_sensor": (0, 260),
        "task_100ms": (200, 260),
        "coolant": (520, 260),
    }.items():
        d.block(name).meta["position"] = [float(x), float(y)]
    return d


def grab(widget: QWidget, name: str) -> None:
    QApplication.processEvents()
    widget.grab().save(str(OUT / name))
    print("wrote", OUT / name)


def main() -> None:
    from nervus.gui.qtfix import unhide_qt_plugins

    unhide_qt_plugins()
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    from nervus.gui.theme import ThemeManager, ThemeMode

    OUT.mkdir(parents=True, exist_ok=True)
    for mode in (ThemeMode.LIGHT, ThemeMode.DARK):
        ThemeManager.instance().set_mode(mode)
        from nervus.gui.views.main_window import MainWindow

        settings = QSettings(tempfile.mktemp(suffix=".ini"), QSettings.Format.IniFormat)
        win = MainWindow(settings)
        win.resize(1400, 860)
        win.show()
        win.files.open(ROOT / "examples" / "throttle_pi.nervus")
        win.view.fit()
        win.scene.select_blocks(["throttle_pi"])
        suffix = "" if mode is ThemeMode.LIGHT else "-dark"
        grab(win, f"editor{suffix}.png")
        if mode is ThemeMode.LIGHT:
            win.workspace_dock.raise_()
            win.resizeDocks([win.workspace_dock], [210], Qt.Orientation.Vertical)
            grab(win, "workspace.png")
            grab(win.workspace_panel, "workspace-panel.png")
            win.diagnostics_dock.raise_()

        win.simulation.run()
        win.simulation.wait()
        for _ in range(20):
            QApplication.processEvents()
        scope = next(iter(win.scopes.values()))
        scope.resize(900, 520)
        grab(scope, f"scope{suffix}.png")

        if mode is ThemeMode.LIGHT:
            # Subsystems: group the ECU part of the throttle model.
            root = win.diagram_model.root
            ecu = win.editor.create_subsystem([root.block(n) for n in ("tps_sample", "error", "throttle_pi")])
            assert ecu is not None
            win.editor.rename(ecu, "ECU")
            win.editor.auto_layout()
            win.view.fit()
            win.scene.select_blocks(["ECU"])
            grab(win, "subsystem-outer.png")
            win.diagram_model.enter(ecu)
            win.editor.auto_layout()
            win.view.fit()
            grab(win, "subsystem-inner.png")
            win.diagram_model.up()
            for _ in range(4):
                win.editor.undo_stack.undo()
            # Code generation dialog for the ECU subsystem of the throttle_ecu example.
            win.files.open(ROOT / "examples" / "throttle_ecu.nervus")
            win.view.fit()
            win.scene.select_blocks(["ECU"])
            dlg = win.generate_code()
            assert dlg is not None
            dlg.resize(1000, 720)
            dlg.tabs.setCurrentIndex(1)
            dlg.run_sil()
            grab(dlg, "codegen.png")
            dlg.close()

            # Test Manager with results, then the Data Inspector comparing two calibrations.
            win.tests_dock.raise_()
            win.resizeDocks([win.tests_dock], [230], Qt.Orientation.Vertical)
            win.test_panel.run_all()
            win.tests.wait()
            for _ in range(30):
                QApplication.processEvents()
            win.test_panel.tree.resizeColumnToContents(0)
            grab(win, "test-manager.png")
            inspector = win.show_inspector()
            inspector.resize(1100, 560)
            inspector.select(["test: tip-in, baseline calibration", "test: tip-in, tight calibration"], ["plate_angle"])
            grab(inspector, "data-inspector.png")
            inspector.close()
            win.diagnostics_dock.raise_()

            # A masked subsystem: parameters in the Properties panel, and the Edit Mask dialog.
            md, sub = masked_example()
            win.diagram_model.set_diagram(md)
            win.scene.select_blocks(["combustion"])
            win.view.fit()
            grab(win, "mask-properties.png")
            from nervus.gui.views.mask_dialog import MaskDialog

            mdlg = MaskDialog(sub, win)
            mdlg.show()
            grab(mdlg, "mask-dialog.png")
            mdlg.close()

            # Atomic subsystems with their own task period.
            win.diagram_model.set_diagram(tasks_example())
            win.view.fit()
            grab(win.view, "subsystem-tasks.png")

            # Enabled and triggered subsystem.
            gd = gated_example()
            win.diagram_model.set_diagram(gd)
            win.scene.select_blocks(["tooth_counter"])
            win.view.fit()
            grab(win.view, "subsystem-gated.png")

            # Variant subsystem: the Variants dialog.
            md2, sub2 = masked_example()
            sub2.mask_icon = ""
            sub2.active_variant = "petrol"
            sub2.add_variant("diesel", condition="ENGINE == 2")
            sub2.variants["petrol"].condition = "ENGINE == 1"
            md2.workspace["ENGINE"] = 1
            win.diagram_model.set_diagram(md2)
            win.scene.select_blocks(["combustion"])
            win.view.fit()
            grab(win, "variants-properties.png")
            from nervus.gui.views.variant_dialog import VariantDialog

            vdlg = VariantDialog(sub2, win)
            vdlg.show()
            grab(vdlg, "variants-dialog.png")
            vdlg.close()

            # Component library: a library in the panel and a linked copy (dashed outline).
            from nervus.library import instantiate, save_to_library

            lib_dir = Path(tempfile.mkdtemp())
            md3, comp = masked_example()
            lib_path = save_to_library(comp, lib_dir / "engine_parts.nervlib")
            win.library.add_library(lib_path)
            md3.remove("combustion")
            linked = instantiate(lib_path, "combustion")
            md3.add(linked, name="combustion")
            md3.connect(md3.block("air"), linked)
            md3.connect(linked, md3.block("scope"))
            win.diagram_model.set_diagram(md3)
            win.scene.select_blocks(["combustion"])
            win.view.fit()
            tree = win.library.tree
            tree.scrollToBottom()
            grab(win, "library-linked.png")
            win.library.remove_library(lib_path.resolve())

            # Lambda control example: the plant and the fuel task.
            win.files.open(ROOT / "examples" / "lambda_control.nervus")
            win.view.fit()
            grab(win.view, "lambda-model.png")
            win.diagram_model.enter(win.diagram_model.root.block("ECU"))
            win.view.fit()
            grab(win.view, "lambda-ecu.png")
            win.diagram_model.up()

            # Library example: two linked engines, and the inside of one.
            win.files.open(ROOT / "examples" / "engine_comparison.nervus")
            win.view.fit()
            grab(win.view, "engine-comparison.png")
            win.diagram_model.enter(win.diagram_model.root.block("engine_1_6l"))
            win.view.fit()
            grab(win.view, "engine-component.png")
            win.diagram_model.up()

            # Data types shown on the wires.
            win.files.open(ROOT / "examples" / "fixed_point_sensor.nervus")
            win.act_types.setChecked(True)
            win.refresh_types()
            win.view.fit()
            grab(win.view, "datatypes.png")
            win.act_types.setChecked(False)
            win.refresh_types()

            # Linear analysis of a textbook open loop.
            from nervus import Diagram
            from nervus.blocks import Inport, Outport, TransferFunction

            ol = Diagram("open_loop")
            u = ol.add(Inport(port=1), name="u")
            g = ol.add(TransferFunction(numerator=[10.0], denominator=[0.1, 1.1, 1.0, 0.0]), name="L")
            ol.chain(u, g, ol.add(Outport(port=1), name="y"))
            win.diagram_model.set_diagram(ol)
            adlg = win.show_analysis()
            adlg.resize(980, 680)
            adlg.run()
            grab(adlg, "analysis.png")
            adlg.close()
            win.files.open(ROOT / "examples" / "throttle_pi.nervus")
            win.show_help_for_type("control.discrete_pid")
            assert win._help is not None
            grab(win._help, "help.png")
            win.show_help_for_type("math.gain")
            win._help.resize(980, 720)
            grab(win._help, "help-gain.png")
            dlg_mod = __import__("nervus.gui.views.settings_dialog", fromlist=["SettingsDialog"])
            dlg = dlg_mod.SettingsDialog(win.diagram_model.diagram.settings, win)
            dlg.show()
            grab(dlg, "settings.png")
            dlg.close()
        win.files.editor.undo_stack.setClean()
        for w in list(win.scopes.values()):
            w.close()
        win.close()


if __name__ == "__main__":
    main()
