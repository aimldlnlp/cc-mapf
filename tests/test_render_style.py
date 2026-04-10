from __future__ import annotations

import matplotlib.pyplot as plt

from cc_mapf.model import RenderConfig
from cc_mapf.render import apply_style


def test_render_style_uses_dejavu_serif_without_bold() -> None:
    apply_style(RenderConfig())
    family = plt.rcParams["font.family"]
    assert "DejaVu Serif" in family
    assert plt.rcParams["font.weight"] == "normal"
    assert plt.rcParams["axes.titleweight"] == "normal"
    assert plt.rcParams["axes.labelweight"] == "normal"
