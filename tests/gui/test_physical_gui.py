"""Drawing circuits: physical ports, links, undo, delete."""

from PySide6.QtCore import QPointF


def test_link_and_simulate_circuit(window) -> None:  # type: ignore[no-untyped-def]
    ed = window.editor
    src = ed.add_block("electrical.voltage_source", QPointF(0, 0), V=10.0)
    r = ed.add_block("electrical.resistor", QPointF(150, 0), R=1000.0)
    c = ed.add_block("electrical.capacitor", QPointF(300, 0), C=1e-3)
    gnd = ed.add_block("electrical.reference", QPointF(150, 150))
    vc = ed.add_block("electrical.voltage_sensor", QPointF(300, 150))
    item = window.scene._item(r)
    assert [p.name for p in item.phys_ports] == ["p", "n"]
    assert item.phys_ports[0].outward == (-1, 0) and item.phys_ports[1].outward == (1, 0)
    for a, pa, b, pb in ((src, "p", r, "p"), (r, "n", c, "p"), (c, "n", gnd, "p"), (src, "n", gnd, "p"),
                         (vc, "p", c, "p"), (vc, "n", gnd, "p")):  # fmt: skip
        assert ed.link_ports(a, pa, b, pb)
    assert len(window.scene.links) == 6
    assert not ed.link_ports(r, "p", window.editor.add_block("rotational.inertia", QPointF(0, 300)), "a")  # domains
    ed.connect_ports(vc, 0, ed.add_block("sinks.scope", QPointF(450, 150)), 0)
    from nervus import simulate

    res = simulate(window.diagram_model.root, 1.0)
    assert abs(res[vc.name][-1] - 10 * (1 - 2.718281828**-1)) < 1e-3
    # Deleting a block removes its links; undo restores them.
    ed.delete([c], [])
    assert len(window.scene.links) == 3
    ed.undo_stack.undo()
    assert len(window.scene.links) == 6
    link = next(iter(window.scene.links.values()))
    link.setSelected(True)
    ed.delete([], window.scene.selected_links())
    assert len(window.scene.links) == 5


def test_import_and_export_spice(window, tmp_path) -> None:  # type: ignore[no-untyped-def]
    f = tmp_path / "divider.cir"
    f.write_text("Divider\nV1 in 0 10\nR1 in out 1k\nR2 out 0 1k\n.tran 1m 10m\n.end\n")
    assert window.import_spice(str(f))
    root = window.diagram_model.root
    assert {"V1", "R1", "R2", "V(out)"} <= {b.name for b in root.blocks}
    assert len(window.scene.links) == len(root.links) > 0
    out = tmp_path / "back.cir"
    assert window.export_spice(str(out))
    assert "R2 out 0 1k" in out.read_text()
