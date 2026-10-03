---
name: modeling-3d
description: Specification for live 3D reconstruction, point cloud accumulation, timeline scrubbing, and autonomous target modeling.
---

# Live 3D Reconstruction & Timeline Scrubbing

## Overview
When enabled via `--enable-3d-modeling` or `DJI_ENABLE_3D_MODELING=true`, `dji-ground` synchronizes live video frames with 6-DOF aircraft pose and gimbal angle telemetry to produce a real-time 3D point cloud / mesh and chronological session recording.

## 1. Mathematical Formulation & Keyframe Extraction
- Each keyframe $i$ records:
  - Timestamp $t_i$
  - Camera pose matrix $T_{cw} = \begin{bmatrix} R & t \\ 0 & 1 \end{bmatrix}$ derived from aircraft position $(x, y, z)$, attitude $(\phi, \theta, \psi)$, and gimbal pitch $\theta_g$.
  - RGB image $I_i$.
- Keyframe selection criteria:
  - Translation $\Delta d > 0.25\text{ m}$ OR Rotation $\Delta \theta > 8^\circ$ OR $\Delta t > 500\text{ ms}$.
- Dense / semi-dense reprojection:
  - Feature correspondences between keyframe pairs $(I_i, I_{i-1})$ or monocular depth estimation yield 3D world points:
    $$P_w = T_{cw}^{-1} \cdot \left( d \cdot K^{-1} \begin{bmatrix} u \\ v \\ 1 \end{bmatrix} \right)$$
  - Points are color-stamped with the corresponding RGB pixel.
  - Voxel downsampling (e.g. 5 cm grid in `high` resolution) maintains spatial detail while preventing unbounded memory consumption.

## 2. Interactive Timeline Scrubbing
- Every keyframe, incremental point cloud slice, and synchronized telemetry packet is stored in SQLite and binary chunks.
- The Web UI provides a scrubbing bar representing flight time $[0, T_{\text{current}}]$.
- Scrubbing to time $\tau$:
  1. Displays the point cloud accumulated up to time $\tau$.
  2. Renders the drone's position, heading, and camera frustum at time $\tau$.
  3. Displays the exact camera frame captured at time $\tau$.
  4. Shows telemetry gauges at time $\tau$.

## 3. "Find Item X and 3D Model It" Workflow
- FastMCP tool: `scan_target_object(target_label="red car", radius_m=5.0)`:
  1. Activates detector / VLM to locate `target_label` in the camera viewport.
  2. Estimates target centroid $P_{\text{target}}$ by ray-plane intersection.
  3. Mints motion token and initiates `orbit` mode around $P_{\text{target}}$ at radius $R = \text{radius\_m}$.
  4. Accumulates 360-degree high-density 3D point cloud slices.
  5. On completion, transitions to hover, compiles final `.ply` / `.gltf` model, and exports model metadata.
