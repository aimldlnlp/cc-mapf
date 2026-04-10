from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Cell = tuple[int, int]
Plan = dict[str, list[Cell]]
RenderPreset = Literal["showcase", "diagnostic"]


@dataclass
class GridMap:
    width: int
    height: int
    obstacles: set[Cell] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Grid dimensions must be positive.")
        normalized = {tuple(cell) for cell in self.obstacles}
        for cell in normalized:
            x, y = cell
            if not (0 <= x < self.width and 0 <= y < self.height):
                raise ValueError(f"Obstacle {cell} is out of bounds.")
        self.obstacles = normalized

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "obstacles": [[x, y] for x, y in sorted(self.obstacles)],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GridMap":
        return cls(
            width=int(data["width"]),
            height=int(data["height"]),
            obstacles={tuple(cell) for cell in data.get("obstacles", [])},
        )


@dataclass(frozen=True)
class AgentSpec:
    id: str
    start: Cell
    goal: Cell

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "start": list(self.start), "goal": list(self.goal)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSpec":
        return cls(id=str(data["id"]), start=tuple(data["start"]), goal=tuple(data["goal"]))


@dataclass(frozen=True)
class ConnectivitySpec:
    mode: str = "adjacency"
    radius: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "radius": self.radius}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ConnectivitySpec":
        data = data or {}
        return cls(mode=str(data.get("mode", "adjacency")), radius=int(data.get("radius", 1)))


@dataclass
class Instance:
    name: str
    grid: GridMap
    agents: list[AgentSpec]
    connectivity: ConnectivitySpec = field(default_factory=ConnectivitySpec)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ids = [agent.id for agent in self.agents]
        if len(ids) != len(set(ids)):
            raise ValueError("Agent ids must be unique.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "grid": self.grid.to_dict(),
            "agents": [agent.to_dict() for agent in self.agents],
            "connectivity": self.connectivity.to_dict(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Instance":
        return cls(
            name=str(data["name"]),
            grid=GridMap.from_dict(data["grid"]),
            agents=[AgentSpec.from_dict(item) for item in data["agents"]],
            connectivity=ConnectivitySpec.from_dict(data.get("connectivity")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ValidationResult:
    valid: bool
    makespan: int
    sum_of_costs: int
    vertex_conflicts: list[dict[str, Any]] = field(default_factory=list)
    swap_conflicts: list[dict[str, Any]] = field(default_factory=list)
    connectivity_failures: list[dict[str, Any]] = field(default_factory=list)
    move_failures: list[dict[str, Any]] = field(default_factory=list)
    missing_paths: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "makespan": self.makespan,
            "sum_of_costs": self.sum_of_costs,
            "vertex_conflicts": self.vertex_conflicts,
            "swap_conflicts": self.swap_conflicts,
            "connectivity_failures": self.connectivity_failures,
            "move_failures": self.move_failures,
            "missing_paths": self.missing_paths,
        }


@dataclass
class PlannerResult:
    status: str
    plan: Plan | None
    runtime_s: float
    expanded_nodes: int | None
    connectivity_rejections: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        serial_plan: dict[str, list[list[int]]] | None = None
        if self.plan is not None:
            serial_plan = {
                agent_id: [[x, y] for x, y in path]
                for agent_id, path in self.plan.items()
            }
        return {
            "status": self.status,
            "plan": serial_plan,
            "runtime_s": self.runtime_s,
            "expanded_nodes": self.expanded_nodes,
            "connectivity_rejections": self.connectivity_rejections,
            "metadata": self.metadata,
        }


@dataclass
class SimulationTrace:
    states: list[dict[str, Cell]]
    padded_plan: Plan
    validation: ValidationResult


@dataclass
class RenderConfig:
    font_family: str = "DejaVu Serif"
    font_weight: str = "normal"
    dpi: int = 160
    figsize: tuple[float, float] = (6.0, 6.0)
    gif_fps: int = 4
    interpolation_steps: int = 3
    show_connectivity_edges: bool = True
    palette: list[str] = field(
        default_factory=lambda: [
            "#4C5B61",
            "#7D6B57",
            "#819A91",
            "#A67C52",
            "#59788E",
            "#B26E63",
            "#8E9AAF",
            "#7C9885",
        ]
    )
    snapshot_timestep_policy: str = "middle"
    annotation_style: str = "minimal"
    # Theme support
    theme: str = "light"  # light, dark, cyberpunk, ocean_dark, high_contrast
    palette_preset: str = "earthy"  # earthy, vibrant, ocean, forest, sunset, cyberpunk, pastel, high_contrast
    glow_effect: bool = False
    glow_radius: int = 3
    agent_size: float = 0.32
    # Theme colors (auto-populated based on theme)
    background_color: str = "#FFFFFF"
    grid_color: str = "#D9D5CF"
    obstacle_facecolor: str = "#D7D2C9"
    obstacle_edgecolor: str = "#B2ACA2"
    text_color: str = "#2C2C2C"
    axes_edgecolor: str = "#A9A39A"
    connectivity_edge_color: str = "#8A8883"
    agent_edgecolor: str = "#55514B"
    title_color: str = "#2C2C2C"
    subtitle_color: str = "#555555"

    def to_dict(self) -> dict[str, Any]:
        return {
            "font_family": self.font_family,
            "font_weight": self.font_weight,
            "dpi": self.dpi,
            "figsize": list(self.figsize),
            "gif_fps": self.gif_fps,
            "interpolation_steps": self.interpolation_steps,
            "show_connectivity_edges": self.show_connectivity_edges,
            "palette": list(self.palette),
            "snapshot_timestep_policy": self.snapshot_timestep_policy,
            "annotation_style": self.annotation_style,
            "theme": self.theme,
            "palette_preset": self.palette_preset,
            "glow_effect": self.glow_effect,
            "glow_radius": self.glow_radius,
            "agent_size": self.agent_size,
            "background_color": self.background_color,
            "grid_color": self.grid_color,
            "obstacle_facecolor": self.obstacle_facecolor,
            "obstacle_edgecolor": self.obstacle_edgecolor,
            "text_color": self.text_color,
            "axes_edgecolor": self.axes_edgecolor,
            "connectivity_edge_color": self.connectivity_edge_color,
            "agent_edgecolor": self.agent_edgecolor,
            "title_color": self.title_color,
            "subtitle_color": self.subtitle_color,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RenderConfig":
        data = data or {}
        figsize = tuple(data.get("figsize", (6.0, 6.0)))
        return cls(
            font_family=str(data.get("font_family", "DejaVu Serif")),
            font_weight=str(data.get("font_weight", "normal")),
            dpi=int(data.get("dpi", 160)),
            figsize=(float(figsize[0]), float(figsize[1])),
            gif_fps=int(data.get("gif_fps", 4)),
            interpolation_steps=int(data.get("interpolation_steps", 3)),
            show_connectivity_edges=bool(data.get("show_connectivity_edges", True)),
            palette=list(data.get("palette", cls().palette)),
            snapshot_timestep_policy=str(data.get("snapshot_timestep_policy", "middle")),
            annotation_style=str(data.get("annotation_style", "minimal")),
            theme=str(data.get("theme", "light")),
            palette_preset=str(data.get("palette_preset", "earthy")),
            glow_effect=bool(data.get("glow_effect", False)),
            glow_radius=int(data.get("glow_radius", 3)),
            agent_size=float(data.get("agent_size", 0.32)),
            background_color=str(data.get("background_color", "#FFFFFF")),
            grid_color=str(data.get("grid_color", "#D9D5CF")),
            obstacle_facecolor=str(data.get("obstacle_facecolor", "#D7D2C9")),
            obstacle_edgecolor=str(data.get("obstacle_edgecolor", "#B2ACA2")),
            text_color=str(data.get("text_color", "#2C2C2C")),
            axes_edgecolor=str(data.get("axes_edgecolor", "#A9A39A")),
            connectivity_edge_color=str(data.get("connectivity_edge_color", "#8A8883")),
            agent_edgecolor=str(data.get("agent_edgecolor", "#55514B")),
            title_color=str(data.get("title_color", "#2C2C2C")),
            subtitle_color=str(data.get("subtitle_color", "#555555")),
        )


@dataclass(frozen=True)
class SuiteScale:
    width: int
    height: int
    agents: int

    def to_dict(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height, "agents": self.agents}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SuiteScale":
        return cls(width=int(data["width"]), height=int(data["height"]), agents=int(data["agents"]))


@dataclass
class SuiteConfig:
    name: str
    families: list[str]
    scales: list[SuiteScale]
    seeds: list[int]
    planners: list[str]
    time_limit_s: float = 60.0
    time_limit_s_by_scale: dict[str, float] = field(default_factory=dict)
    render_enabled: bool = True
    render_preset: RenderPreset = "showcase"
    output_root: str = "artifacts/runs"
    render: RenderConfig = field(default_factory=RenderConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "families": self.families,
            "scales": [scale.to_dict() for scale in self.scales],
            "seeds": self.seeds,
            "planners": self.planners,
            "time_limit_s": self.time_limit_s,
            "time_limit_s_by_scale": self.time_limit_s_by_scale,
            "render": {
                "enabled": self.render_enabled,
                "preset": self.render_preset,
                **self.render.to_dict(),
            },
            "output_root": self.output_root,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SuiteConfig":
        render_data = dict(data.get("render", {}))
        return cls(
            name=str(data["name"]),
            families=[str(item) for item in data["families"]],
            scales=[SuiteScale.from_dict(item) for item in data["scales"]],
            seeds=[int(seed) for seed in data["seeds"]],
            planners=[str(item) for item in data["planners"]],
            time_limit_s=float(data.get("time_limit_s", 60.0)),
            time_limit_s_by_scale={
                str(scale): float(value) for scale, value in dict(data.get("time_limit_s_by_scale", {})).items()
            },
            render_enabled=bool(render_data.pop("enabled", True)),
            render_preset=str(render_data.pop("preset", "showcase")),  # type: ignore[arg-type]
            output_root=str(data.get("output_root", "artifacts/runs")),
            render=RenderConfig.from_dict(render_data),
        )


@dataclass
class ShowcaseManifest:
    run_id: str
    sources: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "sources": self.sources}


class Planner(Protocol):
    name: str

    def solve(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        """Return a plan for the provided instance."""
